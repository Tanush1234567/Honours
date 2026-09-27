# =============================================================================
# run_static.py
# Entry point for the static (single-window, no FARSITE) test.
#
# What it does:
#   1. Reads landscape.tif → derives grid CRS/origin/resolution/dimensions
#   2. Reads ignition.shp → rasterises onto that exact grid → 3-state grid
#   3. Saves the initial grid as a GeoTIFF           (grid_initial.tif)
#   4. Solves the AFFVRP MILP once with Gurobi
#   5. Applies the drop schedule to the grid
#   6. Saves the updated grid as a GeoTIFF           (grid_after_drops.tif)
#   7. Saves a visualisation PNG                     (static_result.png)
#   8. Saves a JSON log                              (logs/result.json)
#
# Usage:
#   python run_static.py
#
# Required files in inputs/ :
#   landscape.tif   (GeoTIFF exported/converted from FlamMap6's .lcp)
#   ignition.shp + .shx + .dbf + .prj   (ALL FOUR — a bare .shp will fail)
#
# IMPORTANT: ignition.shp and landscape.tif must come from the SAME FlamMap6
# project/area. If they were generated separately (different landscapes),
# their custom projections will not describe the same physical location and
# the code will raise a clear error rather than silently returning 0 cells.
# =============================================================================

import os
import sys

