# Mathematical Model — Discretised AFFVRP (`optimisation.py`)

## 1. Sets and Indices

| Symbol | Description |
|---|---|
| $C = \{(r,c)\}$ | Grid cells, $r \in \{0,\dots,\text{ROWS}-1\}$, $c \in \{0,\dots,\text{COLS}-1\}$ |
| $T = \{0,1,\dots,W-1\}$ | Discrete timesteps within the current rolling window (1 min each) |
| $K = \{1,\dots,n_K\}$ | Tankers |
| $P = \{1,\dots,n_P\}$ | Scoopers |
| $S = \{0,1,2\}$ | Cell states: 0 = unburned, 1 = burning, 2 = extinguished |
| $B \subseteq C$ | Burning cells at start of window (suppression targets) |
| $F(r,c)$ | Drop footprint of cell $(r,c)$: set of cells $(r_2,c_2)$ covered by a drop centred at $(r,c)$, with weight $\eta(r_2,c_2)$ |
| $N(r,c)$ | Moore (8-cell) neighbourhood of $(r,c)$ |
| $\text{AF}$ | Airfield cell |
| $\text{WS}$ | Set of water-source cells |

## 2. Parameters

| Symbol | Description |
|---|---|
| $V_K, V_P$ | Max Manhattan cells/timestep for tanker / scooper (from cruise speed) |
| $Q_K = C_k/C_p$ | Tanker capacity in drop units |
| $Q_P = 1$ | Scooper capacity in drop units |
| $t_0$ | Absolute minute offset of this window (for $Z$) |
| $M$ | Big-M constant |

## 3. Decision Variables

| Variable | Domain | Meaning |
|---|---|---|
| $x^k_{r,c,t}$ | binary | Tanker $k$ is at cell $(r,c)$ at time $t$ |
| $x^p_{r,c,t}$ | binary | Scooper $p$ is at cell $(r,c)$ at time $t$ |
| $d^k_{r,c,t}$ | binary, $(r,c)\in B$ | Tanker $k$ drops water at $(r,c)$ at time $t$ |
| $d^p_{r,c,t}$ | binary, $(r,c)\in B$ | Scooper $p$ drops water at $(r,c)$ at time $t$ |
| $y_{r,c,t,s}$ | binary | Cell $(r,c)$ has state $s$ at time $t$ |
| $q^k_{k,t}$ | integer $[0,Q_K]$ | Water load of tanker $k$ at time $t$ |
| $q^p_{p,t}$ | binary | Water load of scooper $p$ at time $t$ (0 or 1) |
| $Z$ | continuous $\geq 0$ | Time of the last drop (min-max variable) |

## 4. Objective — Hierarchical (two-stage)

**Primary (priority 10) — minimise total burning cell-timesteps:**

$$\min \sum_{(r,c)\in C}\sum_{t\in T} y_{r,c,t,1}$$

**Secondary (priority 0) — minimise total flight distance, subject to the primary optimum:**

$$\min \sum_{k\in K}\sum_{t\in T\setminus\{|T|-1\}}\ \sum_{\substack{(r_1,c_1),(r_2,c_2)\in C \\ \text{Manhattan} \leq V_K}} d\big((r_1,c_1),(r_2,c_2)\big)\, x^k_{r_1,c_1,t}\, x^k_{r_2,c_2,t+1}$$

$$+\ \sum_{p\in P}\sum_{t\in T\setminus\{|T|-1\}}\ \sum_{\substack{(r_1,c_1),(r_2,c_2)\in C \\ \text{Manhattan} \leq V_P}} d\big((r_1,c_1),(r_2,c_2)\big)\, x^p_{r_1,c_1,t}\, x^p_{r_2,c_2,t+1}$$

where $d(\cdot,\cdot)$ is Euclidean distance in cell units.

*(Implemented in Gurobi as linear terms over the pre-filtered arc set, not as a literal product of two binaries — the reachability filter on Manhattan distance makes this exact.)*

## 5. Constraints

**(1) Initial fire state**
$$y_{r,c,0,s} = \mathbb{1}[\text{grid}(r,c) = s] \quad \forall (r,c)\in C,\ s\in S$$

**(2) Exactly one state per cell per timestep**
$$\sum_{s\in S} y_{r,c,t,s} = 1 \quad \forall (r,c)\in C,\ t\in T$$

**(3) Extinguished is absorbing**
$$y_{r,c,t+1,2} \geq y_{r,c,t,2} \quad \forall (r,c)\in C,\ t\in T\setminus\{|T|-1\}$$

**(4) Fire propagation (Moore neighbourhood)**

Lower bound — ignites if a neighbour burns and cell not extinguished next step:
$$y_{r,c,t+1,1} \geq y_{r',c',t,1} - y_{r,c,t+1,2} \quad \forall (r',c')\in N(r,c)$$

Upper bound — can only burn if it was already burning or had a burning neighbour:
$$y_{r,c,t+1,1} \leq y_{r,c,t,1} + \sum_{(r',c')\in N(r,c)} y_{r',c',t,1}$$

