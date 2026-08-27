import numpy as np
import matplotlib.pyplot as plt
import gurobipy as gp
from gurobipy import GRB

np.random.seed(0)
n = 20 #Number of clients
xc = np.random.rand(n+1) * 200 #x coordinates
yc = np.random.rand(n+1) * 100 #y coordinates

N = list(range(1,n+1)) #is set of clients
V = [0] + N #is set of vertices including the depot
A = [(i,j) for i in V  for j in V if i != j] #all possible routes
c = {}
for i,j in A:
    dis = np.hypot(xc[j]-xc[i],yc[j]-yc[i])
    c[(i,j)] = dis #cost function 

Q = 20 #vehicle capacity
q = {}
for i in N:
    q[(i)] = np.random.randint(1,10)

model = gp.Model("VRP")

x = model.addVars(A, vtype = GRB.BINARY)
u = model.addVars(N, vtype=GRB.CONTINUOUS)

model.setObjective(gp.quicksum(x[i,j] * c[(i,j)] for i,j in A),GRB.MINIMIZE) #minimise cost

for i in N:
    model.addConstr(gp.quicksum(x[i, j] for j in V if j != i) ==1)

for j in N:
    model.addConstr(gp.quicksum(x[i, j] for i in V if i != j) ==1)

#addConstr vs addConstrs
#addConstr if you have single constraint expression such as model.addConstr(gp.quicksum(x[i, j] for i in V if i != j) ==1)
#addConstrs if you multiple constraints but want one constraint per index such as:
#model.addConstrs(gp.quicksum((x[i,j] for j in V if j != i) == 1 for i in N)
#this adds multiple constraints for each i and is used now in the following steps

model.addConstrs((x[i,j] == 1) >> (u[i] + q[i] == u[j]) for i,j in A if i != 0 and j != 0)

#if x[i,j] = 1 then it implies that u[i] + q[j] = u[j]. CANNOT WRITE AS: 
#model.addConstr(u[i] + q[j] == u[j] for i,j in A if x[i,j] == 1 and i != 0 and j != 0)
#since python cannot evaluate x[i,j] == 1 since this is a gurobi variable and will not return true or false

model.addConstrs(u[i] >= q[i] for i in N)
model.addConstrs(Q >= u[i] for i in N)


model.Params.MIPGap = 0.1 #stops when you have 10% accuracy
model.Params.TimeLimit = 30 #stops after 30 secs
model.optimize()

active_arcs = [a for a in A if x[a].x > 0.9]
for i,j in active_arcs: 
    plt.plot([xc[i],xc[j]],[yc[i],yc[j]],c='r')


plt.scatter(xc[1:],yc[1:],c="b")
plt.plot(xc[0],yc[0],marker='s',c="g") #depot
plt.show()
