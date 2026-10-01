"""Independent schedule validation and deterministic fire/load replay."""
import math
import numpy as np
from .scenario import fleet


def replay_and_validate(scenario, result):
    if not result.get("has_solution"):
        raise ValueError("There is no feasible solution to replay")
    s, cfg = scenario, scenario.settings
    W = cfg.horizon_steps
    ac = {a["id"]: a for a in fleet(cfg)}
    routes, actions = result["routes"], result["actions"]
    if set(routes) != set(ac):
        raise ValueError("Routes do not match the configured fleet")
    distance = 0.0
    for name, aircraft in ac.items():
        route = routes[name]
        if len(route) != W + 1 or [p["step"] for p in route] != list(range(W + 1)):
            raise ValueError("A route must contain every state boundary")
        for p in route:
            r, c, q = p["row"], p["col"], p["water_l"]
            if any(not isinstance(v, int) for v in (r, c, q)):
                raise ValueError("Route coordinates and loads must be integers")
            if not (0 <= r < s.grid.shape[0] and 0 <= c < s.grid.shape[1]):
                raise ValueError("Route leaves the grid")
            if not 0 <= q <= aircraft["capacity_l"]:
                raise ValueError("Water load outside capacity")
        if (route[0]["row"], route[0]["col"]) != cfg.airfield or route[0]["water_l"] != aircraft["capacity_l"]:
            raise ValueError("Invalid initial aircraft state")
        if aircraft["return_required"] and (route[-1]["row"], route[-1]["col"]) != cfg.airfield:
            raise ValueError("Aircraft did not return to the airfield")
        for p, q in zip(route, route[1:]):
            d = (abs(p["row"] - q["row"]) * s.georef["cell_size_y"] +
                 abs(p["col"] - q["col"]) * s.georef["cell_size_x"])
            if d > aircraft["speed_m_min"] * cfg.step_minutes + 1e-6:
                raise ValueError("Aircraft exceeds its speed limit")
            distance += d
    for t in range(W + 1):
        occupied = set()
        for route in routes.values():
            cell = (route[t]["row"], route[t]["col"])
            if cell != cfg.airfield and cell in occupied:
                raise ValueError("Aircraft share a non-depot cell")
            occupied.add(cell)
    busy = set()
    used = {(name, t): 0 for name in ac for t in range(W)}
    replenished = {(name, t): 0 for name in ac for t in range(1, W + 1)}
    fire_events = {t: [] for t in range(1, W + 1)}
    for action in actions:
        name, kind = action["aircraft"], action["kind"]
        if name not in ac or kind not in ("drop", "refill"):
            raise ValueError("Unknown aircraft or action")
        a, b, volume = action["start_step"], action["end_step"], action["volume_l"]
        if any(not isinstance(v, int) for v in (a, b, volume)) or not 0 <= a < b <= W or volume <= 0:
            raise ValueError("Invalid action interval/volume")
        cell = action["row"], action["col"]
        duration = cfg.drop_steps if kind == "drop" else ac[name]["refill_steps"]
        if b - a != duration:
            raise ValueError("Wrong service duration")
        for t in range(a, b):
            if (name, t) in busy:
                raise ValueError("Overlapping aircraft actions")
            busy.add((name, t))
        for t in range(a, b + 1):
            p = routes[name][t]
            if (p["row"], p["col"]) != cell:
                raise ValueError("Aircraft moves during its service interval")
        if kind == "drop":
            if volume != cfg.drop_volume_l or cell not in s.footprints:
                raise ValueError("Invalid drop origin/volume")
            used[name, a] += volume
            fire_events[b].append(cell)
        else:
            sites = (cfg.airfield,) if ac[name]["kind"] == "tanker" else cfg.water_cells
            if cell not in sites or volume != ac[name]["capacity_l"] - routes[name][a]["water_l"]:
                raise ValueError("Refill away from a source or wrong refill amount")
            replenished[name, b] += volume
    for name in ac:
        for t in range(W):
            before = routes[name][t]["water_l"]
            after = routes[name][t + 1]["water_l"]
            if used[name, t] > before or after != before - used[name, t] + replenished[name, t + 1]:
                raise ValueError("Water conservation violated")
    delivered = np.zeros_like(s.grid, dtype=np.int64)
    states = [s.grid.copy()]
    burning_mask = s.grid == 1
    for t in range(1, W + 1):
        for cell in fire_events[t]:
            for target, litres in s.footprints[cell].items():
                delivered[target] += litres
        state = s.grid.copy()
        state[burning_mask & (delivered >= s.demand_l)] = 2
        states.append(state)
    for action in actions:
        if action["kind"] == "drop" and states[action["start_step"]][action["row"], action["col"]] != 1:
            raise ValueError("Drop begins on a non-burning cell")
    predicted = result.get("predicted_extinguished")
    if predicted is not None:
        if len(predicted) != W + 1:
            raise ValueError("Missing predicted fire states")
        for t, cells in enumerate(predicted):
            actual = set(map(tuple, np.argwhere(burning_mask & (states[t] == 2)).tolist()))
            if actual != set(map(tuple, cells)):
                raise ValueError(f"Optimiser/replay fire mismatch at boundary {t}")
    burn = sum(int(np.sum(state == 1)) for state in states[1:])
    if burn != result["burn_cell_steps"] or not math.isclose(distance, result["flight_distance_m"], abs_tol=1e-4):
        raise ValueError("Reported objectives do not match replay")
    return {"states": states, "delivered_l": delivered, "burn_cell_steps": burn,
            "flight_distance_m": distance, "validated": True}
