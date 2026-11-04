"""Create a reproducible six-stop mobile-market routing instance.

Uses prepared CSVs from inspect_and_prepare.py. Pantry is a candidate depot,
not a verified logistics facility. Distances here are straight-line ONLY for
selecting nearby sites; road-network routing is the next milestone.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd


def clean_coordinates(df: pd.DataFrame, label: str) -> pd.DataFrame:
    required = {"lat", "lon"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")
    result = df.copy()
    for col in ("lat", "lon"):
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result = result.dropna(subset=["lat", "lon"])
    result = result[result.lat.between(-90, 90) & result.lon.between(-180, 180)].reset_index(drop=True)
    if result.empty:
        raise ValueError(f"No valid {label} coordinates")
    return result


def haversine_km(lat: float, lon: float, other_lats, other_lons) -> np.ndarray:
    """Straight-line great-circle distances, NOT road distances."""
    radius = 6371.0088
    p1 = np.radians(lat)
    p2 = np.radians(np.asarray(other_lats, dtype=float))
    dp = p2 - p1
    dl = np.radians(np.asarray(other_lons, dtype=float) - lon)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * radius * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def build_case(markets: pd.DataFrame, pantries: pd.DataFrame, n_stops: int = 6,
               pantry_row: int | None = None):
    markets = clean_coordinates(markets, "markets")
    pantries = clean_coordinates(pantries, "pantries")
    if "site_id" not in markets.columns:
        raise ValueError("markets_clean.csv must contain 'site_id'")
    markets["site_id"] = markets.site_id.astype(str)
    if markets.site_id.duplicated().any():
        raise ValueError("Duplicate market site_id values")
    if not 1 <= n_stops <= len(markets):
        raise ValueError(f"--stops must be between 1 and {len(markets)}")
    if pantry_row is not None:
        if not 0 <= pantry_row < len(pantries):
            raise ValueError(f"--pantry-row must be 0..{len(pantries)-1}")
        depot_idx = pantry_row
    else:
        # Choose the pantry minimizing distance to ALL markets, a reproducible
        # central candidate rather than a validated operational facility.
        totals = [haversine_km(p.lat, p.lon, markets.lat, markets.lon).sum()
                  for p in pantries.itertuples(index=False)]
        depot_idx = int(np.argmin(totals))
    depot = pantries.iloc[depot_idx]
    candidates = markets.copy()
    candidates["distance_to_depot_km_straight"] = haversine_km(
        float(depot.lat), float(depot.lon), candidates.lat, candidates.lon
    )
    candidates = candidates.sort_values(
        ["distance_to_depot_km_straight", "site_id"], kind="stable"
    ).head(n_stops).reset_index(drop=True)
    result = pd.concat([
        pd.DataFrame([{
            "node_id": "DEPOT", "role": "depot", "name": str(depot.get("name", "Candidate Pantry")),
            "lat": float(depot.lat), "lon": float(depot.lon),
            "source_id": str(depot.get("depot_id", depot_idx)),
            "straight_line_km_to_depot": 0.0,
        }]),
        pd.DataFrame({
            "node_id": candidates.site_id.map(lambda x: f"M_{x}"),
            "role": "market",
            "name": candidates.get("name", pd.Series(["Market"] * len(candidates))).astype(str),
            "lat": candidates.lat.to_numpy(),
            "lon": candidates.lon.to_numpy(),
            "source_id": candidates.site_id,
            "straight_line_km_to_depot": candidates.distance_to_depot_km_straight,
        })
    ], ignore_index=True)
    return result, depot_idx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", default="outputs/markets_clean.csv")
    parser.add_argument("--pantries", default="outputs/pantry_depots.csv")
    parser.add_argument("--output", default="data/case_study_locations.csv")
    parser.add_argument("--stops", type=int, default=6)
    parser.add_argument("--pantry-row", type=int, default=None,
                        help="0-based row number after cleaning invalid coordinates; omit for automatic central candidate")
    args = parser.parse_args()
    locations, pantry_row = build_case(pd.read_csv(args.markets), pd.read_csv(args.pantries),
                                       n_stops=args.stops, pantry_row=args.pantry_row)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    locations.to_csv(target, index=False)
    print(f"Chosen candidate pantry row: {pantry_row}")
    print(f"Markets selected: {(locations.role == 'market').sum()}")
    print(f"Saved: {target}")
    print(locations[["node_id", "role", "name", "lat", "lon", "straight_line_km_to_depot"]].to_string(index=False))
    print("NOTE: Straight-line distances are ONLY for site selection, not route costs or driving times.")


if __name__ == "__main__":
    main()
