import gurobipy as gp
from gurobipy import GRB
import math

coords       = {0: (0,0), 1: (20,10), 2: (5,30), 3: (15,25), 4: (10,5)}
nodes        = list(coords.keys())
fire_zones   = [1,2,3]
vehicles     = range(3)

capacity     = {0: 15000, 1: 3000, 2: 4000}
demand       = {0: 0, 1: 12000, 2: 10500, 3: 8000, 4: 0}
speed        = {0: 5, 1: 15, 2: 10}
water_source = 4

e       = {0: 0,     1: 0,     2: 20,    3: 10,    4: 0}
l       = {0: 200, 1: 60, 2: 80, 3: 70, 4: 200}
service = {0: 0,     1: 5,     2: 5,     3: 5,     4: 5}

M_time = 50000
M_load = 20000

def dist(i, j):
    dx = coords[i][0] - coords[j][0]
    dy = coords[i][1] - coords[j][1]
    return math.sqrt(dx**2 + dy**2)

model = gp.Model("VRPTW_Heterogeneous_Fleet")
arcs = [(i,j) for i in nodes for j in nodes if i != j]

x = model.addVars(nodes, nodes, vehicles, vtype=GRB.BINARY,    name='x')
T = model.addVars(nodes, vehicles,        vtype=GRB.CONTINUOUS, name='T')
L = model.addVars(nodes, vehicles,        vtype=GRB.CONTINUOUS, name='L')
u = model.addVars(nodes, vehicles,        vtype=GRB.CONTINUOUS, name='u')
d= model.addVars(fire_zones, vehicles, vtype = GRB.CONTINUOUS, name = 'd')

t = {(i,j,k): dist(i,j)/speed[k]
     for i in nodes for j in nodes for k in vehicles if i != j}

# Objective
model.setObjective(
    gp.quicksum(x[i,j,k]*t[i,j,k] for (i,j) in arcs for k in vehicles),
    GRB.MINIMIZE
)

# # C0 — forcing tanker 1 to be used
# model.addConstr(
#     (gp.quicksum(x[0,j,1] for j in nodes if j!=0) == 1), name='forcing'
# )

# C1 — each fire zone visited exactly once
model.addConstrs(
    (gp.quicksum(x[i,j,k] for i in nodes for k in vehicles if i != j) >= 1
     for j in fire_zones), name='coverage'
)

# C2 — flow conservation
for k in vehicles:
    for i in nodes:
        model.addConstr(
            gp.quicksum(x[i,j,k] for j in nodes if j != i) ==
            gp.quicksum(x[j,i,k] for j in nodes if j != i), name=f'flow_conservation_{i}_{k}'
        )

# C3 — each vehicle departs depot at most once
model.addConstrs(
    (gp.quicksum(x[0,j,k] for j in nodes if j != 0) <= 1
     for k in vehicles), name='depot_out'
)

# C5 — time propagation
for i in nodes:
    for j in nodes:
        for k in vehicles:
            if i != j and j!=0:
                model.addConstr(
                    T[j,k] >= T[i,k] + service[i] + t[i,j,k] - M_time*(1 - x[i,j,k]),name = 'time_propogation'
                )

# C6 — time window lower bound
model.addConstrs(
    (T[j,k] >= e[j] for j in nodes for k in vehicles), name='tw_lower'
)

for j in fire_zones:
    for k in vehicles:
        model.addConstr(
            d[j,k] <= capacity[k] * gp.quicksum(x[i,j,k] for i in nodes if i != j),
            name=f'drop_requires_visit_{j}_{k}'
        )

# C7 — time window upper bound
for j in nodes:
    for k in vehicles:
        model.addConstr(
            T[j,k] <= l[j] + M_time*(1 - gp.quicksum(x[i,j,k] for i in nodes if i != j)), name = 'tw_upper'
        )

# C8 — load propagation (exclude depot as destination AND water source as origin)
for i in nodes:
    for j in nodes:
        for k in vehicles:
            if i != j and j != 0 and j != water_source:
                model.addConstr(
                    L[j,k] <= L[i,k] - d[j,k]*x[i,j,k] + M_load*(1 - x[i,j,k])
                )
                model.addConstr(
                    L[j,k] >= L[i,k] - d[j,k]*x[i,j,k] - M_load*(1 - x[i,j,k])
                )

