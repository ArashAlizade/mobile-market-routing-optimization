# Commit 9 — Interactive routing and decision-maker dashboard

## Purpose
An independent application for the existing Mobile Market Routing Optimization repository. It reads prepared market and pantry location CSVs, estimates road travel with OSRM, enumerates at most two-stop candidate tours, rejects time-infeasible tours, and solves a route-based set-partitioning MILP using Pyomo/HiGHS. No code or data is written to the source Food Access repository.

## Installation
1. Copy `routing_dashboard.py`, `src/routes.py`, and `src/milp_solver.py` into your repository, preserving your existing `app.py` and other scripts.
2. Merge or replace your `requirements.txt` with the included list (if your existing app has additional requirements, retain them).
3. Keep `outputs/markets_clean.csv` and `outputs/pantry_depots.csv` in your repository for actual source-derived location inputs. If they are absent, the application uses a clearly marked six-site demo dataset under `demo_data/`.
4. In Anaconda Prompt:

```bash
conda activate mobile_routing
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m streamlit run routing_dashboard.py
```

## Live demo
- Set depot type to Pantry candidate; use the sample depot or one of the imported candidate pantries.
- Select six market sites, fleet minimum 3 and maximum 5, service 120 minutes, 08:00–18:00.
- Set illustrative fixed vehicle cost $50, mileage cost $0.80/mile, and driver labor $20/hour.
- Click **Optimize routes**. First show **Route map**; then **Costs & insights**; then **Vehicle schedules** and **Validation & export**.
- Change the depot or stops and **click Optimize routes again**. Results from the previous solve remain visible but are marked stale until recomputed.

## Technical model
Candidate routes consist of (DEPOT, i, DEPOT) and (DEPOT, i, j, DEPOT). With n markets there are n² possible directed routes. Fixed 120-minute (configurable) service and flexible daily operating windows are evaluated by a forward schedule. A route is dropped if service finishes after its permitted closing time or the vehicle returns after shift end.

Binary `z_r` selects a time-feasible route, with objective **min ∑r (F + c_d D_r + c_t H_r) z_r**. Each market is served exactly once; selected routes are between minimum and maximum fleet limits. Distance `D_r` is the sum of OSRM road-distance arc estimates (miles). Duty time `H_r` includes driving, waiting, and market service, calculated from fixed depot departure.

## Validation
The dashboard checks (1) exact stop coverage, (2) fleet bounds, (3) maximum two stops per vehicle, (4) depot return deadline, (5) service windows and (6) cost sum equals solver objective. The Pyomo solver accepts results only when HiGHS reports optimality. Run the unit tests for route scheduling and cost components.

## Decision-maker outputs
- Daily modeled cost, vehicles used, market stops and total mileage.
- Cost breakdown chart: fixed deployment, road-mileage cost and driver labor.
- Stacked vehicle-cost comparison and the highest-cost vehicle.
- Vehicle service timeline and downloadable route and itinerary CSVs.
- Interactive map with different colors per vehicle; fallback route geometries are dashed, not actual roads.

## Limitations
- These are candidate locations, not validated operating stops. Pantry depot suitability is unverified.
- Cost rates are illustrative and should not be presented as measured operational expenditure.
- Flexible shared working windows are not fixed posted appointments.
- No inventory, food demand, capacity, or resident access model.
- Public OSRM is not live traffic and can reject requests or be rate-limited. Basemap provider terms must be checked for deployment.
- Road shape might fail even when matrix retrieval succeeds; map dashed sketches do not change the optimized route costs.
- Changing inputs requires a new solver run, and the displayed prior result is marked accordingly.

## GitHub commit
```bash
git add routing_dashboard.py src/routes.py src/milp_solver.py requirements.txt demo_data/ docs/COMMIT9_GUIDE.md tests/test_routes.py
git commit -m "Complete routing dashboard with decision-maker analytics"
git pull --rebase origin main
git push origin main
```
Review `git status` before staging and **do not** force push.
