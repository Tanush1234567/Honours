"""Forecast, solve, validate, commit a prefix, export the new fireline, repeat."""
from dataclasses import asdict, replace
import json
import time
from pathlib import Path
import numpy as np
from .fire_io import save_arrival, write_fire_layers
from .grid_utils import fire_stats
from .optimisation import build_model, solve_model
from .replay import replay_and_validate
from .scenario import World, fleet, prepare_scenario
from .wind import sample_wind


def write_json(path, value):
    """Replace complete JSON files atomically so a live reader sees valid JSON."""
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, indent=2, allow_nan=False) + "\n"
    for attempt in range(7):
        try:
            temp.write_text(payload, encoding="utf-8")
            temp.replace(path)
            return
        except PermissionError as exc:
            # OneDrive and Windows indexers can briefly hold the destination
            # between consecutive window updates. Retain atomic replacement.
            if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 6:
                raise
            time.sleep(0.05 * 2**attempt)


def _has_fire(world):
    return bool(np.any(world.grid == 1)) or (world.fire_geometry is not None and not world.fire_geometry.is_empty)


def _finished(world, settings):
    return not _has_fire(world) and all(
        not a["return_required"] or (world.aircraft[a["id"]]["row"], world.aircraft[a["id"]]["col"]) == settings.airfield
        for a in fleet(settings))


def run_rolling(world, georef, settings, engine, output, make_plots=True):
    settings.validate()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    history = [dict(step=world.step, **fire_stats(world.grid))]
    states = [world.grid.copy()]
    routes = {name: [dict(step=world.step, **p)] for name, p in world.aircraft.items()}
    executed_actions, windows = [], []
    distance, burn_steps, index = 0.0, 0, 0
    status = "LIMIT_REACHED"
    write_fire_layers(world, output / "initial", georef)
    while world.step < settings.total_steps:
        if _finished(world, settings):
            status = "EXTINGUISHED"
            break
        start = world.step
        W = min(settings.horizon_steps, settings.total_steps - start)
        commit = min(settings.commit_steps, W)
        wind = sample_wind(settings, index)
        cfg = replace(settings, horizon_steps=W)
        if cfg.heading_mode == "downwind":
            cfg = replace(cfg, drop_heading_deg=(wind.from_deg + 180) % 360)
        directory = output / f"window_{index:03d}"
        directory.mkdir(parents=True, exist_ok=False)
        if _has_fire(world):
            arrival = engine.forecast(world, georef, cfg, wind, directory / "native")
        else:
            # Recover required aircraft after suppression; no empty-ignition
            # native run, and no premature stop with tankers left in the field.
            arrival = np.full(world.grid.shape, np.inf)
        save_arrival(arrival, directory / "forecast_arrival.tif", georef)
        scenario = prepare_scenario(world, georef, cfg, arrival, commit)
        record = {"index": index, "start_step": start, "horizon_steps": W, "commit_steps": commit,
                  "backend": engine.name, "wind": asdict(wind), "drop_heading_deg": cfg.drop_heading_deg,
                  "initial_aircraft": scenario.initial_aircraft, "before": fire_stats(world.grid),
                  "forecast_cells": len(scenario.burning)}
        write_json(directory / "window.json", record)
        built = build_model(scenario)
        try:
            result = solve_model(built, directory)
        finally:
            built.model.dispose()
        if not result["has_solution"]:
            write_json(directory / "plan.json", result)
            record["solver_status"] = result["status"]
            windows.append(record)
            status = "NO_SOLUTION"
            break
        replay = replay_and_validate(scenario, result)
        result["validated"] = True
        write_json(directory / "plan.json", result)
        prefix_actions = [a for a in result["actions"] if a["end_step"] <= commit]
        for action in prefix_actions:
            executed_actions.append({**action, "start_step": start + action["start_step"],
                                     "end_step": start + action["end_step"],
                                     "heading_deg": cfg.drop_heading_deg})
        for name, route in result["routes"].items():
            for p, q in zip(route[:commit], route[1:commit + 1]):
                distance += (abs(p["row"] - q["row"]) * georef["cell_size_y"] +
                             abs(p["col"] - q["col"]) * georef["cell_size_x"])
            routes[name].extend({**p, "step": start + p["step"]} for p in route[1:commit + 1])
        for t in range(1, commit + 1):
            state = replay["states"][t]
            states.append(state.copy())
            history.append(dict(step=start + t, **fire_stats(state)))
            burn_steps += int(np.sum(state == 1))
        # Only the executed prefix affects reality. The rest is discarded.
        before_world = world
        world = World(replay["states"][commit].copy(), replay["delivered_history"][commit].copy(),
                      {name: {k: route[commit][k] for k in ("row", "col", "water_l")}
                       for name, route in result["routes"].items()}, start + commit)
        if _has_fire(before_world) and hasattr(engine, "advance"):
            engine.advance(before_world, world, georef, cfg, arrival, commit)
        write_fire_layers(world, directory / "executed", georef)
        np.savez_compressed(directory / "checkpoint.npz", grid=world.grid, delivered_l=world.delivered_l)
        record.update(after=fire_stats(world.grid), final_aircraft=world.aircraft,
                      solver_status=result["status"], primary_bound=result.get("primary_bound"),
                      primary_gap=result.get("primary_gap"), executed_actions=len(prefix_actions))
        write_json(directory / "window.json", record)
        write_json(directory / "executed.json", {"start_step": start, "end_step": world.step,
                   "aircraft": world.aircraft, "actions": executed_actions[-len(prefix_actions):] if prefix_actions else [],
                   "validated": True})
        windows.append(record)
        write_json(output / "progress.json", {"step": world.step, "stats": fire_stats(world.grid),
                   "aircraft": world.aircraft, "last_window": index})
        if make_plots:
            from .visualise import plot_window
            plot_window(scenario, replay, result, commit, directory / "window.png", start, engine.name)
        print(f"Window {index}: steps {start}..{world.step}, burning {record['before']['burning']} -> "
              f"{record['after']['burning']}, executed actions {len(prefix_actions)}, {result['status']}", flush=True)
        index += 1
    if _finished(world, settings):
        status = "EXTINGUISHED"
    write_fire_layers(world, output / "final", georef)
    np.savez_compressed(output / "execution.npz", fire_states=np.stack(states), delivered_l=world.delivered_l)
    final = {"status": status, "backend": engine.name, "validated": all(w.get("solver_status") in ("OPTIMAL", "FEASIBLE") for w in windows),
             "steps_executed": world.step, "minutes_executed": world.step * settings.step_minutes,
             "fire_extinguished": not _has_fire(world), "final_stats": fire_stats(world.grid),
             "burn_cell_steps": burn_steps, "burn_cell_minutes": burn_steps * settings.step_minutes,
             "flight_distance_m": distance, "routes": routes, "actions": executed_actions,
             "windows": windows, "fire_history": history, "final_aircraft": world.aircraft}
    drop_actions = [a for a in executed_actions if a["kind"] == "drop"]
    final["last_drop_start_min"] = max((a["start_step"]*settings.step_minutes for a in drop_actions), default=None)
    final["last_drop_completion_min"] = max((a["end_step"]*settings.step_minutes for a in drop_actions), default=None)
    write_json(output / "result.json", final)
    if make_plots:
        from .visualise import plot_summary
        plot_summary(final, output)
    return final
