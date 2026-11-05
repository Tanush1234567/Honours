# Test the installed FARSITE DLL

This folder tests **the real installed `farsite.dll`** through
[`native_worker.py`](../native_worker.py). No aircraft, Gurobi, licence for Gurobi,
or graph-spread demo is involved. The test makes its own small landscape and
ignition, sends them to FARSITE, and measures the files FARSITE writes.

## Run it

From the **Honours** folder, in PowerShell:

```powershell
& .\integration_v2\.venv\Scripts\python.exe .\integration_v2\dll_tests\run_dll_tests.py
```

That uses the existing project environment. The default DLL is
`C:\Workspace\FlamMap6\farsite.dll`. For another installation:

```powershell
& .\integration_v2\.venv\Scripts\python.exe .\integration_v2\dll_tests\run_dll_tests.py --dll 'C:\FlamMap6\farsite.dll'
```

Keep the DLL in its FlamMap installation with its companion DLLs and data
folders. Windows and 64-bit Python are required by the existing bridge.

For just the first, simplest test:

```powershell
& .\integration_v2\.venv\Scripts\python.exe .\integration_v2\dll_tests\run_dll_tests.py --probe-only
```

The probe uses only Python's standard library and the installed native libraries.
Full tests use the GIS packages already installed in `integration_v2/.venv`.
For a separate Python environment, install this subfolder's `requirements.txt`.
`--no-plots` skips the plot, and `--timeout 180` changes the time limit **per native
operation**, in seconds. The script can also be run from inside this folder.

## What each test checks

| Test | What I check | Why this matters |
| --- | --- | --- |
| 1. Load the DLL | A child process finds the expected exported functions and creates and destroys a native FARSITE object. | Establishes basic compatibility with the installed binary. It does not by itself prove fire simulation works. |
| 2. Run a fire | FARSITE returns success, writes the raster and shapefile components, supplies valid perimeters at elapsed minutes 1–4, and grows beyond the original ignition. The raster must have the correct dimensions/coordinates and positive arrival times. | Checks actual native calculations and their outputs, beyond function return codes. |
| 3. Repeat the same run | A fresh native process receives identical inputs. Sampled perimeter shapes and arrival raster values must agree within a small numerical tolerance. | Checks repeatability for these fixed inputs with spotting disabled. |
| 4. Restart the fire | The first run's minute-2 polygon becomes the next run's ignition. The written polygon must preserve its shape and the new run must grow beyond it. | Checks that the continuous fireline can be passed back into FARSITE, as required by the dynamic integration. |
| 5. Reject bad input | A deliberately missing landscape must produce a nonzero worker exit and an explicit `SetLandscapeFile` error. It must not produce a result raster. | Checks that an invalid request is reported as a failure. The expected error is a **pass** for this negative test. |
| 6. Make a plot | Plot the measured native perimeters, their areas, and the arrival raster. | Gives you a visual check alongside the numeric assertions. Optional with `--no-plots`. |

No perimeter is artificially enlarged by the Python test. Areas are measured
from the **raw native shapefile**, before the integration unions geometry,
clips suppression cells or converts polygons into the optimiser's grid.

## Inputs used

The generated landscape has five rows and five columns of 30 m cells: a
150 m × 150 m test area. Its five bands contain elevation of 100 m, flat slope,
aspect zero, standard short-grass fuel model 1, and zero canopy cover.

The initial ignition is a 24 m × 24 m square inside the central cell, so its
area is **576 m²**. Wind is fixed at 10 km/h from 225 degrees. The weather,
fuel-moisture values and random seed are fixed and spotting is disabled.
These inputs are synthetic test conditions, not observations of a real fire.

Every native request forecasts 60 minutes, using the workaround already in the
integration. The growth checks inspect minutes 1–4. For the restart, minute 2
of the first forecast becomes time zero of the second forecast. Thus minute 4
of that restarted forecast corresponds to controller minute 6.

## Open the results

The terminal prints `PASS` or `FAIL` for each check. Exit code 0 means the
requested checks passed; exit code 1 means a check failed. A probe-only pass
establishes only library loading/object lifecycle.

Each execution creates a unique directory under `dll_tests/outputs/`:

```text
outputs/<run>/
    REPORT.md                 readable results and numerical measurements
    results.json              machine-readable checks, DLL hash and environment
    native_results.png        measured shapes, area curves and raw arrival raster
    inputs/                   generated GeoTIFF and native LCP landscape
    01_probe/                 library-loading stdout/stderr
    02_growth/                first native forecast: all inputs and outputs
    03_repeat/                same inputs in a fresh native process
    04_restart/               carried native perimeter and second forecast
    05_bad_input/             expected error for the invalid landscape
```

[`LAST_RUN.md`](LAST_RUN.md) contains the report from the most recent execution.
Inside every forecast directory, inspect:

- `command.txt` and `weather.input` to see what was requested;
- `ignition.shp` to see the starting polygon;
- `stdout.log` and `stderr.log` to see native calls and errors;
- `fire_Perimeters.shp` to inspect native fire shapes in QGIS;
- `fire_ArrivalTime.asc` to inspect native arrival times in QGIS.

The arrival raster in the plot covers the **full 60-minute native forecast**;
the area curves show the short intervals used for the tests. Raw native calendar
labels are retained in the shapefile, but these tests use its elapsed-minute
field because the installed build resets calendar labels between restarts.

## What a pass establishes

A pass shows that this particular DLL can be called by this bridge, can produce
fire growth for the supplied synthetic conditions, can repeat that result, and
can accept a previous continuous perimeter as a new ignition. The DLL's SHA-256
hash is recorded so the tested binary is identifiable.

It does not validate the numerical accuracy of FARSITE against a real fire,
prove every terrain/weather combination works, or prove a restart preserves all
internal fuel-moisture and acceleration state. Restarted and uninterrupted runs
are not asserted to be identical. No suppression or aircraft optimisation is
tested here. Your original landscape and the installed DLL are not modified.
