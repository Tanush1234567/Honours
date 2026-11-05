# Dynamic test: implementation, mathematical differences, and validation status

Prepared for the meeting on 6 November 2026. This describes the code currently
present in `integration/`, compared with the separately validated
`integration/static_v3/` implementation. No FlamMap/FARSITE execution or dynamic
Gurobi solve was performed while preparing these notes.

## The central point to explain

The dynamic implementation is an experimental, file-based feedback loop between
FARSITE and an aircraft optimiser. It is **not yet an end-to-end validated
extension of the tested static_v3 model**. The dynamic orchestrator imports the
older `integration/optimisation.py`, not `static_v3/optimisation.py`. The five
passing static cases therefore establish properties of a different optimiser.

A suitable opening statement is:

> I have implemented the structure of a rolling-window coupling. Python writes
> the fire simulator's inputs, launches the external executable, converts its
> output into a grid for the optimiser, and writes the post-suppression grid
> back as the next ignition. The static_v3 model has passed five controlled
> known-answer cases. That validation has not yet been transferred to the
> dynamic integration, which currently calls an older optimisation model and
> still has identified formulation and interface issues.

## 1. How FlamMap/FARSITE and the optimiser communicate

### The components

- `orchestrator.py` coordinates the experiment.
- `farsite_interface.py` writes control and ignition files, launches the fire
  simulator, and parses output files.
- `optimisation.py` constructs and solves the dynamic directory's Gurobi model.
- `grid_utils.py` converts geographic data to the three-state grid and applies
  drop schedules.
- `drop_pattern.py` computes coverage and samples suppression outcomes.
- `wind.py` generates the wind sequence and writes wind/weather files.

The scripts describe FARSITE as the fire-growth component supplied with FlamMap.
The executable configured today is `C:\Workspace\FlamMap6\FlamMap6.exe`, while
the README and function comments describe calling `TestFarsite.exe`. Whether
the configured executable supports the assumed command-line invocation is
unverified.

### The exchange is through files and an in-memory grid

```text
Current burning grid
        |
        v
Ignition shapefile + per-window .input control file
        |
        v
External executable, launched through subprocess.run
        |
        v
ROS raster, or perimeter shapefile as fallback
        |
        v
Python converts output to a three-state NumPy grid
        |
        v
Older integration/optimisation.py builds a Gurobi model
        |
        v
Aircraft routes + drop schedule
        |
        v
Python applies probabilistic drop outcomes to the grid
        |
        v
Remaining burning cells become the next ignition shapefile
        |
        +------------------> next simulator call
```

There is no live socket connection, shared simulator memory, direct exchange of
Gurobi variables with FlamMap, or API that injects each water drop into an
actively running FARSITE process. Python launches the process, waits for it to
finish, and reads its outputs.

### What happens in each iteration

1. Wind is selected from a sequence sampled at the beginning of the run. A
   sample is held constant for that window. Current means are 10 km/h and
   225 degrees, with standard deviations 3 km/h and 15 degrees. The code sets
   drop heading to wind direction plus 180 degrees; its directional convention
   still needs to be checked against the executable's convention.
2. `write_farsite_input()` writes the landscape path, current ignition path,
   start/end times, numerical settings, scalar wind values, output requests,
   and output directory into a `.input` file.
3. `run_farsite()` calls `subprocess.run([FARSITE_EXE, input_file], ...)`. Its
   default timeout is 600 seconds. Successful process termination alone would
   not prove that the expected fire simulation or output interpretation is
   correct.
4. The parser first searches for `_ROS.asc` or `_ROS.tif`. When found, it sets
   cells with `ROS > 0` to burning. Otherwise it searches for a perimeter
   shapefile, rasterises it at ten times the target resolution, and marks a
   coarse cell burning when estimated coverage is greater than 50%.
5. Previously extinguished cells are overwritten with state 2 in Python,
   regardless of the simulator's latest output.
