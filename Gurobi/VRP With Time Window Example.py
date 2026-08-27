import gurobipy as gp
from gurobipy import GRB


nodes = range(4) #0 - depot
customers = nodes[1:]

distance = {
    (0,1):4, (0,2):6, (0,3):9,
    (1,0):4, (1,2):5, (1,3):3,
    (2,0):6, (2,1):5, (2,3):4,
    (3,0):9, (3,1):3, (3,2):4
} #here distance = time taken by the vehicle

service_times = {0:0 , 1:2, 2:2, 3:2}

#Time windows
e = {0:0, 1:5, 2:0, 3: 10} #earliest the vehicle can reach
l = {0:100, 1:15, 2:12, 3:20} #latest the vehcile can reach

#Big M
M = max(distance.values()) + max(service_times.values()) + max(l.values()) #Makes sure that no time is higher than this

model = gp.Model("VRPTW")

x = model.addVars(distance.keys(), vtype = GRB.BINARY)

t = model.addVars(nodes, vtype = GRB.CONTINUOUS) #why nodes? 

model.setObjective(gp.quicksum(distance[i,j] * x[i,j] for (i,j) in distance.keys()),
                   GRB.MINIMIZE)

model.addConstrs(gp.quicksum(x[i,j] for i in nodes if (i,j) in distance.keys())
                 == 1 for j in customers) #incoming flow = 1

model.addConstrs(gp.quicksum(x[i,j] for j in nodes if (i,j) in distance.keys()) 
                 == 1 for i in customers) #outgoing flow = 1

model.addConstrs(t[i] >= e[i] for i in nodes) #should arrive after earliest time
model.addConstrs((t[i] )<= l[i] for i in nodes) #should leave before latest time

model.addConstrs((t[j] >= t[i] + service_times[i] + distance[i,j] - M * (1-x[i,j])
                  ) for (i,j) in distance.keys() if j!= 0) #Time flow constraint

model.addConstr(t[0] == 0)

model.optimize()

if model.status == GRB.OPTIMAL:
    print("\nOptimal total distance:", model.objVal)
    
    print("\nRoute:")
    for (i,j) in distance:
        if x[i,j].X > 0.5:
            print(f"{i} -> {j}")
    
    print("\nArrival Times:")
    for i in nodes:
        print(f"Node {i}: {t[i].X:.2f}")



