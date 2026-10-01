# Validation performed before publishing static_v3

Date: 2026-10-01. Source inputs: repository commit
`b4589e4dd5ee2c12499219faeb4f75cb7ac7c1ad`.

## Executed checks

- **25 pytest tests passed**, including actual small Gurobi solves. No solver
  tests were skipped in this environment.
- The CLI synthetic demo ran end to end with the default 2-tanker/1-scooper
  fleet and passed independent schedule/fire replay validation.
- That demo reached **OPTIMAL**, with 1 burning cell-step, 120 m Manhattan
  travel, and zero burning cells at the final boundary. A scooper can finish
  at the fire; tanker return remains compulsory. The separate single-tanker
  test verifies a 240 m return route for the same fire location.
- The actual bundled landscape was loaded and its ignition rasterised using
  exact polygon intersections: **82 x 230, 30 m pixels, 960 burning cells**.
- The final full model built successfully in approximately **4.2 seconds** here:
  **74,693 variables**, **58,951 binaries**, **74,643 linear constraints**, and
  **29,442 general constraints**. Times are measurements, not performance guarantees.
- GIS output was reopened and checked for matching CRS, affine transform,
  dimensions and fire-state values.

## Full-size solve limitation

The installed Gurobi licence is size-limited. A full-input solve was attempted
and rejected by Gurobi with `Model too large for size-limited license`.
No full-landscape optimality, suppression outcome, or solve-time claim is made.
Use an academic/full licence and run `python integration/static_v3/run_static.py`
to solve that case. The failure is captured in `error.json` and exits nonzero.

## Environment

Small solves and regression tests used Python 3.12, Gurobi 12.0.3,
NumPy 2.3.5, Rasterio 1.4.4, GeoPandas 1.1.1, Shapely 2.1.2 and PyProj 3.7.2,
with SciPy supplying the normal CDF and adaptive quadrature for deposition.
Rasterio 1.4.3 segfaulted on raster reads in this environment; upgrading to
1.4.4 resolved the GIS round-trip checks. Requirements therefore specify
Rasterio >=1.4.4.

## Interpretation

These tests validate software invariants and the documented static formulation.
They do not calibrate the default 1 L/m2 suppression threshold, Gaussian hexagonal
deposition, or aircraft manoeuvre model. No rolling/FARSITE code was changed.