6. The optimiser receives the parsed grid, extinguished mask, fleet size,
   window time offset, wind values, and drop heading. It receives neither the
   complete landscape fuel/terrain model nor a FARSITE fire-history time series.
7. It returns routes and tuples of aircraft ID, type, absolute drop time,
   target row, and target column.
8. `apply_drop_schedule()` applies the drops to the post-FARSITE grid. It does
   not execute them against an advancing fire at their scheduled times; the
   `abs_time` value is unpacked but not used in the update.
9. Only cells still burning are polygonised into the next ignition shapefile.
   The process repeats until the fire-state grid has no burning cells or the
   maximum number of iterations is reached.

### The timing approximation matters

Defaults are 15-minute windows and at most 20 windows, giving a nominal maximum
of 300 simulated minutes. At iteration zero, FARSITE is asked to grow the fire
over minutes 0–15. The optimiser then receives that end-of-window grid but its
schedule is indexed from `t_offset = 0`, with local times 0–14. All drops are
applied afterwards to the end-of-window grid. At the next iteration, FARSITE
starts from the reduced ignition for minutes 15–30.

This implements sequential growth, planning, and suppression updates. It does
not establish a synchronised minute-by-minute trajectory of fire growth and
suppression. Whether the optimiser is intended to plan the elapsed window or
the next future window needs to be resolved explicitly.

### Suppression feedback is a changed ignition, not a changed fuel landscape

The landscape file is reused. The script does not send deposited water, wet
fuel, retardant, or an explicit suppression-barrier map to the fire simulator.
Excluding an extinguished cell from the next ignition does not itself prove
that FARSITE cannot subsequently spread back into or through that location.
The permanent extinguished mask enforces that restriction in the parsed Python
grid, after the simulator has run. This is an interface approximation requiring
validation, not evidence of physically persistent wetting within FARSITE.

## 2. Has the mathematical optimisation model changed?

Relative to the validated static_v3 model, the current dynamic directory uses a
substantially different formulation. It should not be presented as simply
adding an outer FARSITE loop to an otherwise unchanged validated optimiser.

| Component | Validated static_v3 | Current dynamic optimiser |
|---|---|---|
| Position | Integer row/column for each aircraft and boundary | Binary occupancy for every aircraft, grid cell, and time |
| Fire | Fixed burning set; deterministic water-driven extinction | Three binary states per cell and time, with Moore-neighbour propagation constraints |
| Suppression | Integrated integer litres and cumulative threshold | Coverage-triggered extinction lower bounds; no cumulative litres |
| Water | Integer litres with exact balance | Tanker drop units and binary scooper load |
| Service duration | Explicit stationary drop/refill intervals | Location-based actions; imported `R` and `RD` are not enforced as service intervals |
| Time | W action intervals and W+1 boundaries | W states at times 0 through W−1 |
| Objective implementation | Two explicit passes: burn burden then actual displacement | Gurobi multi-objective API: intended burn burden then a defective flight-cost expression |
| Verification | Independent replay plus known-answer comparison | No call to static_v3 replay or equivalent dynamic replay |

### Intended objective and propagation

The dynamic model's primary objective is to minimise the sum of burning-state
indicators over all cells and local times 0 through W−1. This includes the fixed
initial boundary and has no separate boundary W. By contrast, static_v3 counts
boundaries 1 through W.

Neighbourhood propagation adds lower bounds that require a cell to burn when
one of its eight neighbours burns, unless the destination is extinguished. An
upper bound requires a current burning cell or burning neighbour as a source.
These are simplified, wind-independent grid rules, not Rothermel/FARSITE
equations. FARSITE evolves the fire outside the optimiser and the optimiser
also predicts fire evolution with this different rule. Their predictions are
not constrained to match one another.

Wind direction changes the footprint heading. The `wind_speed_kph` argument
does not enter the mathematical constraints or objective. Consequently, passing
the same wind sample to both components is not equivalent to having both use
the same wind-sensitive fire physics.

### Mathematical defects demonstrable without solving

**A. The default fleet is incompatible with depot occupancy.**

