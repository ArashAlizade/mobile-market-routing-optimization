# -*- coding: utf-8 -*-
"""
Created on Thu Oct 22 17:40:43 2026

@author: arash
"""


import pyomo.environ as pyo

from src.routes import calculate_route_cost


def optimize_route_cover_milp(
    markets,
    candidates,
    fleet_min,
    fleet_max,
    fixed_vehicle_cost=50.0,
    cost_per_mile=0.80,
    driver_hourly_rate=20.0,
    assumed_speed_mph=25.0,
    solver_name="appsi_highs"
):
    """
    Route-based MILP using Pyomo.

    Default solver: HiGHS (open source).
    Optional solver: Gurobi.

    Returns:
        (total_cost, selected_routes)
        or None if infeasible.
    """

    if not markets:
        raise ValueError("No markets provided")

    if fleet_min < 1 or fleet_max < fleet_min:
        raise ValueError("Invalid fleet bounds")

    # ---------------------------------------
    # 1. Calculate route costs
    # ---------------------------------------

    routes = []

    for route in candidates:
        cost = calculate_route_cost(
            route,
            fixed_vehicle_cost=fixed_vehicle_cost,
            cost_per_mile=cost_per_mile,
            driver_hourly_rate=driver_hourly_rate,
            assumed_speed_mph=assumed_speed_mph
        )

        routes.append({
            **route,
            **cost
        })

    if not routes:
        return None

    # ---------------------------------------
    # 2. Create MILP model
    # ---------------------------------------

    model = pyo.ConcreteModel()

    model.R = pyo.RangeSet(0, len(routes) - 1)

    # Binary decision variable
    model.z = pyo.Var(model.R, domain=pyo.Binary)

    # ---------------------------------------
    # 3. Objective: Minimize total cost
    # ---------------------------------------

    model.obj = pyo.Objective(
        expr=sum(
            routes[r]["total_cost"] * model.z[r]
            for r in model.R
        ),
        sense=pyo.minimize
    )

    # ---------------------------------------
    # 4. Each market visited exactly once
    # ---------------------------------------

    model.coverage = pyo.ConstraintList()

    for site in markets:

        model.coverage.add(
            sum(
                model.z[r]
                for r in model.R
                if site in routes[r]["stops"]
            ) == 1
        )

    # ---------------------------------------
    # 5. Fleet-size constraints
    # ---------------------------------------

    model.fleet_min = pyo.Constraint(
        expr=sum(model.z[r] for r in model.R)
        >= fleet_min
    )

    model.fleet_max = pyo.Constraint(
        expr=sum(model.z[r] for r in model.R)
        <= fleet_max
    )

    # ---------------------------------------
    # 6. Solve MILP
    # ---------------------------------------

    solver = pyo.SolverFactory(solver_name)

    if not solver.available(exception_flag=False):
        raise RuntimeError(
            f"Solver '{solver_name}' is unavailable"
        )

    results = solver.solve(model, tee=False)

    termination = results.solver.termination_condition

    if termination == pyo.TerminationCondition.infeasible:
        return None

    if termination != pyo.TerminationCondition.optimal:
        raise RuntimeError(
            f"Solver did not prove optimality: {termination}"
        )

    # ---------------------------------------
    # 7. Extract optimal routes
    # ---------------------------------------

    selected_routes = [
        routes[r]
        for r in model.R
        if pyo.value(model.z[r]) > 0.5
    ]

    total_cost = pyo.value(model.obj)

    return total_cost, selected_routes
