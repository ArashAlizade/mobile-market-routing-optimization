"""Detroit case study: road-network data + time-window-feasible routes + HiGHS MILP.

Run from the repository root: python run_detroit.py
"""
from pathlib import Path
import pandas as pd
from src.routes import feasible_routes, clock
from src.Milp_solver import optimize_route_cover_milp

DATA = Path('data/case_study_locations.csv')
TIMES = Path('outputs/travel_time_minutes.csv')
DISTANCES = Path('outputs/travel_distance_miles.csv')
OUTPUT = Path('outputs')

SERVICE_MINUTES = 120
START_MINUTES = 8 * 60
END_MINUTES = 18 * 60
FLEET_MIN = 3
FLEET_MAX = 5
FIXED_VEHICLE_COST = 50.0
COST_PER_MILE = 0.80
DRIVER_HOURLY_RATE = 20.0


def read_square_matrix(path, nodes):
    matrix = pd.read_csv(path, index_col=0)
    matrix.index = matrix.index.astype(str).str.strip()
    matrix.columns = matrix.columns.astype(str).str.strip()
    missing_rows = set(nodes) - set(matrix.index)
    missing_cols = set(nodes) - set(matrix.columns)
    if missing_rows or missing_cols:
        raise ValueError(f'{path}: missing rows {missing_rows}, columns {missing_cols}')
    matrix = matrix.loc[nodes, nodes].apply(pd.to_numeric, errors='raise')
    if matrix.isna().any().any() or (matrix.values < 0).any():
        raise ValueError(f'{path}: missing or negative travel data')
    return matrix


def route_mileage(stops, distance_matrix):
    sequence = ['DEPOT', *stops, 'DEPOT']
    return sum(float(distance_matrix.loc[i, j]) for i, j in zip(sequence, sequence[1:]))


def main():
    locations = pd.read_csv(DATA)
    required = {'node_id', 'role', 'lat', 'lon'}
    if not required.issubset(locations.columns):
        raise ValueError(f'Expected {sorted(required)} in {DATA}')
    if locations.node_id.duplicated().any():
        raise ValueError('node_id values must be unique')
    depot_rows = locations[locations.role == 'depot']
    if len(depot_rows) != 1 or str(depot_rows.iloc[0]['node_id']) != 'DEPOT':
        raise ValueError('Case study requires exactly one DEPOT')
    sites = locations[locations.role == 'market'].copy()
    ids = ['DEPOT', *sites.node_id.astype(str).tolist()]

    time_mat = read_square_matrix(TIMES, ids)
    distance_mat = read_square_matrix(DISTANCES, ids)
    travel_minutes = {(i, j): float(time_mat.loc[i, j]) for i in ids for j in ids}

    # Flexible service windows are planning assumptions, NOT actual market schedules.
    markets = {str(site): {'open': START_MINUTES,
                           'close': END_MINUTES,
                           'service': SERVICE_MINUTES}
               for site in sites.node_id}

    candidates = feasible_routes(markets, travel_minutes, depart=START_MINUTES,
                                 shift_end=END_MINUTES, max_stops=2)
    for route in candidates:
        route['distance_miles'] = route_mileage(route['stops'], distance_mat)

    print('Markets:', len(markets))
    print('Possible directed routes:', len(markets) ** 2)
    print('Time-feasible routes:', len(candidates))

    # Requires the small update to calculate_route_cost in src/routes.py
    # supplied in COMMIT6_README.md.
    result = optimize_route_cover_milp(
        markets, candidates, fleet_min=FLEET_MIN, fleet_max=FLEET_MAX,
        fixed_vehicle_cost=FIXED_VEHICLE_COST,
        cost_per_mile=COST_PER_MILE,
        driver_hourly_rate=DRIVER_HOURLY_RATE,
        solver_name='appsi_highs',
    )
    if result is None:
        print('Infeasible fleet assignment')
        return

    total_cost, routes = result
    OUTPUT.mkdir(exist_ok=True)
    route_rows, stop_rows = [], []
    print(f'Optimal total operating cost: ${total_cost:.2f}')
    for k, r in enumerate(routes, 1):
        seq = ' -> '.join(['DEPOT', *r['stops'], 'DEPOT'])
        print(f'Vehicle {k}: {seq}; {r["distance_miles"]:.2f} miles; '
              f'${r["total_cost"]:.2f}; return {clock(r["return_time"])}')
        route_rows.append({'vehicle': k, 'route_id': r['route_id'], 'route': seq,
                           'distance_miles': r['distance_miles'],
                           'driving_minutes': r['total_drive_min'],
                           'waiting_minutes': r['total_wait_min'],
                           'duty_hours': r['duty_hours'],
                           'route_cost_usd': r['total_cost'],
                           'depot_return': clock(r['return_time'])})
        for stop in r['itinerary']:
            stop_rows.append({'vehicle': k, 'site_id': stop['site_id'],
                              'arrival': clock(stop['arrival']),
                              'service_start': clock(stop['start']),
                              'service_end': clock(stop['finish']),
                              'waiting_minutes': stop['waiting']})
    pd.DataFrame(route_rows).to_csv(OUTPUT / 'detroit_optimized_routes.csv', index=False)
    pd.DataFrame(stop_rows).to_csv(OUTPUT / 'detroit_itinerary.csv', index=False)
    print('Saved outputs/detroit_optimized_routes.csv and outputs/detroit_itinerary.csv')

if __name__ == '__main__':
    main()
