"""
Problem 5 — Discretised Aerial Firefighting VRPTW
==================================================
FIX: The original code required the full cell_demand (2000L) to be delivered
in a SINGLE time step for extinguishment.  Because C1 allows at most one
aircraft per cell per step, Tanker 1 and Tanker 2 (drop_rate=1000L each)
could never independently extinguish a cell, so the solver ignored them.

Fix: Track CUMULATIVE water delivered to each cell across all time steps.
Extinguishment triggers once cumulative delivery >= cell_demand, letting two
tankers each make a separate pass and together extinguish a cell.
"""

import gurobipy as gp
from gurobipy import GRB

# ── Parameters ────────────────────────────────────────────────────────────────

ROWS, COLS  = 5, 5
cells       = [(r, c) for r in range(ROWS) for c in range(COLS)]
T_steps     = list(range(10))          # discrete time steps 0 … 9
A           = [0, 1, 2]               # aircraft: 0 = VLAT, 1 = Tanker 1, 2 = Tanker 2

capacity    = {0: 15000, 1: 3000, 2: 3000}   # litres — mirrors P4 fleet
drop_rate   = {0:  3000, 1: 1000, 2: 1000}   # max L dropped per time step
cell_demand = 2000                            # L required to extinguish one cell

V = 2                                         # max Manhattan distance per step

water_cells = {(0, 0), (4, 4)}               # cells that act as water sources
fire_init   = {(2, 2)}                        # cells burning at t = 0

aircraft_names = {0: "VLAT", 1: "Tanker 1", 2: "Tanker 2"}

def neighbours(r, c):
    return [(r + dr, c + dc)
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]
            if 0 <= r + dr < ROWS and 0 <= c + dc < COLS]

# Big-M for water dynamics
M_w = max(capacity.values()) + cell_demand

# ── Model ──────────────────────────────────────────────────────────────────────

model = gp.Model("FirefightingVRPTW_P5_fixed")
model.Params.TimeLimit = 60

# ── Decision Variables ─────────────────────────────────────────────────────────

# Routing / position
x = model.addVars(A, cells, T_steps,
                  vtype=GRB.BINARY, name="x")           # aircraft a at cell (r,c) at t

# Fire state
y = model.addVars(cells, T_steps,
                  vtype=GRB.BINARY, name="y")           # cell (r,c) burning at t
e = model.addVars(cells, T_steps,
                  vtype=GRB.BINARY, name="e")           # cell (r,c) extinguished at t

# Water on aircraft
q = model.addVars(A, T_steps,
                  vtype=GRB.CONTINUOUS, lb=0, name="q")

# Partial drop per step
d = model.addVars(A, cells, T_steps,
                  vtype=GRB.CONTINUOUS, lb=0, name="d")

# Refill indicator
is_at_water = model.addVars(A, T_steps,
                             vtype=GRB.BINARY, name="wat")

# ── FIX: Cumulative water delivered to each cell ──────────────────────────────
# s[r,c,t] = total litres dropped on cell (r,c) across steps 0..t
# This allows tankers with drop_rate < cell_demand to cooperate over multiple
# steps rather than needing to deliver cell_demand in one visit.
s = model.addVars(cells, T_steps,
                      vtype=GRB.CONTINUOUS, lb=0, name="s")

# ── Objective ─────────────────────────────────────────────────────────────────

model.setObjective(
    gp.quicksum(y[r, c, t] for (r, c) in cells for t in T_steps),
    GRB.MINIMIZE
)

# ═══════════════════════════════════════════════════════════════════════════════
# INITIAL CONDITIONS
# ═══════════════════════════════════════════════════════════════════════════════

for (r, c) in cells:
    model.addConstr(y[r, c, 0] == (1 if (r, c) in fire_init else 0),
                    name=f"y_init_{r}_{c}")
    model.addConstr(e[r, c, 0] == 0,
                    name=f"e_init_{r}_{c}")

for a in A:
    model.addConstr(q[a, 0] == capacity[a], name=f"q_init_{a}")

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING CONSTRAINTS
# ═══════════════════════════════════════════════════════════════════════════════

# C1 — At most one aircraft per cell per time step
model.addConstrs(
    (gp.quicksum(x[a, r, c, t] for a in A) <= 1
     for (r, c) in cells for t in T_steps),
    name="one_per_cell"
)

