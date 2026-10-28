"""Run from any working directory, or python -m integration_v2.run_dynamic."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "integration_v2"

from .config import DEFAULTS, LANDSCAPE, IGNITION, OUTPUT_DIR
from .fire_engine import DemoEngine, FarsiteEngine, NativeSettings
from .fire_io import export_landscape
from .grid_utils import load_landscape_georef, grid_from_ignition_shp, fire_stats
from .orchestrator import run_rolling, write_json
from .scenario import initial_world, prepare_scenario


def demo_world(settings):
    from rasterio.transform import from_origin
    from rasterio.crs import CRS
    grid = np.zeros((5, 5), dtype="int8")
    grid[2, 2] = 1
    georef = {"rows": 5, "cols": 5, "cell_size_x": 30.0, "cell_size_y": 30.0,
              "transform": from_origin(0, 150, 30, 30), "crs": CRS.from_epsg(32633)}
    return initial_world(grid, settings), georef


def find_console():
    import shutil
    candidate = shutil.which("TestFARSITE") or shutil.which("TestFARSITE.exe")
    if candidate:
        return Path(candidate)
    for root in (Path(r"C:\Workspace\FlamMap6"), Path(r"C:\FlamMap6")):
        for name in ("TestFARSITE.exe", "TestFarsite.exe"):
            if (root / name).is_file():
                return root / name
    return Path(r"C:\Workspace\FlamMap6\TestFARSITE.exe")


def main(argv=None):
    p = argparse.ArgumentParser(description="Rolling FARSITE + Gurobi fireline integration")
    p.add_argument("--demo", action="store_true", help="Synthetic spread + real Gurobi; not FARSITE")
    p.add_argument("--native-demo", action="store_true", help="Real installed FARSITE + Gurobi on a generated valid 5x5 landscape")
    p.add_argument("--native-demo-fuel", type=int, default=8, help="Native demo standard fuel model: 8 (timber litter), or 1 for a fast-growing control")
    p.add_argument("--check", action="store_true", help="Validate inputs/configuration and native prerequisites without solving")
    p.add_argument("--prepare-only", action="store_true", help="Validate GIS and export matching LCP without requiring FARSITE")
    p.add_argument("--landscape", type=Path, default=LANDSCAPE)
    p.add_argument("--ignition", type=Path, default=IGNITION)
    native_group = p.add_mutually_exclusive_group()
    native_group.add_argument("--farsite-exe", type=Path, help="Optional alternative: noninteractive TestFARSITE console build")
    native_group.add_argument("--farsite-dll", type=Path, help="Defaults to C:\\Workspace\\FlamMap6\\farsite.dll when installed")
    p.add_argument("--native-config", type=Path, help="JSON overrides for NativeSettings (weather, fuel moisture, resolutions, LCP units)")
    p.add_argument("--start", type=datetime.fromisoformat, default=NativeSettings.start,
                   help="Simulation local date/time, e.g. 2020-07-20T08:00")
    p.add_argument("--farsite-timeout", type=float, default=600)
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    p.add_argument("--horizon", type=int, help="Planning intervals; default 15 (demo 4)")
    p.add_argument("--commit", type=int, help="Executed intervals before reforecast; default 3 (demo 2)")
    p.add_argument("--total-steps", type=int, help="Simulation limit; default 60 (demo 8)")
    p.add_argument("--step-minutes", type=float, default=DEFAULTS.step_minutes)
    p.add_argument("--tankers", type=int, help="Default 2 (demo 1)")
    p.add_argument("--scoopers", type=int, help="Default 1 (demo 0)")
    p.add_argument("--airfield", type=int, nargs=2, metavar=("ROW", "COL"))
    p.add_argument("--water-cell", type=int, nargs=2, action="append", metavar=("ROW", "COL"))
    p.add_argument("--time-limit", type=float, default=DEFAULTS.time_limit_s)
    p.add_argument("--seed", type=int, default=DEFAULTS.wind_seed)
    p.add_argument("--wind-speed", type=float, default=DEFAULTS.wind_speed_mean_kph, help="Mean km/h")
    p.add_argument("--wind-speed-std", type=float, default=DEFAULTS.wind_speed_std_kph)
    p.add_argument("--wind-from", type=float, default=DEFAULTS.wind_from_mean_deg)
    p.add_argument("--wind-dir-std", type=float, default=DEFAULTS.wind_from_std_deg)
    p.add_argument("--heading", type=float, default=DEFAULTS.drop_heading_deg)
    p.add_argument("--heading-mode", choices=("fixed", "downwind"), default="fixed")
    p.add_argument("--demo-spread", type=float, default=DEFAULTS.demo_spread_m_min, help="Demo spread m/min")
    p.add_argument("--water-demand", type=float, default=DEFAULTS.water_demand_l_m2, help="Demonstration suppression threshold L/m2")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("--write-model", action="store_true")
    args = p.parse_args(argv)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    output = args.output_dir.resolve() / tag
    output.mkdir(parents=True, exist_ok=False)
    try:
        if args.demo and args.native_demo:
            raise ValueError("Choose --demo or --native-demo")
        small = args.demo or args.native_demo
        cfg = replace(DEFAULTS,
                      horizon_steps=args.horizon if args.horizon is not None else (4 if small else 15),
                      commit_steps=args.commit if args.commit is not None else (2 if small else 3),
                      total_steps=args.total_steps if args.total_steps is not None else (8 if small else 60),
                      num_tankers=args.tankers if args.tankers is not None else (1 if small else DEFAULTS.num_tankers),
                      num_scoopers=args.scoopers if args.scoopers is not None else (0 if small else DEFAULTS.num_scoopers),
                      airfield=tuple(args.airfield) if args.airfield else DEFAULTS.airfield,
                      water_cells=tuple(map(tuple, args.water_cell)) if args.water_cell else (((0, 4), (4, 0)) if small else DEFAULTS.water_cells),
                      step_minutes=args.step_minutes, time_limit_s=args.time_limit, solver_output=not args.quiet,
                      solver_seed=args.seed, wind_seed=args.seed, drop_heading_deg=args.heading,
                      heading_mode=args.heading_mode, wind_speed_mean_kph=args.wind_speed,
                      wind_speed_std_kph=args.wind_speed_std, wind_from_mean_deg=args.wind_from,
                      wind_from_std_deg=args.wind_dir_std, demo_spread_m_min=args.demo_spread,
                      water_demand_l_m2=args.water_demand, write_model=args.write_model)
        cfg.validate()
        if small:
            world, georef = demo_world(cfg)
            if args.native_demo:
                import rasterio
                args.landscape = output / "synthetic_landscape.tif"
                bands = np.zeros((5, 5, 5), dtype="int16")
                bands[0] = 100  # Elevation m; flat slope/aspect; no canopy.
                if args.native_demo_fuel not in range(1, 14):
                    raise ValueError("--native-demo-fuel must be a standard model in 1..13")
                bands[3] = args.native_demo_fuel
                with rasterio.open(args.landscape, "w", driver="GTiff", height=5, width=5, count=5,
                                   dtype="int16", crs=georef["crs"], transform=georef["transform"]) as dst:
                    dst.write(bands)
                from shapely.geometry import box
                world.fire_geometry = box(63, 63, 87, 87)  # 64% of the central cell.
        else:
            georef = load_landscape_georef(args.landscape)
            grid = grid_from_ignition_shp(args.ignition, georef, cfg.ignition_area_fraction)
            world = initial_world(grid, cfg)
            import geopandas as gpd
            from shapely.geometry import box
            tr = georef["transform"]
            extent = box(tr.c, tr.f + tr.e*georef["rows"], tr.c + tr.a*georef["cols"], tr.f)
            world.fire_geometry = gpd.read_file(args.ignition).to_crs(georef["crs"]).geometry.union_all().intersection(extent)
        # Validate initial service locations, aircraft and deposition before
        # launching native code or constructing an expensive MILP.
        prepare_scenario(world, georef, cfg, np.where(world.grid == 1, 0.0, np.inf), cfg.commit_steps)
        metadata = {"mode": "rolling_horizon", "backend": DemoEngine.name if args.demo else FarsiteEngine.name,
                    "settings": asdict(cfg), "landscape": None if args.demo else str(args.landscape.resolve()),
                    "ignition": None if small else str(args.ignition.resolve()), "synthetic_landscape": args.native_demo,
                    "initial_stats": fire_stats(world.grid),
                    "grid": {"rows": georef["rows"], "cols": georef["cols"], "crs": str(georef["crs"]),
                             "transform": list(georef["transform"])}}
        write_json(output / "scenario.json", metadata)
        if args.prepare_only:
            if args.demo:
                raise ValueError("--prepare-only needs a real multiband landscape; omit --demo")
            preparation_options = None
            if args.native_config:
                preparation_values = json.loads(args.native_config.read_text(encoding="utf-8"))
                if not isinstance(preparation_values, dict):
                    raise ValueError("Native JSON must be an object")
                preparation_options = preparation_values.get("lcp_options")
            export_landscape(args.landscape, output / "landscape.lcp", preparation_options)
            from .fire_io import write_fire_layers
            write_fire_layers(world, output / "initial", georef)
            print(f"Matching LCP and GIS prepared: {output}")
            return 0
        if args.demo:
            engine = DemoEngine()
        else:
            from .fire_io import validate_native_fuels
            validate_native_fuels(args.landscape, world.grid)
            dll = args.farsite_dll
            if dll is None and args.farsite_exe is None:
                for candidate in (Path(r"C:\Workspace\FlamMap6\farsite.dll"), Path(r"C:\FlamMap6\farsite.dll")):
                    if candidate.is_file():
                        dll = candidate
                        break
            native = NativeSettings(executable=(args.farsite_exe or find_console()).resolve() if dll is None else None,
                                    dll_path=dll.resolve() if dll else None, start=args.start, timeout_s=args.farsite_timeout)
            if args.native_config:
                values = json.loads(args.native_config.read_text(encoding="utf-8"))
                if not isinstance(values, dict) or {"executable", "dll_path", "start", "timeout_s"} & values.keys():
                    raise ValueError("Native JSON must be an object; executable/start/timeout use CLI flags")
                if "fuel_moistures" in values:
                    values["fuel_moistures"] = tuple(values["fuel_moistures"])
                native = replace(native, **values)
            engine = FarsiteEngine(args.landscape, georef, native, output)
            write_json(output / "native_settings.json", {**asdict(native), "executable": str(native.executable) if native.executable else None,
                       "dll_path": str(native.dll_path) if native.dll_path else None, "start": native.start.isoformat()})
            metadata["backend"] = engine.name
            write_json(output / "scenario.json", metadata)
        if args.check:
            print(f"Inputs/configuration checked for {engine.name}. No fire simulation or solve performed. Outputs: {output}")
            return 0
        print(f"Backend: {engine.name}; planning {cfg.horizon_steps}, executing {cfg.commit_steps} steps per window", flush=True)
        result = run_rolling(world, georef, cfg, engine, output, not args.no_plots)
        print(f"{result['status']}: {result['steps_executed']} executed steps, "
              f"{result['burn_cell_steps']} burning cell-steps, {result['flight_distance_m']:.0f} m travel")
        print(f"Outputs: {output}")
        return {"EXTINGUISHED": 0, "NO_SOLUTION": 2, "LIMIT_REACHED": 3}[result["status"]]
    except Exception as exc:
        write_json(output / "error.json", {"status": "ERROR", "exception": type(exc).__name__, "message": str(exc)})
        print(f"Run failed: {exc}\nDiagnostics: {output}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
