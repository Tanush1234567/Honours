"""Exercise the real FARSITE DLL through native_worker.py, without Gurobi.

Run from Honours:
  integration_v2/.venv/Scripts/python.exe integration_v2/dll_tests/run_dll_tests.py

Each native operation runs in a child process and leaves its inputs and logs.
The assertions inspect RAW native outputs, before the integration's grid mapper.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
WORKER = HERE.parent / "native_worker.py"
sys.path.insert(0, str(HERE.parents[1]))
SAMPLE_MINUTES = (1, 2, 3, 4)


def require(condition, explanation):
    # Explicit checks also work when Python is run with -O.
    if not condition:
        raise AssertionError(explanation)


def run_worker(dll, directory, timeout, probe=False):
    """Execute only the existing native bridge, never the graph demo."""
    directory.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(WORKER), "--dll", str(dll)]
    if probe:
        command.append("--probe")
    (directory / "invocation.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    try:
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True,
                                errors="replace", stdin=subprocess.DEVNULL, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        for name, data in (("stdout", exc.stdout), ("stderr", exc.stderr)):
            value = data.decode(errors="replace") if isinstance(data, bytes) else (data or "")
            (directory / f"{name}.log").write_text(value, encoding="utf-8")
        raise RuntimeError(f"Native worker timed out after {timeout:g} seconds; see {directory}") from exc
    (directory / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (directory / "stderr.log").write_text(result.stderr, encoding="utf-8")
    return result


def prepare_inputs(output, dll, timeout):
    """Generate known, valid synthetic inputs; do not use the research landscape."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import box
    from integration_v2.fire_engine import NativeSettings
    from integration_v2.fire_io import export_landscape

    inputs = output / "inputs"
    inputs.mkdir()
    transform = from_origin(0, 150, 30, 30)
    # Band order: elevation, slope, aspect, fuel model, canopy cover.
    data = np.zeros((5, 5, 5), dtype="int16")
    data[0] = 100  # Flat terrain at 100 m elevation.
    data[3] = 1    # Standard short-grass fuel, deliberately synthetic.
    source = inputs / "landscape.tif"
    with rasterio.open(source, "w", driver="GTiff", height=5, width=5, count=5,
                       dtype="int16", crs="EPSG:32633", transform=transform) as dst:
        dst.write(data)
    landscape = export_landscape(source, inputs / "landscape.lcp")
    with rasterio.open(landscape) as src:
        require(np.array_equal(src.read(), data), "LCP conversion changed the synthetic pixels")
        require(src.transform.almost_equals(transform), "LCP conversion changed the grid transform")
    native = NativeSettings(dll_path=dll, timeout_s=timeout, minimum_forecast_minutes=60,
                            acceleration_on=True)
    native.validate()
    return {"landscape": landscape, "transform": transform, "crs": "EPSG:32633",
            "initial": box(63, 63, 87, 87), "native": native}