# Drop cannot exceed what the vehicle carries
for j in fire_zones:
    for k in vehicles:
        model.addConstr(d[j,k] <= capacity[k])   # can't drop more than you have

# Drop cannot exceed zone demand
for j in fire_zones:
    for k in vehicles:
        model.addConstr(d[j,k] <= demand[j])

# Total drops across all vehicles must meet zone demand
model.addConstrs(
    (gp.quicksum(d[j,k] for k in vehicles) >= demand[j]
     for j in fire_zones), name='demand_met'
)
# C9 — load reset at water source
model.addConstrs(
    (L[water_source, k] == capacity[k] for k in vehicles), name='lake_refill'
)

#C10 — sufficient water before each drop (fixed)
# for i in nodes:
#     for j in fire_zones:
#         for k in vehicles:
#             if i != j:
#                 model.addConstr(L[i,k] >= demand[j] * x[i,j,k], name = "water_sufficiency")

# C11 — full tank at depot
model.addConstrs(
    (L[0,k] == capacity[k] for k in vehicles), name='full_start'
)

# C12 — load bounds
model.addConstrs((L[i,k] >= 0         for i in nodes for k in vehicles), name = 'LowerLoadBound')
model.addConstrs((L[i,k] <= capacity[k] for i in nodes for k in vehicles), name='UpperLoadBound')

# C13 — MTZ subtour elimination (non-depot nodes only)
for k in vehicles:
    for i in nodes:
        for j in nodes:
            if i != j and i != 0 and j != 0:
                model.addConstr(
                    u[i,k] - u[j,k] + len(nodes)*x[i,j,k] <= len(nodes) - 1,name="MTZ_elimination"
                )

model.write("VRPTW_het_fleet.lp")
model.optimize()

node_names    = {0:'Depot', 1:'Zone 1', 2:'Zone 2', 3:'Zone 3', 4:'Lake'}
vehicle_names = {0:'VLAT', 1:'Tanker 1', 2:'Tanker 2'}

if model.Status == GRB.INFEASIBLE:
    print("\nModel is infeasible. Computing IIS...\n")
    model.computeIIS()
    model.write("model.ilp")
    for c in model.getConstrs():
        if c.IISConstr:
            print(f"Infeasible constraint: {c.ConstrName}")

elif model.Status == GRB.OPTIMAL:
    print(f'\nObjective: {model.ObjVal:.4f} min\n')
    for k in vehicles:
        print(f'── {vehicle_names[k]} ──')
        if any(x[i,j,k].X > 0.5 for (i,j) in arcs):
            for (i,j) in arcs:
                if x[i,j,k].X > 0.5:
                    print(f'  {node_names[i]:10s} -> {node_names[j]:10s}'
                          f' | arrive t={T[j,k].X:.1f}  water={L[j,k].X:.0f}L')
            print()


# import gurobipy as gp
# from gurobipy import GRB

# # ── Parameters ──────────────────────────────────────────
# ROWS, COLS = 5, 5
# cells = [(r,c) for r in range(ROWS) for c in range(COLS)]
# T = range(10)           # time steps 0..9 #tf is this? 
# A = range(3)            # aircraft 0,1,2
# Q = {0: 15000, 1: 3000, 2: 3000}   # water capacity per aircraft
# V = 2                   # max cells per time step (speed)
# drop = 1000             # water used per drop per time step
# water_sources = {(0,0), (4,4)}
# fire_init = {(2,2)}

# def neighbours(r, c):
#     return [(r+dr, c+dc) for dr,dc in [(-1,0),(1,0),(0,-1),(0,1)]
#             if 0<=r+dr<ROWS and 0<=c+dc<COLS]

# m = gp.Model('FirefightingVRPTW')
# m.Params.TimeLimit = 300

