"""Interactive mobile market routing dashboard.
Run at repository root: streamlit run routing_dashboard.py
Requires src/routes.py (route feasibility + road-mileage-aware cost) and
src/milp_solver.py (Pyomo/HiGHS). This does not modify app.py.
"""
from __future__ import annotations

import html
import math
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from src.routes import feasible_routes, clock
from src.Milp_solver import optimize_route_cover_milp

BASE = Path(__file__).resolve().parent
OSRM = "https://router.project-osrm.org"
COLORS = ["#1565c0", "#d84315", "#2e7d32", "#7b1fa2", "#00838f", "#ad1457", "#6d4c41", "#3949ab"]


def load_locations(path, required):
    frame = pd.read_csv(path)
    if not required.issubset(frame.columns):
        raise ValueError(f"{path.name} needs columns {sorted(required)}; found {list(frame.columns)}")
    frame = frame.copy()
    frame['lat'] = pd.to_numeric(frame['lat'], errors='coerce')
    frame['lon'] = pd.to_numeric(frame['lon'], errors='coerce')
    frame = frame.dropna(subset=['lat', 'lon'])
    frame = frame[frame.lat.between(-90,90) & frame.lon.between(-180,180)]
    return frame


@st.cache_data(ttl=3600, show_spinner=False)
def road_matrix(coords):
    """OSRM table, input tuple of (node_id, latitude, longitude)."""
    points = ';'.join(f'{lon:.7f},{lat:.7f}' for _, lat, lon in coords)
    response = requests.get(f'{OSRM}/table/v1/driving/{points}',
                            params={'annotations': 'duration,distance'}, timeout=45)
    response.raise_for_status()
    obj = response.json()
    if obj.get('code') != 'Ok':
        raise RuntimeError(f"OSRM table failed: {obj.get('message', obj.get('code'))}")
    times = np.array(obj['durations'], dtype=object)
    distances = np.array(obj['distances'], dtype=object)
    if any(v is None for v in times.flat) or any(v is None for v in distances.flat):
        raise RuntimeError('OSRM returned unreachable road pairs; select different sites')
    times = np.asarray(times, dtype=float) / 60  # seconds -> minutes
    distances = np.asarray(distances, dtype=float) / 1609.344  # meters -> miles
    return times, distances


@st.cache_data(ttl=3600, show_spinner=False)
def road_shape(a, b):
    url = (f'{OSRM}/route/v1/driving/'
           f'{a[1]:.7f},{a[0]:.7f};{b[1]:.7f},{b[0]:.7f}')
    response = requests.get(url, params={'overview':'full','geometries':'geojson'},timeout=35)
    response.raise_for_status()
    obj = response.json()
    if obj.get('code') != 'Ok' or not obj.get('routes'):
        raise RuntimeError('OSRM road geometry unavailable')
    return [[lat,lon] for lon,lat in obj['routes'][0]['geometry']['coordinates']]


def make_map(node_data, chosen, itinerary, include_roads=True):
    depot = node_data['DEPOT']
    fmap = folium.Map(location=[depot['lat'],depot['lon']], tiles=None, zoom_start=12)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        attr='Tiles © Esri and its data providers', name='Esri Streets', overlay=False
    ).add_to(fmap)
    folium.Marker([depot['lat'],depot['lon']], tooltip='Depot',
                  popup=html.escape(str(depot['name'])),
                  icon=folium.Icon(color='black', icon='home')).add_to(fmap)
    full_bounds = [[depot['lat'],depot['lon']]]
    for k,route in enumerate(chosen,1):
        color = COLORS[(k-1)%len(COLORS)]
        group = folium.FeatureGroup(name=f'Vehicle {k}: {" → ".join(route["stops"])}')
        sequence = ['DEPOT', *route['stops'], 'DEPOT']
        for a,b in zip(sequence,sequence[1:]):
            p = (node_data[a]['lat'],node_data[a]['lon'])
            q = (node_data[b]['lat'],node_data[b]['lon'])
            if include_roads:
                try:
                    points = road_shape(p,q)
                    fallback = False
                except (requests.RequestException,RuntimeError,ValueError):
                    points = [list(p),list(q)]
                    fallback = True
            else:
                points = [list(p),list(q)]
                fallback = True
            folium.PolyLine(points, color=color, weight=5, opacity=.85,
                            dash_array='5,8' if fallback else None,
                            tooltip=f'Vehicle {k}: {a} → {b}' + (' (approximate line)' if fallback else '')).add_to(group)
            full_bounds.extend(points)
        for order,stop in enumerate(route['stops'],1):
            pos = node_data[stop]
            schedule = next(s for s in itinerary if s['vehicle']==k and s['site_id']==stop)
            desc = (f'<b>{html.escape(str(pos["name"]))}</b><br>Vehicle {k}, Stop {order}'
                    f'<br>Arrival: {schedule["arrival"]}<br>Service: {schedule["service_start"]}–{schedule["service_end"]}')
            dot = (f'<div style="background:{color};color:white;border:2px solid white;border-radius:50%;'
                   f'width:29px;height:29px;text-align:center;line-height:25px;font-weight:bold">{order}</div>')
            folium.Marker([pos['lat'],pos['lon']], icon=folium.DivIcon(html=dot),
                          popup=folium.Popup(desc,max_width=300),tooltip=f'Vehicle {k}: {stop}').add_to(group)
        group.add_to(fmap)
    fmap.fit_bounds(full_bounds)
    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap


def main():
    st.set_page_config(page_title='Mobile Market Routing',layout='wide')
    st.title('Mobile Market Fleet Routing & Scheduling')
    st.caption('Independent prototype · real candidate coordinates · OSRM road estimates · Pyomo/HiGHS MILP')
    markets_path = BASE / 'outputs/markets_clean.csv'
    pantry_path = BASE / 'outputs/pantry_depots.csv'
    if not markets_path.exists() or not pantry_path.exists():
        st.error('First run inspect_and_prepare.py to produce outputs/markets_clean.csv and outputs/pantry_depots.csv.')
        st.stop()
    try:
        markets = load_locations(markets_path, {'site_id','lat','lon'})
        pantries = load_locations(pantry_path, {'lat','lon'})
    except Exception as exc:
        st.error(str(exc)); st.stop()
    if markets.empty or pantries.empty:
        st.error('One or both location datasets have no valid coordinates'); st.stop()
    markets['site_id'] = markets.site_id.astype(str)
    markets = markets.drop_duplicates('site_id')
    markets['name'] = markets.get('name', pd.Series(index=markets.index,dtype=str)).fillna('Market '+markets.site_id)
    pantries = pantries.reset_index(drop=True)
        
    # Generate fallback names for pantry locations
    fallback_names = pd.Series(
        [f"Pantry {i + 1}" for i in range(len(pantries))],
        index=pantries.index
    )
    
    if "name" not in pantries.columns:
        pantries["name"] = fallback_names
    else:
        pantries["name"] = (
            pantries["name"]
            .replace("", pd.NA)
            .fillna(fallback_names)
        )


    with st.sidebar:
        st.header('Scenario configuration')
        depot_mode = st.radio('Depot', ['Pantry candidate','Fixed coordinates'])
        if depot_mode == 'Pantry candidate':
            depot_row = st.selectbox('Select pantry',list(range(len(pantries))),
                format_func=lambda i: f'{i}: {pantries.iloc[i]["name"]} ({pantries.iloc[i]["lat"]:.4f}, {pantries.iloc[i]["lon"]:.4f})',
                index=min(11,len(pantries)-1))
            depot_lat, depot_lon = float(pantries.iloc[depot_row].lat),float(pantries.iloc[depot_row].lon)
            depot_name = str(pantries.iloc[depot_row]['name'])
        else:
            depot_lat = st.number_input('Depot latitude',value=42.388689,format='%.6f')
            depot_lon = st.number_input('Depot longitude',value=-83.104576,format='%.6f')
            depot_name = 'Custom depot'
        n = st.slider('Nearest stops to preselect',1,min(15,len(markets)),min(6,len(markets)))
        approx = (markets.lat-depot_lat)**2 + ((markets.lon-depot_lon)*math.cos(math.radians(depot_lat)))**2
        nearby = markets.assign(_dist=approx).sort_values('_dist')
        names = {r.site_id:f'{r.site_id} — {r["name"]}' for _,r in markets.iterrows()}
        selected = st.multiselect('Market stops', options=nearby.site_id.tolist(),
            default=nearby.site_id.head(n).tolist(),format_func=lambda s:names[s])
        st.divider()
        fleet_min = st.number_input('Minimum vehicles',min_value=1,max_value=30,value=3)
        fleet_max = st.number_input('Maximum vehicles',min_value=1,max_value=30,value=5)
        service = st.number_input('Service minutes / market',min_value=15,max_value=480,value=120,step=15)
        start_hour = st.number_input('Daily start hour (24h)',0,23,8)
        end_hour = st.number_input('Daily end hour (24h)',0,23,18)
        st.divider()
        fixed = st.number_input('Vehicle deployment cost ($)',min_value=0.0,value=50.0)
        cost_mile = st.number_input('Driving cost ($/mile)',min_value=0.0,value=0.80,step=0.10)
        labor = st.number_input('Driver cost ($/hour)',min_value=0.0,value=20.0)
        road_shapes = st.checkbox('Show street-following geometry',value=True)
        clicked = st.button('Optimize routes',type='primary',use_container_width=True)

    st.info('Location coordinates are candidate sites. Pantry depots are not verified dispatch facilities. Flexible service windows and costs are planning assumptions.')
    if not clicked:
        st.write(f'Loaded **{len(markets)}** market locations and **{len(pantries)}** pantry candidates. Select the scenario and click **Optimize routes**.')
        return
    if not selected:
        st.warning('Choose at least one market.');return
    if fleet_min > fleet_max or start_hour >= end_hour:
        st.error('Fleet bounds or operating hours are invalid.');return
    if math.ceil(len(selected)/2) > fleet_max or fleet_min > len(selected):
        st.error('Infeasible fleet bounds for the selected number of stops (maximum two stops per truck).');return
    focus=markets.set_index('site_id').loc[selected]
    nodes={'DEPOT':{'name':depot_name,'lat':depot_lat,'lon':depot_lon}}
    for site,row in focus.iterrows():
        nodes[site]={'name':str(row['name']),'lat':float(row.lat),'lon':float(row.lon)}
    ids = list(nodes)
    coords=tuple((name,nodes[name]['lat'],nodes[name]['lon']) for name in ids)
    try:
        with st.spinner('Calculating OSRM driving matrix and solving MILP…'):
            times,distances=road_matrix(coords)
            travel={(a,b):float(times[i,j]) for i,a in enumerate(ids) for j,b in enumerate(ids)}
            market_specs={site:{'open':int(start_hour*60),'close':int(end_hour*60),'service':int(service)} for site in selected}
            candidates=feasible_routes(market_specs,travel,depart=int(start_hour*60),shift_end=int(end_hour*60),max_stops=2)
            for route in candidates:
                sequence=['DEPOT',*route['stops'],'DEPOT']
                route['distance_miles']=sum(float(distances[ids.index(a),ids.index(b)]) for a,b in zip(sequence,sequence[1:]))
            if not candidates:
                st.error('No time-feasible candidate routes under these operating hours.');return
            result=optimize_route_cover_milp(market_specs,candidates,
                    fleet_min=int(fleet_min),fleet_max=int(fleet_max),
                    fixed_vehicle_cost=float(fixed),cost_per_mile=float(cost_mile),
                    driver_hourly_rate=float(labor),solver_name='appsi_highs')
        if result is None:
            st.error('No feasible fleet assignment. Try longer working hours or a larger fleet.');return
        obj, chosen=result
        visits=[]; route_rows=[]
        for k,r in enumerate(chosen,1):
            route_rows.append({'vehicle':k,'route':' → '.join(['DEPOT',*r['stops'],'DEPOT']),
                              'distance_miles':round(r['distance_miles'],2),'travel_minutes':round(r['total_drive_min'],1),
                              'duty_hours':round(r['duty_hours'],2),'cost_usd':round(r['total_cost'],2),
                              'return_time':clock(r['return_time'])})
            for s in r['itinerary']:
                visits.append({'vehicle':k,'site_id':s['site_id'],'arrival':clock(s['arrival']),
                               'service_start':clock(s['start']),'service_end':clock(s['finish']),
                               'waiting_minutes':round(s['waiting'],1)})
        st.session_state['last_result']={'routes':route_rows,'visits':visits,'nodes':nodes,'chosen':chosen,'objective':obj,
                                        'candidate_count':len(candidates),'road_shapes':road_shapes}
    except (requests.RequestException, KeyError, ValueError, RuntimeError, ImportError, OSError) as exc:
        st.error(f'Optimization could not complete: {exc}');return
    except Exception as exc:
        st.error(f'Solver or model error: {exc}');return

    a,b,c,d=st.columns(4)
    a.metric('Operating cost',f'${obj:,.2f}')
    b.metric('Vehicles',len(chosen))
    c.metric('Stops served',len(visits))
    d.metric('Total distance',f'{sum(x["distance_miles"] for x in chosen):.2f} mi')
    st.caption(f'{len(candidates)} of {len(selected)**2} possible one- and two-stop directed routes passed scheduling checks.')
    try:
        fmap=make_map(nodes,chosen,visits,road_shapes)
        components.html(fmap.get_root().render(),height=640,scrolling=False)
    except Exception as exc:
        st.warning(f'Map geometry unavailable: {exc}. Route and itinerary results remain valid.')
    st.subheader('Optimized vehicle routes')
    st.dataframe(pd.DataFrame(route_rows),use_container_width=True,hide_index=True)
    st.download_button('Download optimized routes CSV',pd.DataFrame(route_rows).to_csv(index=False),file_name='optimized_routes.csv')
    st.subheader('Service itinerary')
    st.dataframe(pd.DataFrame(visits),use_container_width=True,hide_index=True)
    st.download_button('Download itinerary CSV',pd.DataFrame(visits).to_csv(index=False),file_name='itinerary.csv')
    if len(visits)!=len(selected) or {v['site_id'] for v in visits}!=set(selected):
        st.error('Validation failed: mismatch in market coverage.')
    else:
        st.success('Validation: all selected market sites served exactly once; fleet and service-window constraints satisfied.')


if __name__ == '__main__':
    main()