`FLEET = [(2, 2)]` means four aircraft. All are constrained to start at the same
airfield cell at time zero, but the occupancy constraint permits at most one
aircraft in every cell, including that airfield. Therefore the default
non-empty-fire model requires `4 <= 1`. If construction reaches a solve, that
formulation is infeasible. Static_v3 explicitly allows shared-depot occupancy.

**B. Extinction is not restricted to delivered suppression.**

The model has absorbing-state and suppression lower bounds but lacks a converse
condition preventing `extinguished = 1` without a drop. It can therefore label
cells extinguished spontaneously to reduce its burning objective. A drop-free
transition from burning to extinguished satisfies the displayed propagation
and suppression inequalities. An isolated burning cell can also lose its
burning state without a persistence constraint. These are formulation defects,
not merely unknown physical parameters.

**C. A scooper can regain water without visiting a source.**

For an empty scooper with no current drop and no next-step water-source visit,
the implemented load bounds allow its next load to be either zero or one.
Choosing one satisfies both bounds, so water conservation is not enforced.
Static_v3's exact balance and refill-completion variables prevent this.

**D. Flight cost is not the cost of the selected transition.**

For each occupied origin, the secondary expression sums distances to all
reachable destinations, multiplied only by the origin occupancy. It does not
select the destination actually occupied at the next time. It is consequently
not the reported total distance flown along the route.

**E. Terminal drop and duration accounting differ from static_v3.**

Drop variables exist at the final local time W−1, but water and fire transitions
only exist through W−2. A final-time drop can therefore be returned without a
corresponding next-boundary consumption or suppression state. Drop and refill
durations are not enforced as stationary service intervals. The variable `Z`
is only lower-bounded by selected drop times and is not minimised; it must not
be interpreted as a verified time to complete extinguishment.

**F. Source and target footprint roles need correction.**

The suppression loop starts with a target cell, reads that cell's outgoing
footprint, and uses the resulting cells as possible drop origins. For
directional/asymmetric footprints this reverses the intended source-to-target
relationship. Static_v3 explicitly accumulates delivery from each selected
origin to its affected targets.

## 3. Other changes from the static test

### Optimiser prediction and applied suppression do not agree

The dynamic optimiser uses deterministic footprint-triggered extinction bounds
and does not account for the magnitude of a positive footprint coefficient.
After solving, the execution helper instead samples extinction with probability

```text
0.8 × exp(−0.3 × distance_in_cells)
```

for each currently burning cell in the footprint. Failed deposits do not build
a stored cumulative water amount. This differs from static_v3's deterministic
threshold model and permits planned suppression to disagree with the applied
fire state. The current dynamic pipeline does not replay and compare the
predicted versus applied fire history.

### Aircraft continuity is not implemented

The fire grid and permanent extinguished mask are carried between iterations.
Aircraft positions and loads are not. Every optimiser call resets each aircraft
to the depot with a full load. Routes are used for plotting but are not turned
into the next window's initial aircraft state. The comment claiming continuity
is handled by the orchestrator does not match the implemented arguments.

### Randomness has two separate sources

Wind uses a seeded `default_rng`. Applied suppression uses the global
`np.random.rand()` generator, for which the dynamic scripts do not set a seed.
The configured wind seed therefore does not reproduce the whole experiment.
Monte Carlo mode assigns comparable wind seeds to fleet alternatives, but has
not established controlled suppression randomness or validated fleet comparisons.

### Geographic preparation is less strict than in static_v3

The dynamic grid is configured as 50×50 cells of 3,000 m, covering 150×150 km.
It uses hard-coded EPSG:32633 and origin values of zero. The transform treats
the configured Y origin as the lower edge despite a configuration comment
calling it the top-left origin. Alignment with the actual landscape must be
checked.

The ROS reader assumes matching raster shape, extent, and resolution, and does
not reproject or resample. The perimeter reader has CRS-checking code inside a
non-executing triple-quoted string. Geographic differences can therefore lead
to errors or incorrect cell placement. The meaning of `ROS > 0` as a burning
mask also requires comparison with actual outputs for the chosen simulation
time; a field called rate of spread is not automatically a validated fire-state
history.