# # ── Decision Variables ───────────────────────────────────
# x = m.addVars(A, cells, T, vtype=GRB.BINARY, name='x')   # aircraft at cell
# y = m.addVars(cells, T, vtype=GRB.BINARY, name='y')       # cell burning
# e = m.addVars(cells, T, vtype=GRB.BINARY, name='e')       # cell extinguished
# w = m.addVars(A, T, vtype=GRB.BINARY, name='w')           # aircraft refilling
# q = m.addVars(A, T, vtype=GRB.CONTINUOUS, lb=0, name='q') # water remaining

# # ── Objective ────────────────────────────────────────────
# m.setObjective(gp.quicksum(y[r,c,t] for (r,c) in cells for t in T), GRB.MINIMIZE)

# # ── Initial conditions ───────────────────────────────────
# for (r,c) in cells:
#     m.addConstr(y[r,c,0] == (1 if (r,c) in fire_init else 0))
#     m.addConstr(e[r,c,0] == 0)
# for a in A:
#     m.addConstr(q[a,0] == Q[a])

# # ── One aircraft per cell per time step ─────────────────
# m.addConstrs(
#     (gp.quicksum(x[a,r,c,t] for a in A) <= 1
#      for (r,c) in cells for t in T), 'one_per_cell')

# # ── Each aircraft at exactly one location ────────────────
# m.addConstrs(
#     (gp.quicksum(x[a,r,c,t] for (r,c) in cells) + w[a,t] == 1
#      for a in A for t in T), 'location')

# # ── Movement (speed) constraint ──────────────────────────
# for a in A:
#     for t in T:
#         if t < max(T):
#             for (r1,c1) in cells:
#                 for (r2,c2) in cells:
#                     if abs(r1-r2)+abs(c1-c2) > V:
#                         m.addConstr(x[a,r1,c1,t] + x[a,r2,c2,t+1] <= 1)

# # ── Water dynamics ───────────────────────────────────────
# for a in A:
#     for t in T:
#         if t < max(T):
#             # Refill: if at water source, reset to Q
#             m.addConstr(q[a,t+1] <= Q[a]*w[a,t] + q[a,t])
#             # Consumption: drop water when flying over cells
#             m.addConstr(q[a,t+1] <= q[a,t] - drop*(1-w[a,t]) + Q[a]*w[a,t])
#             # Must have water to drop
#             m.addConstr(q[a,t] >= drop*(1 - w[a,t]))

# # ── Refill only at water sources ─────────────────────────
# for a in A:
#     for t in T:
#         m.addConstr(
#             w[a,t] <= gp.quicksum(x[a,r,c,t]
#                 for (r,c) in water_sources))

# # ── Fire suppression ─────────────────────────────────────
# for (r,c) in cells:
#     for t in T:
#         if t < max(T):
#             # Stays extinguished
#             m.addConstr(e[r,c,t+1] >= e[r,c,t])
#             # Extinguished if aircraft visits burning cell
#             for a in A:
#                 m.addConstr(e[r,c,t+1] >= x[a,r,c,t] + y[r,c,t] - 1)

# # ── Fire propagation ─────────────────────────────────────
# for (r,c) in cells:
#     for t in T:
#         if t < max(T):
#             nb = neighbours(r,c)
#             # Burns next step if a neighbour burns now and not extinguished
#             for (r2,c2) in nb:
#                 m.addConstr(y[r,c,t+1] >= y[r2,c2,t] - e[r,c,t+1])
#             # Cannot burn if extinguished
#             m.addConstr(y[r,c,t] + e[r,c,t] <= 1)
#             # Can only burn if had a burning neighbour (or was already burning)
#             m.addConstr(
#                 y[r,c,t+1] <= y[r,c,t] +
#                 gp.quicksum(y[r2,c2,t] for (r2,c2) in nb))

# m.optimize()

# # ── Print results ────────────────────────────────────────
# print(f'Total burn area-time: {m.ObjVal:.0f}')
# for t in T:
#     burning = [(r,c) for (r,c) in cells if y[r,c,t].X > 0.5]
#     print(f't={t}: {len(burning)} burning cells: {burning}')
#     for a in A:
#         loc = [(r,c) for (r,c) in cells if x[a,r,c,t].X > 0.5]
#         if loc: print(f'  Aircraft {a} at {loc[0]}, water={q[a,t].X:.0f}L')
#         elif w[a,t].X > 0.5: print(f'  Aircraft {a} refilling')
