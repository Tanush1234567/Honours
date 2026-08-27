# Aerial FireFighting Vehicle Routing Problem (AFFVRP)

## 🎓 Honours Thesis – TU Delft / NLR

---

## 🎯 Objective

The goal is to couple a wildfire simulation tool (**FARSITE**, inside FlamMap 6) with a **Gurobi MILP optimiser** in a rolling-horizon loop to optimally route firefighting aircraft over an evolving wildfire.

### Primary objective:
- Minimise total burning cell-timesteps (fire spread)

### Secondary objective:
- Minimise total flight distance

---

## 🔥 Problem Formulation

### Spatial & temporal discretisation
- Uniform grid of cells
- Discrete time steps

### Cell states
- 0 → Unburned
- 1 → Burning
- 2 → Extinguished

---

## ✈️ Aircraft Types

### Tankers
- High capacity
- Must return to airfield to refuel

### Scoopers
- Lower capacity
- Can refill mid-mission at water bodies

---

## 💧 Drop Pattern Model

### Hexagonal footprint
- Lateral distribution: η(x, y)

- Longitudinal distribution:
  λ(x, h) = k · h^1.5

- Standard deviation:
  σ = λ / 6

### Grid resolution
- Cell size ≈ σ

### Coverage rule
- A cell is extinguished if ≥ 50% area coverage

---

## 🌬️ Wind Model

- Wind is stochastic per rolling horizon window
- Sampled from:
  N(mean, std)

### Consistency rule
Same wind sample is used for:
- FARSITE simulation
- Gurobi optimisation

---

## 🔁 Rolling Horizon Loop

For each window W:

1. Sample wind
2. Run FARSITE (TestFarsite.exe via subprocess)
3. Parse output → fire grid (3-state model)
4. Solve MILP (Gurobi AFFVRP)
5. Apply drop decisions
6. Update fire state (extinguished cells remain permanent)
7. Write ignition shapefile for next iteration
8. Log + visualise results
9. Stop when no burning cells remain

---

## 📊 Gurobi MILP Model

### Decision variables
- x_k, x_p → aircraft location binaries
- d_k, d_p → drop decision binaries
- y[cell, t, state] → fire state evolution
- q_k, q_p → water load
- Z → latest drop timing variable

---

### Constraints

#### Aircraft dynamics
- Manhattan speed limits
- Feasible movement between grid cells

#### Logistics
- Tankers: start/end at airfield
- Scoopers: refill at water cells

#### Fire propagation
- Moore neighbourhood spread model

#### Suppression coupling
- Drop footprint extinguishes cells
- 50% coverage threshold

#### Collision avoidance
- One aircraft per cell per timestep

---

### Objective function
- Minimise burning cell-timesteps
- Minimise flight distance

---

## 🧠 Rolling System Architecture

- FARSITE = fire evolution engine
- Gurobi = decision optimiser
- Orchestrator = loop controller

---

## 📁 Code Structure

- config.py → parameters
- drop_pattern.py → hexagonal dispersion model
- farsite_interface.py → simulation interface
- grid_utils.py → spatial + GIS utilities
- wind.py → stochastic wind generator
- optimisation.py → full MILP model
- orchestrator.py → rolling horizon controller
- visualise.py → plotting + GIF generation

---

## 🎲 Monte Carlo Simulation

### Purpose
Evaluate fleet performance under stochastic wind conditions.

### Setup
- Multiple fleet configurations tested
- Same wind seeds used for fairness

### Example fleets
- 2 Tankers + 1 Scooper
- 1 Tanker + 2 Scooper

### Output
- JSON logs per run
- Aggregated performance metrics

---

## 📊 Outputs

- Fire spread visualisations
- Time-series burn analysis
- GIF animations of fire evolution
- Fleet comparison charts
- Monte Carlo aggregated results