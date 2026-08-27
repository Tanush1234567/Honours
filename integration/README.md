# FARSITE + Gurobi Rolling-Horizon Integration
## Aerial FireFighting Vehicle Routing Problem (AFFVRP)

---

## File map

```
integration/
├── config/
│   └── config.py          ← ALL tunable parameters live here
├── outputs/               ← created automatically; per-run sub-dirs
├── logs/                  ← JSON logs + .log files per run
├── inputs/                ← you supply these (see "Required inputs" below)
│   ├── landscape.lcp
│   ├── ignition.shp
│   ├── weather.wtr        ← written automatically by wind.py
│   └── wind.wnd           ← written automatically by wind.py
├── config.py              (re-export shim — ignore)
├── drop_pattern.py        ← hexagonal drop footprint model (problem stmt §2.0.3)
├── farsite_interface.py   ← writes FARSITE .input files, calls TestFarsite.exe,
│                             parses perimeter / ROS output back to grid
├── grid_utils.py          ← 3-state grid helpers, serialisation, logging
├── optimisation.py        ← spatially-discretised AFFVRP Gurobi model
├── orchestrator.py        ← rolling-horizon master loop + Monte Carlo runner
├── visualise.py           ← per-iteration plots, summary chart, GIF animation
├── wind.py                ← stochastic wind sampling, .wnd / .wtr writers
└── requirements.txt
```

---

## Required inputs (you supply)

| File | What it is |
|------|-----------|
| `inputs/landscape.lcp` | FARSITE landscape file — fuel model, canopy, slope, aspect, elevation. Export from FlamMap GUI. |
| `inputs/ignition.shp` | Initial fire perimeter polygon in the same CRS as the LCP. |
| `C:\FlamMap6\TestFarsite.exe` | The FARSITE CLI binary shipped with FlamMap 6. Path set in `config.py`. |

Weather and wind stream files (`weather.wtr`, `wind.wnd`) are **written automatically** by `wind.py` at the start of each run based on the parameters in `config.py`.

---

## Setup

```bash
pip install -r requirements.txt
```

Gurobi requires a valid licence. Academic licences are free from gurobi.com.

---

## Running

### Single run (one fleet, one wind sequence)
```bash
python orchestrator.py --mode single
```

### Monte Carlo fleet comparison (N wind sequences per fleet)
```bash
python orchestrator.py --mode monte_carlo --n_sims 100
```

Fleet combinations are defined in `config.py → FLEET`.

---

## Key parameters to tune (all in `config/config.py`)

### Grid resolution
```python
CELL_SIZE_M = 100   # [m]
```
Set this to roughly the standard deviation σ of your drop pattern at your
typical release altitude (σ = k·h^1.5 / 6, where k=DROP_K, h=DROP_H).
Smaller cells → more spatial accuracy but exponentially more Gurobi variables.
A 50×50 grid at 100 m cells covers 5×5 km — typical for a single fire front.

### Window length
```python
WINDOW_MINUTES = 15
```
The most sensitive parameter. Shorter windows give a fresher fire state to
the optimiser but increase the number of FARSITE + Gurobi calls. Longer
windows reduce coupling fidelity. Start at 15 min; FARSITE runs in ~30–60 s
for small landscapes, so you stay well within the 5-minute Gurobi budget.

### Gurobi time limit
```python
GUROBI_TIME_LIMIT = 300   # [s]
```
Must be ≤ WINDOW_MINUTES × 60 for the loop to be real-time feasible.
For offline analysis there is no constraint — raise it to improve solution
quality for large grids.

### Drop pattern
```python
DROP_K   = 0.05    # relates release altitude to max lateral spread
DROP_H   = 40.0    # [m] release altitude
DROP_PHI = 0.8     # direct-hit suppression probability
```
Calibrate DROP_K and DROP_H against your aircraft's published drop parameters.
DROP_PHI and DROP_PHI_DECAY control how likely a burning cell is to be
suppressed — increase PHI for retardant drops, decrease for water-only.

### Wind stochasticity
```python
WIND_SPEED_MEAN  = 10.0   # [km/h]
WIND_SPEED_STD   =  3.0
WIND_DIR_MEAN    = 225.0  # [degrees]
WIND_DIR_STD     = 15.0
RANDOM_SEED      = 42     # None = non-reproducible
```
For Monte Carlo fleet comparison, each simulation index gets seed = RANDOM_SEED + sim,
so every fleet option experiences the same sequence of wind events.

### Fleet
```python
FLEET = [(2, 2), (3, 1), (1, 3)]   # (tankers, scoopers) per run
```
Add as many combinations as you want. In single mode, one run per entry.
In Monte Carlo mode, N_SIMS runs per entry.

---

## How the loop works (concise)

```
for each window i:
    1. sample wind_i
    2. write FARSITE .input  (start=i*W, end=(i+1)*W, ignition=current perimeter)
    3. run TestFarsite.exe   → ROS raster or perimeter shapefile
    4. parse output          → 3-state grid  (cells > 50% covered = BURNING)
    5. run Gurobi AFFVRP     → drop schedule x[a,r,c,t] for t in [0,W)
    6. apply drops           → extinguished cells locked permanently
    7. write new ignition shp from post-drop grid
    8. log + plot
    if no burning cells remain: stop
```

The FARSITE run at step 3 DOES NOT know about the drops. It propagates the
fire as if no suppression happened. The optimiser at step 5 sees the
post-FARSITE (worst-case) fire state and plans drops to counter it. The
drops are then applied in step 6, and FARSITE's NEXT run starts from the
smaller (post-drop) perimeter. This is the correct coupling: FARSITE models
fire physics; Gurobi models aircraft decisions.

---

## Output files

After a run `outputs/<run_tag>/` contains:

| File | Contents |
|------|---------|
| `iter_NNN_grid.png` | Two-panel fire state map (before / after drops) with routes |
| `iter_NNN/grid_post_farsite.tif` | GeoTIFF of fire state after FARSITE, before drops |
| `iter_NNN/grid_post_drops.tif` | GeoTIFF of fire state after drops applied |
| `iter_NNN/farsite_iter_NNN.input` | FARSITE input file used for this window |
| `summary.png` | Burning cells, drops, and Gurobi gap vs iteration |
| `simulation.gif` | Animated loop of all grid snapshots |

`logs/<run_tag>/iter_NNN.json` contains structured per-iteration data
(stats, drop list, wind, optimiser result) for post-processing in Python.

---

## CRS / projection note

Everything must be in the same projected CRS (UTM or similar — NOT lat/lon).
Set `GRID_CRS`, `GRID_ORIGIN_X`, `GRID_ORIGIN_Y` in `config.py` to match
your LCP file. You can find these from FlamMap's landscape properties panel
or with `gdalinfo landscape.lcp`.
