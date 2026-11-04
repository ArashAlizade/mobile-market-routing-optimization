"""Run after you export mobile_market_locations.csv from your independent Streamlit app.

The public outlets.parquet schema may change. Run once without --category-col to see
column names, then pass explicit mappings. This script NEVER writes to the source repo.
"""
import argparse
from pathlib import Path
import pandas as pd
from src.location_data import market_locations, pantry_depots

parser = argparse.ArgumentParser()
parser.add_argument('--markets', default='data/mobile_market_locations.csv')
parser.add_argument('--outlets', default='data/outlets.parquet')
parser.add_argument('--category-col')
parser.add_argument('--lat-col')
parser.add_argument('--lon-col')
parser.add_argument('--name-col')
parser.add_argument('--pantry-value', action='append')
args = parser.parse_args()
out = Path('outputs')
out.mkdir(exist_ok=True)
markets = market_locations(pd.read_csv(args.markets))
markets.to_csv(out/'markets_clean.csv', index=False)
print(f'Validated {len(markets)} markets; saved outputs/markets_clean.csv')
outlets = pd.read_parquet(args.outlets)
print('Outlets columns:', outlets.columns.tolist())
if not (args.category_col and args.lat_col and args.lon_col):
    print('Provide --category-col, --lat-col, and --lon-col to extract pantry depots.')
else:
    kwargs = {}
    if args.pantry_value:
        kwargs['pantry_values'] = args.pantry_value
    depots = pantry_depots(outlets, category_col=args.category_col,
                           lat_col=args.lat_col, lon_col=args.lon_col,
                           name_col=args.name_col, **kwargs)
    depots.to_csv(out/'pantry_depots.csv', index=False)
    print(f'Extracted {len(depots)} pantry locations; saved outputs/pantry_depots.csv')
    print('Pantry coordinates are depot candidates, not verified loading facilities.')
