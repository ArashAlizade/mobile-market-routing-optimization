# Mobile Market Routing Optimization

Independent Python/Streamlit project for location-based mobile-market fleet scheduling and route visualization. **Step 1** imports and displays publicly shared proposed mobile-market site coordinates; no routing optimizer is implemented yet.

## Independence and data provenance

This repository contains its **own application code** and does not import modules from or make changes to the source food-access dashboard. It only issues read-only HTTP GET requests for two public data files:

- [`model_meta.json`](https://github.com/shayan9574/detroit-food-access-dashboard/blob/main/data/model_meta.json) (candidate sites)
- [`baseline_results.xlsx`](https://github.com/shayan9574/detroit-food-access-dashboard/blob/main/outputs/baseline_results.xlsx) (baseline intervention selections)

Sites designated `mobile_market` in the baseline's `selected_facilities` sheet are matched to candidate coordinates. These are **proposed intervention locations**, not confirmed real-world mobile-market stops or schedules. Source files belong to their respective owners; review data licensing/permissions before redistributing a derived dataset.

## Run on Windows (Anaconda Prompt)

```bat
conda activate mobile_routing
cd "C:\Users\arash\Downloads\mobile-market-routing-optimization"
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The app also supports manual upload if GitHub source files change or are unavailable.

## Roadmap

1. Import and visualize market locations — implemented.
2. Choose market subset and depot.
3. Set fleet bounds, capacity planning assumptions and at most two stops per vehicle.
4. Add routing and time-window optimization.
5. Visualize vehicle-specific routes, arrival/service times and metrics.
6. Propose integration into the existing food-access dashboard (without modifying its repository without permission).

## Repository publication

Create an **empty** GitHub repository called `mobile-market-routing-optimization`, then from this folder run:

```bash
git init
git add .
git commit -m "Initial independent mobile-market location importer"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mobile-market-routing-optimization.git
git push -u origin main
```
