# Validation performed

Validation was performed during implementation on 24 October 2026 (Singapore
client date). The isolated environment is `integration_v2/.venv`, with Python
3.14, Gurobi 13, rasterio, GeoPandas, Shapely, SciPy, Matplotlib and Pillow.

## Automated tests

- **27 dynamic integration tests passed.** These cover timed ignition, retaining
  existing fire without water, cross-window aircraft position/load and partial
  suppression, refill timing, service boundaries, rejecting premature drops,
  no pre-wetting, independent replay rejection, prefix-only execution,
  feedback into the next forecast, slow-spread progress, permanent barriers,
  reproducible wind, exact perimeter area coverage, native batch protocol,
  paths with spaces, missing outputs, native timeout diagnostics, CRS/grid
  mismatch, shapefile round-trip, LCP pixel equality, missing research fuel and
  loading the installed FARSITE DLL, and actual native fire growth with continuous
  perimeter carry-over into a second native forecast, and recovery from a
  transient Windows/OneDrive lock during atomic JSON output.
- **25 original static_v3 regression tests passed.** The baseline source and
  inputs were left unchanged. Existing affine deprecation warnings are not
  integration failures.

The DLL probe test skips on machines without the Windows installation. It
checks native library loading and interface construction/destruction, not fire
physics. Console protocol tests use a test double and are not counted as native
FARSITE simulations.

```powershell
integration_v2/.venv/Scripts/python.exe -m pytest integration_v2/tests -q
integration_v2/.venv/Scripts/python.exe -m pytest integration/static_v3/tests -q
```

The installed Gurobi licence is bound to the user's Windows account. Solver
verification was run under that account after the restricted tool account
reported a username mismatch; no licence file was changed.

## End-to-end runs

`--native-demo --quiet --time-limit 10` ran the installed
`C:\Workspace\FlamMap6\farsite.dll` and Gurobi on the generated 5×5 landscape:

- Backend recorded as `NATIVE_FLAMMAP_FARSITE_DLL`.
- Both optimisation windows reported `OPTIMAL`; independent replay passed.
- The first two executed intervals included one completed drop; the fire cell
  changed from burning to extinguished and the tanker retained 5,000 L.
- The next window carried that state and executed the tanker return.
- Final status `EXTINGUISHED`, 1 burning cell-step, 240 m executed distance,
  24 unburned cells and 1 extinguished cell.
- Native ASCII arrival data, timed perimeter shapefile, clipped fireline,
  JSON logs, GeoTIFFs, summary plot and animation were generated.

This small native smoke case uses synthetic timber-litter fuel model 8 and a
compact ignition. It verifies native execution, GIS exchange, optimisation and
suppression/return accounting; it does **not** establish calibrated physical
spread or suppression accuracy.

A separate **real FARSITE** short-grass control ran:

```powershell
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --native-demo --native-demo-fuel 1 --tankers 0 --total-steps 8 --quiet --no-plots
```

Across four two-step windows, burning-cell counts changed from 1 to 1, 3, 4 and
4. The continuous fireline length increased each window (approximately 151,
193, 232 and 263 m). The run reached its configured limit with 21 executed
burning cell-steps and zero flight distance. This checks actual native spread
and feedback, not a test double. Native growth sensitivity on a real complete
fuel landscape remains necessary for the research experiment.

The graph `--demo` with an aircraft also extinguished its initial fire and
returned the tanker with the same routing/water metrics. A separate no-aircraft
control used:

```powershell
integration_v2/.venv/Scripts/python.exe integration_v2/run_dynamic.py --demo --tankers 0 --total-steps 8 --quiet --wind-speed 0 --wind-speed-std 0 --wind-dir-std 0 --demo-spread 10
```

That control demonstrates growth across successive committed windows, including
growth requiring more time than one execution prefix. `LIMIT_REACHED` and exit
code 3 are expected because no aircraft are available to suppress the fire.
The generated `result.json` contains the complete executed fire counts.
That graph control's counts at executed boundaries 2, 4, 6 and 8 were 1, 5,
13 and 21 cells; its executed total was 68 burning cell-steps.

Two native integration details were caught during these checks: ignition setup
must precede loading the native model inputs, and this build returned misleading
stationary perimeters for short forecasts. A fuel-conditioning issue is the
suspected cause of the latter; it was not verified inside the binary. The final default native
forecast is at least 60 minutes even for a short optimisation window. Only the
executed prefix is charged or applied. These fixes are covered by the native
growth test.

## Research-data check

The copied static TIFF has shape 82×230 and eight bands. All 18,860 pixels in
each of bands 4–8 equal -9999. Its ignition rasterisation marks 960 cells.
Native FARSITE rejected ignition on that missing fuel data during the initial
check. The final runner detects the missing fuel band before launching FARSITE.

LCP export of the copied source preserved all eight pixel arrays, shape,
transform and CRS. The copied TIFF and four ignition shapefile components
remain byte-identical to their static_v3 counterparts. The separate old LCPs
have a different grid and were not substituted.

The integration is implemented and its native/demo execution paths were tested.
A real landscape with populated fuel data is still required to run the user's
original geographical scenario. Missing research fuel was not replaced with
invented fuel values. Synthetic fuel exists only in the explicitly requested
`--native-demo` landscape within that run's output folder.
