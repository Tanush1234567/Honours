# Static v3: fixed-fire aerial firefighting test

This is a self-contained replacement experiment under `integration/static_v3`.
It does not change or import the older static tests or rolling integration.
The bundled landscape and ignition files are copied unchanged from
`static_test_fixed_v2/static_test_final/inputs` at commit
`b4589e4dd5ee2c12499219faeb4f75cb7ac7c1ad`.

## What “static” means here

The initial ignition is a **fixed fire snapshot**. There is no FARSITE call,
fire spread, natural burnout, stochastic suppression, or rolling horizon.
An initially burning cell stays burning until cumulative water delivered to it
reaches its threshold. Unburned cells remain unburned; extinguished cells stay
extinguished. All aircraft decisions are for one finite horizon.

This deliberately isolates routing, refill logistics, suppression accounting,
and GIS alignment. It is not a wildfire forecast. Dynamic propagation and
feedback to FARSITE belong in a later integration change.

## Run

From the **Honours repository root**, with Python 3.10 or newer:

```bash
python -m venv .venv
# Activate .venv using your platform's command, then:
python -m pip install -r integration/static_v3/requirements.txt

# Small end-to-end case, suitable for Gurobi's size-limited licence:
python integration/static_v3/run_static.py --demo

# Bundled 82 x 230 landscape; needs a Gurobi licence permitting larger models:
python integration/static_v3/run_static.py

# Inspect full-size model construction without solving:
python integration/static_v3/run_static.py --build-only
```

You can also run `python run_static.py` from inside `integration/static_v3`.
All default input/output paths are relative to the new package, independent
of the working directory. `--demo` uses a synthetic 5 x 5 grid, 5 intervals,
and its own valid depot/water locations; fleet sizes still come from settings.

For your own data:

```bash
python integration/static_v3/run_static.py --landscape path/to/landscape.tif --ignition path/to/ignition.shp --airfield 0 0 --water-cell 0 229 --water-cell 81 0 --time-limit 120
```

Run `--help` for flags, including `--tankers`, `--scoopers`, `--horizon`,
`--heading`, `--quiet`, and `--write-model`. Edit the `Settings` defaults in
`config.py` for capacities, speed, service times and suppression parameters.

The bundled depot/water cells are **placeholders**, not verified infrastructure.
Every site must be in bounds and outside the initial burning area. The landscape
must use metres and a north-up, unrotated affine transform. Rectangular pixels
are supported. The shapefile needs `.shp`, `.shx`, `.dbf`, and `.prj` files.

## Changes from v2

| Previous problem | v3 behavior |
| --- | --- |
| Multiple aircraft forced into a capacity-one depot | Depot sharing is allowed; other sampled positions remain exclusive. |
| Fire disappears without water | Exact cumulative-water threshold determines extinguishment. |
| Isolated burning cells turn unburned | Initial burning cells persist until the threshold is met. |
| Flight objective sums distances to unused destinations | Objective sums actual consecutive Manhattan displacement in metres. |
| Scoopers regain water by waiting | Explicit start/full load, discharge, source-only refill and conservation. |
| Footprint mapping reversed | Every source has an explicit target-to-litres map shared with replay. |
| Reflected heading and missed origin cell | Centred world-coordinate hexagon with exact cell intersections. |
| Probabilistic execution contradicts deterministic model | Deterministic cumulative deposition used consistently. |
| Final drops have no water cost or state consequence | W intervals, W+1 boundaries, with actions completed by W. |
| Argument mismatch after solving | One package-level scenario and result contract. |
| Multi-objective attribute errors and misleading objective labels | Two single-objective passes with separate values, bounds and statuses. |
| Arbitrary Z value | Actual last drop start/completion times calculated from the schedule. |
| Quadratic enumeration of all landscape cells | Integer aircraft coordinates and target/action variables; no cell-pair loops. |
| Timeout without incumbent treated as a solution | Explicit `has_solution=false`, null objectives, and nonzero exit status. |

## Explicit modelling choices

**Water deposition:** the footprint retains the old hexagonal dimensions:
length `2 * drop_ramp_m + drop_plateau_m`, width
`drop_k * drop_height_m**1.5`. Its origin is now its **centre**, and heading
is specified directly (0=north, 90=east), without a wind-from/wind-to conversion.
The original longitudinal profile and lateral Gaussian are normalised over that
polygon. Exact cell intersections bound a cell-area integral: the lateral normal
CDF is integrated analytically, and the along-track profile uses adaptive
quadrature. The Gaussian is truncated at the hexagon's +/-3-sigma boundary and
normalised there. Allocations are rounded down to integer litres. Water
outside the raster, on non-burning cells, and sub-litre remainders is not
redistributed. This conserves discharged volume.

