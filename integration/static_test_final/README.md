# static_test — Single-Window AFFVRP (No FARSITE), Fixed

Tests the Gurobi MILP in isolation on a static fire snapshot.
No FARSITE, no wind sampling, no rolling loop.

---

## What changed from the previous version — and why

### Bug: `GRID_CRS` was hand-typed in `config.py`

The old code had:
```python
GRID_CRS = "EPSG:32633"   # a generic UTM zone — wrong
```

FlamMap6 landscapes use a **custom, landscape-specific Albers projection**
(no EPSG code — it's defined by exact `latitude_of_center` /
`longitude_of_center` / `standard_parallel_1/2` values baked into the
landscape's own metadata). Any hand-typed EPSG string can never correctly
match this. When the ignition shapefile was reprojected to the wrong CRS
before being rasterised onto the grid, it silently landed outside the grid
bounds — hence 0 burning cells, with no error at all.

### Fix: grid georeferencing is now derived from `landscape.tif` directly

`grid_utils.load_landscape_georef()` reads CRS, transform, resolution, and
dimensions straight out of the landscape GeoTIFF at runtime. This is now
the single source of truth. `GRID_ROWS`, `GRID_COLS`, `GRID_ORIGIN_X`,
`GRID_ORIGIN_Y`, `GRID_CRS`, and `CELL_SIZE_M` no longer exist as constants
in `config.py` — every function that used them now takes a `georef` dict
instead.

### Also added: loud, specific errors instead of silent failure

- Missing `.shx` / `.dbf` sidecar files → clear error naming which file is missing
- Missing `.prj` (no CRS) → clear error, doesn't guess
- Ignition polygon doesn't overlap the landscape grid at all, even after
  reprojection → clear error explaining this usually means the ignition
  shapefile and landscape file came from **different FlamMap6 sessions**
  (this is exactly what happened with the `inputs.zip` you sent me —
  see below)
- `AIRFIELD_CELL` outside the grid, or inside the fire perimeter → warning
  at startup rather than a confusing Gurobi infeasibility later

---

## About the inputs.zip you sent me

I tested the fixed code against your actual `ignition.shp` + `landscape.tif`.
The shapefile bundle itself was complete this time (`.shp`, `.shx`, `.dbf`,
`.prj` all present) — good. But their custom Albers projections have
different centers:

- `ignition.shp` centre: lat 38.0047, lon -90.5054 (~St. Louis area)
- `landscape.tif` centre: lat 36.25605, lon -85.41335 (~TN/KY border)

These are ~400 km apart — they describe **different physical areas** and
cannot be made to align by reprojection. You'll need to re-export both the
ignition perimeter and the landscape from the **same FlamMap6 project**, so
they share the same landscape extent and projection. Once you do, the code
will pick them up with no config changes needed.

---

## Files

```
static_test/
├── config/
│   └── config.py       ← edit fleet size, airfield/water cells, wind
├── inputs/
│   ├── landscape.tif    ← YOU supply this
│   └── ignition.shp     ← YOU supply this, PLUS .shx, .dbf, .prj alongside it
├── outputs/             ← created automatically
├── logs/                ← created automatically
├── drop_pattern.py
├── grid_utils.py
├── optimisation.py
├── visualise.py
├── run_static.py        ← ENTRY POINT — run this
└── requirements.txt
```

---

## Setup

```bash
pip install -r requirements.txt
```

Requires a valid Gurobi licence (free for academics at gurobi.com).

---

## Before running

1. Put a **matching** `landscape.tif` + `ignition.shp` (+ `.shx` + `.dbf` +
   `.prj`) — all from the same FlamMap6 project — into `inputs/`.
2. Open `config/config.py` and check/set:
   - `AIRFIELD_CELL`, `WATER_CELLS` — grid indices `(row, col)`. Run once
     first; `run_static.py` prints the actual grid size and warns you if
     these are out of bounds or inside the fire.
   - `NUM_TANKERS`, `NUM_SCOOPERS`
   - `WIND_DIR_DEG` — sets drop heading only (no FARSITE feed)

---

## Run

```bash
cd static_test
python run_static.py
```

The console will print the grid size and CRS it detected from
`landscape.tif`, the number of burning cells identified, and — if
something's wrong with your inputs — a specific error telling you what to
check, rather than a silent "0 burning cells."

---

## Testing on a subset (recommended before the full-size run)

Your uploaded `landscape.tif` is 668 × 1640 cells (30 m resolution ≈ 49 km ×
20 km). At `WINDOW_MINUTES = 15`, the full MILP is very large and slow to
solve. Before running the full grid, it's worth cropping both files to a
small area around your fire (e.g. 20×20 cells) with `gdal_translate` or in
QGIS, just to confirm the model builds and solves correctly on your machine
— then scale back up to the full landscape once that works.

---

## Outputs

| File | Description |
|------|-------------|
| `outputs/grid_initial.tif` | Initial fire state from ignition shapefile. Same CRS/transform as `landscape.tif` — they'll align perfectly in QGIS. |
| `outputs/grid_after_drops.tif` | Updated fire state after drops applied. Values: 0=unburned, 1=burning, 2=extinguished |
| `outputs/static_result.png` | Two-panel plot: before drops (left) and after drops (right) with routes |
| `logs/result.json` | Full structured log: stats, drop schedule, Gurobi objective and gap |

---

## Function signature changes (if you're comparing to the earlier version)

| Function | Change |
|----------|--------|
| `grid_utils.load_landscape_georef(landscape_tif)` | **New.** Returns the `georef` dict used everywhere below. |
| `grid_utils.grid_from_ignition_shp(shp_path, georef)` | Now takes `georef` instead of reading `GRID_*` from config |
| `grid_utils.save_grid(grid, path, georef)` | Now takes `georef` |
| `grid_utils.cell_to_utm(row, col, georef)` / `utm_to_cell(easting, northing, georef)` | Now take `georef` |
| `grid_utils.check_cell_in_bounds(name, cell, georef)` | **New.** Startup sanity check. |
| `drop_pattern.compute_drop_footprint(..., cell_size_m, ...)` | `cell_size_m` is now an explicit parameter (was `CELL_SIZE_M` from config) |
| `drop_pattern.apply_drop_to_grid(..., cell_size_m, ...)` | Same |
| `optimisation.build_and_solve(..., georef, ...)` | Now takes `georef`; derives `V_K`/`V_P` from `georef['cell_size_x']` |
| `visualise.plot_result(..., georef, ...)` | Now takes `georef` for plot extent |
