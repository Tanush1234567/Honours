# =============================================================================
# orchestrator.py
# Rolling-horizon loop that couples FARSITE fire simulation with the
# spatially-discretised AFFVRP optimiser.
#
# Execution order per window i:
#
#   1. Sample wind for window i
#   2. Run FARSITE for window i  →  updated fire perimeter
#   3. Parse FARSITE output      →  3-state grid
#   4. Run Gurobi AFFVRP         →  drop schedule + aircraft routes
#   5. Apply drops               →  updated grid  (extinguished cells locked)
#   6. Write new ignition shp    →  input for FARSITE window i+1
#   7. Log + plot
#   8. Check termination
#
# Termination conditions:
#   (a) No burning cells remain
#   (b) MAX_ITERATIONS reached
#   (c) All drops exhausted and fire still spreading (fleet insufficient — flagged)
#
# The orchestrator also supports:
#   - Pre-computed mode: run FARSITE for all windows first, then optimise
#     (set PRECOMPUTED = True in config)
#   - Monte Carlo mode: outer loop over fleet combinations (FLEET list in config)
# =============================================================================

import os
import sys
import time
import logging
import pathlib
import numpy as np
from datetime import datetime

# Local modules
from config.config import (
    IGNITION_SHP, OUTPUT_DIR, LOG_DIR,
    WINDOW_MINUTES, MAX_ITERATIONS, FLEET,
    RANDOM_SEED,
)
from wind            import WindSampler, write_wind_file, write_weather_file
from farsite_interface import (
    write_farsite_input,
    write_ignition_shapefile,
    run_farsite,
    parse_farsite_output,
)
from grid_utils import (
    grid_from_ignition_shp,
    apply_drop_schedule,
    build_extinguished_mask,
    is_fire_out,
    fire_stats,
    save_grid,
    log_iteration,
)
from optimisation import build_and_solve
from visualise    import plot_iteration, plot_summary, animate_run


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

#! NO CLUE HOW THIS WORKS. NEED TO LOOK INTO IT