This retains the previous profile's shape without treating a density at one
point as a coverage probability. Footprint weights now have explicit water-volume
units. Profile parameters still need empirical calibration for the aircraft used.

**Extinguishment:** `water_demand_l_m2=1.0` is a **demonstration assumption**,
not an empirical suppression threshold. At 30 m resolution it gives 900 L per
cell. Multiple drops can accumulate toward that threshold. Change this parameter
for your study; do not interpret the default as a real-world effectiveness claim.
The 50% area rule applies to **initial ignition rasterisation**, not to converting
a density value into a suppression probability.

**Routing:** movement limits and costs both use Manhattan distance. This gives
a genuine linear distance objective and a conservative substitute for straight-line
travel. A route can wait. Drops and refills occupy fixed-location service intervals;
these represent a local manoeuvre, not a detailed aircraft trajectory. Speed is not
rounded up when a cell is too large to cross in one timestep. Tankers return by the
end; scoopers return only if `return_scoopers=True`.

**Service timing:** a drop consumes water at its start and deposits water at its
completion. Refill water is credited only at completion. An aircraft cannot move
or perform another action while in service. Refill is to full capacity, with
configurable positive durations. The defaults are 1 interval/drop, 2/tanker refill,
and 1/scooper refill.

**Objective:** minimise burning-cell samples at boundaries 1..W, then distance
without worsening the primary incumbent. The initial fixed sample is excluded,
and the final boundary is included so terminal actions have a measured effect.
`burn_cell_minutes` scales the sampled sum by timestep duration. This is a
discrete post-action metric, not an exact continuous-time burn-area integral.

**Optimality:** 80% of the solver budget is initially allocated to the burning
objective; any remaining time goes to distance. If the primary pass times out,
the second pass protects its incumbent, but the final status is `FEASIBLE` rather
than globally `OPTIMAL`. Construction time is measured separately. See
`MODEL.md` for the formulation and limits.

## Outputs

Each run creates a unique directory under `integration/static_v3/outputs/`:

| File | Contents |
| --- | --- |
| `scenario.json` | Parameters, grid georeferencing, paths and initial statistics. |
| `result.json` | Status, objective values, bounds/gaps, routes, loads, timed actions, fire history and validation flag. |
| `grid_initial.tif` | Initial fire states, aligned with the landscape. |
| `grid_after_drops.tif` | Independently replayed final fire states. |
| `replay.npz` | Full fire-state trajectory and final delivered litres. |
| `static_result.png` | Initial/final fire maps and routes. |
| `solver.log` | Gurobi log when solver output is enabled. |
| `model.lp` | Optional model export with `--write-model`. |
| `infeasible.ilp` | IIS if the primary model is infeasible. |
| `error.json` | Failure details, including licence/dependency/runtime errors. |

State values are 0=unburned, 1=burning, 2=extinguished. The output GeoTIFF is a
fire-state raster; it does not replace the landscape's fuel/elevation bands.

Before successful output, the independent replay checks positions, speed,
service duration, depot return, occupancy, drop eligibility, water conservation,
every predicted extinguishment state, and both reported objectives.

## Tests and validation

```bash
python -m pip install -r integration/static_v3/requirements-dev.txt
python -m pytest integration/static_v3/tests -q
```

Tests include no-aircraft fire persistence, shared depot feasibility, a known
single-fire optimum, stationary zero-distance routes, final-interval water
accounting, refill service, cumulative suppression, directional source/target
mapping, footprint conservation/orientation, low-speed movement, GIS round trips,
and invalid solution rejection. Solver tests report an explicit skip if Gurobi
or its licence is unavailable.

The bundled ignition has **960** burning cells under exact polygon intersections
and an inclusive 50% threshold. The v2 README's 959 came from a 10x sampled area
test with a strict `>` threshold. The input files themselves have not changed.

See `VALIDATION.md` for the actual test/build results and full-size solve limit.

## Remaining scope boundaries

There is no calibration of fire intensity, fuel, evaporation, wind drift, terrain,
turn radius, continuous-path collision avoidance, or runway queues. Non-depot
occupancy is checked at discrete boundaries only. Landscape bands supply GIS
alignment here, not burnability or fire physics. These are declared model limits,
not features claimed by the solver status. The current static model should be
validated and calibrated before connecting it to the rolling simulation.
