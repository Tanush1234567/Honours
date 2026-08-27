# =============================================================================
# optimisation.py
# The spatially and temporally discretised AFFVRP.
#
# Design follows the problem statement directly:
#
#   SPACE  : uniform grid of rectangular cells C = {(r,c)}
#   TIME   : discrete timesteps T = {0,1,...,W-1} within the current window
#   STATES : y[c,t,s] in {0,1}  — state s in {0=unburned,1=burning,2=extinguished}
#   AIRCRAFT: heterogeneous fleet of tankers (K) and scoopers (P)
#
#   PRIMARY OBJECTIVE  : minimise total burning cell-timesteps  Σ y[c,t,1]
#                        (minimises fire spread and time to extinguishment)
#   SECONDARY OBJECTIVE: minimise total flight distance (tie-breaker)
#
# Key constraints included:
#   - Linear flight dynamics  (max speed in grid cells per timestep)
#   - Water capacity per aircraft
#   - Drop pattern applied as coverage over neighbouring cells
#   - One aircraft per cell per timestep
#   - Scoopers refill at water-source cells (zero ground speed, problem statement §2.0.5)
#   - Tankers return to airfield to refuel (multi-trip)
#   - Time windows (can be tightened for priority cells)
#   - Once extinguished, a cell cannot burn again
# =============================================================================

import numpy as np
from gurobipy import Model, GRB, quicksum
from config.config import (
    GRID_ROWS, GRID_COLS, WINDOW_MINUTES,
    Ck, Cp, CRUISE_K, CRUISE_P, MAX_TRIPS, R, RD, M_BIG,
    GUROBI_TIME_LIMIT, AIRFIELD_CELL, WATER_CELLS,
    STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED,
    CELL_SIZE_M
)
from drop_pattern import compute_drop_footprint


# ---------------------------------------------------------------------------
# Helper: convert km/min cruise speed → max cells per timestep
# One timestep = 1 minute (FARSITE_TIMESTEP)
# ---------------------------------------------------------------------------
def _speed_to_cells_per_step(cruise_kmmin: float) -> int:
    cell_km = CELL_SIZE_M / 1000.0
    return max(1, int(np.floor(cruise_kmmin / cell_km)))


V_K = _speed_to_cells_per_step(CRUISE_K)   # tanker  max cells/timestep
V_P = _speed_to_cells_per_step(CRUISE_P)   # scooper max cells/timestep


# ---------------------------------------------------------------------------
# Helper: travel time in timesteps between two cells (Manhattan metric used
# for the linear flight dynamics constraint; Euclidean for time cost)
# ---------------------------------------------------------------------------
def _manhattan(c1, c2):
    return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1])


def _euclidean_cells(c1, c2):
    return np.hypot(c1[0] - c2[0], c1[1] - c2[1])