def _setup_logging(log_dir: str, run_tag: str) -> logging.Logger:
    pathlib.Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = os.path.join(log_dir, f'run_{run_tag}.log')

    logger = logging.getLogger('orchestrator')
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s',
                            datefmt='%H:%M:%S')

    fh = logging.FileHandler(log_path, mode='w')
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Single fleet / single simulation run
# ---------------------------------------------------------------------------
def run_simulation(
    num_tankers:  int,
    num_scoopers: int,
    run_tag:      str,
    wind_sampler: WindSampler,
    logger:       logging.Logger,
) -> dict:
    """
    Execute the full rolling-horizon loop for one fleet configuration.

    Returns
    -------
    dict  summary statistics for this run (used by Monte Carlo outer loop)
    """
    out_dir = os.path.join(OUTPUT_DIR, run_tag)
    log_dir = os.path.join(LOG_DIR,    run_tag)
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    pathlib.Path(log_dir).mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting run: {num_tankers} tankers, {num_scoopers} scoopers")
    logger.info(f"Output dir : {out_dir}")

    # ------------------------------------------------------------------
    # Pre-sample all wind events so we can write the full .wnd file
    # that FARSITE needs before it starts.
    # ------------------------------------------------------------------

    #! The wind and weather path are written in the output directory but 
    #! farsite_interface uses input directory. CHECK THIS
    wind_sequence = wind_sampler.sample_sequence(MAX_ITERATIONS)
    wnd_path = os.path.join(out_dir, 'wind.wnd')
    wtr_path = os.path.join(out_dir, 'weather.wtr')
    write_wind_file(wind_sequence, wnd_path)
    write_weather_file(wtr_path, MAX_ITERATIONS)
    logger.info(f"Wind file written → {wnd_path}")

    # ------------------------------------------------------------------
    # Initialise grid from the original ignition shapefile
    # ------------------------------------------------------------------
    grid = grid_from_ignition_shp(IGNITION_SHP)
    extinguished_mask = build_extinguished_mask(grid)

    logger.info(f"Initial fire state: {fire_stats(grid)}")

    # Current ignition shapefile (updated each iteration)
    current_ignition_shp = os.path.join(out_dir, 'ignition_iter_000.shp')
    # Write iteration 0 ignition from the initial grid
    write_ignition_shapefile(grid, current_ignition_shp)

    # Accumulated results
    history = []
    total_drops = 0

    # ------------------------------------------------------------------
    # ROLLING-HORIZON LOOP
    # ------------------------------------------------------------------
    for iteration in range(MAX_ITERATIONS):

        iter_tag    = f'iter_{iteration:03d}'
        iter_outdir = os.path.join(out_dir, iter_tag)
        pathlib.Path(iter_outdir).mkdir(parents=True, exist_ok=True)

        wind = wind_sequence[iteration]
        t_offset = iteration * WINDOW_MINUTES

        logger.info(
            f"=== Iteration {iteration} | t={t_offset}–{t_offset+WINDOW_MINUTES} min "
            f"| wind {wind['speed_kph']:.1f} km/h @ {wind['dir_deg']:.0f}° ==="
        )

        # --------------------------------------------------------------
        # STEP 1: Run FARSITE for this window
        # --------------------------------------------------------------
        logger.info("Running FARSITE …")
        farsite_input = write_farsite_input(
            iteration       = iteration,
            wind_speed_kph  = wind['speed_kph'],
            wind_dir_deg    = wind['dir_deg'],
            ignition_shp    = current_ignition_shp,
            output_subdir   = iter_outdir,
        )
        t_farsite_start = time.time()
        try:
            run_farsite(farsite_input)
            logger.info(f"FARSITE done in {time.time()-t_farsite_start:.1f}s")
        except RuntimeError as e:
            logger.error(f"FARSITE error: {e}")
            logger.warning("Skipping FARSITE output; using previous grid state.")

        # --------------------------------------------------------------
        # STEP 2: Parse FARSITE output → updated grid
        # --------------------------------------------------------------
        try:
            grid_after_farsite = parse_farsite_output(
                iter_outdir, iteration, extinguished_mask
            )
            logger.info(f"Post-FARSITE fire state: {fire_stats(grid_after_farsite)}")
        except FileNotFoundError as e:
            logger.warning(f"Could not parse FARSITE output: {e}. Using previous grid.")
            grid_after_farsite = grid.copy()

        grid_before_opt = grid_after_farsite.copy()

        # Save the post-FARSITE grid as a GeoTIFF checkpoint
        save_grid(grid_after_farsite, os.path.join(iter_outdir, 'grid_post_farsite.tif'))

        # Early exit: fire might have gone out on its own
        if is_fire_out(grid_after_farsite):
            logger.info("Fire extinguished naturally — stopping.")
            break

        # --------------------------------------------------------------
        # STEP 3: Run Gurobi AFFVRP
        # --------------------------------------------------------------
        logger.info(
            f"Running AFFVRP optimiser "
            f"({num_tankers} tankers, {num_scoopers} scoopers) …"
        )
        t_opt_start = time.time()
        opt_result = build_and_solve(
            grid             = grid_after_farsite,
            extinguished_mask= extinguished_mask,
            num_tankers      = num_tankers,
            num_scoopers     = num_scoopers,
            t_offset         = t_offset,
            wind_speed_kph   = wind['speed_kph'],
            wind_dir_deg     = wind['dir_deg'],
            drop_heading_deg = wind['drop_heading'],
        )
        logger.info(
            f"Optimiser done in {time.time()-t_opt_start:.1f}s | "
            f"status={opt_result['status']} | "
            f"obj={opt_result['obj']:.2f} | "
            f"gap={opt_result.get('gap')}"
        )

        drop_schedule = opt_result['drop_schedule']
        routes        = opt_result['routes']
        total_drops  += len(drop_schedule)

        if not drop_schedule:
            logger.warning("Optimiser returned no drops this window.")

        # --------------------------------------------------------------
        # STEP 4: Apply drops to grid
        # --------------------------------------------------------------
        grid_after_drops, ext_cells = apply_drop_schedule(
            grid_after_farsite,
            drop_schedule,
            wind['drop_heading'],
        )
        extinguished_mask = build_extinguished_mask(grid_after_drops)

        logger.info(
            f"Drops applied: {len(drop_schedule)} drops, "
            f"{len(ext_cells)} cells newly extinguished. "
            f"State: {fire_stats(grid_after_drops)}"
        )

        save_grid(grid_after_drops, os.path.join(iter_outdir, 'grid_post_drops.tif'))

        # --------------------------------------------------------------
        # STEP 5: Write new ignition shapefile for next FARSITE run
        # --------------------------------------------------------------
        next_ignition = os.path.join(
            out_dir, f'ignition_iter_{iteration+1:03d}.shp'
        )
        write_ignition_shapefile(grid_after_drops, next_ignition)
        current_ignition_shp = next_ignition

        # --------------------------------------------------------------
        # STEP 6: Log + plot
        # --------------------------------------------------------------
        log_iteration(
            log_dir       = log_dir,
            iteration     = iteration,
            grid_before   = grid_before_opt,
            grid_after    = grid_after_drops,
            drop_schedule = drop_schedule,
            wind          = wind,
            opt_result    = opt_result,
        )

        plot_iteration(
            iteration     = iteration,
            grid_before   = grid_before_opt,
            grid_after    = grid_after_drops,
            drop_schedule = drop_schedule,
            routes        = routes,
            wind          = wind,
            output_dir    = out_dir,
        )

        # Record for summary
        history.append({
            'iteration':    iteration,
            'burning_pre':  fire_stats(grid_before_opt)['burning'],
            'burning_post': fire_stats(grid_after_drops)['burning'],
            'n_drops':      len(drop_schedule),
            'opt_gap':      opt_result.get('gap'),
            'Z':            opt_result.get('Z'),
        })

        # --------------------------------------------------------------
        # STEP 7: Termination check
        # --------------------------------------------------------------
        grid = grid_after_drops

        if is_fire_out(grid):
            logger.info(f"Fire fully extinguished at iteration {iteration}.")
            break
        else:
            remaining = fire_stats(grid)['burning']
            logger.info(f"End of iteration {iteration}: {remaining} cells still burning.")

    # ------------------------------------------------------------------
    # Post-run summary
    # ------------------------------------------------------------------
    plot_summary(log_dir=log_dir, output_dir=out_dir)
    animate_run(output_dir=out_dir)

    summary = {
        'run_tag':       run_tag,
        'num_tankers':   num_tankers,
        'num_scoopers':  num_scoopers,
        'iterations':    len(history),
        'total_drops':   total_drops,
        'final_burning': fire_stats(grid)['burning'],
        'fire_out':      is_fire_out(grid),
        'history':       history,
    }

    logger.info(
        f"Run complete. Iterations={summary['iterations']}, "
        f"Total drops={summary['total_drops']}, "
        f"Fire out={summary['fire_out']}"
    )
    return summary


