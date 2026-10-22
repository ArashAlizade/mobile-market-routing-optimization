"""Independent, read-only importer for proposed Detroit mobile-market locations."""
from io import BytesIO
import json
import pandas as pd
import requests
import streamlit as st

META_URL = "https://raw.githubusercontent.com/shayan9574/detroit-food-access-dashboard/main/data/model_meta.json"
BASE_URL = "https://raw.githubusercontent.com/shayan9574/detroit-food-access-dashboard/main/outputs/baseline_results.xlsx"

st.set_page_config(page_title="Mobile Market Routing", layout="wide")
st.title("Mobile Market Routing")
st.caption("Step 1 — Import and visualize locations (independent project)")
st.info("These are candidate / selected intervention sites, not confirmed operational mobile-market stops.")

@st.cache_data(ttl=3600)
def download(url: str) -> bytes:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content


def normalize_id(series: pd.Series) -> pd.Series:
    """Normalize integer-like IDs in spreadsheets and JSON without float-string mismatches."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all() and (numeric % 1 == 0).all():
        return numeric.astype("int64").astype(str)
    return series.astype("string").str.strip()


def read_markets(meta_bytes: bytes, baseline_bytes: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = json.loads(meta_bytes)
    if "sites" not in meta:
        raise ValueError("model_meta.json is missing the 'sites' key")
    sites = pd.DataFrame(meta["sites"])
    needed = {"j", "lat", "lon"}
    if not needed.issubset(sites.columns):
        raise ValueError(f"Candidate file must contain {sorted(needed)}; found {sites.columns.tolist()}")
    sites = sites.rename(columns={"j": "site_id"}).copy()
    sites["site_id"] = normalize_id(sites["site_id"])
    for c in ("lat", "lon"):
        sites[c] = pd.to_numeric(sites[c], errors="coerce")
    sites = sites.dropna(subset=["site_id", "lat", "lon"])
    sites = sites[sites.lat.between(-90, 90) & sites.lon.between(-180, 180)].copy()
    if "zip" not in sites.columns:
        sites["zip"] = ""
    sites["name"] = "Site " + sites["site_id"].astype(str)
    sites = sites[["site_id", "name", "lat", "lon", "zip"]].drop_duplicates("site_id")

    baseline = pd.read_excel(BytesIO(baseline_bytes), sheet_name="selected_facilities")
    needed_baseline = {"site_id", "intervention_type"}
    if not needed_baseline.issubset(baseline.columns):
        raise ValueError(f"Selected-facilities sheet needs {sorted(needed_baseline)}")
    selected = baseline.loc[
        baseline["intervention_type"].astype(str).str.strip().str.lower().eq("mobile_market"),
        ["site_id"],
    ].copy()
    selected["site_id"] = normalize_id(selected["site_id"])
    markets = sites.merge(selected.drop_duplicates(), on="site_id", how="inner")
    return sites, markets

source = st.radio("Location source", ["Public GitHub files (read-only)", "Upload source files"], horizontal=True)
if source == "Public GitHub files (read-only)":
    try:
        meta_bytes, baseline_bytes = download(META_URL), download(BASE_URL)
    except requests.RequestException as err:
        st.error(f"Source download failed: {err}. Try uploading the files instead.")
        st.stop()
else:
    meta_file = st.file_uploader("model_meta.json", type="json")
    baseline_file = st.file_uploader("baseline_results.xlsx", type="xlsx")
    if meta_file is None or baseline_file is None:
        st.stop()
    meta_bytes, baseline_bytes = meta_file.getvalue(), baseline_file.getvalue()

try:
    sites, markets = read_markets(meta_bytes, baseline_bytes)
except (ValueError, KeyError, json.JSONDecodeError, ImportError) as err:
    st.error(f"Could not interpret source data: {err}")
    st.stop()

left, right = st.columns(2)
left.metric("Candidate sites with coordinates", len(sites))
right.metric("Selected mobile-market sites", len(markets))
if markets.empty:
    st.warning("No selected mobile-market IDs matched candidate-site IDs. Check file versions and fields.")
else:
    st.dataframe(markets, use_container_width=True, hide_index=True)
    st.map(markets, latitude="lat", longitude="lon")
    st.download_button("Export locations CSV", markets.to_csv(index=False).encode("utf-8"),
                       file_name="mobile_market_locations.csv", mime="text/csv")