### Current geometry can produce no useful drops

The old footprint code samples density at grid points rather than integrating
over cell polygons. The footprint is 80 m long, compared with 3,000 m cell
spacing. The selected origin lies at the tapered start, where the width and
density are zero. An isolated scalar evaluation of the existing functions at
headings 0, 45, 90, 135, 180, 225, 270, and 315 degrees returned zero affected
cells for all eight headings. This check used standard-library scalar maths
substitutions, not a NumPy integration run. Static_v3's cell integration was
specifically designed to retain water credit on coarse cells.

### Construction cost is substantial before the solver starts

The old movement code loops over every aircraft, interval, origin cell, and
destination cell. At defaults, this is

```text
4 aircraft × 14 transitions × 2,500² cell pairs = 350,000,000 pair checks
```

before considering other model-building work. Most pairs become forbidden-move
constraints. The configured Gurobi time limit does not include Python model
construction. This is a scaling concern derived from loop counts, not a measured
runtime. Static_v3 avoids this all-cell-pair movement construction.

## 4. What is validated?

### Evidence available for the static implementation

Saved results under
`static_v3/validation_cases/outputs/20261015T120839Z_c5439b/` record five passing
controlled cases, both solver stages optimal, independent replay validation,
and no expected-value mismatches:

| Case | Burning cell-steps | Travel | Result |
|---|---:|---:|---|
| Single drop | 1 | 200 m | Pass |
| Two accumulated drops | 2 | 200 m | Pass |
| Tanker refill | 6 | 400 m | Pass |
| Scooper refill | 5 | 400 m | Pass |
| Unreachable fire | 3 | 0 m | Pass |

These use a 3×3, 100 m-cell synthetic grid and one aircraft. They verify the
static implementation's accounting on those cases, not wildfire physics or
the current dynamic code. The static project also contains regression/GIS
tests, a historical record of 25 passing automated checks, and saved
replay-validated full-landscape incumbents without a proof of optimality.

### Evidence available for the dynamic implementation

No end-to-end dynamic result logs or dynamic test suite were found in the
reviewed integration checkout. The expected `integration/outputs` and
`integration/logs` directories are absent. This does not prove no experiment
has ever run elsewhere; it means there is no such evidence here to support a
validation claim.

During this review, the Python files were parsed successfully and selected
scalar geometry and inequality checks were performed. Syntax checks do not
verify imports, executable compatibility, model feasibility, geographic
alignment, real fire outputs, or dynamic feedback.

The correct validation statement is:

> The static implementation has controlled software-verification evidence.
> The current dynamic integration is not yet validated end to end. Its code
> has been reviewed and several definite inconsistencies have been identified.

## 5. What remains unverified without running?

Some issues are already demonstrable; a run is not required to recognise the
depot contradiction, loose extinction/load rules, missing aircraft carryover,
or missing replay. Other questions require execution against real dependencies
and the actual fire simulator:

| Item | Status from this review |
|---|---|
| Python syntax | Parsed successfully |
| Imports in the default terminal environment | Required packages are absent; another IDE environment may differ |
| Ignition dataset completeness | Only `.shp` found; `.shx`, `.dbf`, and `.prj` absent in `integration/inputs` |
| Executable launch and accepted arguments | Not run; configured binary differs from the documented CLI |
| `.input` keys, units, dates, and formats | Generated by code, not accepted/verified with the executable |
| Weather/wind files reaching simulator | Files are generated, but their paths are not emitted by the input writer |
| Weather/wind time resolution | Writers discard minute fields, giving repeated hour records within 15-minute windows |
| ROS/perimeter names and meaning | Assumed by parser; not checked against an actual run |
| Raster/vector/grid alignment | Assumed or hard-coded in dynamic interface; not validated |
| Default multi-aircraft model | Depot constraints are contradictory if a non-empty-fire solve is built |
| Prediction versus applied suppression | Different rules; no dynamic comparison validator |
| Two-window fire feedback | Not demonstrated with a real executable |
| Continuous aircraft state across windows | Missing from current implementation |
| Build time, solve time, and real-time suitability | Not measured for the dynamic setup |
| Physical accuracy and operational safety | Not established by code or static tests |