# ---------------------------------------------------------------------------
# Monte Carlo fleet comparison loop
# ---------------------------------------------------------------------------
def run_monte_carlo(n_simulations: int = 50) -> None:
    """
    Run the full simulation n_simulations times for each fleet in config.FLEET.
    Each simulation uses a different wind seed so fleet options face the same
    sequence of fire conditions, enabling fair comparison.

    Results are saved to outputs/monte_carlo_results.json.
    """
    import json

    run_tag_base = datetime.now().strftime('%Y%m%d_%H%M%S')
    logger = _setup_logging(LOG_DIR, f'mc_{run_tag_base}')
    logger.info(f"Monte Carlo: {n_simulations} simulations × {len(FLEET)} fleets")

    all_results = {}

    for (nt, ns) in FLEET:
        fleet_key  = f'{nt}T_{ns}S'
        fleet_results = []
        logger.info(f"=== Fleet {fleet_key} ===")

        for sim in range(n_simulations):
            seed = (RANDOM_SEED or 0) + sim   # deterministic per sim index
            wind_sampler = WindSampler(seed=seed)
            run_tag = f'{run_tag_base}_{fleet_key}_sim{sim:03d}'

            try:
                summary = run_simulation(nt, ns, run_tag, wind_sampler, logger)
                fleet_results.append(summary)
            except Exception as e:
                logger.error(f"Simulation {sim} failed: {e}")
                fleet_results.append({'error': str(e)})

        all_results[fleet_key] = fleet_results
        logger.info(
            f"Fleet {fleet_key}: "
            f"avg iterations = "
            f"{np.mean([r.get('iterations',0) for r in fleet_results if 'error' not in r]):.1f}, "
            f"fire out in "
            f"{sum(1 for r in fleet_results if r.get('fire_out', False))}/{n_simulations} sims"
        )

    out_path = os.path.join(OUTPUT_DIR, f'monte_carlo_{run_tag_base}.json')
    pathlib.Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    logger.info(f"Monte Carlo results saved → {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='FARSITE + Gurobi rolling-horizon wildfire suppression'
    )
    parser.add_argument(
        '--mode', choices=['single', 'monte_carlo'], default='single',
        help='single: one run per fleet in config. monte_carlo: N runs per fleet.'
    )
    parser.add_argument(
        '--n_sims', type=int, default=50,
        help='Number of Monte Carlo simulations per fleet (ignored in single mode).'
    )
    args = parser.parse_args()

    if args.mode == 'single':
        run_tag_base = datetime.now().strftime('%Y%m%d_%H%M%S')
        master_logger = _setup_logging(LOG_DIR, run_tag_base)

        for (nt, ns) in FLEET:
            sampler = WindSampler(seed=RANDOM_SEED)
            tag     = f'{run_tag_base}_{nt}T_{ns}S'
            run_simulation(nt, ns, tag, sampler, master_logger)

    elif args.mode == 'monte_carlo':
        run_monte_carlo(n_simulations=args.n_sims)
