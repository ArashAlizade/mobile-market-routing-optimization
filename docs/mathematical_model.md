# Phase 1: Mobile market fleet routing and scheduling

## Sets and parameters
- `N`: market stops that must each be visited once.
- `0`: one depot; all routes return here.
- `R`: feasible directed tours with 1 or 2 stops, generated *before* optimization.
- `a_ir`: 1 if route `r` covers stop `i`; else 0.
- `c_r`: travel cost of route `r`, in travel minutes in this demonstration.
- `f`: fixed vehicle use cost in travel-minute equivalents.
- `K_min`, `K_max`: min and max number of vehicles used.
- `e_i`, `l_i`: earliest service start and latest service completion (minutes after midnight).
- `s_i`: fixed service duration; baseline 120 minutes.
- `t_ij`: vehicle travel minutes on directed arc `i -> j`.

## Decision
`z_r in {0,1}`: route `r` is used by one vehicle.

## Set-partitioning master problem
Minimize `sum_{r in R} (c_r + f) z_r`

subject to

- `sum_{r in R} a_ir z_r = 1` for each `i in N`;
- `K_min <= sum_{r in R} z_r <= K_max`;
- `z_r in {0,1}`.

## Feasible route-generation and service times
For each sequence `r=(i,j)` or `r=(i)`, initialize the truck clock at the depot opening time `T0`.
For every market `i`, compute

- `arrival_i = finish_previous + t_previous,i` (first leg starts at `T0`),
- `start_i = max(arrival_i, e_i)`,
- `finish_i = start_i + s_i`.

Reject route if `finish_i > l_i` for any stop, or if depot return occurs after `T_end`.
This uses a fixed departure at `T0`, earliest-feasible scheduling and unlimited waiting. For a time-independent travel matrix, leaving no earlier than `T0` cannot improve completion feasibility over this schedule.

## Modeling notes
- The base objective measures travel time, not kilometers. Replace with distance costs when road distances are available; preserve the separate time matrix for feasibility.
- `f` is a *penalty parameter* in travel-minute equivalents, not a measured fleet cost.
- A route uses one vehicle for the day. Vehicles have identical capabilities.
- No customer demand or capacity constraint is assumed.
- For candidate routes with at most two stops, at most `n^2` directed routes exist before filtering.
- This pedagogical Python solver enumerates feasible route combinations and is suitable only for small instances. An MILP solver can replace it for larger cases.