*(Skipped for permanently extinguished cells from prior windows.)*

**(5) Suppression coupling**

For each burning cell $(r,c)$ covered by a footprint centred at $(r_2,c_2)\in B$:
$$y_{r,c,t+1,2} \geq d^k_{r_2,c_2,t} + y_{r,c,t,1} - 1 \quad \forall k\in K$$
$$y_{r,c,t+1,2} \geq d^p_{r_2,c_2,t} + y_{r,c,t,1} - 1 \quad \forall p\in P$$

**(6) Aircraft location — exactly one cell per timestep**
$$\sum_{(r,c)\in C} x^k_{r,c,t} = 1 \quad \forall k\in K,\ t\in T$$
$$\sum_{(r,c)\in C} x^p_{r,c,t} = 1 \quad \forall p\in P,\ t\in T$$

**(7) At most one aircraft per cell per timestep**
$$\sum_{k\in K} x^k_{r,c,t} + \sum_{p\in P} x^p_{r,c,t} \leq 1 \quad \forall (r,c)\in C,\ t\in T$$

**(8) Linear flight dynamics (speed limit)**

For all pairs with Manhattan distance $> V_K$ (resp. $V_P$):
$$x^k_{r_1,c_1,t} + x^k_{r_2,c_2,t+1} \leq 1$$
$$x^p_{r_1,c_1,t} + x^p_{r_2,c_2,t+1} \leq 1$$

**(9) Drop only when present at the cell**
$$d^k_{r,c,t} \leq x^k_{r,c,t}, \qquad d^p_{r,c,t} \leq x^p_{r,c,t} \quad \forall (r,c)\in B,\ t\in T$$

**(10) Drop only on burning cells**
$$d^k_{r,c,t} \leq y_{r,c,t,1}, \qquad d^p_{r,c,t} \leq y_{r,c,t,1} \quad \forall (r,c)\in B,\ t\in T$$

**(11) Tanker water capacity dynamics**
$$q^k_{k,0} = Q_K$$
$$q^k_{k,t+1} \leq Q_K \cdot x^k_{\text{AF},t} + q^k_{k,t} - \sum_{(r,c)\in B} d^k_{r,c,t}$$
$$q^k_{k,t+1} \geq q^k_{k,t} - \sum_{(r,c)\in B} d^k_{r,c,t}$$
$$\sum_{(r,c)\in B} d^k_{r,c,t} \leq q^k_{k,t} \quad \text{(cannot drop with empty tank)}$$

**(12) Scooper water capacity dynamics**
$$q^p_{p,0} = 1$$
$$q^p_{p,t+1} \leq 1 - \sum_{(r,c)\in B} d^p_{r,c,t} + \sum_{(r,c)\in \text{WS}} x^p_{r,c,t+1}$$
$$q^p_{p,t+1} \geq \sum_{(r,c)\in \text{WS}} x^p_{r,c,t+1} - \sum_{(r,c)\in B} d^p_{r,c,t}$$
$$\sum_{(r,c)\in B} d^p_{r,c,t} \leq q^p_{p,t}$$

**(13) Tanker starts and ends at airfield**
$$x^k_{\text{AF},0} = 1, \qquad x^k_{\text{AF},|T|-1} = 1 \quad \forall k\in K$$

**(14) Scooper starts at airfield**
$$x^p_{\text{AF},0} = 1 \quad \forall p\in P$$

*(No end-of-window return required — continuity is handled by the orchestrator across windows.)*

**(15) Min-max linkage — defines $Z$ as the time of the last drop**
$$Z \geq (t_0+t)\cdot d^k_{r,c,t} \quad \forall k\in K,\ (r,c)\in B,\ t\in T$$
$$Z \geq (t_0+t)\cdot d^p_{r,c,t} \quad \forall p\in P,\ (r,c)\in B,\ t\in T$$

*(Currently $Z$ is computed but not part of the active objective — available as a secondary/tertiary criterion if you want to add it back into the hierarchy.)*

## 6. Notes on Design Choices

- **Absorbing extinguished state (3):** once a cell is suppressed it can never reignite, even if the propagation constraint would otherwise ignite it from a neighbour — enforced by subtracting $y_{r,c,t+1,2}$ in constraint (4).
- **Footprint-weighted suppression (5):** the drop footprint from `drop_pattern.py` determines which non-target cells are also affected by a single drop, not just the cell the aircraft is aimed at.
- **Speed limit as Manhattan distance (8):** a computationally cheap proxy for true flight dynamics; conservative because Manhattan distance ≥ Euclidean distance.
- **Tanker vs scooper refuel logic (11)–(12):** tankers refuel only at the airfield (any amount, up to $Q_K$); scoopers refuel to full at any water-source cell — this mirrors the real operational difference described in the problem statement.
- **Rolling horizon boundary:** the model solves only for the current window $[t_0, t_0+W)$. Fire state and extinguished-cell status carry over between windows via the orchestrator, not within this model.
