"""Commit 5: build OSRM driving-time and distance matrices from case study sites.

Run from the repository root: python build_travel_matrix.py
Input: data/case_study_locations.csv (node_id, lat, lon)
Output: outputs/travel_time_minutes.csv, outputs/travel_distance_miles.csv,
        outputs/travel_arcs.csv
"""
from pathlib import Path
import pandas as pd
import requests

INPUT = Path('data/case_study_locations.csv')
OUTPUT = Path('outputs')
OSRM_BASE = 'https://router.project-osrm.org'
METERS_PER_MILE = 1609.344


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f'Missing {INPUT}; run prepare_case_study.py first')
    sites = pd.read_csv(INPUT, dtype={'node_id': str})
    required = {'node_id', 'lat', 'lon'}
    if not required.issubset(sites.columns):
        raise ValueError(f'Missing columns: {sorted(required - set(sites.columns))}')
    if sites.empty or sites['node_id'].isna().any() or sites['node_id'].duplicated().any():
        raise ValueError('node_id must be unique and nonempty')
    for col, lo, hi in [('lat', -90, 90), ('lon', -180, 180)]:
        sites[col] = pd.to_numeric(sites[col], errors='coerce')
        if not sites[col].between(lo, hi).all():
            raise ValueError(f'Invalid or missing {col}')
    if 'DEPOT' not in set(sites['node_id']):
        raise ValueError('Expected a DEPOT node')

    # OSRM expects longitude,latitude (not latitude,longitude).
    coords = ';'.join(f'{lon:.7f},{lat:.7f}' for lat, lon in zip(sites['lat'], sites['lon']))
    url = f'{OSRM_BASE}/table/v1/driving/{coords}'
    response = requests.get(url, params={'annotations': 'duration,distance'}, timeout=60)
    response.raise_for_status()
    result = response.json()
    if result.get('code') != 'Ok':
        raise RuntimeError(f'OSRM table failed: {result.get("code")}: {result.get("message", "")}')

    node_ids = sites['node_id'].tolist()
    n = len(node_ids)
    durations, distances = result.get('durations'), result.get('distances')
    if durations is None or distances is None or len(durations) != n or len(distances) != n:
        raise ValueError('Incomplete OSRM table response')
    if any(len(row) != n for row in durations + distances):
        raise ValueError('OSRM matrix dimensions do not match input nodes')
    if any(value is None for matrix in (durations, distances) for row in matrix for value in row):
        raise RuntimeError('At least one origin-destination pair is unreachable; no estimates substituted')

    # Preserve raw precision; do not round travel times before feasibility checks.
    duration_df = pd.DataFrame([[v / 60 for v in row] for row in durations],
                               index=node_ids, columns=node_ids)
    distance_df = pd.DataFrame([[v / METERS_PER_MILE for v in row] for row in distances],
                               index=node_ids, columns=node_ids)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    duration_df.to_csv(OUTPUT / 'travel_time_minutes.csv', index_label='node_id')
    distance_df.to_csv(OUTPUT / 'travel_distance_miles.csv', index_label='node_id')
    arcs = [{'origin': i, 'destination': j,
             'travel_minutes': float(duration_df.loc[i, j]),
             'distance_miles': float(distance_df.loc[i, j])}
            for i in node_ids for j in node_ids]
    pd.DataFrame(arcs).to_csv(OUTPUT / 'travel_arcs.csv', index=False)
    print(f'OSRM road matrix created: {n} x {n} ({n*n} directed pairs).')
    print(f'Wrote {OUTPUT / "travel_time_minutes.csv"}')
    print(f'Wrote {OUTPUT / "travel_distance_miles.csv"}')
    print(f'Wrote {OUTPUT / "travel_arcs.csv"}')
    print('\nDepot outbound driving times (minutes):')
    print(duration_df.loc['DEPOT'].round(1).to_string())


if __name__ == '__main__':
    main()