def build_and_solve(
    grid: np.ndarray,
    extinguished_mask: np.ndarray,
    num_tankers: int,
    num_scoopers: int,
    t_offset: int,
    wind_speed_kph: float,
    wind_dir_deg: float,
    drop_heading_deg: float = None
) -> dict:
    """
    Build and solve the spatially discretised AFFVRP for one rolling window.

    Parameters
    ----------
    grid : np.ndarray shape (GRID_ROWS, GRID_COLS)
        Current 3-state fire grid at the START of this window.
    extinguished_mask : np.ndarray bool
        Permanently extinguished cells (never re-enter as targets).
    num_tankers, num_scoopers : int
        Fleet size for this solve.
    t_offset : int
        Absolute minute of the start of this window (for time-window constraints).
    wind_speed_kph, wind_dir_deg : float
        Wind for this window — used to derive drop heading if not supplied.
    drop_heading_deg : float or None
        Aircraft heading during drops. If None, inferred as wind_dir_deg + 180
        (aircraft drops into the wind — standard AFF practice).

    Returns
    -------
    dict with keys:
        'status'        : Gurobi status string
        'obj'           : objective value
        'drop_schedule' : list of (aircraft_id, aircraft_type, timestep, row, col)
        'routes'        : dict {aircraft_id: [(t, r, c), ...]}
        'Z'             : value of Z (latest drop time, if used)
    """
    if drop_heading_deg is None:
        # Aircraft drop INTO the wind (approaches from downwind side)
        drop_heading_deg = (wind_dir_deg + 180.0) % 360.0

    T = list(range(WINDOW_MINUTES))   # discrete timesteps 0..W-1
    cells = [(r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS)]
    K = list(range(num_tankers))
    P = list(range(num_scoopers))

    # Burning cells at start of window — these are the suppression targets
    burning_cells = [(r, c) for r in range(GRID_ROWS)
                             for c in range(GRID_COLS)
                             if grid[r, c] == STATE_BURNING]

    if not burning_cells:
        return {'status': 'NO_FIRE', 'obj': 0.0, 'drop_schedule': [],
                'routes': {}, 'Z': 0.0}

    # ------------------------------------------------------------------
    # Precompute drop footprints for every burning cell
    # footprint[(r,c)] = {(r2,c2): eta_value, ...}  cells suppressed if
    # aircraft drops at (r,c) with heading drop_heading_deg
    # ------------------------------------------------------------------
    footprints = {}
    for (r, c) in burning_cells:
        footprints[(r, c)] = compute_drop_footprint(
            r, c, drop_heading_deg, GRID_ROWS, GRID_COLS
        )

    # ------------------------------------------------------------------
    # Water capacity in "drop units"
    # One drop unit = Cp (scooper capacity). Tanker can carry Ck/Cp units.
    # Each drop at one cell costs 1 unit regardless of cell size (simplification;
    # refine by weighting by footprint area if desired).
    # ------------------------------------------------------------------
    Q_k = int(Ck / Cp)   # tanker  drops per full tank
    Q_p = 1               # scooper carries 1 load, refills after each drop

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------
    mdl = Model('AFFVRP_discretised')
    mdl.setParam('OutputFlag', 0)
    mdl.setParam('TimeLimit', GUROBI_TIME_LIMIT)

    # --- Decision variables ---

    # x_k[k, r, c, t]: tanker k is at cell (r,c) at timestep t
    x_k = mdl.addVars(K, cells, T, vtype=GRB.BINARY, name='x_k')

    # x_p[p, r, c, t]: scooper p is at cell (r,c) at timestep t
    x_p = mdl.addVars(P, cells, T, vtype=GRB.BINARY, name='x_p')

    # d_k[k, r, c, t]: tanker k drops water at cell (r,c) at timestep t
    # Only valid for burning cells
    d_k = mdl.addVars(K, burning_cells, T, vtype=GRB.BINARY, name='d_k')

    # d_p[p, r, c, t]: scooper p drops water at cell (r,c) at timestep t
    d_p = mdl.addVars(P, burning_cells, T, vtype=GRB.BINARY, name='d_p')

    # y[r, c, t, s]: cell (r,c) has state s at timestep t
    # s=0 unburned, s=1 burning, s=2 extinguished
    y = mdl.addVars(cells, T, [0, 1, 2], vtype=GRB.BINARY, name='y')

    # q_k[k, t]: water load of tanker k at timestep t (in drop units)
    q_k = mdl.addVars(K, T, vtype=GRB.INTEGER, lb=0, ub=Q_k, name='q_k')

    # q_p[p, t]: water load of scooper p (0 or 1)
    q_p = mdl.addVars(P, T, vtype=GRB.BINARY, name='q_p')

    # Z: time of last drop (min-max variable, absolute minutes)
    Z = mdl.addVar(vtype=GRB.CONTINUOUS, lb=0, name='Z')

    mdl.update()

    # ----------------------------------------------------------------
    # OBJECTIVE — Problem statement: minimise fire spread and time to
    # extinguishment. Primary = total burning cell-timesteps; secondary
    # = total flight distance.
    # ----------------------------------------------------------------
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

    # Hierarchical: primary burn minimisation >> secondary flight minimisation
    mdl.setObjectiveN(burn_sum, index=1, priority=10, name='MinBurn')
    mdl.setObjectiveN(flight_cost_k + flight_cost_p, index=0, priority=0, name='MinFlight')

    # ----------------------------------------------------------------
    # CONSTRAINTS
    # ----------------------------------------------------------------

    # 1. INITIAL FIRE STATE — set y[c,0,s] from the input grid
    for (r, c) in cells:
        s_init = int(grid[r, c])
        for s in [0, 1, 2]:
            mdl.addConstr(y[r, c, 0, s] == (1 if s == s_init else 0),
                          name=f'init_state_{r}_{c}_{s}')

    # 2. EXACTLY ONE STATE PER CELL PER TIMESTEP  Σ_s y[c,t,s] = 1
    for (r, c) in cells:
        for t in T:
            mdl.addConstr(
                quicksum(y[r, c, t, s] for s in [0, 1, 2]) == 1,
                name=f'one_state_{r}_{c}_{t}'
            )

    # 3. EXTINGUISHED IS ABSORBING — once extinguished, always extinguished
    #    y[c,t+1,2] >= y[c,t,2]
    for (r, c) in cells:
        for t in T[:-1]:
            mdl.addConstr(y[r, c, t + 1, 2] >= y[r, c, t, 2],
                          name=f'ext_absorb_{r}_{c}_{t}')

    # 4. FIRE PROPAGATION (simplified Moore neighbourhood)
    #    A cell ignites at t+1 if it is unburned at t, has a burning neighbour
    #    at t, and is not extinguished at t+1.
    #    y[r,c,t+1,1] >= y[r2,c2,t,1] - y[r,c,t+1,2]  for each neighbour
    #    y[r,c,t+1,1] <= Σ_neighbours y[r2,c2,t,1] + y[r,c,t,1]  (must have source)
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
            continue   # permanently extinguished; skip propagation constraints
        for t in T[:-1]:
            nb = _neighbours(r, c)
            # Lower bound: ignites if any neighbour is burning and cell not ext
            for (nr, nc) in nb:
                mdl.addConstr(
                    y[r, c, t + 1, STATE_BURNING] >=
                    y[nr, nc, t, STATE_BURNING] - y[r, c, t + 1, STATE_EXTINGUISHED],
                    name=f'prop_lb_{r}_{c}_{nr}_{nc}_{t}'
                )
            # Upper bound: can only burn if already burning or had burning neighbour
            mdl.addConstr(
                y[r, c, t + 1, STATE_BURNING] <=
                y[r, c, t, STATE_BURNING] +
                quicksum(y[nr, nc, t, STATE_BURNING] for (nr, nc) in nb),
                name=f'prop_ub_{r}_{c}_{t}'
            )

    # 5. SUPPRESSION COUPLING — a burning cell becomes extinguished if an aircraft
    #    drops water at it (or a cell in its footprint covers it).
    #    y[r,c,t+1,2] >= d_k[k,r2,c2,t] + y[r,c,t,1] - 1
    #    for any (r2,c2) whose footprint includes (r,c)
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

    # 6. AIRCRAFT LOCATION — each aircraft occupies exactly one cell per timestep
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

    # 7. AT MOST ONE AIRCRAFT PER CELL PER TIMESTEP
    for (r, c) in cells:
        for t in T:
            mdl.addConstr(
                quicksum(x_k[k, r, c, t] for k in K) +
                quicksum(x_p[p, r, c, t] for p in P) <= 1,
                name=f'one_ac_{r}_{c}_{t}'
            )

    # 8. LINEAR FLIGHT DYNAMICS — an aircraft at (r1,c1) at t can only be at
    #    cells reachable within its speed limit at t+1.
    #    |r1-r2| + |c1-c2| <= V  (Manhattan distance proxy for speed limit)
    #    Problem statement: "linear flight dynamics prevent physically unrealistic
    #    manoeuvres."
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

    # 9. DROP ONLY WHEN AT CELL (must be present to drop)
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

    # 10. DROP ONLY ON BURNING CELLS (problem statement: aircraft only fly over
    #     burning areas during water release)
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

    # 11. TANKER WATER CAPACITY DYNAMICS
    #     q_k[k,0] = Q_k  (full at start of window)
    #     q_k[k,t+1] = q_k[k,t] - drops_at_t  (decrease by drops made)
    #     If tanker returns to airfield, reset to Q_k (handled via big-M)
    at_airfield_k = {}
    for k in K:
        for t in T:
            at_airfield_k[k, t] = x_k[k, AIRFIELD_CELL[0], AIRFIELD_CELL[1], t]

    for k in K:
        mdl.addConstr(q_k[k, 0] == Q_k, name=f'q_k_init_{k}')
    for k in K:
        for t in T[:-1]:
            drops_t = quicksum(d_k[k, r, c, t] for (r, c) in burning_cells)
            # If at airfield: refill to Q_k; otherwise decrease by drops
            mdl.addConstr(
                q_k[k, t + 1] <=
                Q_k * at_airfield_k[k, t] + q_k[k, t] - drops_t,
                name=f'q_k_ub_{k}_{t}'
            )
            mdl.addConstr(
                q_k[k, t + 1] >= q_k[k, t] - drops_t,
                name=f'q_k_lb_{k}_{t}'
            )
            # Cannot drop with empty tank
            mdl.addConstr(
                drops_t <= q_k[k, t],
                name=f'q_k_nonempty_{k}_{t}'
            )

    # 12. SCOOPER WATER CAPACITY DYNAMICS
    #     Scooper carries one load (q_p in {0,1}). After a drop, must visit a
    #     water cell to refill. Problem statement §2.0.5: "fill only at zero
    #     ground speed over a water source" — modelled as: must be AT a water
    #     cell at the next timestep to set q_p back to 1.
    water_set = set(map(tuple, WATER_CELLS))

    def _at_water(p, t):
        return quicksum(
            x_p[p, wr, wc, t] for (wr, wc) in WATER_CELLS
        )

    for p in P:
        mdl.addConstr(q_p[p, 0] == 1, name=f'q_p_init_{p}')
    for p in P:
        for t in T[:-1]:
            drops_t = quicksum(d_p[p, r, c, t] for (r, c) in burning_cells)
            # After a drop the load is 0 unless the scooper is at water next step
            mdl.addConstr(
                q_p[p, t + 1] <= 1 - drops_t + _at_water(p, t + 1),
                name=f'q_p_ub_{p}_{t}'
            )
            mdl.addConstr(
                q_p[p, t + 1] >= _at_water(p, t + 1) - drops_t,
                name=f'q_p_lb_{p}_{t}'
            )
            # Cannot drop with empty tank
            mdl.addConstr(
                drops_t <= q_p[p, t],
                name=f'q_p_nonempty_{p}_{t}'
            )

    # 13. TANKER START/END AT AIRFIELD
    for k in K:
        mdl.addConstr(x_k[k, AIRFIELD_CELL[0], AIRFIELD_CELL[1], 0] == 1,
                      name=f'k_start_{k}')
        mdl.addConstr(x_k[k, AIRFIELD_CELL[0], AIRFIELD_CELL[1], T[-1]] == 1,
                      name=f'k_end_{k}')

    # 14. SCOOPER START AT AIRFIELD (returns not required within a window;
    #     continuity between windows handled by the orchestrator)
    for p in P:
        mdl.addConstr(x_p[p, AIRFIELD_CELL[0], AIRFIELD_CELL[1], 0] == 1,
                      name=f'p_start_{p}')

    # 15. MIN-MAX CONSTRAINT (Z): Z >= time of each drop (absolute minutes)
    #     This captures time-to-extinguishment for priority cells.
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

    # ----------------------------------------------------------------
    # SOLVE
    # ----------------------------------------------------------------
    mdl.optimize()

    # ----------------------------------------------------------------
    # EXTRACT RESULTS
    # ----------------------------------------------------------------
    status = mdl.Status
    status_map = {2: 'OPTIMAL', 3: 'INFEASIBLE', 5: 'UNBOUNDED', 9: 'TIME_LIMIT'}
    status_str = status_map.get(status, f'CODE_{status}')

    if status in (GRB.OPTIMAL, GRB.TIME_LIMIT) and mdl.SolCount > 0:
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
        'gap':           mdl.MIPGap if mdl.SolCount > 0 else None
    }
