# =============================================================================
# optimisation.py  (static_test — identical MILP logic to integration version)
# Only change: imports come from local config, and wind/t_offset are optional
# since there is no rolling loop.
# =============================================================================

import numpy as np
from gurobipy import Model, GRB, quicksum
from config.config import (
    GRID_ROWS, GRID_COLS, WINDOW_MINUTES,
    Ck, Cp, CRUISE_K, CRUISE_P, M_BIG,
    GUROBI_TIME_LIMIT, AIRFIELD_CELL, WATER_CELLS,
    STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED,
    CELL_SIZE_M,
    WIND_DIR_DEG,
)
from drop_pattern import compute_drop_footprint


def _speed_to_cells_per_step(cruise_kmmin: float) -> int:
    cell_km = CELL_SIZE_M / 1000.0
    return max(1, int(np.floor(cruise_kmmin / cell_km)))


V_K = _speed_to_cells_per_step(CRUISE_K)
V_P = _speed_to_cells_per_step(CRUISE_P)


def _manhattan(c1, c2):
    return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1])


def _euclidean_cells(c1, c2):
    return np.hypot(c1[0] - c2[0], c1[1] - c2[1])


def build_and_solve(
    grid: np.ndarray,
    extinguished_mask: np.ndarray,
    num_tankers: int,
    num_scoopers: int,
    t_offset: int = 0,
    wind_dir_deg: float = None,
    drop_heading_deg: float = None,
) -> dict:
    """
    Build and solve the AFFVRP for one static window.

    Parameters
    ----------
    grid : np.ndarray  shape (GRID_ROWS, GRID_COLS)
        3-state fire grid.  0=unburned, 1=burning, 2=extinguished.
    extinguished_mask : np.ndarray bool
        Permanently extinguished cells (excluded from propagation).
    num_tankers, num_scoopers : int
        Fleet sizes.
    t_offset : int
        Minute offset for the Z (time-to-last-drop) variable. 0 for static test.
    wind_dir_deg : float or None
        Wind direction in degrees. Defaults to WIND_DIR_DEG from config.
    drop_heading_deg : float or None
        Aircraft heading during drops. Defaults to wind_dir_deg + 180.

    Returns
    -------
    dict with keys: status, obj, drop_schedule, routes, Z, gap
    """
    if wind_dir_deg is None:
        wind_dir_deg = WIND_DIR_DEG
    if drop_heading_deg is None:
        drop_heading_deg = (wind_dir_deg + 180.0) % 360.0

    T = list(range(WINDOW_MINUTES))
    cells = [(r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS)]
    K = list(range(num_tankers))
    P = list(range(num_scoopers))

    burning_cells = [(r, c) for r in range(GRID_ROWS)
                             for c in range(GRID_COLS)
                             if grid[r, c] == STATE_BURNING]

    if not burning_cells:
        return {'status': 'NO_FIRE', 'obj': 0.0, 'drop_schedule': [],
                'routes': {}, 'Z': 0.0, 'gap': None}

    # Precompute drop footprints
    footprints = {}
    for (r, c) in burning_cells:
        footprints[(r, c)] = compute_drop_footprint(
            r, c, drop_heading_deg, GRID_ROWS, GRID_COLS
        )

    Q_k = int(Ck / Cp)
    Q_p = 1

    mdl = Model('AFFVRP_static')
    mdl.setParam('OutputFlag', 1)   # show Gurobi log so you can see progress
    mdl.setParam('TimeLimit', GUROBI_TIME_LIMIT)

    # --- Decision variables ---
    x_k = mdl.addVars(K, cells, T, vtype=GRB.BINARY, name='x_k')
    x_p = mdl.addVars(P, cells, T, vtype=GRB.BINARY, name='x_p')
    d_k = mdl.addVars(K, burning_cells, T, vtype=GRB.BINARY, name='d_k')
    d_p = mdl.addVars(P, burning_cells, T, vtype=GRB.BINARY, name='d_p')
    y   = mdl.addVars(cells, T, [0, 1, 2], vtype=GRB.BINARY, name='y')
    q_k = mdl.addVars(K, T, vtype=GRB.INTEGER, lb=0, ub=Q_k, name='q_k')
    q_p = mdl.addVars(P, T, vtype=GRB.BINARY, name='q_p')
    Z   = mdl.addVar(vtype=GRB.CONTINUOUS, lb=0, name='Z')

    mdl.update()

    # --- Objectives ---
    burn_sum = quicksum(y[r, c, t, STATE_BURNING]
                        for (r, c) in cells for t in T)

    flight_cost_k = quicksum(
        _euclidean_cells((r1, c1), (r2, c2)) * x_k[k, r1, c1, t]
        for k in K
        for (r1, c1) in cells
        for (r2, c2) in cells if (r1, c1) != (r2, c2)
        for t in T[:-1]
        if _manhattan((r1, c1), (r2, c2)) <= V_K
    )
    flight_cost_p = quicksum(
        _euclidean_cells((r1, c1), (r2, c2)) * x_p[p, r1, c1, t]
        for p in P
        for (r1, c1) in cells
        for (r2, c2) in cells if (r1, c1) != (r2, c2)
        for t in T[:-1]
        if _manhattan((r1, c1), (r2, c2)) <= V_P
    )

    mdl.setObjectiveN(burn_sum, index=1, priority=10, name='MinBurn')
    mdl.setObjectiveN(flight_cost_k + flight_cost_p, index=0, priority=0, name='MinFlight')

    # --- Constraints ---

    # 1. Initial fire state
    for (r, c) in cells:
        s_init = int(grid[r, c])
        for s in [0, 1, 2]:
            mdl.addConstr(y[r, c, 0, s] == (1 if s == s_init else 0),
                          name=f'init_{r}_{c}_{s}')

    # 2. Exactly one state per cell per timestep
    for (r, c) in cells:
        for t in T:
            mdl.addConstr(
                quicksum(y[r, c, t, s] for s in [0, 1, 2]) == 1,
                name=f'one_state_{r}_{c}_{t}'
            )

    # 3. Extinguished is absorbing
    for (r, c) in cells:
        for t in T[:-1]:
            mdl.addConstr(y[r, c, t + 1, 2] >= y[r, c, t, 2],
                          name=f'ext_absorb_{r}_{c}_{t}')

    # 4. Fire propagation (Moore neighbourhood)
    def _neighbours(r, c):
        nb = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                    nb.append((nr, nc))
        return nb

    for (r, c) in cells:
        if extinguished_mask[r, c]:
            continue
        for t in T[:-1]:
            nb = _neighbours(r, c)
            for (nr, nc) in nb:
                mdl.addConstr(
                    y[r, c, t + 1, STATE_BURNING] >=
                    y[nr, nc, t, STATE_BURNING] - y[r, c, t + 1, STATE_EXTINGUISHED],
                    name=f'prop_lb_{r}_{c}_{nr}_{nc}_{t}'
                )
            mdl.addConstr(
                y[r, c, t + 1, STATE_BURNING] <=
                y[r, c, t, STATE_BURNING] +
                quicksum(y[nr, nc, t, STATE_BURNING] for (nr, nc) in nb),
                name=f'prop_ub_{r}_{c}_{t}'
            )

    # 5. Suppression coupling
    for (r, c) in burning_cells:
        for t in T[:-1]:
            for (r2, c2), eta_val in footprints.get((r, c), {}).items():
                if (r2, c2) in burning_cells:
                    for k in K:
                        mdl.addConstr(
                            y[r, c, t + 1, STATE_EXTINGUISHED] >=
                            d_k[k, r2, c2, t] + y[r, c, t, STATE_BURNING] - 1,
                            name=f'supp_k_{r}_{c}_{r2}_{c2}_{k}_{t}'
                        )
                    for p in P:
                        mdl.addConstr(
                            y[r, c, t + 1, STATE_EXTINGUISHED] >=
                            d_p[p, r2, c2, t] + y[r, c, t, STATE_BURNING] - 1,
                            name=f'supp_p_{r}_{c}_{r2}_{c2}_{p}_{t}'
                        )

    # 6. Each aircraft at exactly one cell per timestep
    for k in K:
        for t in T:
            mdl.addConstr(
                quicksum(x_k[k, r, c, t] for (r, c) in cells) == 1,
                name=f'loc_k_{k}_{t}'
            )
    for p in P:
        for t in T:
            mdl.addConstr(
                quicksum(x_p[p, r, c, t] for (r, c) in cells) == 1,
                name=f'loc_p_{p}_{t}'
            )

    # 7. At most one aircraft per cell per timestep
    for (r, c) in cells:
        for t in T:
            mdl.addConstr(
                quicksum(x_k[k, r, c, t] for k in K) +
                quicksum(x_p[p, r, c, t] for p in P) <= 1,
                name=f'one_ac_{r}_{c}_{t}'
            )

    # 8. Linear flight dynamics
    for k in K:
        for t in T[:-1]:
            for (r1, c1) in cells:
                for (r2, c2) in cells:
                    if _manhattan((r1, c1), (r2, c2)) > V_K:
                        mdl.addConstr(
                            x_k[k, r1, c1, t] + x_k[k, r2, c2, t + 1] <= 1,
                            name=f'dyn_k_{k}_{r1}_{c1}_{r2}_{c2}_{t}'
                        )
    for p in P:
        for t in T[:-1]:
            for (r1, c1) in cells:
                for (r2, c2) in cells:
                    if _manhattan((r1, c1), (r2, c2)) > V_P:
                        mdl.addConstr(
                            x_p[p, r1, c1, t] + x_p[p, r2, c2, t + 1] <= 1,
                            name=f'dyn_p_{p}_{r1}_{c1}_{r2}_{c2}_{t}'
                        )

    # 9. Drop only when present at cell
    for k in K:
        for (r, c) in burning_cells:
            for t in T:
                mdl.addConstr(d_k[k, r, c, t] <= x_k[k, r, c, t],
                              name=f'drop_loc_k_{k}_{r}_{c}_{t}')
    for p in P:
        for (r, c) in burning_cells:
            for t in T:
                mdl.addConstr(d_p[p, r, c, t] <= x_p[p, r, c, t],
                              name=f'drop_loc_p_{p}_{r}_{c}_{t}')

    # 10. Drop only on burning cells
    for k in K:
        for (r, c) in burning_cells:
            for t in T:
                mdl.addConstr(
                    d_k[k, r, c, t] <= y[r, c, t, STATE_BURNING],
                    name=f'drop_burn_k_{k}_{r}_{c}_{t}'
                )
    for p in P:
        for (r, c) in burning_cells:
            for t in T:
                mdl.addConstr(
                    d_p[p, r, c, t] <= y[r, c, t, STATE_BURNING],
                    name=f'drop_burn_p_{p}_{r}_{c}_{t}'
                )

    # 11. Tanker water dynamics
    at_airfield_k = {
        (k, t): x_k[k, AIRFIELD_CELL[0], AIRFIELD_CELL[1], t]
        for k in K for t in T
    }
    for k in K:
        mdl.addConstr(q_k[k, 0] == Q_k, name=f'q_k_init_{k}')
    for k in K:
        for t in T[:-1]:
            drops_t = quicksum(d_k[k, r, c, t] for (r, c) in burning_cells)
            mdl.addConstr(
                q_k[k, t + 1] <=
                Q_k * at_airfield_k[k, t] + q_k[k, t] - drops_t,
                name=f'q_k_ub_{k}_{t}'
            )
            mdl.addConstr(
                q_k[k, t + 1] >= q_k[k, t] - drops_t,
                name=f'q_k_lb_{k}_{t}'
            )
            mdl.addConstr(drops_t <= q_k[k, t], name=f'q_k_nonempty_{k}_{t}')

    # 12. Scooper water dynamics
    def _at_water(p, t):
        return quicksum(x_p[p, wr, wc, t] for (wr, wc) in WATER_CELLS)

    for p in P:
        mdl.addConstr(q_p[p, 0] == 1, name=f'q_p_init_{p}')
    for p in P:
        for t in T[:-1]:
            drops_t = quicksum(d_p[p, r, c, t] for (r, c) in burning_cells)
            mdl.addConstr(
                q_p[p, t + 1] <= 1 - drops_t + _at_water(p, t + 1),
                name=f'q_p_ub_{p}_{t}'
            )
            mdl.addConstr(
                q_p[p, t + 1] >= _at_water(p, t + 1) - drops_t,
                name=f'q_p_lb_{p}_{t}'
            )
            mdl.addConstr(drops_t <= q_p[p, t], name=f'q_p_nonempty_{p}_{t}')

    # 13. Tanker start and end at airfield
    for k in K:
        mdl.addConstr(x_k[k, AIRFIELD_CELL[0], AIRFIELD_CELL[1], 0] == 1,
                      name=f'k_start_{k}')
        mdl.addConstr(x_k[k, AIRFIELD_CELL[0], AIRFIELD_CELL[1], T[-1]] == 1,
                      name=f'k_end_{k}')

    # 14. Scooper starts at airfield
    for p in P:
        mdl.addConstr(x_p[p, AIRFIELD_CELL[0], AIRFIELD_CELL[1], 0] == 1,
                      name=f'p_start_{p}')

    # 15. Z: time of last drop
    for k in K:
        for (r, c) in burning_cells:
            for t in T:
                mdl.addConstr(
                    Z >= (t_offset + t) * d_k[k, r, c, t],
                    name=f'Z_k_{k}_{r}_{c}_{t}'
                )
    for p in P:
        for (r, c) in burning_cells:
            for t in T:
                mdl.addConstr(
                    Z >= (t_offset + t) * d_p[p, r, c, t],
                    name=f'Z_p_{p}_{r}_{c}_{t}'
                )

    # --- Solve ---
    mdl.optimize()

    status_map = {2: 'OPTIMAL', 3: 'INFEASIBLE', 5: 'UNBOUNDED', 9: 'TIME_LIMIT'}
    status_str = status_map.get(mdl.Status, f'CODE_{mdl.Status}')

    if mdl.Status in (GRB.OPTIMAL, GRB.TIME_LIMIT) and mdl.SolCount > 0:
        obj = mdl.ObjVal
        drop_schedule = []
        routes = {}

        for k in K:
            routes[f'tanker_{k}'] = []
            for t in T:
                for (r, c) in cells:
                    if x_k[k, r, c, t].X > 0.5:
                        routes[f'tanker_{k}'].append((t, r, c))
            for t in T:
                for (r, c) in burning_cells:
                    if d_k[k, r, c, t].X > 0.5:
                        drop_schedule.append((f'tanker_{k}', 'tanker', t_offset + t, r, c))

        for p in P:
            routes[f'scooper_{p}'] = []
            for t in T:
                for (r, c) in cells:
                    if x_p[p, r, c, t].X > 0.5:
                        routes[f'scooper_{p}'].append((t, r, c))
            for t in T:
                for (r, c) in burning_cells:
                    if d_p[p, r, c, t].X > 0.5:
                        drop_schedule.append((f'scooper_{p}', 'scooper', t_offset + t, r, c))

        z_val = Z.X
    else:
        obj, drop_schedule, routes, z_val = 0.0, [], {}, 0.0

    return {
        'status':        status_str,
        'obj':           obj,
        'drop_schedule': drop_schedule,
        'routes':        routes,
        'Z':             z_val,
        'gap':           mdl.MIPGap if mdl.SolCount > 0 else None,
    }