def simulate(context, dll, directory, timeout, ignition, offset_minutes=0):
    """Stage inputs, run FARSITE, then inspect the native files directly."""
    import geopandas as gpd
    import numpy as np
    import rasterio
    from integration_v2.fire_engine import write_native_input
    from integration_v2.wind import Wind

    directory.mkdir()
    shutil.copy2(context["landscape"], directory / "landscape.lcp")
    shutil.copy2(context["landscape"].with_suffix(".prj"), directory / "landscape.prj")
    gpd.GeoDataFrame({"id": [1]}, geometry=[ignition], crs=context["crs"]).to_file(
        directory / "ignition.shp", driver="ESRI Shapefile")
    start = context["native"].start + timedelta(minutes=offset_minutes)
    write_native_input(directory / "weather.input", start, start + timedelta(minutes=60),
                       context["native"], Wind(10.0, 225.0), seed=42)
    (directory / "command.txt").write_text(
        "landscape.lcp weather.input ignition.shp 0 fire 1\n", encoding="ascii")
    process = run_worker(dll, directory, timeout)
    require(process.returncode == 0,
            f"Native worker exited with {process.returncode}; see {directory / 'stderr.log'}")
    for name in ("fire_ArrivalTime.asc", "fire_Perimeters.shp", "fire_Perimeters.shx", "fire_Perimeters.dbf"):
        require((directory / name).is_file(), f"FARSITE did not produce {name}")

    # No initial-fire override, extinguished mask, union, or area-based grid
    # conversion here: these are the bytes/geometries written by FARSITE itself.
    with rasterio.open(directory / "fire_ArrivalTime.asc") as src:
        require(src.shape == (5, 5), f"Arrival raster has unexpected shape: {src.shape}")
        require(src.transform.almost_equals(context["transform"], precision=1e-6),
                "Native arrival raster does not align with the input landscape")
        if src.crs is not None:
            require(src.crs == rasterio.crs.CRS.from_string(context["crs"]), "Native raster CRS mismatch")
        arrival = src.read(1, masked=True).astype(float)
        values = arrival.compressed()
        require(values.size > 0, "Native arrival raster contains only NoData")
        require(np.isfinite(values).all() and (values >= 0).all(), "Invalid native arrival times")
        require(np.any(values > 0), "Native raster reports no positive arrival times")

    frame = gpd.read_file(directory / "fire_Perimeters.shp")
    field = next((name for name in frame.columns if name.lower().startswith("elapsed_m")), None)
    require(field is not None, "Native perimeter file has no elapsed-minute field")
    times = np.asarray(frame[field], dtype=float)
    require(np.isfinite(times).all() and (times >= 0).all(), "Invalid native perimeter times")
    geometry = {}
    for minute in SAMPLE_MINUTES:
        rows = frame.loc[np.isclose(times, minute, atol=1e-6, rtol=0)]
        require(not rows.empty, f"Missing native perimeter at elapsed minute {minute}")
        require(rows.geom_type.isin(["Polygon", "MultiPolygon"]).all(),
                "This synthetic test expects native polygon perimeters")
        require(rows.geometry.notna().all() and rows.geometry.is_valid.all()
                and not rows.geometry.is_empty.any(), f"Invalid perimeter at minute {minute}")
        geometry[minute] = rows.geometry.union_all()
    return {"geometry": geometry, "arrival": arrival, "all_perimeters": frame,
            "area_samples": [{"elapsed_minutes": t, "area_m2": float(geometry[t].area)} for t in SAMPLE_MINUTES],
            "positive_arrival_cells": int(np.sum(values > 0))}