There is also a failure-handling issue: nonzero simulator exit codes and missing
output can lead the orchestrator to continue using the previous grid. A
completed-looking run can therefore contain windows with no successful FARSITE
advance. A dynamic validation run must identify such windows as failures, not
count them as successful simulator coupling. Missing executables, timeouts, or
other exception types are not all caught by that fallback.

The current input writer imports configured weather/wind filenames but does
not include either in the emitted control file. The files generated by the
orchestrator are also written into the run directory, not those configured
input paths. Actual simulator weather behaviour cannot be inferred merely from
the existence of generated `.wnd` and `.wtr` files.

## A practical validation plan to propose

1. **Reconcile the optimiser first.** Either connect the verified static_v3
   formulation through an explicit dynamic interface or fix the older model
   and give it equivalent known-answer tests. Merely changing an import is not
   sufficient because function signatures, inputs, and result formats differ.
2. **Verify the fire simulator alone.** With complete inputs and an identified
   supported executable, run one short no-suppression case. Compare its
   perimeter with a reference GUI run and verify dates, weather, output names,
   and grid alignment. Treat failure as failure rather than silently reusing
   the previous fire state.
3. **Verify geographic round trips.** Convert a known burning-cell pattern to
   an ignition shapefile and back. Check positions, cell counts, projection,
   transform, and coverage thresholds.
4. **Verify the boundary feedback.** Run two windows with no aircraft, then
   repeat with a deliberately known suppression action. Confirm the next
   ignition represents the intended remaining fire and assess whether the
   external simulator respects the required suppression treatment.
5. **Define and verify time semantics.** Decide whether a forecast is used to
   plan future actions or to update a completed window. Apply drops at the
   intended times, and preserve aircraft position, water load, and any active
   service between replans.
6. **Add dynamic replay and limiting cases.** No fire, no aircraft, no reachable
   targets, failed simulator, one known drop, terminal actions, and two-window
   water conservation should have explicit expected outcomes. A frozen-spread
   configuration using the same formulation should reproduce its static
   benchmark.
7. **Evaluate performance and uncertainty afterwards.** Measure total build,
   solve, parsing, and simulator time; record gaps and failures; seed all random
   streams; then run repeated comparisons. A 300 s solver cap alone does not
   establish that a 15-minute control loop is computationally practical.

## Source locations for questions during the meeting

All line numbers refer to the files reviewed on 5 November 2026.

- Dynamic orchestrator imports: `integration/orchestrator.py:37–59`.
- Wind/weather generation and initialisation: `orchestrator.py:119–137`.
- Simulator call, parsing, and fallback: `orchestrator.py:163–199`.
- Optimiser arguments, drop application, and feedback: `orchestrator.py:209–258`.
- Input-file contents: `farsite_interface.py:93–127`.
- Ignition export: `farsite_interface.py:133–170`.
- Subprocess call: `farsite_interface.py:176–192`.
- ROS/perimeter parsing: `farsite_interface.py:223–305`.
- Model variables and objectives: `optimisation.py:106–204`.
- Fire propagation and suppression: `optimisation.py:225–287`.
- Occupancy and movement: `optimisation.py:303–333`.
- Load bounds and starting aircraft states: `optimisation.py:365–438`.
- `Z` and result extraction: `optimisation.py:440–507`.
- Drop application ignores action time: `grid_utils.py:110–121`.
- Probabilistic suppression: `drop_pattern.py:133–185`.
- Wind seed, heading, and timestamp generation: `wind.py:34–112`.
- Current default parameters: `config/config.py:12–109`.

No application source files were changed during this review.
