
import pandas as pd

from src.routes import minutes, clock, feasible_routes
from src.Milp_solver import optimize_route_cover_milp

# --------------------------------------------------
# 1. Load market data
# --------------------------------------------------

sites = pd.read_csv("data/example_markets.csv")

markets = {
    r.site_id: {
        "open": minutes(r.open),
        "close": minutes(r.close),
        "service": int(r.service)
    }
    for r in sites.itertuples(index=False)
}


# --------------------------------------------------
# 2. Define travel-time matrix
# --------------------------------------------------

# Synthetic symmetric driving times (minutes)
# These are NOT actual road-network travel times.

ids = ["DEPOT", *markets.keys()]

upper = {
    ("DEPOT", "A"): 20,
    ("DEPOT", "B"): 15,
    ("DEPOT", "C"): 25,
    ("DEPOT", "D"): 30,
    ("A", "B"): 15,
    ("A", "C"): 20,
    ("A", "D"): 30,
    ("B", "C"): 30,
    ("B", "D"): 20,
    ("C", "D"): 25
}

travel = {(i, i): 0 for i in ids}

for (i, j), value in upper.items():
    travel[i, j] = value
    travel[j, i] = value


# --------------------------------------------------
# 3. Cost assumptions
# --------------------------------------------------

FIXED_VEHICLE_COST = 50.0  # USD per vehicle
COST_PER_MILE = 0.80       # USD per mile
DRIVER_HOURLY_RATE = 20.0  # USD per hour
ASSUMED_SPEED_MPH = 25.0   # Synthetic distance estimate

FLEET_MIN = 2
FLEET_MAX = 3


# --------------------------------------------------
# 4. Generate time-feasible routes
# --------------------------------------------------

candidates = feasible_routes(
    markets,
    travel,
    depart=8 * 60,
    shift_end=18 * 60,
    max_stops=2
)

print("Possible directed routes:", len(markets) ** 2)
print("Feasible routes:", len(candidates))


# --------------------------------------------------
# 5. Optimize fleet operating costs
# --------------------------------------------------

answer = optimize_route_cover_milp(
    markets=markets,
    candidates=candidates,
    fleet_min=2,
    fleet_max=3,
    fixed_vehicle_cost=50.0,
    cost_per_mile=0.80,
    driver_hourly_rate=20.0,
    assumed_speed_mph=25.0,
    solver_name="appsi_highs"
)

if answer is None:
    print("No feasible fleet assignment")

else:
    total_cost, chosen = answer

    print("\nOPTIMIZATION RESULTS")
    print("-------------------------------")
    print(f"Total operating cost: ${total_cost:.2f}")
    print(f"Vehicles used: {len(chosen)}")

    route_rows = []
    itinerary_rows = []

    for idx, r in enumerate(chosen, 1):

        sequence = (
            "DEPOT -> "
            + " -> ".join(r["stops"])
            + " -> DEPOT"
        )

        print(
            f"Vehicle {idx}: {sequence}\n"
            f"  Route cost: ${r['total_cost']:.2f}\n"
            f"  Distance: {r['distance_miles']:.2f} miles\n"
            f"  Driving time: {r['total_drive_min']:.1f} min\n"
            f"  Return time: {clock(r['return_time'])}"
        )

        route_rows.append({
            "vehicle": idx,
            "route_id": r["route_id"],
            "sequence": sequence,
            "distance_miles": r["distance_miles"],
            "drive_min": r["total_drive_min"],
            "waiting_min": r["total_wait_min"],
            "duty_hours": r["duty_hours"],
            "fixed_cost": r["fixed_cost"],
            "distance_cost": r["distance_cost"],
            "labor_cost": r["labor_cost"],
            "total_cost": r["total_cost"],
            "depot_return": clock(r["return_time"])
        })

        for stop in r["itinerary"]:

            itinerary_rows.append({
                "vehicle": idx,
                "site_id": stop["site_id"],
                "arrival": clock(stop["arrival"]),
                "start": clock(stop["start"]),
                "finish": clock(stop["finish"]),
                "waiting_min": stop["waiting"]
            })

    # Export optimized results
    pd.DataFrame(route_rows).to_csv(
        "optimized_routes.csv",
        index=False
    )

    pd.DataFrame(itinerary_rows).to_csv(
        "itinerary.csv",
        index=False
    )

    print("\nResults exported successfully.")
