# -*- coding: utf-8 -*-
"""

@author: Wissam
Line 158 why define u as the trip counter as an extra variable and why not do it for scoopers (is it because they do not travel back)?
Why is Z (time of last drop) relevant
Explain how the fire zones work
"""

import numpy as np
import matplotlib.pyplot as plt
from gurobipy import Model, GRB, quicksum, LinExpr
import logging
from datetime import datetime
import os
from matplotlib.patches import Patch
import cartopy
import cartopy.crs as ccrs


os.chdir('C:/Users/wsm92/Documents/ATO/Thesis/code')

# Case_study = 'Random'
# Case_study = 'Sicily' 
# Case_study = 'Izmir' 
# Case_study = 'Brisbane' 
Case_study = 'Bordeaux'


logger = logging.getLogger()
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
log_filename = f'Results_{Case_study}_{current_time.replace(":","_")}.log'
file_handler = logging.FileHandler(log_filename, mode='w')
logger.addHandler(file_handler)
logger.setLevel(logging.DEBUG)


rnd = np.random
#USER INPUTS:---------------vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv

n = 5 # Number of fires 
width = 120
height = 120
Cp = 5 #Select Scooper capacity
Ck = 10 #Select Tanker capacity
cruise_p = 6 # 6 km/min = 360 km/h
cruise_k = 12 # km/min Tanker cruise speed
timelimit = 300 #seconds for each fleet combination
trips = 4
I = [20, 15, 25, 25, 15, 
     30, 30, 15, 15, 15,
     15, 10, 10, 10, 15, 
     10, 10, 15, 15, 15,
     15, 10, 10, 10, 15, 
     10, 10, 15, 15, 15] # Select intensity of each fire

spread = 3 #Maximum distance between subfires of the same fire
nodenrs = 10 #Maximum number of subfires such that the plot shows node indices. 
#Small fleets
# fleet = [(1,1),(1,2),(1,3),(1,4),(1,5),
#           (2,1),(2,2),(2,3),(2,4),(2,5),
#           (3,1),(3,2),(3,3),(3,4),(3,5),
#           (4,1),(4,2),(4,3),(4,4),(4,5),
#           (5,1),(5,2),(5,3),(5,4),(5,5)]

#Large fleets
# fleet = [(5,5),(5,6),(5,7),(5,8),(5,9),(5,10),
#             (6,5),(6,6),(6,7),(6,8),(6,9),(6,10),
#             (7,5),(7,6),(7,7),(7,8),(7,9),(7,10),
#             (8,5),(8,6),(8,7),(8,8),(8,9),(8,10),
#             (9,5),(9,6),(9,7),(9,8),(9,9),(10,10),
#             (10,5),(10,6),(10,7),(10,8),(10,9),(10,10)]

fleet = [(10,1)] # (Tankers, Scoopers)


fire_threshold=5 #Maximum distance between subfires for them to be considered within the same fire
I = [int(x/Cp) for x in I]
#Generating original nodes: n fires + 2 nodes, one depot and one water body.

xc = rnd.rand(n+2)*width
yc = rnd.rand(n+2)*height

#To manually enter node locations, 
#set manual = 1, then specify coordinates:
manual = 1
if manual == 1:
    xc[0], yc[0] = 20, 10 #Airfield location
    xc[1], yc[1] = 20, 25 #Water body location
    xc[2], yc[2] = 20, 30 #Fire 1 location
    xc[3], yc[3] = 22, 32 #Fire 2 location
    xc[4], yc[4] = 70, 28 #Fire 3 location
    xc[5], yc[5] = 73, 32 #Fire 4 location
    xc[6], yc[6] = 72, 33 #Fire 4 location
    ###------------------------------------------------------

    
### Generating multiple nodes for each actual node/fire:
d = 1 #counter
while d <=n:
    for c in range (1, I[d-1]):
        xc = np.append(xc, (xc[d+1]+spread*rnd.rand()))
        yc = np.append(yc, (yc[d+1]+spread*rnd.rand()))
    d += 1



### Define sets:
Dep = [0]

