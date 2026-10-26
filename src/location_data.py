"""Independent input normalization for mobile-market routing (no source app code)."""
from __future__ import annotations
import pandas as pd


def market_locations(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the CSV exported by our Step 1 Streamlit importer."""
    required = {'site_id', 'lat', 'lon'}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f'Market data missing columns: {sorted(missing)}')
    out = frame.copy()
    out['site_id'] = out['site_id'].astype(str).str.strip()
    out['lat'] = pd.to_numeric(out['lat'], errors='coerce')
    out['lon'] = pd.to_numeric(out['lon'], errors='coerce')
    out = out.dropna(subset=['lat','lon'])
    out = out[out.lat.between(-90,90) & out.lon.between(-180,180)]
    out = out[out.site_id.ne('')].drop_duplicates('site_id')
    if 'name' not in out.columns:
        out['name'] = 'Market ' + out['site_id']
    if out.empty:
        raise ValueError('No valid market locations')
    return out[['site_id','name','lat','lon']].reset_index(drop=True)


def pantry_depots(frame: pd.DataFrame, *, category_col: str, lat_col: str,
                  lon_col: str, name_col: str | None = None,
                  pantry_values=('food pantry', 'food_pantry', 'pantry')) -> pd.DataFrame:
    """Select pantry records ONLY by explicit pantry category. No inferred categories."""
    required = {category_col, lat_col, lon_col}
    if name_col: required.add(name_col)
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f'Outlet data missing columns: {sorted(missing)}')
    allowed = {str(v).strip().lower() for v in pantry_values}
    out = frame.loc[frame[category_col].astype(str).str.strip().str.lower().isin(allowed)].copy()
    out['lat'] = pd.to_numeric(out[lat_col], errors='coerce')
    out['lon'] = pd.to_numeric(out[lon_col], errors='coerce')
    out = out.dropna(subset=['lat','lon'])
    out = out[out.lat.between(-90,90) & out.lon.between(-180,180)].reset_index(drop=True)
    out['name'] = out[name_col].astype(str) if name_col else ['Pantry '+str(i+1) for i in range(len(out))]
    out.insert(0,'depot_id', ['PANTRY_'+str(i+1).zfill(3) for i in range(len(out))])
    return out[['depot_id','name','lat','lon']]
