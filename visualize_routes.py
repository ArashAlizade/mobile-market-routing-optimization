"""Plot previously optimized Detroit mobile-market routes, without re-solving MILP.

Run from repository root: python visualize_routes.py
Inputs:
 data/case_study_locations.csv
 outputs/detroit_optimized_routes.csv
 outputs/detroit_itinerary.csv
Output: outputs/detroit_routes.html
"""
from pathlib import Path
import argparse
import html
import time

import folium
import pandas as pd
import requests

COLORS = ['#1565c0', '#d84315', '#2e7d32', '#8e24aa', '#00838f', '#ad1457', '#6d4c41']
OSRM = 'https://router.project-osrm.org'


def read_inputs(root):
    locations = pd.read_csv(root / 'data/case_study_locations.csv', dtype={'node_id': str})
    routes = pd.read_csv(root / 'outputs/detroit_optimized_routes.csv')
    itinerary = pd.read_csv(root / 'outputs/detroit_itinerary.csv', dtype={'site_id': str})
    required = {'node_id', 'lat', 'lon'}
    if not required <= set(locations.columns):
        raise ValueError(f'Location data requires {sorted(required)}')
    if not {'vehicle', 'route'} <= set(routes.columns):
        raise ValueError('Optimized routes must have vehicle and route columns')
    if not {'vehicle', 'site_id'} <= set(itinerary.columns):
        raise ValueError('Itinerary requires vehicle and site_id')
    locations['lat'] = pd.to_numeric(locations['lat'], errors='raise')
    locations['lon'] = pd.to_numeric(locations['lon'], errors='raise')
    if (locations['node_id'].isna().any() or locations['node_id'].duplicated().any()
            or not locations['lat'].between(-90, 90).all()
            or not locations['lon'].between(-180, 180).all()):
        raise ValueError('Invalid or duplicate location coordinates/IDs')
    if 'DEPOT' not in set(locations.node_id):
        raise ValueError('A DEPOT row is required')
    if routes.empty:
        raise ValueError('No optimized routes were found')
    return locations.set_index('node_id'), routes, itinerary


def parse_route(sequence, valid_ids):
    stops = [part.strip() for part in str(sequence).split('->')]
    if len(stops) < 3 or stops[0] != 'DEPOT' or stops[-1] != 'DEPOT':
        raise ValueError(f'Invalid depot-to-depot route: {sequence}')
    if any(s not in valid_ids for s in stops):
        raise ValueError(f'Unknown site ID in route: {sequence}')
    if len(set(stops[1:-1])) != len(stops[1:-1]):
        raise ValueError(f'Duplicate market in route: {sequence}')
    return stops


