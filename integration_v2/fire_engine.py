"""Explicit demo forecast and checked TestFARSITE six-field batch adapter."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import heapq
import json
import math
from pathlib import Path
import subprocess
import sys
import numpy as np
from .fire_io import (export_landscape, read_arrival, write_fire_layers, validate_native_fuels,
                      read_perimeter_forecast, mask_polygons)


class DemoEngine:
    name = "DEMO_GRAPH_SPREAD_NOT_FARSITE"

    def forecast(self, world, georef, settings, wind, output):
        """Synthetic Moore-neighbour earliest-arrival propagation, barriers respected.

        Demonstrates the coupling only. This is not Rothermel or a fire forecast.
        """
        arrival = np.full(world.grid.shape, np.inf)
        queue = []
        for r, c in np.argwhere(world.grid == 1):
            seed = 0.0 if world.ignition_minutes is None else min(0.0, float(world.ignition_minutes[r, c]) - world.step*settings.step_minutes)
            arrival[r, c] = seed
            heapq.heappush(queue, (seed, int(r), int(c)))
        limit = settings.horizon_steps * settings.step_minutes
        wind_to = math.radians((wind.from_deg + 180) % 360)
        while queue:
            minutes, r, c = heapq.heappop(queue)
            if minutes != arrival[r, c] or minutes > limit:
                continue
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if not (dr or dc) or not (0 <= rr < arrival.shape[0] and 0 <= cc < arrival.shape[1]):
                        continue
                    if world.grid[rr, cc] == 2:
                        continue
                    east, north = dc * georef["cell_size_x"], -dr * georef["cell_size_y"]
                    distance = math.hypot(east, north)
                    projection = (east * math.sin(wind_to) + north * math.cos(wind_to)) / distance
                    factor = math.exp(0.04 * wind.speed_kph * projection)
                    candidate = minutes + distance / (settings.demo_spread_m_min * factor)
                    if world.grid[rr, cc] == 0:
                        candidate = max(0.0, candidate)
                    if candidate < arrival[rr, cc] and candidate <= limit + 1e-9:
                        arrival[rr, cc] = candidate
                        heapq.heappush(queue, (candidate, rr, cc))
        arrival[world.grid == 1] = 0
        return arrival

    def advance(self, before, after, georef, settings, arrival, commit):
        times = (np.where(before.grid == 1, before.step*settings.step_minutes, np.inf)
                 if before.ignition_minutes is None else before.ignition_minutes.copy())
        new = (before.grid == 0) & (after.grid != 0)
        times[new] = before.step*settings.step_minutes + arrival[new]
        times[after.grid == 2] = np.inf
        after.ignition_minutes = times


@dataclass(frozen=True)
class NativeSettings:
    executable: Path | None = None
    dll_path: Path | None = None
    start: datetime = datetime(2020, 7, 20, 8, 0)
    timeout_s: float = 600.0
    temperature_f: float = 85.0
    humidity_pct: float = 25.0
    elevation_ft: float = 1500.0
    cloud_pct: float = 0.0
    fuel_moistures: tuple = (6, 7, 8, 60, 90)  # 1h, 10h, 100h, live herb, live woody
    timestep_minutes: float = 1.0
    distance_resolution_m: float = 15.0
    perimeter_resolution_m: float = 15.0
    acceleration_on: bool = True
    minimum_forecast_minutes: float = 60.0
    lcp_options: dict | None = None

    def validate(self):
        if self.dll_path is not None:
            if self.executable is not None:
                raise ValueError("Choose the FARSITE DLL or console executable, not both")
            if not Path(self.dll_path).is_file():
                raise FileNotFoundError(f"FARSITE DLL missing: {self.dll_path}")
        else:
            if self.executable is None:
                raise ValueError("Supply a FARSITE DLL or a TestFARSITE executable")
            exe = Path(self.executable)
            if exe.name.lower() == "flammap6.exe":
                raise ValueError("FlamMap6.exe is the GUI. Supply a batch-capable TestFARSITE executable")
            if not exe.is_file():
                raise FileNotFoundError(f"FARSITE console executable missing: {exe}")
        if self.start.tzinfo is not None or self.start.second or self.start.microsecond:
            raise ValueError("Use a local simulation start time at an exact minute, without a time zone")
        for name in ("timeout_s", "timestep_minutes", "distance_resolution_m", "perimeter_resolution_m", "minimum_forecast_minutes"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(self.temperature_f) or not -50 <= self.temperature_f <= 140:
            raise ValueError("temperature_f must be between -50 and 140")
        if not math.isfinite(self.humidity_pct) or not 1 <= self.humidity_pct <= 100:
            raise ValueError("humidity_pct must be in [1,100]")
        if not math.isfinite(self.cloud_pct) or not 0 <= self.cloud_pct <= 100:
            raise ValueError("cloud_pct must be in [0,100]")
        if not math.isfinite(self.elevation_ft) or self.elevation_ft < 0:
            raise ValueError("elevation_ft must be finite and nonnegative")
        if len(self.fuel_moistures) != 5 or any(not isinstance(v, int) or not 0 < v <= 300 for v in self.fuel_moistures):
            raise ValueError("Supply five positive integer fuel moisture percentages <=300")
        if not isinstance(self.acceleration_on, bool):
            raise ValueError("acceleration_on must be a boolean")


def write_native_input(path, start, end, native, wind, seed):
    """Self-contained weather and fuels; English RAWS winds are mph, not km/h.

    Three conditioning days and a trailing day surround the simulated period.
    These uniform demonstration weather values are configurable, not observations.
    """
    if end.year != start.year or (start - timedelta(days=3)).year != start.year or (end + timedelta(days=1)).year != start.year:
        raise ValueError("Native run including conditioning must stay within one calendar year")
    if start.second or end.second or start.microsecond or end.microsecond:
        raise ValueError("Native FARSITE start/end must fall on exact minutes")
    first = (start - timedelta(days=3)).replace(minute=0)
    last = (end + timedelta(days=1)).replace(minute=0) + timedelta(hours=1)
    hours = int((last - first).total_seconds() // 3600) + 1
    lines = ["FARSITE INPUTS FILE VERSION 1.0",
             f"FARSITE_START_TIME: {start:%m %d %H%M}",
             f"FARSITE_END_TIME: {end:%m %d %H%M}",
             f"FARSITE_TIMESTEP: {native.timestep_minutes:g}",
             f"FARSITE_DISTANCE_RES: {native.distance_resolution_m:g}",
             f"FARSITE_PERIMETER_RES: {native.perimeter_resolution_m:g}",
             "FARSITE_MIN_IGNITION_VERTEX_DISTANCE: 1.0",
             "FARSITE_SPOT_PROBABILITY: 0.0", "FARSITE_SPOT_IGNITION_DELAY: 0",
             "FARSITE_MINIMUM_SPOT_DISTANCE: 0.0", f"FARSITE_ACCELERATION_ON: {int(native.acceleration_on)}",
             "FARSITE_FILL_BARRIERS: 1", f"SPOTTING_SEED: {seed}",
             "FUEL_MOISTURES_DATA: 1", "0 " + " ".join(map(str, native.fuel_moistures)),
             f"RAWS_ELEVATION: {native.elevation_ft:g}", "RAWS_UNITS: English", f"RAWS: {hours}"]
    for i in range(hours):
        when = first + timedelta(hours=i)
        lines.append(f"{when:%Y %m %d %H%M} {native.temperature_f:g} {native.humidity_pct:g} 0.0 "
                     f"{wind.speed_kph / 1.609344:.8f} {wind.from_deg:.8f} {native.cloud_pct:g}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")


class FarsiteEngine:
    name = "NATIVE_TESTFARSITE"

    def __init__(self, landscape, georef, native, output):
        native.validate()
        validate_native_fuels(landscape)
        self.native, self.georef = native, georef
        if native.dll_path is not None:
            self.name = "NATIVE_FLAMMAP_FARSITE_DLL"
            probe = subprocess.run(self.worker_command(probe=True), capture_output=True, text=True,
                                   timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if probe.returncode:
                raise RuntimeError(f"FARSITE DLL interface probe failed: {probe.stderr}")
        self.landscape = export_landscape(landscape, Path(output) / "native_landscape.lcp", native.lcp_options)

    def worker_command(self, probe=False):
        return [sys.executable, str(Path(__file__).with_name("native_worker.py")),
                "--dll", str(Path(self.native.dll_path).resolve()), *( ["--probe"] if probe else [])]

    def forecast(self, world, georef, settings, wind, output):
        directory = Path(output).resolve()
        # The legacy batch parser splits on spaces and does not understand
        # quotes. Use short relative names and set cwd, preserving shp sidecars.
        import shutil
        directory.mkdir(parents=True, exist_ok=True)
        staged = directory / "landscape.lcp"
        try:
            staged.hardlink_to(self.landscape)
        except OSError:
            shutil.copy2(self.landscape, staged)
        shutil.copy2(self.landscape.with_suffix(".prj"), staged.with_suffix(".prj"))
        layers = write_fire_layers(world, directory, georef)
        if "ignition" not in layers:
            return np.full(world.grid.shape, np.inf)
        start = self.native.start + timedelta(minutes=world.step * settings.step_minutes)
        # Forecast beyond a short MILP window if needed. The installed engine's
        # short forecasts empirically returned stationary perimeters in this
        # installed build; a full-hour forecast passed the native growth check.
        end = start + timedelta(minutes=max(10.0, self.native.minimum_forecast_minutes,
                                           settings.horizon_steps * settings.step_minutes))
        if start.second or end.second or start.microsecond or end.microsecond:
            raise ValueError("Native coupling requires whole-minute step boundaries")
        if self.native.timestep_minutes > settings.step_minutes:
            raise ValueError("FARSITE internal timestep must not exceed the optimisation timestep")
        write_native_input(directory / "weather.input", start, end, self.native, wind, settings.wind_seed)
        barrier = "barriers.shp" if "barriers" in layers else "0"
        command = f"landscape.lcp weather.input ignition.shp {barrier} fire 1"
        (directory / "command.txt").write_text(command + "\n", encoding="ascii")
        (directory / "request.json").write_text(json.dumps({"backend": self.name, "command": command,
            "start": start.isoformat(), "end": end.isoformat(), "wind_speed_kph": wind.speed_kph,
            "wind_from_deg": wind.from_deg}, indent=2), encoding="utf-8")
        try:
            process = subprocess.run(self.worker_command() if self.native.dll_path is not None else
                                     [str(Path(self.native.executable).resolve()), "command.txt"],
                                     cwd=directory, capture_output=True, text=True, errors="replace",
                                     stdin=subprocess.DEVNULL, timeout=self.native.timeout_s, check=False,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            (directory / "stdout.log").write_text(_timeout_text(exc.stdout), encoding="utf-8")
            (directory / "stderr.log").write_text(_timeout_text(exc.stderr), encoding="utf-8")
            raise RuntimeError("FARSITE timed out; use a noninteractive batch build. See native logs") from exc
        (directory / "stdout.log").write_text(process.stdout, encoding="utf-8")
        (directory / "stderr.log").write_text(process.stderr, encoding="utf-8")
        if process.returncode:
            raise RuntimeError(f"FARSITE exited with code {process.returncode}; see {directory / 'stderr.log'}")
        arrival_path = directory / "fire_ArrivalTime.asc"
        if not arrival_path.is_file():
            # Some TestFARSITE builds return 0 even when a run failed.
            raise FileNotFoundError(f"FARSITE did not produce {arrival_path.name}; see native stdout/stderr")
        # Keep the arrival raster as a checked diagnostic. Timed polygon area
        # coverage supplies the optimiser's fire samples, as in the statement.
        read_arrival(arrival_path, georef, world)
        arrival, self.perimeters = read_perimeter_forecast(directory / "fire_Perimeters.shp", world, georef, settings)
        return arrival

    def advance(self, before, after, georef, settings, arrival, commit):
        from shapely.ops import unary_union
        after.fire_geometry = self.perimeters[commit].difference(unary_union(mask_polygons(after.grid == 2, georef)))


def _timeout_text(value):
    return value.decode(errors="replace") if isinstance(value, bytes) else (value or "")
