# Growing fire: one tanker and one scooper

This is a separate synthetic input set for watching actual FARSITE growth and
rolling aircraft decisions over several windows. The launcher supplies this
scenario's defaults; the existing five-by-five native demo is unchanged.

## Run from the Honours folder

```powershell
.\integration_v2\.venv\Scripts\python.exe .\integration_v2\inputs\growing_fire\run_scenario.py
```

Do not add `--demo` or `--native-demo`: those modes generate different inputs.
This launcher uses the normal real-FARSITE path with the files in this folder.
Run from your Windows login so the installed Gurobi licence matches your user.

To check inputs without solving:

```powershell
.\integration_v2\.venv\Scripts\python.exe .\integration_v2\inputs\growing_fire\run_scenario.py --check
```

Normal runner options can be appended, for example:

```powershell
.\integration_v2\.venv\Scripts\python.exe .\integration_v2\inputs\growing_fire\run_scenario.py --total-steps 24 --time-limit 60 --quiet
```

The time limit is wall-clock seconds per optimisation window; total steps is
simulation duration. Supplying longer runs can allow fire to reach the edge of
this small landscape. The input files are already generated. To recreate them:

```powershell
.\integration_v2\.venv\Scripts\python.exe .\integration_v2\inputs\growing_fire\create_inputs.py
```

## Defaults for this scenario

| Setting | Value |
| --- | --- |
| Grid | 12 by 12 cells, each 30 by 30 m; 360 by 360 m extent |
| Initial fire | Nine cells in a 3 by 3 block: rows 7-9, columns 2-4 (zero based) |
| Landscape | Flat, elevation 100 m, no canopy, standard short-grass fuel model 1 |
| Fleet | One tanker (10,000 L initially) and one scooper (5,000 L initially) |
| Drop volume | 5,000 L per drop, as in the existing model |
| Airfield | Row 11, column 0; both aircraft start here |
| Scooper refill location | Row 11, column 11 |
| Wind | Constant 10 km/h from 225 degrees (southwest), blowing northeast |
| Drop heading | 45 degrees, clockwise from north |
| Plan / execute | Plan six one-minute intervals, execute two, update and repeat |
| Simulation limit | 16 minutes, unless the fire is extinguished and required returns finish earlier |
| Solver time budget | 20 seconds per window |
| Suppression threshold | Existing demonstration value, 1 L/m2 |
| Native forecast | At least 60 minutes internally; only the execution prefix advances the controller |

The refill cell is a configured service point; there is no simulated lake or
water polygon. All terrain, fuel, ignition and weather values are synthetic.
This is a coupling and behaviour demonstration, not a calibrated wildfire case.
Suppression remains the existing permanent cell-threshold/barrier model.

## Outputs and what to watch

Each command gets a new timestamped directory under
`integration_v2/outputs/growing_fire/`, keeping these runs separate from the old
development outputs. Checks and failed attempts also create directories.

- `simulation.gif`: executed grid evolution, with red burning, blue extinguished
  and grey unburned cells. It does not show aircraft icons.
- `window_NNN/window.png`: starting state, executed state with aircraft routes,
  and the rest of that window's proposed forecast.
- `summary.png`: burning/extinguished counts and each aircraft's carried water.
- `result.json`: actual executed drops/refills, routes and fire history.
- `window_NNN/executed/fireline.gpkg`: updated continuous active boundary for GIS.

Growth may create new burning cells while drops extinguish other cells, so the
total burning count alone does not measure all propagation. This case is meant
to persist through multiple windows, not necessarily end in complete extinction.
`LIMIT_REACHED` (exit code 3) means the configured duration ended with fire or
required aircraft recovery remaining; it is not a native engine failure.

## Validation performed

An actual installed-DLL/Gurobi run completed in:

`integration_v2/outputs/growing_fire/20261109T144102Z_c0f8db/`

All eight windows solved to optimality and passed the existing independent plan
replay checks. A separate inspection of the saved inputs and execution arrays
confirmed:

- Valid five-band native landscape, with short-grass fuel in all 144 cells.
- Exactly nine initially burning cells, and exactly one tanker and one scooper.
- Sixteen executed minutes, with 23 previously unburned cells igniting.
- Burning counts at two-minute boundaries: 9 initially, then
  6, 9, 11, 16, 18, 19, 23 and 24.
- Final state: 24 burning, eight extinguished and 112 unburned cells.
- The tanker made two drops; the scooper made four drops and three refills.
- Extinguished grid cells remained extinguished throughout the saved sequence.

This establishes visible native propagation alongside suppression and refill
activity for this installation and configuration. Solver time limits can lead
to different feasible choices on another run; these are reference observations,
not hard-coded trajectories.

Two other folders created during validation are
`20261109T144033Z_d2bcc9` (input check) and
`20261109T144043Z_655254` (sandbox-account Gurobi licence mismatch).
The completed run above used the Windows account matching the licence.

## Files supplied

`landscape.tif` and the matching `ignition.shp/.shx/.dbf/.prj/.cpg` are the actual
GIS inputs. `native_settings.json` holds the native weather/moisture/resolution
settings. `inputs.json` records the input design. `create_inputs.py` reproduces
the GIS files; `run_scenario.py` supplies the scenario-specific runner arguments.
