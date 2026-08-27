import gurobipy as gp
from gurobipy import GRB

n = 5
nodes = range(n)
customers = nodes[1:]
vehicles = [0, 1]

demand = {1: 15, 2: 20, 3: 10, 4: 25}
max_cap = {0: 40, 1: 40}

cost = {
    (0,1): 8,  (0,2): 12, (0,3): 6,  (0,4): 10,
    (1,0): 8,  (1,2): 9,  (1,3): 7,  (1,4): 14,
    (2,0): 12, (2,1): 9,  (2,3): 11, (2,4): 5,
    (3,0): 6,  (3,1): 7,  (3,2): 11, (3,4): 13,
    (4,0): 10, (4,1): 14, (4,2): 5,  (4,3): 13,
}

model = gp.Model("Multi-Vehicle")

arcs = list(cost.keys())

x = model.addVars(nodes, nodes, vehicles, vtype = GRB.BINARY) #x(i,j,k) i to j with k
u = model.addVars(nodes, vehicles, vtype = GRB.CONTINUOUS) #for subtour elimination

model.setObjective(gp.quicksum(cost[i,j] * x[i,j,k] for (i,j) in arcs for k in vehicles),GRB.MINIMIZE) 

model.addConstrs(gp.quicksum((x[i,j,k] for i in nodes for k in vehicles if i != j)) == 1 for j in customers) #ensures that each node is only reached once

model.addConstrs(gp.quicksum((x[0,j,k] for j in customers)) <= 1  for k in vehicles) #ensures that the vehicle leaves the depot max once

for k in vehicles:
    for i in nodes:
        model.addConstr(gp.quicksum(x[i,j,k] for j in nodes if i != j)
                        == gp.quicksum(x[j,i,k] for j in nodes if i != j)) #flow conservation
        


model.addConstrs(gp.quicksum(demand[j] * x[i,j,k] for (i,j) in arcs if j in customers) <= max_cap[k] for k in vehicles)

#MTZ SUBTOUR ELIMINATION: 
#A subtour is essentially a disconnected loop that doesn't pass through the depot.
#So a vehicle could go 1-2-1 and never go through the depot. This forces it to start and end at a depot

for k in vehicles:
    for i in customers:
        for j in customers:
            if i != j:
                model.addConstr(u[i,k] - u[j,k] + n * x[i,j,k] <= n -1)


model.optimize()

for k in vehicles:
    print(f"Vehicle {k} route:")
    for i in nodes:
        for j in nodes:
            if i !=j and x[i,j,k].X > 0.5:
                print(f"{i}  ---->  {j}")

        


