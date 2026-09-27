# static_test — Single-Window AFFVRP (No FARSITE)

Tests the Gurobi MILP in isolation on a static fire snapshot.
No FARSITE, no wind sampling, no rolling loop.

---

## What it does

```
ignition.shp
     │
     ▼
grid_from_ignition_shp()   → 3-state grid  (0=unburned, 1=burning, 2=extinguished)
     │
     ├──► grid_initial.tif              (GeoTIFF, open in QGIS)
     │
     ▼
build_and_solve()           → Gurobi AFFVRP MILP (one 15-min window)
     │
     ▼
apply_drop_schedule()       → updated grid after drops
     │
     ├──► grid_after_drops.tif          (GeoTIFF — the updated landscape file)
     ├──► outputs/static_result.png     (before/after visualisation)
     └──► logs/result.json              (structured log)
```

---

## Files

```
static_test/
├── config/
│   └── config.py       ← all parameters here; edit before running
├── inputs/
│   └── ignition.shp    ← YOU supply this (+ .dbf .shx .prj)
├── outputs/            ← created automatically
├── logs/               ← created automatically
├── drop_pattern.py     ← hexagonal drop footprint (unchanged from integration)
├── grid_utils.py       ← grid helpers (wind param removed from log_result)
├── optimisation.py     ← full AFFVRP MILP (identical logic to integration)
├── visualise.py        ← single-panel plot (no wind annotation)
├── run_static.py       ← ENTRY POINT — run this
└── requirements.txt
```

---

## Setup

```bash
pip install -r requirements.txt
```

Requires a valid Gurobi licence (free for academics at gurobi.com).

---

## Before running — fill in config/config.py

| Parameter | What to set |
|-----------|-------------|
| `GRID_ORIGIN_X` | UTM easting of top-left corner of your study area (from `gdalinfo`) |
| `GRID_ORIGIN_Y` | UTM northing of top-left corner |
| `GRID_ROWS`, `GRID_COLS` | Grid dimensions (e.g. 50×50 for a 5×5 km area at 100 m cells) |
| `GRID_CRS` | EPSG code matching your ignition shapefile (e.g. `"EPSG:32754"`) |
| `AIRFIELD_CELL` | `(row, col)` of the airfield — must NOT be inside the fire |
| `WATER_CELLS` | List of `(row, col)` water source cells for scoopers |
| `NUM_TANKERS`, `NUM_SCOOPERS` | Fleet size |
| `WIND_DIR_DEG` | Wind direction in degrees (sets drop heading = dir + 180°) |

---

## Run

```bash
cd static_test
python run_static.py
```

---

## Outputs

| File | Description |
|------|-------------|
| `outputs/grid_initial.tif` | Initial fire state from ignition shapefile. Open in QGIS. Values: 0=unburned, 1=burning |
| `outputs/grid_after_drops.tif` | Updated fire state after drops applied. Values: 0, 1, 2=extinguished |
| `outputs/static_result.png` | Two-panel plot: before drops (left) and after drops (right) with routes |
| `logs/result.json` | Full structured log: stats, drop schedule, Gurobi objective and gap |

---

## Changes from integration/

| File | Change |
|------|--------|
| `config/config.py` | Removed: `FARSITE_EXE`, `LCP_FILE`, `WEATHER_FILE`, `WIND_FILE`, `WIND_SPEED_MEAN/STD`, `WIND_DIR_MEAN/STD`, `RANDOM_SEED`, `FARSITE_*` parameters, `FLEET`, `MAX_ITERATIONS`. Added: `NUM_TANKERS`, `NUM_SCOOPERS`, `WIND_SPEED_KPH`, `WIND_DIR_DEG` (fixed, not sampled), `GRID_CRS` |
| `grid_utils.py` | `log_iteration()` renamed to `log_result()` — wind dict parameter removed |
| `optimisation.py` | `wind_dir_deg` and `drop_heading_deg` now optional (default from config). `OutputFlag=1` so Gurobi progress is visible |
| `visualise.py` | `plot_iteration()` renamed to `plot_result()` — wind annotation removed, single panel pair only |
| `run_static.py` | **New file** — replaces `orchestrator.py`. Single solve, no loop, no FARSITE calls |
| `farsite_interface.py` | **Deleted** — not needed |
| `wind.py` | **Deleted** — not needed |
| `orchestrator.py` | **Deleted** — replaced by `run_static.py` |
