# Static model validation with known answers

Expected result: **5/5 cases passed**, with both solver passes reporting
`OPTIMAL` for every case. These are hand-derived expectations, not results
from a solver run performed while creating this folder.

| Case | Demand (L/cell) | Drop intervals (minutes) | Refill interval | Fire out at minute | Burning cell-steps | Total travel (m) | Final water (L) |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| `single_drop` | 2,500 | 1-2 | None | 2 | 1 | 200 | 5,000 |
| `two_drops` | 7,500 | 1-2, 2-3 | None | 3 | 2 | 200 | 0 |
| `tanker_refill` | 7,500 | 1-2, 6-7 | 3-5 | 7 | 6 | 400 | 0 |
| `scooper_refill` | 7,500 | 1-2, 5-6 | 3-4 | 6 | 5 | 400 | 0 |
| `unreachable` | 2,500 | None | None | Never | 3 | 0 | 10,000 |

The first four cases finish with **0 burning, 1 extinguished, 8 unburned**
cells. The unreachable case finishes with **1 burning, 0 extinguished,
8 unburned** cells.

## Run

From `integration/static_v3`, using your Python environment with the project's
dependencies and a working Gurobi licence:

```powershell
# Inspect expected results only; this does not load Gurobi or solve.
python validation_cases/run_validation.py --expected-only

# Start with the simplest case.
python validation_cases/run_validation.py --case single_drop

# Run all five validation cases.
python validation_cases/run_validation.py
```

You can also open `run_validation.py` in the IDE and run it directly. Paths
are resolved from the script, so the working directory does not affect outputs.
If dependencies are missing, install the existing project requirements in your
chosen environment: `python -m pip install -r requirements.txt`.

After any Gurobi licence/parameter messages, the all-cases run should print:

```text
PASS single_drop: OPTIMAL | burn=1 | travel=200 m | drops=1 | refills=0 | final burning=0 | final water=5000 L
PASS two_drops: OPTIMAL | burn=2 | travel=200 m | drops=2 | refills=0 | final burning=0 | final water=0 L
PASS tanker_refill: OPTIMAL | burn=6 | travel=400 m | drops=2 | refills=1 | final burning=0 | final water=0 L
PASS scooper_refill: OPTIMAL | burn=5 | travel=400 m | drops=2 | refills=1 | final burning=0 | final water=0 L
PASS unreachable: OPTIMAL | burn=3 | travel=0 m | drops=0 | refills=0 | final burning=1 | final water=10000 L
5/5 cases passed.
```

The script prints the `EXPECTED` lines before solving, then the checked `PASS`
or `FAIL` lines. A failed comparison, missing dependency, licence error, or
unproven optimum gives a nonzero exit code and diagnostics. It does not accept
`FEASIBLE` as proof of these known optima. Solver time is limited to 30 seconds
per case; runtime and model build timings are not fixed expected values.

## Why these answers are known

Every case uses a synthetic **3 x 3 grid**, **100 x 100 m cells**, one aircraft,
and **one-minute intervals**. Coordinates are zero-based `(row, column)`.
The depot is `(1, 0)` and the only burning cell is `(1, 1)`: exactly 100 m away.
The scooper water source is also `(1, 0)` to isolate refill duration. Tankers
must return, and scooper return is explicitly enabled for this experiment.

Speed is 100 m/min except in `unreachable`, where it is 50 m/min. A drop
discharges 5,000 L, occupies one stationary interval, and delivers water at
completion. A tanker refill takes two stationary intervals; a scooper refill
takes one. Aircraft start full. The single-drop and two-drop cases use a
10,000 L tanker; refill cases use a 5,000 L aircraft.

The real deposition code is used. The hexagonal footprint is 80 m long and
about 12.65 m wide, points north, and fits entirely inside the fire cell.
Integration and conservative rounding credit 4,999-5,000 L to that cell per
drop. Therefore 2,500 L demand requires one drop and 7,500 L requires two.
Demand is set with `water_demand_l_m2=0.25` or `0.75`, multiplied by the
10,000 m2 cell area. No footprint weights or solver decisions are forced.

- **Single drop:** fly 0-1, drop 1-2, return 2-3. Fire is still burning at
  minute 1 and extinguished at minute 2. Travel is 100 + 100 = 200 m.
- **Two drops:** fly 0-1, drop 1-2 and 2-3, return 3-4. The first deposit
  is below 7,500 L; the second crosses it. Two sampled boundaries are burning.
- **Tanker refill:** fly 0-1, drop 1-2, return 2-3, refill 3-5, fly 5-6,
  drop 6-7, return 7-8. The second drop cannot happen earlier because the
  aircraft is empty after its first drop. Six sampled boundaries are burning.
- **Scooper refill:** the same sequence with refill 3-4, fly 4-5, drop 5-6,
  and return 6-7. Five sampled boundaries are burning.
- **Unreachable:** positions are integer cells. Every move to another cell
  requires at least 100 m, exceeding the 50 m allowed per interval. The aircraft
  stays at the depot, performs no drops, and the fire persists for all three
  sampled boundaries. Travel allowance does not accumulate while waiting.

These earliest completion times give lower bounds on burning cell-steps.
The schedules above attain them and use the minimum required travel, proving
both objective values. Tight horizons also fix the complete routes and loads.
The objective counts burning cells at boundaries **1 through W**, excluding
the initial boundary and including the final one. At one minute per interval,
burning cell-minutes numerically equal burning cell-steps.

## Checks and saved outputs

The runner imports the existing `optimisation.py`, `scenario.py`,
`drop_pattern.py`, and `replay.py`. All parameter overrides live in `cases.py`;
the existing `config.py` and normal runner are unchanged. Hand-derived
expectations are in `expected_results.json`, separate from scenario generation.

Every result first passes the existing independent replay validator, then
is compared with the expected objectives, exact action intervals and volumes,
route at every boundary, water at every boundary, and complete fire history.
It also checks footprint containment and deposited litres. A passing replay
alone is insufficient: a valid but suboptimal schedule fails the known-answer
comparison.

Results go to `validation_cases/outputs/<unique_run_id>/`. Each case contains
`expected.json`, `scenario.json`, `result.json`, `validation.json`, `solver.log`,
`model.lp`, and `replay.npz` when those stages complete. `summary.json` contains
the pass/fail result for every selected case. Existing runs are preserved.

These cases validate the static optimisation and accounting rules. They do
not establish real-world suppression effectiveness, GIS input alignment,
multi-aircraft separation, or fire spread behaviour.