def make_plot(context, baseline, restarted, destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import geopandas as gpd

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for geom, label, color, style in (
        (context["initial"], "Initial ignition", "black", "--"),
        (baseline["geometry"][2], "Perimeter at 2 min / restart input", "#2563eb", "-"),
        (baseline["geometry"][4], "First forecast at 4 min", "#dc2626", "-"),
        (restarted["geometry"][4], "Restart +4 min (global minute 6)", "#9333ea", "-"),
    ):
        gpd.GeoSeries([geom]).boundary.plot(ax=axes[0], color=color, linestyle=style, label=label)
    axes[0].set(xlim=(0, 150), ylim=(0, 150), xlabel="Easting (m)", ylabel="Northing (m)", title="Raw native fire perimeters")
    axes[0].legend(fontsize=7)
    axes[0].set_aspect("equal")
    first = baseline["area_samples"]
    second = restarted["area_samples"]
    axes[1].plot([0] + [p["elapsed_minutes"] for p in first],
                 [context["initial"].area] + [p["area_m2"] for p in first], "o-", label="First forecast")
    axes[1].plot([2] + [2 + p["elapsed_minutes"] for p in second],
                 [baseline["geometry"][2].area] + [p["area_m2"] for p in second], "o-", label="Restart from minute 2")
    axes[1].set(xlabel="Controller time (min)", ylabel="Perimeter area (m²)", title="Measured native area")
    axes[1].legend(fontsize=8)
    view = axes[2].imshow(baseline["arrival"], extent=(0, 150, 0, 150), origin="upper", cmap="inferno")
    axes[2].set(xlabel="Easting (m)", ylabel="Northing (m)", title="Raw arrival raster: full 60-min forecast")
    fig.colorbar(view, ax=axes[2], label="Arrival time (min)")
    fig.suptitle("Real farsite.dll on synthetic terrain — no aircraft or optimiser")
    fig.savefig(destination, dpi=150)
    plt.close(fig)


def write_reports(output, metadata, checks):
    overall = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    result = {"status": overall, "metadata": metadata, "checks": checks}
    (output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# FARSITE DLL test results", "", f"Overall: **{overall}**", "",
             f"DLL: `{metadata['dll']}`", "", f"Outputs: `{output}`", "",
             "| Check | Result | Evidence |", "| --- | --- | --- |"]
    for check in checks:
        lines.append(f"| {check['name']} | {check['status']} | {check['message'].replace('|', '/').replace(chr(10), ' ')} |")
    for check in checks:
        if check.get("metrics"):
            lines.extend(["", f"## {check['name']}", "", "```json", json.dumps(check["metrics"], indent=2), "```"])
    lines.extend(["", "These checks exercise the installed native DLL. The terrain and weather are synthetic.",
                  "A pass checks execution and data exchange; it does not establish real-world forecast accuracy.", ""])
    report = "\n".join(lines)
    (output / "REPORT.md").write_text(report, encoding="utf-8")
    (HERE / "LAST_RUN.md").write_text(report, encoding="utf-8")
    return overall


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dll", type=Path, default=Path(r"C:\Workspace\FlamMap6\farsite.dll"))
    parser.add_argument("--output-dir", type=Path, default=HERE / "outputs")
    parser.add_argument("--timeout", type=float, default=120, help="Seconds allowed per native operation")
    parser.add_argument("--probe-only", action="store_true", help="Load/create/destroy check only; needs standard Python, not GIS packages")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    dll = args.dll.resolve()
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    output = args.output_dir.resolve() / tag
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"dll": str(dll), "dll_sha256": hashlib.sha256(dll.read_bytes()).hexdigest() if dll.is_file() else None,
                "python": sys.version, "python_executable": sys.executable, "python_bits": struct.calcsize("P")*8,
                "platform": platform.platform(), "probe_only": args.probe_only,
                "native_forecast_minutes": 60, "sampled_minutes": list(SAMPLE_MINUTES),
                "synthetic_fuel_model": 1, "wind_kph": 10.0, "wind_from_degrees": 225.0}
    checks, captured = [], {}

    def check(name, action):
        started = time.perf_counter()
        try:
            message, metrics = action()
            record = {"name": name, "status": "PASS", "message": message, "metrics": metrics}
        except Exception as exc:
            record = {"name": name, "status": "FAIL", "message": f"{type(exc).__name__}: {exc}"}
        record["seconds"] = round(time.perf_counter() - started, 3)
        checks.append(record)
        print(f"{record['status']}: {name} - {record['message']}", flush=True)
        return record["status"] == "PASS"

    def probe():
        require(dll.is_file(), f"DLL not found: {dll}")
        process = run_worker(dll, output / "01_probe", args.timeout, probe=True)
        require(process.returncode == 0, f"Interface probe exited with {process.returncode}; see 01_probe/stderr.log")
        require("constructor and destructor available" in process.stdout, "Probe did not confirm native object lifecycle")
        return "Expected exports found; native object created and destroyed in a child process.", {}

    def growth():
        captured["context"] = context = prepare_inputs(output, dll, args.timeout)
        captured["baseline"] = data = simulate(context, dll, output / "02_growth", args.timeout, context["initial"])
        final = data["geometry"][4]
        require(final.area > context["initial"].area + 1e-6, "Fire area did not increase by elapsed minute 4")
        require(final.difference(context["initial"]).area > 1e-6, "Native fire did not grow outside the initial ignition")
        areas = [p["area_m2"] for p in data["area_samples"]]
        require(all(b + 1e-6 >= a for a, b in zip(areas, areas[1:])), "Unexpected shrinking fire in the uniform no-suppression control")
        return "Raw native perimeters expanded; arrival raster contains positive arrival times.", {
            "initial_area_m2": float(context["initial"].area), "native_area_samples": data["area_samples"],
            "positive_arrival_cells": data["positive_arrival_cells"]}

    def repeat():
        context, first = captured["context"], captured["baseline"]
        other = simulate(context, dll, output / "03_repeat", args.timeout, context["initial"])
        import numpy as np
        for minute in SAMPLE_MINUTES:
            require(first["geometry"][minute].symmetric_difference(other["geometry"][minute]).area <= 1e-6,
                    f"Identical inputs produced a different perimeter at minute {minute}")
        a, b = first["arrival"], other["arrival"]
        require(np.array_equal(np.ma.getmaskarray(a), np.ma.getmaskarray(b)), "Repeated raster NoData masks differ")
        require(np.allclose(a.compressed(), b.compressed(), atol=1e-6, rtol=0), "Repeated arrival values differ")
        return "Two independent native runs agreed on sampled shapes and the full arrival raster.", {}

    def restart():
        import geopandas as gpd
        context = captured["context"]
        seed = captured["baseline"]["geometry"][2]
        captured["restart"] = data = simulate(context, dll, output / "04_restart", args.timeout, seed, offset_minutes=2)
        written = gpd.read_file(output / "04_restart" / "ignition.shp").geometry.union_all()
        require(seed.symmetric_difference(written).area <= 1e-6, "Restart ignition lost or changed the native perimeter")
        require(data["geometry"][4].area > seed.area + 1e-6, "Restarted simulation did not grow beyond its carried perimeter")
        return "Native minute-2 perimeter was written as the next ignition and continued growing.", {
            "restart_at_controller_minute": 2, "carried_ignition_area_m2": float(seed.area),
            "restart_native_area_samples": data["area_samples"]}

    def rejected_input():
        directory = output / "05_bad_input"
        directory.mkdir()
        (directory / "command.txt").write_text("missing.lcp weather.input ignition.shp 0 fire 1\n", encoding="ascii")
        process = run_worker(dll, directory, args.timeout)
        require(process.returncode != 0, "Missing landscape was incorrectly accepted")
        require("SetLandscapeFile returned" in process.stderr, "Worker crashed or failed somewhere other than the expected input check")
        require(not (directory / "fire_ArrivalTime.asc").exists(), "Failed run unexpectedly produced a result raster")
        return "A missing landscape caused an explicit worker error rather than a successful forecast.", {"expected_worker_exit_code": process.returncode}

    loaded = check("1. DLL loading and object lifecycle", probe)
    if loaded and not args.probe_only:
        grew = check("2. Real fire growth and native output validation", growth)
        if grew:
            check("3. Repeatability with identical inputs", repeat)
            check("4. Restart from the previous native perimeter", restart)
        else:
            checks.append({"name": "3-4. Repeat and restart", "status": "SKIP", "message": "Growth check failed; no verified baseline to reuse."})
        check("5. Invalid input is rejected", rejected_input)
        if grew and not args.no_plots and "restart" in captured:
            check("6. Inspectable plot", lambda: (
                make_plot(captured["context"], captured["baseline"], captured["restart"], output / "native_results.png")
                or "Saved native_results.png from measured native outputs.", {}))
    overall = write_reports(output, metadata, checks)
    print(f"\nOverall: {overall}\nReport: {output / 'REPORT.md'}\nLatest report: {HERE / 'LAST_RUN.md'}", flush=True)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
