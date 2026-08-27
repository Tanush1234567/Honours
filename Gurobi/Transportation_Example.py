import gurobipy as gp
from gurobipy import GRB
import os

cwd = os.getcwd()

# Nodes
customers = [1,2,3]
warehouses = [1,2] 

#maximum supply at each warehouse
supply = {1: 35, 2: 50}

#demand from customers
demand = {1:30, 2:40, 3:15}

# Variable shipping cost per unit
# (from warehouse w to customer c)
cost = {
(1,1): 2,
(1,2): 4,
(1,3): 5,
(2,1): 3,
(2,2): 1,
(2,3): 7
}

# Fixed cost to open each warehouse
fixed_cost = {1: 500, 2: 400}

model = gp.Model("transportation_model_example")

#Define Variable

compact_form = True

#Defines both the control variables in one go. (note the function is addVars not addVar)
if compact_form:
    x = model.addVars(warehouses, customers, name = 'x', vtype=GRB.CONTINUOUS,lb = 0)
    y = model.addVars(warehouses, name = 'y', lb=0, vtype=GRB.BINARY)

#This allows for better control for each route. For example if warehouse 1 - customer 2 
#is not possible then we easily eliminate it here
else:
    x = {}
    for w in warehouses:
        for c in customers:
            x[w,c] = model.addVar(vtype=GRB.CONTINUOUS, name = 'x[w,c]', lb=0 )
    y = {}
    for w in warehouses:
        y[w] = model.addVar(vtype=GRB.BINARY, name = "y[w]", lb=0)

#Set the Objective of the Problem
model.setObjective(gp.quicksum(cost[w,c] * x[w,c] for w in warehouses for c in customers) + 
                   gp.quicksum(fixed_cost[w] for w in warehouses), GRB.MINIMIZE)

#Add Constraints that delivery = x[w,c] from a warehouse has to be less than the supply = supply[w] * y[w]

for w in warehouses: 
    model.addConstr(gp.quicksum(x[w,c] for c in customers) <= supply[w] * y[w])

#Delivery to a customer = demand of the point: x[w,c] = demand[w]
for c in customers:
    model.addConstr(gp.quicksum(x[w,c] for w in warehouses) == demand[c])

#Write the .lp file: This writes the whole optimisation problem in normal mathematical terms
#cwd - current working directory and makes a file of transportation_problem_example
model.write(os.path.join(cwd,"transportation_problem_example.lp"))

model.optimize()


#Post Process Data: 
if model.status == GRB.OPTIMAL: #If we found the optimal solution then- 
    print("\nOptimal solution found:\n")
    for w in warehouses:
        if y[w].x > 0.1: #if y[w] > 0 then the warehouse is open. Dont use 1 and 0 as there could be slight differences with exact values
            print(f"Warehouse {w} is OPEN (fixed cost ={fixed_cost[w]})")
            for c in customers:
                    if x[w, c].x > 1e-6: #same here if we use 0 then slight noises might cause a positive route when it never occured
                        print(f" Ship {x[w, c].x:.1f}units to {c}")
else:
    print(f"Warehouse {w} is CLOSED")
#.x signfies the use of the numerical value of y. Should be used after optimisation is ran

print(f"\nTotal cost = {model.objVal:.2f}")
