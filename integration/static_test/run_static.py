# =============================================================================
# run_static.py
# Entry point for the static (single-window, no FARSITE) test.
#
# What it does:
#   1. Reads the ignition shapefile → 3-state grid  (BURNING where fire is)
#   2. Saves the initial grid as a GeoTIFF           (grid_initial.tif)
#   3. Solves the AFFVRP MILP once with Gurobi
#   4. Applies the drop schedule to the grid
#   5. Saves the updated grid as a GeoTIFF           (grid_after_drops.tif)
#   6. Saves a visualisation PNG                     (static_result.png)
#   7. Saves a JSON log                              (logs/result.json)
#
# Usage:
#   python run_static.py
#
# Before running, edit config/config.py:
#   - GRID_ORIGIN_X, GRID_ORIGIN_Y  ← from gdalinfo on your landscape/ignition file
#   - GRID_ROWS, GRID_COLS          ← grid dimensions
#   - GRID_CRS                      ← must match your ignition shapefile CRS
#   - AIRFIELD_CELL, WATER_CELLS    ← grid-index locations
#   - NUM_TANKERS, NUM_SCOOPERS     ← fleet size
# =============================================================================

import os
import sys

from config.config import (
    IGNITION_SHP, OUTPUT_DIR, LOG_DIR,
    NUM_TANKERS, NUM_SCOOPERS,
    WIND_DIR_DEG,
)
from grid_utils import (
    grid_from_ignition_shp,
    apply_drop_schedule,
    build_extinguished_mask,
    fire_stats,
    save_grid,
    log_result,
)
from optimisation import build_and_solve
from visualise import plot_result


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR,    exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Load ignition shapefile → initial 3-state grid
    # ------------------------------------------------------------------
    print(f"\n[run_static] Reading ignition shapefile: {IGNITION_SHP}")
    if not os.path.exists(IGNITION_SHP):
        print(f"[ERROR] Ignition shapefile not found: {IGNITION_SHP}")
        print("        Place your ignition .shp (and accompanying .dbf/.shx/.prj)")
        print("        in the inputs/ folder, then re-run.")
        sys.exit(1)

    grid = grid_from_ignition_shp(IGNITION_SHP)
    stats = fire_stats(grid)
    print(f"[run_static] Grid loaded — "
          f"{stats['burning']} burning cells, "
          f"{stats['unburned']} unburned, "
          f"{stats['total']} total")

    if stats['burning'] == 0:
        print("[run_static] No burning cells found. "
              "Check GRID_ORIGIN_X/Y and GRID_CRS match your shapefile.")
        sys.exit(1)

    # Save initial grid as GeoTIFF (viewable in QGIS)
    initial_tif = os.path.join(OUTPUT_DIR, 'grid_initial.tif')
    save_grid(grid, initial_tif)
    print(f"[run_static] Initial grid saved → {initial_tif}")

    grid_before = grid.copy()
    extinguished_mask = build_extinguished_mask(grid)

    # ------------------------------------------------------------------
    # 2. Solve MILP
    # ------------------------------------------------------------------
    print(f"\n[run_static] Solving AFFVRP MILP "
          f"({NUM_TANKERS} tankers, {NUM_SCOOPERS} scoopers) ...")

    result = build_and_solve(
        grid=grid,
        extinguished_mask=extinguished_mask,
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
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Apply drops → updated grid
    # ------------------------------------------------------------------
    drop_heading_deg = (WIND_DIR_DEG + 180.0) % 360.0
    grid_after, extinguished_cells = apply_drop_schedule(
        grid, result['drop_schedule'], drop_heading_deg
    )

    stats_after = fire_stats(grid_after)
    print(f"\n[run_static] After drops — "
          f"{stats_after['burning']} burning, "
          f"{stats_after['extinguished']} extinguished")
    print(f"[run_static] Cells extinguished this window: {len(extinguished_cells)}")

    # ------------------------------------------------------------------
    # 4. Save updated grid as GeoTIFF  ← this is the "updated landscape file"
    # ------------------------------------------------------------------
    after_tif = os.path.join(OUTPUT_DIR, 'grid_after_drops.tif')
    save_grid(grid_after, after_tif)
    print(f"[run_static] Updated grid saved → {after_tif}")
    print(f"             Load this in QGIS to inspect the post-drop fire state.")
    print(f"             Values: 0=unburned, 1=burning, 2=extinguished")

    # ------------------------------------------------------------------
    # 5. Visualise
    # ------------------------------------------------------------------
    plot_result(
        grid_before=grid_before,
        grid_after=grid_after,
        drop_schedule=result['drop_schedule'],
        routes=result['routes'],
        output_dir=OUTPUT_DIR,
    )

    # ------------------------------------------------------------------
    # 6. Log
    # ------------------------------------------------------------------
    log_result(
        log_dir=LOG_DIR,
        grid_before=grid_before,
        grid_after=grid_after,
        drop_schedule=result['drop_schedule'],
        opt_result=result,
    )

    # ------------------------------------------------------------------
    # 7. Print drop schedule to console
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
