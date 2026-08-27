import gurobipy as gp
from gurobipy import GRB
import pandas as pd

customers = ["c1","c2","c3","c4","c5","c6"]
depots = ["d1","d2","d3","d4"] #3 - newcastle 4 - birmingham 5 - london 6 - exeter
factories = ["f1","f2"] #1 - liverpool 2 - brigton

supply = {"f1": 150000, "f2": 200000}
throughput = {"d1": 70000, "d2": 50000, "d3": 100000, "d4": 40000}
demand = {"c1":50000, "c2": 10000, "c3": 40000, "c4": 35000, "c5": 60000, "c6": 20000}

cost = {
    ("f1","d1"): 0.5,
    ("f1","d2"): 0.5,
    ("f1","d3"): 1,
    ("f1","d4"): 0.2,
    ("f2","d2"): 0.3,
    ("f2","d3"): 0.5,
    ("f2","d4"): 0.2,
    ("f1","c1"): 1,
    ("f1","c3"): 1.5,
    ("f1","c4"): 2,
    ("f1","c6"): 1,
    ("f2","c1"): 2,
    ("d1","c2"): 1.5,
    ("d1","c3"): 0.5,
    ("d1","c4"): 1.5,
    ("d1","c6"): 1.0,
    ("d2","c1"): 1.0,
    ("d2","c2"): 0.5,
    ("d2","c3"): 0.5,
    ("d2","c4"): 1.0,
    ("d2","c5"): 0.5,
    ("d3","c2"): 1.5,
    ("d3","c3"): 2.0,
    ("d3","c5"): 0.5,
    ("d3","c6"): 1.5,
    ("d4","c3"): 0.2,
    ("d4","c4"): 1.5,
    ("d4","c5"): 0.5,
    ("d4","c6"): 1.5,
}

arcs = list(cost.keys())

model = gp.Model("Transport")
flow = model.addVars(arcs, vtype= GRB.CONTINUOUS)

model.setObjective(gp.quicksum(cost[i,j] * flow[i,j] for i,j in arcs),GRB.MINIMIZE)

model.addConstrs(gp.quicksum(flow[i,j] for j in customers if (i,j) in arcs)<=supply[i] for i in factories)
model.addConstrs(gp.quicksum(flow[i,j] for i in factories + depots if (i,j) in arcs) == demand[j] for j in customers)

model.addConstrs((gp.quicksum(flow[i,j] for i in factories if (i,j) in arcs)
                  ==gp.quicksum(flow[j,k] for k in customers if (j,k) in arcs)) for j in depots)

model.addConstrs(gp.quicksum(flow[i,j] for i in factories if (i,j) in arcs)
                 <= throughput[j] for j in depots)

model.optimize()

product_flow = pd.DataFrame(columns=["From", "To", "Flow"])

for arc in arcs:
    if flow[arc].x > 1e-6:
        product_flow.loc[len(product_flow)] = [arc[0], arc[1], flow[arc].x]

product_flow.index=[""] * len(product_flow)
print(product_flow)