from gurobipy import * 
milp_model = Model("milp_model") # Creates a MILP model 
x = milp_model.addVar(vtype=GRB.BINARY, name= 'x', lb=0) # Creates a new decision variable named x which is binary [0,1]
y = milp_model.addVar(vtype=GRB.CONTINUOUS, name = 'y', lb=0) #Continous variable y
z = milp_model.addVar(vtype=GRB.INTEGER, name = 'z',lb= 0) #Lower BOund = 0

obj_fn = 2 * x + y + 3 * z
milp_model.setObjective(obj_fn, GRB.MAXIMIZE) # Maximise the objective function

c1 = milp_model.addConstr(x + 2*y +z <= 4, "c1") #Set constraints
c2 = milp_model.addConstr(2* z + y <= 5, "c2") #Set constraints
c3 = milp_model.addConstr(x + y >= 1, "c1") #Set constraints

milp_model.optimize() #Runs the optimisation

print('Objective Function Value: %.2f' % milp_model.ObjVal) #Prints the final objective value
for v in milp_model.getVars():
    print('%s: %g' % (v.varName, v.X)) #Prints individual variable value