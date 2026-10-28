# Dynamic fireline integration

This folder extends the working `integration/static_v3` experiment into an
automatic FARSITE/Gurobi rolling loop. The original static implementation is
unchanged. Read [EXPLANATION.md](EXPLANATION.md) for the model, the differences
from static v3, and the coupling assumptions.

The controller forecasts fire growth, optimises routes and drops, executes only
the first part of the plan, carries actual aircraft positions and water forward,
exports the updated fireline and suppression barriers, and repeats.

## Run from the Honours folder

An isolated environment has been created at `integration_v2/.venv`. To recreate it:

```powershell
python -m venv integration_v2/.venv
integration_v2/.venv/Scripts/python.exe -m pip install -r integration_v2/requirements.txt
```

Run the real installed FlamMap FARSITE DLL and Gurobi on a small, generated,
valid landscape:

```powershell
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --native-demo --quiet
```

The DLL is detected at `C:\Workspace\FlamMap6\farsite.dll` or
`C:\FlamMap6\farsite.dll`. Set `--farsite-dll PATH` for another installation.
The DLL bridge needs Windows x64 and the accompanying FlamMap DLLs/data folders.
A noninteractive TestFARSITE batch executable is also supported with
`--farsite-exe PATH`. `FlamMap6.exe` is the GUI, not a batch executable.

For a portable coupling demonstration using synthetic graph spread and real
Gurobi, without requiring FlamMap:

```powershell
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --demo --quiet
```

Both small cases use one tanker, a 4-step forecast, a 2-step execution prefix,
and an 8-step limit by default. The backend is recorded in every result. The
graph demo is explicitly labelled `DEMO_GRAPH_SPREAD_NOT_FARSITE`.

To see real FARSITE growth across windows without aircraft suppression:

```powershell
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --native-demo --native-demo-fuel 1 --tankers 0 --quiet
```

The normal native smoke case uses synthetic timber-litter fuel model 8 and a
compact ignition. This control uses short-grass fuel model 1. Reaching the time
limit is expected with no aircraft. The native engine computes at least a
60-minute forecast for reliable fuel conditioning; only the requested planning
window and execution prefix enter the optimiser and executed results.

## Use the research landscape

**The copied static landscape is not ready for dynamic fire simulation.** Its
terrain bands are valid, but fuel-model and canopy bands 4–8 are entirely
`-9999`. Static v3 only uses its grid/georeferencing, so this did not prevent
the static experiment from working. The dynamic runner rejects this input
instead of reporting zero fire growth as a successful forecast.

Supply a complete FlamMap landscape with real fuel data and a polygon ignition
in the same region. A proper GeoTIFF landscape is exported to LCP automatically;
an existing LCP with a `.prj` is supported too. The generated native landscape
and optimiser grid share exactly the same pixels, extent and CRS.

```powershell
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --landscape C:/data/complete_landscape.tif --ignition C:/data/ignition.shp --airfield 0 0 --water-cell 0 229 --water-cell 81 0 --horizon 15 --commit 3 --total-steps 60 --time-limit 120
```

Choose real, in-bounds, initially unburned service sites. The copied sites are
placeholders. Native weather/fuel-moisture defaults are demonstration settings;
set them for the experiment using `--native-config`:

```powershell
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --native-demo --native-config integration_v2/inputs/native_settings.example.json
```

The example contains Fahrenheit temperature, percent humidity, feet elevation,
five fuel-moisture percentages, and native calculation resolutions. Wind is
controlled by `--wind-speed`, `--wind-speed-std`, `--wind-from`,
`--wind-dir-std`, and `--seed`. Native English RAWS records receive mph after
conversion from the configured km/h. `--heading-mode downwind` rotates the
drop footprint using that same sample; the default keeps the static heading.

Check prerequisites without solving:

```powershell
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --native-demo --check
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --check --landscape C:/data/complete_landscape.tif --ignition C:/data/ignition.shp
```

`--prepare-only` checks initial GIS alignment and writes a matching LCP and
initial layers without running the native engine or solver. This permits
inspection of the copied static geometry even though its fuel bands are missing.
Use `--help` for all flags. A normal run requires a valid Gurobi licence; the
full research grid needs a licence permitting large models.

## Outputs

Each run creates a unique directory under `integration_v2/outputs/`.

| File or folder | Meaning |
| --- | --- |
| `scenario.json`, `native_settings.json` | Exact settings, georeferencing and selected backend. |
| `initial/`, `final/` | State GeoTIFF, ignition polygons, permanent suppression barriers and `fireline.gpkg`. |
| `window_NNN/native/` | Staged landscape, weather, ignition, barriers, native arrival/perimeter outputs and stdout/stderr logs. |
| `window_NNN/forecast_arrival.tif` | Cell ignition times relative to this window, in minutes; NoData means unreached. Native values use exact polygon/cell area coverage. |
| `window_NNN/plan.json`, `solver.log` | Full proposed plan, statuses, bounds, routes, loads and objective values. |
| `window_NNN/executed/` | Actual fire state and new continuous fireline after the executed prefix. |
| `window_NNN/checkpoint.npz`, `executed.json` | Carried deposition, fire state, aircraft state and committed actions. |
| `window_NNN/window.png` | Before, executed prefix, and remaining forecast; these are explicitly distinguished. |
| `progress.json` | Latest completed window for monitoring. |
| `result.json`, `execution.npz` | Executed trajectory, actions, statistics and fire history. |
| `summary.png`, `simulation.gif` | Executed fire counts, loads and animation. |
| `error.json` | Actionable diagnostic if a prerequisite or runtime check fails. |

Open `fireline.gpkg` in QGIS to inspect the updated fireline. In native mode this
is the continuous perimeter, including growth smaller than one grid cell;
`grid.tif` is the three-state optimiser representation. Ignition and barrier
shapefiles can also be opened in FlamMap. The program does not edit an already
open FlamMap GUI project.

Exit codes: `0` = extinguished and required returns complete (or successful
check/preparation), `1` = error, `2` = no feasible solver incumbent,
`3` = configured simulation limit reached with fire/recovery remaining.

## Tests

```powershell
integration_v2/.venv/Scripts/python.exe -m pip install -r integration_v2/requirements-dev.txt
integration_v2/.venv/Scripts/python.exe -m pytest integration_v2/tests -q
```

See [VALIDATION.md](VALIDATION.md) for the checks actually performed and their
limits. If Gurobi reports a username mismatch, run from your own Windows login;
the installed academic licence is bound to your username.