# C2 — Each aircraft occupies exactly one cell per time step
model.addConstrs(
    (gp.quicksum(x[a, r, c, t] for (r, c) in cells) == 1
     for a in A for t in T_steps),
    name="one_cell_per_aircraft"
)

# C3 — Refill indicator
model.addConstrs(
    (is_at_water[a, t] == gp.quicksum(x[a, r, c, t] for (r, c) in water_cells)
     for a in A for t in T_steps),
    name="is_at_water"
)

# C4 — Movement: speed limit V cells per step (Manhattan distance)
for a in A:
    for t in T_steps[:-1]:
        for (r1, c1) in cells:
            for (r2, c2) in cells:
                if abs(r1 - r2) + abs(c1 - c2) > V:
                    model.addConstr(
                        x[a, r1, c1, t] + x[a, r2, c2, t + 1] <= 1,
                        name=f"move_{a}_{t}_{r1}{c1}_{r2}{c2}"
                    )

# ═══════════════════════════════════════════════════════════════════════════════
# DROP CONSTRAINTS
# ═══════════════════════════════════════════════════════════════════════════════

# C5 — Can only drop at the occupied cell, up to drop_rate
for a in A:
    for (r, c) in cells:
        for t in T_steps:
            model.addConstr(
                d[a, r, c, t] <= drop_rate[a] * x[a, r, c, t],
                name=f"drop_at_cell_{a}_{r}_{c}_{t}"
            )

# C6 — No drops at water source cells
for a in A:
    for (r, c) in water_cells:
        for t in T_steps:
            model.addConstr(
                d[a, r, c, t] == 0,
                name=f"no_drop_at_water_{a}_{r}_{c}_{t}"
            )

# C7 — Drop cannot exceed cell demand per step (no wasted water in a single step)
for (r, c) in cells:
    for t in T_steps:
        model.addConstr(
            gp.quicksum(d[a, r, c, t] for a in A) <= cell_demand,
            name=f"drop_cap_{r}_{c}_{t}"
        )

# C7b — No drops on already-extinguished cells (prevents wasted water)
for a in A:
    for (r, c) in cells:
        for t in T_steps:
            model.addConstr(
                d[a, r, c, t] <= drop_rate[a] * (1 - e[r, c, t]),
                name=f"no_drop_if_ext_{a}_{r}_{c}_{t}"
            )

# ═══════════════════════════════════════════════════════════════════════════════
# WATER DYNAMICS
# ═══════════════════════════════════════════════════════════════════════════════

for a in A:
    for t in T_steps[:-1]:
        total_drop_t = gp.quicksum(d[a, r, c, t] for (r, c) in cells)

        model.addConstr(
            q[a, t + 1] >= q[a, t] - total_drop_t - M_w * is_at_water[a, t],
            name=f"q_consume_lb_{a}_{t}"
        )
        model.addConstr(
            q[a, t + 1] <= q[a, t] - total_drop_t + M_w * is_at_water[a, t],
            name=f"q_consume_ub_{a}_{t}"
        )
        model.addConstr(
            q[a, t + 1] >= capacity[a] - M_w * (1 - is_at_water[a, t]),
            name=f"q_refill_{a}_{t}"
        )
        model.addConstr(q[a, t + 1] <= capacity[a], name=f"q_cap_{a}_{t}")

# Must have sufficient water before dropping
for a in A:
    for t in T_steps:
        model.addConstr(
            q[a, t] >= gp.quicksum(d[a, r, c, t] for (r, c) in cells),
            name=f"water_sufficiency_{a}_{t}"
        )

# Load upper bounds
model.addConstrs(
    (q[a, t] <= capacity[a] for a in A for t in T_steps),
    name="q_ub"
)


# s[r,c,t] accumulates all drops on cell (r,c) through step t.
# Extinguishment is triggered when s reaches cell_demand, so aircraft
# with drop_rate < cell_demand (tankers, 1000L) can cooperate over multiple
# visits instead of needing to deliver 2000L in a single step.

for (r, c) in cells:
    # At t=0: cumulative = drops at t=0
    model.addConstr(
        s[r, c, 0] == gp.quicksum(d[a, r, c, 0] for a in A),
        name=f"s_init_{r}_{c}"
    )
    # At subsequent steps: accumulate
    for t in T_steps[1:]:
        model.addConstr(
            s[r, c, t] == s[r, c, t - 1] +
            gp.quicksum(d[a, r, c, t] for a in A),
            name=f"s_{r}_{c}_{t}"
        )
    # Cap cumulative at cell_demand (no point delivering more)
    for t in T_steps:
        model.addConstr(
            s[r, c, t] <= cell_demand,
            name=f"s_cap_{r}_{c}_{t}"
        )