def road_geometry(a, b, timeout=25):
    """Return road-following [[lat,lon], ...] shape; raise on OSRM failure."""
    coords = f'{a[1]:.7f},{a[0]:.7f};{b[1]:.7f},{b[0]:.7f}'
    url = f'{OSRM}/route/v1/driving/{coords}'
    response = requests.get(url, params={'overview': 'full', 'geometries': 'geojson', 'steps': 'false'}, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    if result.get('code') != 'Ok' or not result.get('routes'):
        raise RuntimeError(f'OSRM route unavailable: {result.get("code")}')
    raw = result['routes'][0]['geometry']['coordinates']
    if len(raw) < 2:
        raise ValueError('OSRM returned insufficient road geometry')
    return [[lat, lon] for lon, lat in raw]


def popup_text(site_id, locations, itinerary, vehicle=None, order=None):
    name = locations.loc[site_id].get('name', site_id)
    name = site_id if pd.isna(name) else str(name)
    parts = [f'<b>{html.escape(name)}</b>', f'ID: {html.escape(site_id)}']
    if vehicle is not None:
        parts.append(f'Vehicle: {html.escape(str(vehicle))}; stop: {order}')
        matches = itinerary[(itinerary['vehicle'].astype(str) == str(vehicle)) & (itinerary.site_id == site_id)]
        if len(matches):
            row = matches.iloc[0]
            for key, label in [('arrival', 'Arrival'), ('service_start', 'Service start'), ('service_end', 'Service end')]:
                if key in matches.columns and pd.notna(row[key]):
                    parts.append(f'{label}: {html.escape(str(row[key]))}')
    return '<br>'.join(parts)



def create_map(root=Path("."), allow_straight_fallback=False):
    """
    Create an interactive map showing optimized mobile market routes.

    Features:
    - Esri street basemap
    - Depot marker
    - Different colors for each vehicle
    - Road-following routes using OSRM
    - Numbered market stops
    - Service schedule information
    - Interactive vehicle layer controls
    - Export to HTML
    """

    root = Path(root)

    # ---------------------------------------------
    # 1. Load optimization results
    # ---------------------------------------------

    locations, routes, itinerary = read_inputs(root)

    # Depot coordinates
    center = [
        float(locations.loc["DEPOT", "lat"]),
        float(locations.loc["DEPOT", "lon"])
    ]

    # ---------------------------------------------
    # 2. Initialize Folium map
    # ---------------------------------------------

    fmap = folium.Map(
        location=center,
        zoom_start=12,
        tiles=None
    )

    # Esri street basemap
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/"
            "services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles © Esri and its data providers",
        name="Esri Street Map",
        overlay=False,
        control=True,
        show=True
    ).add_to(fmap)

    # ---------------------------------------------
    # 3. Create coordinate dictionary
    # ---------------------------------------------

    coords = {
        str(idx): [
            float(row.lat),
            float(row.lon)
        ]
        for idx, row in locations.iterrows()
    }

    # ---------------------------------------------
    # 4. Add depot marker
    # ---------------------------------------------

    folium.Marker(
        location=center,
        tooltip="Mobile Market Depot",
        popup=popup_text(
            "DEPOT",
            locations,
            itinerary
        ),
        icon=folium.Icon(
            color="black",
            icon="home"
        )
    ).add_to(fmap)

    # ---------------------------------------------
    # 5. Initialize route geometry storage
    # ---------------------------------------------

    geometry_cache = {}

    all_points = [center]

    fallback_legs = 0

    # ---------------------------------------------
    # 6. Process each optimized vehicle route
    # ---------------------------------------------

    for pos, row in enumerate(
        routes.itertuples(index=False),
        start=1
    ):

        vehicle = row.vehicle

        stops = parse_route(
            row.route,
            set(coords)
        )

        # Assign a distinct color to each vehicle
        color = COLORS[(pos - 1) % len(COLORS)]

        # Separate map layer for each vehicle
        group = folium.FeatureGroup(
            name=(
                f"Vehicle {vehicle}: "
                f"{' → '.join(stops[1:-1])}"
            ),
            show=True
        )

        # -----------------------------------------
        # 7. Draw each road segment
        # -----------------------------------------

        for origin, destination in zip(
            stops[:-1],
            stops[1:]
        ):

            key = (origin, destination)

            if key not in geometry_cache:

                try:
                    points = road_geometry(
                        coords[origin],
                        coords[destination]
                    )

                    geometry_cache[key] = (
                        points,
                        False
                    )

                    time.sleep(0.1)

                except (
                    requests.RequestException,
                    ValueError,
                    RuntimeError
                ) as exc:

                    if not allow_straight_fallback:
                        raise RuntimeError(
                            f"Road geometry unavailable for "
                            f"{origin} -> {destination}. "
                            f"Retry later or enable "
                            f"straight-line fallback."
                        ) from exc

                    print(
                        f"WARNING: Straight-line fallback "
                        f"for {origin} -> {destination}: {exc}"
                    )

                    geometry_cache[key] = (
                        [
                            coords[origin],
                            coords[destination]
                        ],
                        True
                    )

            points, is_fallback = geometry_cache[key]

            fallback_legs += int(is_fallback)

            # Plot route segment
            folium.PolyLine(
                locations=points,
                color=color,
                weight=5,
                opacity=0.85,
                dash_array="7, 9" if is_fallback else None,
                tooltip=(
                    f"Vehicle {vehicle}: "
                    f"{origin} → {destination}"
                    + (
                        " [STRAIGHT-LINE FALLBACK]"
                        if is_fallback else ""
                    )
                )
            ).add_to(group)

            all_points.extend(points)

        # -----------------------------------------
        # 8. Add numbered market stops
        # -----------------------------------------

        for stop_num, site_id in enumerate(
            stops[1:-1],
            start=1
        ):

            marker_html = (
                f'<div style="'
                f'background:{color};'
                f'color:white;'
                f'border:2px solid white;'
                f'border-radius:50%;'
                f'width:30px;'
                f'height:30px;'
                f'line-height:26px;'
                f'text-align:center;'
                f'font-weight:bold;'
                f'box-shadow:0 1px 5px #555;'
                f'">'
                f'{stop_num}'
                f'</div>'
            )

            folium.Marker(
                location=coords[site_id],
                icon=folium.DivIcon(
                    html=marker_html
                ),
                tooltip=(
                    f"Vehicle {vehicle} / "
                    f"Stop {stop_num}: {site_id}"
                ),
                popup=folium.Popup(
                    popup_text(
                        site_id,
                        locations,
                        itinerary,
                        vehicle,
                        stop_num
                    ),
                    max_width=300
                )
            ).add_to(group)

        # Add route layer to the map
        group.add_to(fmap)

        # -----------------------------------------
        # 9. Print route summary
        # -----------------------------------------

        distance = getattr(
            row,
            "distance_miles",
            None
        )

        cost = getattr(
            row,
            "route_cost_usd",
            None
        )

        print(
            f"Vehicle {vehicle}: "
            f"{' -> '.join(stops)} | "
            f"miles={distance}, "
            f"cost USD={cost}"
        )

    # ---------------------------------------------
    # 10. Add vehicle layer selector
    # ---------------------------------------------

    folium.LayerControl(
        collapsed=False
    ).add_to(fmap)

    # Automatically fit the map to all routes
    fmap.fit_bounds(all_points)

    # ---------------------------------------------
    # 11. Export interactive HTML map
    # ---------------------------------------------

    output = root / "outputs" / "detroit_routes.html"

    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    fmap.save(str(output))

    print(f"\nSaved interactive map: {output}")

    if fallback_legs:
        print(
            f"WARNING: {fallback_legs} road segments "
            f"use approximate straight-line geometry."
        )

    return output
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Visualize previously optimized routes on a Folium street map.')
    parser.add_argument('--root', type=Path, default=Path('.'), help='Project repository root')
    parser.add_argument('--allow-straight-fallback', action='store_true', help='Show dashed direct lines if OSRM route geometry fails')
    args = parser.parse_args()
    create_map(args.root, args.allow_straight_fallback)
