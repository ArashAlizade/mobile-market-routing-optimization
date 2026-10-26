
from itertools import permutations
import pandas as pd

DEPOT = "DEPOT"


# -------------------------------------------------
# 1. Time conversion
# -------------------------------------------------

def minutes(time_string):
    h, m = map(int, str(time_string).split(":"))

    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Time must be HH:MM")

    return 60 * h + m


def clock(value):
    return f"{int(value)//60:02d}:{int(value)%60:02d}"


# -------------------------------------------------
# 2. Generate candidate routes
# -------------------------------------------------

def enumerate_routes(market_ids, max_stops=2):
    ids = list(market_ids)

    if len(ids) != len(set(ids)) or DEPOT in ids:
        raise ValueError(
            "Market IDs must be unique and distinct from DEPOT"
        )

    for size in range(1, min(max_stops, len(ids)) + 1):
        yield from permutations(ids, size)


# -------------------------------------------------
# 3. Evaluate route feasibility
# -------------------------------------------------

def evaluate_route(
    stops,
    markets,
    travel_minutes,
    depart=480,
    shift_end=1080
):
    """
    Check time-window feasibility.

    Each vehicle:
    - Starts at the depot
    - Visits the assigned markets
    - Completes service before each closing time
    - Returns to the depot before shift_end
    """

    if not stops:
        raise ValueError("Route must contain a market")

    t = depart
    previous = DEPOT
    itinerary = []

    for market_id in stops:

        row = markets[market_id]

        drive = float(travel_minutes[previous, market_id])

        arrival = t + drive
        start = max(arrival, row["open"])
        finish = start + row["service"]

        if finish > row["close"]:
            return None

        itinerary.append({
            "site_id": market_id,
            "arrival": arrival,
            "start": start,
            "finish": finish,
            "waiting": start - arrival,
            "drive": drive
        })

        t = finish
        previous = market_id

    return_drive = float(
        travel_minutes[previous, DEPOT]
    )

    returned = t + return_drive

    if returned > shift_end:
        return None

    total_drive = (
        sum(x["drive"] for x in itinerary)
        + return_drive
    )

    total_wait = sum(
        x["waiting"] for x in itinerary
    )

    total_service = sum(
        markets[i]["service"] for i in stops
    )

    return {
        "stops": tuple(stops),
        "itinerary": itinerary,
        "return_time": returned,
        "total_drive_min": total_drive,
        "total_wait_min": total_wait,
        "total_service_min": total_service,
        "duty_minutes": returned - depart
    }


# -------------------------------------------------
# 4. Generate feasible routes
# -------------------------------------------------

def feasible_routes(
    markets,
    travel_minutes,
    depart=480,
    shift_end=1080,
    max_stops=2
):

    routes = []

    for seq in enumerate_routes(markets, max_stops):

        evaluated = evaluate_route(
            seq,
            markets,
            travel_minutes,
            depart,
            shift_end
        )

        if evaluated is not None:
            routes.append({
                "route_id": f"R{len(routes)+1:03d}",
                **evaluated
            })

    return routes


# -------------------------------------------------
# 5. Calculate operating cost in dollars
# -------------------------------------------------


def calculate_route_cost(
    route,
    fixed_vehicle_cost=50.0,
    cost_per_mile=0.80,
    driver_hourly_rate=20.0,
    assumed_speed_mph=25.0
):
    """
    Calculate total operating cost in USD.

    Uses actual OSRM road mileage when available.
    Otherwise, uses an assumed speed for synthetic tests.
    """

    # 1. Driving time (minutes)
    driving_minutes = route["total_drive_min"]

    # 2. Driving distance (miles)
    distance_miles = route.get("distance_miles")

    if distance_miles is None:
        # Fallback for synthetic examples only
        distance_miles = (
            driving_minutes / 60.0
        ) * assumed_speed_mph

    # 3. Total driver duty time (hours)
    duty_hours = route["duty_minutes"] / 60.0

    # 4. Cost components
    fixed_cost = fixed_vehicle_cost
    distance_cost = cost_per_mile * distance_miles
    labor_cost = driver_hourly_rate * duty_hours

    # 5. Total operating cost
    total_cost = (
        fixed_cost
        + distance_cost
        + labor_cost
    )

    return {
        "total_cost": total_cost,
        "fixed_cost": fixed_cost,
        "distance_cost": distance_cost,
        "labor_cost": labor_cost,
        "distance_miles": distance_miles,
        "duty_hours": duty_hours
    }



# -------------------------------------------------
# 6. Optimize fleet assignments
# -------------------------------------------------

def optimize_route_cover(
    markets,
    candidates,
    fleet_min,
    fleet_max,
    fixed_vehicle_cost=50.0,
    cost_per_mile=0.80,
    driver_hourly_rate=20.0,
    assumed_speed_mph=25.0
):
    """
    Exact enumeration for small datasets.

    Objective:
    Minimize total operating cost in USD.

    Includes:
    - Fixed vehicle cost
    - Distance-dependent cost
    - Driver labor cost
    """

    ids = frozenset(markets)

    if not ids:
        raise ValueError("No markets")

    if fleet_min < 1 or fleet_max < fleet_min:
        raise ValueError("Invalid fleet bounds")

    best = None

    # Calculate the cost of every candidate route
    costed_candidates = []

    for route in candidates:

        cost_info = calculate_route_cost(
            route,
            fixed_vehicle_cost,
            cost_per_mile,
            driver_hourly_rate,
            assumed_speed_mph
        )

        costed_candidates.append({
            **route,
            **cost_info
        })

    # Find candidate routes serving each site
    by_site = {
        i: [
            r for r in costed_candidates
            if i in r["stops"]
        ]
        for i in ids
    }

    def search(remaining, chosen, objective):

        nonlocal best

        if not remaining:

            if (
                fleet_min <= len(chosen) <= fleet_max
                and (
                    best is None
                    or objective < best[0]
                )
            ):
                best = (objective, list(chosen))

            return

        if len(chosen) >= fleet_max:
            return

        if best is not None and objective >= best[0]:
            return

        site = min(
            remaining,
            key=lambda s: len(by_site[s])
        )

        for route in by_site[site]:

            coverage = set(route["stops"])

            if coverage <= remaining:

                search(
                    remaining - coverage,
                    chosen + [route],
                    objective + route["total_cost"]
                )

    search(set(ids), [], 0.0)

    return best
