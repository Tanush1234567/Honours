"""Run with `python integration/static_v3/run_static.py` from the repo root."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid
import numpy as np

# Direct script execution and `python -m integration.static_v3.run_static`
# both resolve this package, never another version's config/drop modules.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "integration.static_v3"

from .config import DEFAULTS, LANDSCAPE_TIF, IGNITION_SHP, OUTPUT_DIR
from .grid_utils import load_landscape_georef, grid_from_ignition_shp, save_grid, fire_stats
from .scenario import prepare_scenario
from .optimisation import build_model, solve_model, model_size
from .replay import replay_and_validate
from .visualise import plot_result


def demo_scenario(settings):
    """Small 3-aircraft case that fits a size-limited Gurobi licence."""
    from rasterio.transform import from_origin
    from rasterio.crs import CRS
    grid = np.zeros((5, 5), dtype=np.int8)
    grid[2, 2] = 1
    georef = {"rows": 5, "cols": 5, "cell_size_x": 30.0, "cell_size_y": 30.0,
              "transform": from_origin(0, 150, 30, 30), "crs": CRS.from_epsg(32633)}
    settings = replace(settings, horizon_steps=5, airfield=(0, 0), water_cells=((0, 4), (4, 0)))
    return prepare_scenario(grid, georef, settings)


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deterministic fixed-fire AFFVRP test")
    parser.add_argument("--landscape", type=Path, default=LANDSCAPE_TIF)
    parser.add_argument("--ignition", type=Path, default=IGNITION_SHP)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--demo", action="store_true", help="Run a small synthetic smoke test")
    parser.add_argument("--build-only", action="store_true", help="Build/count the model without solving")
    parser.add_argument("--time-limit", type=float, default=DEFAULTS.time_limit_s)
    parser.add_argument("--tankers", type=int, default=DEFAULTS.num_tankers)
    parser.add_argument("--scoopers", type=int, default=DEFAULTS.num_scoopers)
    parser.add_argument("--horizon", type=int, default=DEFAULTS.horizon_steps)
    parser.add_argument("--airfield", nargs=2, type=int, metavar=("ROW", "COL"))
    parser.add_argument("--water-cell", nargs=2, type=int, action="append", metavar=("ROW", "COL"))
    parser.add_argument("--heading", type=float, default=DEFAULTS.drop_heading_deg)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--write-model", action="store_true")
    args = parser.parse_args(argv)
    settings = replace(DEFAULTS, time_limit_s=args.time_limit, num_tankers=args.tankers,
                       num_scoopers=args.scoopers, horizon_steps=args.horizon,
                       airfield=tuple(args.airfield) if args.airfield else DEFAULTS.airfield,
                       water_cells=tuple(map(tuple, args.water_cell)) if args.water_cell else DEFAULTS.water_cells,
                       drop_heading_deg=args.heading, solver_output=not args.quiet,
                       write_model=args.write_model)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    output = args.output_dir.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    built = None
    try:
        settings.validate()
        if args.demo:
            scenario = demo_scenario(settings)
        else:
            georef = load_landscape_georef(args.landscape)
            grid = grid_from_ignition_shp(args.ignition, georef, settings.ignition_area_fraction)
            scenario = prepare_scenario(grid, georef, settings)
        metadata = {"mode": "fixed_fire_no_spread", "settings": asdict(scenario.settings),
                    "demo": args.demo, "landscape": str(args.landscape.resolve()),
                    "ignition": str(args.ignition.resolve()), "initial_stats": fire_stats(scenario.grid),
                    "grid": {"rows": scenario.georef["rows"], "cols": scenario.georef["cols"],
                             "cell_size_x_m": scenario.georef["cell_size_x"],
                             "cell_size_y_m": scenario.georef["cell_size_y"],
                             "crs": str(scenario.georef["crs"]),
                             "transform": list(scenario.georef["transform"])},
                    "water_demand_per_cell_l": scenario.demand_l}
        _write_json(output / "scenario.json", metadata)
        print(f"Initial grid: {metadata['initial_stats']}")
        print(f"Suppression threshold: {scenario.demand_l} L/cell (demonstration parameter)")
        save_grid(scenario.grid, output / "grid_initial.tif", scenario.georef)
        built = build_model(scenario)
        print(f"Model: {model_size(built)}")
        if args.build_only:
            _write_json(output / "result.json", {"status": "BUILD_ONLY", "has_solution": False,
                                                  "model": model_size(built)})
            print(f"Model built; no solve requested. Outputs: {output}")
            return 0
        result = solve_model(built, output)
        if not result["has_solution"]:
            _write_json(output / "result.json", result)
            print(f"No feasible incumbent: {result['status']}. Diagnostics: {output}", file=sys.stderr)
            return 2
        replay = replay_and_validate(scenario, result)
        result["validated"] = True
        result["final_stats"] = fire_stats(replay["states"][-1])
        result["fire_history"] = [dict(step=t, **fire_stats(g)) for t, g in enumerate(replay["states"])]
        _write_json(output / "result.json", result)
        save_grid(replay["states"][-1], output / "grid_after_drops.tif", scenario.georef)
        np.savez_compressed(output / "replay.npz", fire_states=np.stack(replay["states"]),
                            delivered_l=replay["delivered_l"])
        plot_result(scenario, replay, result, output / "static_result.png")
        print(f"{result['status']}: {result['burn_cell_steps']} burning cell-steps, "
              f"{result['flight_distance_m']:.0f} m travel; final {result['final_stats']}")
        print(f"Replay validated. Outputs: {output}")
        return 0
    except Exception as exc:
        _write_json(output / "error.json", {"status": "ERROR", "has_solution": False,
                                             "exception": type(exc).__name__, "message": str(exc)})
        print(f"Run failed: {exc}\nDiagnostics: {output}", file=sys.stderr)
        return 1
    finally:
        if built is not None:
            built.model.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