subfires = 0
for i in range(n):        
    subfires += I[i]
    
F = [i for i in range(2,subfires+2)] # Fires


#Subsets of fires
Fs = list(range(1,n+1))

#Distance between each pair of subfires
dist = {(i,j): (np.hypot(xc[i] - xc[j], yc[i]-yc[j])) for i in F for j in F if i!=j}



#Grouping each set ofsubfires within their mother fire, by checking 
#their distance. Neighboring fires are put into groups. 
Nf = {fs: () for fs in Fs}
counter = 1
while counter<=n:
    data =[]
    for (i,j) in dist:
        if dist[i,j]<fire_threshold:
           # print(i,j)
            if not any(i in val for val in Nf.values()):
                while len(data)<1:
                    data.append(i)
                if data[0] ==i:
                    data.append(j)
                if data[0] ==j:
                    data.append(i)
                    Nf[counter] = list(set(data))
    counter+=1


N = [0] + F # Nodes (Fires and depot) - Note node 1 is the water body

A = [(i,j) for i in N for j in N] # All Arcs

AK = [] #arcs useful by tankers: to from depot and to/from subfires of the same fire
for f in Fs:
    for j in Nf[f]:
        AK.append((0,j))
        AK.append((j,0))
        for i in Nf[f]:
            if i!=j:
                AK.append((i,j))
                AK.append((j,i))
AK = list(set(AK))
    
U = [u for u in range(1,trips+1)] # Trips 
Dexit = [0]
Denter = [1]
#-------------------------------------------------------
### Define parameters:

R = 1 # Processing time, time to carry out dropping operation.
RD = 0 # Refilling of tankers at depot
M = 1000. #Big value
# Ck = 10
# Cp = 5
D = {f: Cp for f in F}
TW = {f: (0,rnd.randint(100,1000)) for f in F}
#--------------------------------------------------------

#Time of travel dictionary, p for scoopers and k for tankers.
Tp = {(i,j): (np.hypot(xc[i] - xc[j], yc[i]-yc[j]))/cruise_p for i in N for j in N}
Tk = {(i,j): (np.hypot(xc[i] - xc[j], yc[i]-yc[j]))/cruise_k for i in N for j in N}
# Making sure to include distance to water and back for scoopers.  

for i in F:
    for j in F:
        Tp[i,j] = R + ((np.hypot(xc[i] - xc[1],yc[i]-yc[1]))/cruise_p) +((np.hypot(xc[j] - xc[1],yc[j]-yc[1])/cruise_p));

    #--------------------------------------------------------