from config.config import (
    LANDSCAPE_TIF, IGNITION_SHP, OUTPUT_DIR, LOG_DIR,
    NUM_TANKERS, NUM_SCOOPERS,
    AIRFIELD_CELL, WATER_CELLS,
    WIND_DIR_DEG,
)
from grid_utils import (
    load_landscape_georef,
    grid_from_ignition_shp,
    apply_drop_schedule,
    build_extinguished_mask,
    fire_stats,
    save_grid,
    log_result,
    check_cell_in_bounds,
)
from optimisation import build_and_solve
from visualise import plot_result


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR,    exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Load landscape georeferencing (CRS, origin, resolution, dims)
    # ------------------------------------------------------------------
    print(f"\n[run_static] Reading landscape: {LANDSCAPE_TIF}")
    if not os.path.exists(LANDSCAPE_TIF):
        print(f"[ERROR] Landscape file not found: {LANDSCAPE_TIF}")
        sys.exit(1)

    georef = load_landscape_georef(LANDSCAPE_TIF)

    if abs(georef['cell_size_x'] - georef['cell_size_y']) > 1e-6:
        print(f"[WARNING] Non-square cells detected "
              f"({georef['cell_size_x']} x {georef['cell_size_y']}). "
              "The MILP's speed-to-cells conversion assumes square cells; "
              "results may be slightly inaccurate.")

    # Sanity-check configured airfield/water cells against the real grid size
    check_cell_in_bounds('AIRFIELD_CELL', AIRFIELD_CELL, georef)
    for i, wc in enumerate(WATER_CELLS):
        check_cell_in_bounds(f'WATER_CELLS[{i}]', wc, georef)

    # ------------------------------------------------------------------
    # 2. Load ignition shapefile → initial 3-state grid
    # ------------------------------------------------------------------
    print(f"\n[run_static] Reading ignition shapefile: {IGNITION_SHP}")
    for ext in ['.shp', '.shx', '.dbf']:
        sidecar = os.path.splitext(IGNITION_SHP)[0] + ext
        if not os.path.exists(sidecar):
            print(f"[ERROR] Missing required shapefile component: {sidecar}")
            print("        A shapefile needs .shp + .shx + .dbf (+ .prj) "
                  "all present together. Check your inputs/ folder.")
            sys.exit(1)

    grid = grid_from_ignition_shp(IGNITION_SHP, georef)
    stats = fire_stats(grid)
    print(f"[run_static] Grid loaded — "
          f"{stats['burning']} burning cells, "
          f"{stats['unburned']} unburned, "
          f"{stats['total']} total")

    if stats['burning'] == 0:
        print("[run_static] No burning cells found. See warning above for "
              "likely cause (BURN_FRACTION_THRESHOLD too high, or the "
              "polygon is smaller than one grid cell).")
        sys.exit(1)

    if grid[AIRFIELD_CELL[0], AIRFIELD_CELL[1]] == 1:
        print(f"[WARNING] AIRFIELD_CELL {AIRFIELD_CELL} is inside the fire "
              "perimeter. This will likely make the MILP infeasible "
              "(tankers can't start/end inside a burning cell in this "
              "formulation). Move it in config.py.")

    # Save initial grid as GeoTIFF (viewable in QGIS, aligned with landscape.tif)
    initial_tif = os.path.join(OUTPUT_DIR, 'grid_initial.tif')
    save_grid(grid, initial_tif, georef)
    print(f"[run_static] Initial grid saved → {initial_tif}")

    grid_before = grid.copy()
    extinguished_mask = build_extinguished_mask(grid)

    # ------------------------------------------------------------------
    # 3. Solve MILP
    # ------------------------------------------------------------------
    print(f"\n[run_static] Solving AFFVRP MILP "
          f"({NUM_TANKERS} tankers, {NUM_SCOOPERS} scoopers) ...")

    result = build_and_solve(
        grid=grid,
        extinguished_mask=extinguished_mask,
        georef=georef,
        num_tankers=NUM_TANKERS,
        num_scoopers=NUM_SCOOPERS,
        t_offset=0,
        wind_dir_deg=WIND_DIR_DEG,
    )

    print(f"\n[run_static] Gurobi status : {result['status']}")
    print(f"[run_static] Objective     : {result['obj']:.2f}  (total burning cell-timesteps)")
    if result['gap'] is not None:
        print(f"[run_static] MIP gap       : {result['gap']*100:.2f}%")
    print(f"[run_static] Drops planned : {len(result['drop_schedule'])}")
    print(f"[run_static] Z (last drop) : t={result['Z']:.1f} min")

    if result['status'] == 'INFEASIBLE':
        print("\n[ERROR] Model is infeasible. Common causes:")
        print("  - AIRFIELD_CELL is inside the fire perimeter")
        print("  - WINDOW_MINUTES is too short for any aircraft to reach burning cells")
        print("  - WATER_CELLS unreachable by scoopers within the time horizon")
        print("  Tip: compute mdl.computeIIS() in optimisation.py to see exactly")
        print("  which constraints conflict.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4. Apply drops → updated grid
    # ------------------------------------------------------------------
    drop_heading_deg = (WIND_DIR_DEG + 180.0) % 360.0
    grid_after, extinguished_cells = apply_drop_schedule(
        grid, result['drop_schedule'], drop_heading_deg, georef['cell_size_x']
    )

    stats_after = fire_stats(grid_after)
    print(f"\n[run_static] After drops — "
          f"{stats_after['burning']} burning, "
          f"{stats_after['extinguished']} extinguished")
    print(f"[run_static] Cells extinguished this window: {len(extinguished_cells)}")

    # ------------------------------------------------------------------
    # 5. Save updated grid as GeoTIFF  ← the "updated landscape file"
    # ------------------------------------------------------------------
    after_tif = os.path.join(OUTPUT_DIR, 'grid_after_drops.tif')
    save_grid(grid_after, after_tif, georef)
    print(f"[run_static] Updated grid saved → {after_tif}")
    print(f"             Load this in QGIS alongside landscape.tif — they "
          f"share the same CRS/transform so they'll align perfectly.")
    print(f"             Values: 0=unburned, 1=burning, 2=extinguished")

    # ------------------------------------------------------------------
    # 6. Visualise
    # ------------------------------------------------------------------
    plot_result(
        grid_before=grid_before,
        grid_after=grid_after,
        drop_schedule=result['drop_schedule'],
        routes=result['routes'],
        georef=georef,
        output_dir=OUTPUT_DIR,
    )

    # ------------------------------------------------------------------
    # 7. Log
    # ------------------------------------------------------------------
    log_result(
        log_dir=LOG_DIR,
        grid_before=grid_before,
        grid_after=grid_after,
        drop_schedule=result['drop_schedule'],
        opt_result=result,
    )

    # ------------------------------------------------------------------
    # 8. Print drop schedule to console
    # ------------------------------------------------------------------
    if result['drop_schedule']:
        print("\n[run_static] Drop schedule:")
        print(f"  {'Aircraft':<12} {'Type':<8} {'Time (min)':>10} {'Row':>5} {'Col':>5}")
        print("  " + "-" * 45)
        for (ac_id, ac_type, abs_t, r, c) in sorted(result['drop_schedule'], key=lambda x: x[2]):
            print(f"  {ac_id:<12} {ac_type:<8} {abs_t:>10} {r:>5} {c:>5}")
    else:
        print("\n[run_static] No drops were made (fire may be unreachable within the time horizon).")

    print("\n[run_static] Done.")
    print(f"  Outputs → {os.path.abspath(OUTPUT_DIR)}/")
    print(f"  Logs    → {os.path.abspath(LOG_DIR)}/")


if __name__ == '__main__':
    main()
