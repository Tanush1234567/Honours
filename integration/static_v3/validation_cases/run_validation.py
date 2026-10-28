"""Run hand-solvable cases through static_v3 and check independent expectations."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "integration.static_v3.validation_cases"

HERE = Path(__file__).resolve().parent


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def summary_line(name, expected, prefix):
    return (
        f"{prefix} {name}: OPTIMAL | burn={expected['burn_cell_steps']}"
        f" | travel={expected['flight_distance_m']} m"
        f" | drops={len(expected['drop_start_steps'])}"
        f" | refills={len(expected['refill_start_steps'])}"
        f" | final burning={expected['final_burning']}"
        f" | final water={expected['water_l'][-1]} L"
    )


def compare(scenario, result, replay, expected):
    """Compare against hand-derived constants, without fixing solver decisions."""
    import numpy as np

    mismatches = []

    def check(label, actual, wanted):
        if actual != wanted:
            mismatches.append(f"{label}: expected {wanted!r}, got {actual!r}")

    check("status", result["status"], "OPTIMAL")
    check("primary_status", result["primary_status"], "OPTIMAL")
    check("secondary_status", result["secondary_status"], "OPTIMAL")
    check("demand_l", scenario.demand_l, expected["demand_l"])
    check("burn_cell_steps", result["burn_cell_steps"], expected["burn_cell_steps"])
    check("burn_cell_minutes", result["burn_cell_minutes"], expected["burn_cell_steps"])
    if not math.isclose(result["flight_distance_m"], expected["flight_distance_m"], abs_tol=1e-4):
        mismatches.append(f"flight_distance_m: expected {expected['flight_distance_m']}, "
                          f"got {result['flight_distance_m']}")
    check("fleet", sorted(result["routes"]), [expected["aircraft"]])
    route = result["routes"].get(expected["aircraft"], [])
    check("route_cells", [[p["row"], p["col"]] for p in route], expected["route_cells"])
    check("water_l", [p["water_l"] for p in route], expected["water_l"])

    actions = []
    for kind, starts, duration, cell in (
        ("drop", expected["drop_start_steps"], 1, (1, 1)),
        ("refill", expected["refill_start_steps"], expected["refill_duration"], (1, 0)),
    ):
        for start in starts:
            actions.append({
                "aircraft": expected["aircraft"], "kind": kind,
                "start_step": start, "end_step": start + duration,
                "row": cell[0], "col": cell[1], "volume_l": 5000,
            })
    actions.sort(key=lambda action: (action["start_step"], action["aircraft"], action["kind"]))
    check("actions", result["actions"], actions)
    burning = [int(np.count_nonzero(state == 1)) for state in replay["states"]]
    check("burning_history", burning, expected["burning_history"])
    check("final_extinguished", int(np.count_nonzero(replay["states"][-1] == 2)),
          expected["final_extinguished"])
    extinction = next((t for t, state in enumerate(replay["states"]) if state[1, 1] == 2), None)
    check("extinguished_at_step", extinction, expected["extinguished_at_step"])
    for t, state in enumerate(replay["states"]):
        wanted = scenario.grid.copy()
        if expected["extinguished_at_step"] is not None and t >= expected["extinguished_at_step"]:
            wanted[1, 1] = 2
        if not np.array_equal(state, wanted):
            mismatches.append(f"grid at step {t} differs from the expected fire map")

    # Keep the real numerical footprint; do not inject idealised deposition.
    footprint = scenario.footprints[(1, 1)]
    check("footprint cells", sorted(footprint), [(1, 1)])
    credited = footprint.get((1, 1), 0)
    if not 4999 <= credited <= 5000:
        mismatches.append(f"expected 4999..5000 L per drop in the fire cell, got {credited}")
    drops = len(expected["drop_start_steps"])
    check("final delivered_l", int(replay["delivered_l"][1, 1]), drops * credited)
    return mismatches


def run_case(name, expected, output):
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "expected.json", expected)
    try:
        import numpy as np
        from .cases import make_scenario
        from ..optimisation import build_and_solve
        from ..replay import replay_and_validate

        scenario = make_scenario(name)
        write_json(output / "scenario.json", {
            "mode": "fixed_fire_no_spread", "settings": asdict(scenario.settings),
            "grid": scenario.grid.tolist(), "georef": scenario.georef,
            "demand_l": scenario.demand_l,
            "footprint": [{"row": r, "col": c, "litres": v}
                          for (r, c), v in scenario.footprints[(1, 1)].items()],
        })
        result = build_and_solve(scenario, output)
        # Preserve the solver result even if replay or comparison fails.
        write_json(output / "result.json", result)
        if not result["has_solution"]:
            raise ValueError(f"No feasible solver result: {result['status']}")
        replay = replay_and_validate(scenario, result)
        result["validated"] = True
        write_json(output / "result.json", result)
        np.savez_compressed(output / "replay.npz", fire_states=np.stack(replay["states"]),
                            delivered_l=replay["delivered_l"])
        mismatches = compare(scenario, result, replay, expected)
        report = {"case": name, "passed": not mismatches, "replay_validated": True,
                  "mismatches": mismatches}
    except Exception as exc:
        report = {"case": name, "passed": False,
                  "error": f"{type(exc).__name__}: {exc}"}
    write_json(output / "validation.json", report)
    return report


def main(argv=None):
    expectations = json.loads((HERE / "expected_results.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["all", *expectations], default="all")
    parser.add_argument("--expected-only", action="store_true",
                        help="Print expectations without importing model dependencies or solving")
    args = parser.parse_args(argv)
    names = list(expectations) if args.case == "all" else [args.case]
    print("Hand-derived expected results (one-minute steps):")
    for name in names:
        print(summary_line(name, expectations[name], "EXPECTED"))
    if args.expected_only:
        return 0

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    output = HERE / "outputs" / run_id
    output.mkdir(parents=True, exist_ok=False)
    reports = []
    for name in names:
        report = run_case(name, expectations[name], output / name)
        reports.append(report)
        if report["passed"]:
            print(summary_line(name, expectations[name], "PASS"))
        else:
            print(f"FAIL {name}")
            for message in report.get("mismatches", [report.get("error", "Unknown failure")]):
                print(f"  {message}")
    write_json(output / "summary.json", reports)
    passed = sum(report["passed"] for report in reports)
    print(f"{passed}/{len(reports)} cases passed.")
    print(f"Outputs: {output}")
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