# ═══════════════════════════════════════════════════════════════════════════════
# FIRE SUPPRESSION
# ═══════════════════════════════════════════════════════════════════════════════

for (r, c) in cells:
    for t in T_steps[:-1]:
        # Once extinguished, stays extinguished
        model.addConstr(e[r, c, t + 1] >= e[r, c, t],
                        name=f"e_persist_{r}_{c}_{t}")

        # FIX: extinguishment requires cumulative water >= cell_demand
        # (replaces the original single-step requirement)
        #   cell_demand * e[r,c,t+1] <= s[r,c,t]
        # i.e., e[r,c,t+1] can only be 1 if s[r,c,t] >= cell_demand
        model.addConstr(
            cell_demand * e[r, c, t + 1] <= s[r, c, t],
            name=f"e_needs_cumwater_{r}_{c}_{t}"
        )

        # Can only extinguish a burning cell
        model.addConstr(
            e[r, c, t + 1] - e[r, c, t] <= y[r, c, t],
            name=f"e_only_if_burning_{r}_{c}_{t}"
        )

        # Mutual exclusion: burning XOR extinguished
        model.addConstr(y[r, c, t] + e[r, c, t] <= 1,
                        name=f"burn_xor_ext_{r}_{c}_{t}")

# ═══════════════════════════════════════════════════════════════════════════════
# FIRE PROPAGATION
# ═══════════════════════════════════════════════════════════════════════════════

for (r, c) in cells:
    for t in T_steps[:-1]:
        nb = neighbours(r, c)

        # Persistence: already burning carries forward unless extinguished
        model.addConstr(
            y[r, c, t + 1] >= y[r, c, t] - e[r, c, t + 1],
            name=f"fire_persist_{r}_{c}_{t}"
        )

        # Spread from each burning neighbour (unless extinguished next step)
        for (r2, c2) in nb:
            model.addConstr(
                y[r, c, t + 1] >= y[r2, c2, t] - e[r, c, t + 1],
                name=f"fire_spread_{r}_{c}_{r2}_{c2}_{t}"
            )

        # Upper bound: fire can only start from a source
        model.addConstr(
            y[r, c, t + 1] <= y[r, c, t] +
            gp.quicksum(y[r2, c2, t] for (r2, c2) in nb),
            name=f"fire_ub_{r}_{c}_{t}"
        )

# ── Solve ──────────────────────────────────────────────────────────────────────

model.write("firefighting_p5_fixed.lp")
model.optimize()

# ── Results ────────────────────────────────────────────────────────────────────

if model.Status == GRB.INFEASIBLE:
    print("\nModel infeasible — computing IIS...\n")
    model.computeIIS()
    model.write("firefighting_p5_fixed.ilp")
    for c_obj in model.getConstrs():
        if c_obj.IISConstr:
            print(f"  Infeasible: {c_obj.ConstrName}")

elif model.Status in (GRB.OPTIMAL, GRB.TIME_LIMIT):
    status_str = "OPTIMAL" if model.Status == GRB.OPTIMAL else "TIME LIMIT (best found)"
    print(f"\nStatus : {status_str}")
    print(f"Total burn area-time : {model.ObjVal:.0f} cell-steps\n")

    for t in T_steps:
        burning      = [(r, c) for (r, c) in cells if y[r, c, t].X > 0.5]
        extinguished = [(r, c) for (r, c) in cells if e[r, c, t].X > 0.5]
        print(f"── t={t:2d}  burning={len(burning):2d} cells  extinguished={len(extinguished)} ──")
        for a in A:
            loc = [(r, c) for (r, c) in cells if x[a, r, c, t].X > 0.5]
            if loc:
                (r, c) = loc[0]
                drop_here = sum(d[a, r2, c2, t].X
                                for (r2, c2) in cells if d[a, r2, c2, t].X > 0.5)
                cum_here  = s[r, c, t].X
                refill_tag = " [REFILLING]" if is_at_water[a, t].X > 0.5 else ""
                print(f"   {aircraft_names[a]:10s}  cell=({r},{c})  "
                      f"water={q[a,t].X:6.0f}L  dropped={drop_here:.0f}L  "
                      f"cum_at_cell={cum_here:.0f}L{refill_tag}")
        if burning:
            print(f"   Burning cells : {burning}")
        print()