ctr=0
while ctr <= len(fleet)-1:
    Tankers = fleet[ctr][0]
    Scoopers = fleet[ctr][1]
    K = [k for k in range(1,Tankers+1)] # Tankers
    P = [p for p in range(1,Scoopers+1)] # Scoopers
    
    
    #------- Variables
    mdl = Model('main')
    #just addVar: 
    #xku = mdl.addVars(N,N,K,U,vtype = GRB.BINARY, name='xku') #1 if aircraft k travels from i to j on trip u
    xku = {}
    for k in K:
        for u in U:
            for f in Fs:
                for j in Nf[f]:
                    xku[0,j,k,u] = mdl.addVar(vtype = GRB.BINARY, name = 'xkuf[%i,%i,%i,%i]'%(0,j,k,u))
                    xku[j,0,k,u] = mdl.addVar(vtype = GRB.BINARY, name = 'xkuf[%i,%i,%i,%i]'%(i,0,k,u))
                    for i in Nf[f]:
                        if i!=j:    
                            xku[i,j,k,u] = mdl.addVar(vtype = GRB.BINARY, name = 'xkuf[%i,%i,%i,%i]'%(i,j,k,u))
    
    xp = mdl.addVars(N,N,P,vtype = GRB.BINARY, name='xp') #1 if aircraft p travels from i to j
    tau_ku = mdl.addVars(F,K,U, vtype = GRB.CONTINUOUS, lb=0,ub = 800,name='tau_ku') #Time when k starts dropping on f on trip u
    tau_p = mdl.addVars(F,P,vtype = GRB.CONTINUOUS, lb=0,ub=800,name='tau_p') #Time when p starts dropping on i
    tau_kuD = mdl.addVars(Dep,K,U,vtype = GRB.CONTINUOUS, lb=0, ub=800, name='tau_kuD') #Time when k returns to Depot on trip u
    tau_pD0 = mdl.addVars(Dep,P,Dexit,vtype = GRB.CONTINUOUS, lb=0,ub=800,name='tau_pD0') #Time when p leaves depot to a fire
    tau_pD1 = mdl.addVars(Dep,P,Denter,vtype = GRB.CONTINUOUS, lb=0,ub=800,name='tau_pD1') #Time when p returns to Depot
    Z = mdl.addVar(vtype = GRB.CONTINUOUS, name='Z') #Z Minmax variable
    mdl.update() 
    
    
    #-------Objectives
    #-------------------(1): minimize latest arrival to any fire
    mdl.modelSense = GRB.MINIMIZE
    mdl.setObjectiveN(Z,index=10);
    
    
    # #-------------------(2): Minimize aggregate travel time
    mdl.modelSense = GRB.MINIMIZE
    if i!=j:
            mdl.setObjectiveN(quicksum(quicksum(quicksum(xku[i,j,k,u]*Tk[i,j] 
                                                                  for (i,j) in AK) 
                                                                        for k in K)
                                                                            for u in U)
                              + quicksum(quicksum(xp[i,j,p]*Tp[i,j] 
                                                  for i in N for j in N)
                                                     for p in P),index=0);
    #-------Constraints
    
    #-------Z constraints:
        #3
    for j in F:
        for u in U:
            for k in K:
                lhs = LinExpr()
                lhs += tau_ku[j,k,u]
                mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=Z,
                name='Z for tankers_f'
                +str(j)+'_u'+str(u)+'_k'+str(k));
    #4
    for j in F:
        for p in P:
            lhs = LinExpr()
            lhs += tau_p[j,p]
            mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=Z,
            name='Z for scoopers_f'
            +str(j)+'_p'+str(p));
    
    #-------------------------------------
    
    #-------------------(5):
    #5
     
    for f in Fs:
        for j in Nf[f]:
            lhs = LinExpr()
            # Add all variables heading to the current fire node (tankers)
            for u in U:
                for k in K:
                    for arc in AK:
                        if arc[1] == j:
                            #print(arc[0],arc[1],k,u)
                            lhs+= xku[arc[0],arc[1],k,u]
    
            for p in P:
                for i in N:
                    if i!=j:
                        lhs += xp[i,j,p]
    
            mdl.addConstr(lhs=lhs,sense=GRB.EQUAL,rhs=1,
                          name='(5): Every fire visited once_j'
                          +str(j));
            
    #--------------------(6):
    #6
    for j in F:
        lhs = LinExpr()
        for p in P:  
            for i in N:
                if i != j:
                    lhs += xp[i,j,p]
                    
        mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=1,
                      name='(6): Scoopers visit each fire once at most_j'
                      +str(j)+'_p'+str(p));
    
    #--------------------(7): 
    #7
    for j in F:
        lhs = LinExpr()
        for p in P:     
            for i in F:
                if i == j:
                    lhs += xp[i,j,p]
                    
        mdl.addConstr(lhs=lhs,sense=GRB.EQUAL,rhs=0,
                      name='(7): Scoopers cant go back to same fire_j'
                      +str(j)+'_p'+str(p))
    
    #---------------------(8): 
    #8
    for u in U:
        for k in K:
            lhs = LinExpr()
            for f in Fs:
                for j in Nf[f]:
                    lhs += xku[0,j,k,u]
            mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=1,
                          name='(8): Tankers leave depot only (at most) once per trip_u'
                          +str(u)+'_k'+str(k))
    
    #---------------------(9): 
    #9
    for p in P:
        lhs = LinExpr()
        for j in F:
            lhs += xp[0,j,p]
        mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=1,
                          name='(9): Every scooper leaves depot (at most) once_p'
                          +str(p));
    
    #-------------------(10): 
    #10
    for u in U[:-1]:
        for k in K:
            lhs = LinExpr()
            for j in F:
                lhs += xku[0,j,k,(u+1)]
            for i in F:
                lhs -= xku[i,0,k,u]
            mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=0,
                          name='(10): Trip u must be active for u+1 to start_u'
                          +str(u)+'_k'+str(k));
    
    #-------------------(11): 
    #11
    for p in P:
        lhs = LinExpr()
        for j in F:
            lhs += xp[0,j,p]
        for j in F:
            lhs -= xp[j,0,p]
        mdl.addConstr(lhs=lhs,sense=GRB.EQUAL,rhs=0,
                          name='(11): Scooper conservation of flow for depot_p'
                          +str(p));
    
    # #-------------------(12): 
    #12
    for p in P:
        for j in F:
            lhs = LinExpr()
            for i in N:
                if i != j:
                    lhs += xp[i,j,p]
            for i in N:
                if i != j:
                    lhs -= xp[j,i,p]
            mdl.addConstr(lhs=lhs,sense=GRB.EQUAL,rhs=0,
                          name='(12): Scooper conservation of flow_j'+str(j)+'_p'+str(p))
    
    
    #-------------------(13): 
    #13
    for f in Fs:
        for j in Nf[f]:
            for k in K:
                for u in U:
                    lhs = LinExpr()
                    outgoing_arcs=[arc for arc in AK if arc[0]==j]
                    for oa in outgoing_arcs:
                         lhs += xku[oa[0],oa[1],k,u]
                    ingoing_arcs=[arc for arc in AK if arc[1]==j]
                    for ia in ingoing_arcs:
                         lhs -= xku[ia[0],ia[1],k,u] 
    
                    mdl.addConstr(lhs=lhs,sense=GRB.EQUAL,rhs=0,
                              name='(13): Tanker conservation of flow_j'
                              +str(j)+'_k'+str(k)+'_u'+str(u))
    
    #---------------------(14):
    #14
    for k in K:
        for u in U:
            lhs = LinExpr()
            for j in F: 
                lhs+= xku[0,j,k,u]
                lhs-= xku[j,0,k,u]
                
            mdl.addConstr(lhs=lhs,sense=GRB.EQUAL,rhs=0,
                      name='(14): Tanker conservation of flow depot'
                      +'_k'+str(k)+'_u'+str(u))
    #-------------------(15):
    #15
    
    for f in Fs:  
        for j in Nf[f]:
            lhs = LinExpr()
            for u in U:
                for k in K:
                    lhs += Ck*xku[0,j,k,u]
                    for i in Nf[f]:
                        if i!=j:    
                            lhs += Ck*xku[i,j,k,u] 
            for p in P:
                for i in N:    
                    if j!=i:
                        lhs += Cp*xp[i,j,p]
                        
            lhs -= D[j]
            mdl.addConstr(lhs=lhs,sense=GRB.GREATER_EQUAL,rhs=0,
                          name='(15): Fire demand must be at least satisfied_f'
                          +str(f));
        
    #New constraint for tanker capacity adjustment:
    #------------------(16):
    #16
    
    for f in Fs:
        for u in U:
            for k in K:
                lhs = LinExpr()
                for j in Nf[f]:
                    lhs += D[j]*xku[0,j,k,u] 
                    for i in Nf[f]:
                        if i!=j:    
                            lhs += D[j]*xku[i,j,k,u] 
                lhs -= Ck
                mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=0,
                          name='(16): tanker goes to next fires while it has capacity_f'
                          +str(f));
    
    
    #-------------------(13):
    
    #13
    for f in Fs:
        for j in Nf[f]:     
            for u in U:
                for k in K:
                    lhs = LinExpr()
                    lhs += tau_ku[j,k,u]
                    lhs -= tau_kuD[0,k,u]
                    lhs -= RD 
                    lhs -= Tk[0,j]
                    lhs += (1-xku[0,j,k,u])*M
                    mdl.addConstr(lhs=lhs,sense=GRB.GREATER_EQUAL,rhs=0,
                    name='(17): Time precedence tankers depot to fire_'
                    +str(f)+'_'+str(u)+'_'+str(k));
    
    #-------------------(14):
    
    #14
    for j in F:
        for p in P:
            lhs = LinExpr()
            lhs += tau_p[j,p]
            lhs -= tau_pD0[0,p,0]
            lhs -= RD
            lhs -= Tp[0,j]
            lhs += (1-xp[0,j,p])*M
            mdl.addConstr(lhs=lhs,sense=GRB.GREATER_EQUAL,rhs=0,
            name='(18): Time precedence scoopers depot to fire_f'
            +str(f)+'_p'+str(p));
    
    #-------------------(15):
    
    #15
    for j in F:
        for p in P:
            for i in F:
                if j!=i:
                    lhs = LinExpr()
                    lhs += tau_p[j,p]
                    lhs -= tau_p[i,p]
                    lhs -= R
                    lhs -= Tp[i,j]
                    lhs += (1-xp[i,j,p])*M
                    mdl.addConstr(lhs=lhs,sense=GRB.GREATER_EQUAL,rhs=0,
                    name='(19): Time precendence scoopers fire to fire_f'
                    +str(f)+'_p'+str(p));
    
    #-------------------(16):
    
    #16
    for j in F:
        for p in P:
            lhs = LinExpr()
            lhs += tau_pD1[0,p,1]
            lhs -= tau_p[j,p]
            lhs -= R
            lhs -= Tp[j,0]
            lhs += (1-xp[j,0,p])*M
            mdl.addConstr(lhs=lhs,sense=GRB.GREATER_EQUAL,rhs=0,
            name='(20): Time precendence scoopers fire to depot_f'
            +str(f)+'_p'+str(p));
    
    #-------------------(17):
    
    #17
    for j in F:
        for u in U[:-1]:
            for k in K:
                lhs = LinExpr()
                lhs += tau_kuD[0,k,u+1]
                lhs -= tau_ku[j,k,u]
                lhs -= R
                lhs -= Tk[j,0]
                lhs += (1-xku[j,0,k,u])*M
                mdl.addConstr(lhs=lhs,sense=GRB.GREATER_EQUAL,rhs=0,
                name='(21): Time precendence tankers fire to depot_f'
                +str(f)+'_u'+str(u)+'_k'+str(k));
    
    
    #New time constraint tankers fire to fire:
    for f in Fs:
        for j in Nf[f]:
            for u in U:
                for k in K:
                    for i in Nf[f]:
                        if i!=j:
                            lhs = LinExpr()
                            lhs += tau_ku[j,k,u]
                            lhs -= tau_ku[i,k,u]
                            lhs -= Tk[i,j]
                            lhs += (1-xku[i,j,k,u])*M
                            mdl.addConstr(lhs=lhs,sense=GRB.GREATER_EQUAL,rhs=0,
                            name='(22): Time precendence tankers fire to fire'
                            +str(f)+'_u'+str(u)+'_k'+str(k));
                    
    
    #-------------------(18):
    
    #18
    for j in F:
        for u in U:
            for k in K:
                lhs = LinExpr()
                lhs += tau_ku[j,k,u]
                lhs -= TW[j][1]
                mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=0,
                name='(23): Time window tankers_f'
                +str(f)+'_u'+str(u)+'_k'+str(k));
    
    #-------------------(19):
    
    #19
    for j in F:
        for p in P:
            lhs = LinExpr()
            lhs += tau_p[j,p]
            lhs -= TW[j][1]
            mdl.addConstr(lhs=lhs,sense=GRB.LESS_EQUAL,rhs=0,
            name='(24): Time window scoopers_f'
            +str(f)+'_p'+str(p));
            
    mdl.params.TimeLimit = timelimit
    #Solve
    mdl.optimize()
    
    
    
    #Creating a list with active arcs
    active_arcs = []
    for p in P:
        active_arcs.append([(i,j) for (i,j) in A if xp[i,j,p].x>0.99])
    for k in K:
        for u in U:
            active_arcs.append([(i,j) for (i,j) in AK if xku[i,j,k,u].x>0.99])
            
    active_arcs = [empty for empty in active_arcs if empty!=[]]
    #print("Active arcs:", active_arcs)
    
    # Define arcs per aircraft
    arcs_p = {}
    for p in P:
        active_arcs_p = [(i,j) for (i,j) in A if xp[i,j,p].x>0.99]
        arcs_p[p] = active_arcs_p
    arcs_k = {}    
    for k in K:
        dummy = []
        for u in U:
            dummy.append([(i,j) for (i,j) in AK if xku[i,j,k,u].x>0.99])
        arcs_k[k] = dummy
        
        
        
    solution = []
    for v in mdl.getVars():
        if v.x!=0:
             solution.append([v.varName,v.x]) 
    

    # edges_p = [(i, j) for p in arcs_p for i, j in arcs_p[p]]
    # edges_k = [(i, j) for k in arcs_k for u in arcs_k[k] for i, j in u ]

    
    Airfield = plt.plot(xc[0],yc[0], c= 'g', marker = 's', markersize=10, label = 'Airfield')
    Water_body = plt.plot(xc[1],yc[1], c= 'b', marker = 's', markersize=15, label = 'Water body')
    Fire = plt.scatter(xc[2:],yc[2:], c='r', label = 'Fire')
    

    for p in arcs_p:
        for i, j in arcs_p[p]:
            plt.plot([xc[i], xc[j]], [yc[i], yc[j]], '-', color='deepskyblue', label = 'Scoopers')
        
    for k in arcs_k:
        for b in arcs_k[k]:
            for i, j in b:
                plt.plot([xc[i], xc[j]], [yc[i], yc[j]], '-', color='orange', label = 'Tankers')


    # Create a custom legend for the edges
    custom_legend = [Patch(color='green', label='Airfield'),
                      Patch(color='blue', label='Water body'),
                      Patch(color='red', label='Fires'),
                      Patch(color='deepskyblue', label='Scoopers'),
                      Patch(color='orange', label='Tankers')]
    plt.legend(handles=custom_legend, bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0.)

    # Add axis labels
    plt.xlabel('X-coordinates [km]')
    plt.ylabel('Y-coordinates [km]')
    
    # Adding the node numbers on the plot
    if subfires<=nodenrs:
        for i in range(len(Nf)):
            plt.annotate(f"{Nf[i+1]}", xy=(xc[i+2], yc[i+2]), xytext=(xc[i+2]-3, yc[i+2]+3),
                      fontsize=12, color='blue')
    # Add a title
    plt.title(f"{Case_study} case: {subfires} subfires, {Tankers} tankers and {Scoopers} scoopers")
    # Add text to the plot
    #plt.text(1, 0.5, f"Tanker arcs: {arcs_k} Scooper arcs: {arcs_p}")
    # plt.show()
    plt.savefig(f"Plot {Case_study}_{subfires}_subfires {Tankers} tankers and {Scoopers} scoopers.png", bbox_inches='tight')
            
         
    # print("SOLUTION: ", solution)
    print("Tankers: ", Tankers, "Scoopers: ", Scoopers)
    print("ARCS PER SCOOPER: ", arcs_p)
    print("ARCS PER TANKER: ", arcs_k)
    print("Latest fire visited after: ", str(round(Z.x, 2)), "minutes")
    # print("Aggregate flying time: ", str())
    # log result
    result = [('Fleet: {} tankers and {} scoopers'.format(Tankers, Scoopers)),
              ('ARCS PER SCOOPER: ', arcs_p),
              ('ARCS PER TANKER: ', arcs_k),
              ('Latest fire visited after: ', str(round(Z.x, 2)), 'minutes')]
    

    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    logger.info('Result of iteration {} at {} using {} tankers and {} scoopers: {}'.format(ctr+1, timestamp, Tankers, Scoopers, result))
    ctr+=1
file_handler.close()
