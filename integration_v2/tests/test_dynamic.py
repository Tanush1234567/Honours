from dataclasses import replace
import copy
import json
import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin
from integration_v2.config import Settings
from integration_v2.scenario import initial_world, prepare_scenario, World
from integration_v2.optimisation import build_model, solve_model
from integration_v2.replay import replay_and_validate
from integration_v2.orchestrator import run_rolling
from integration_v2.fire_engine import DemoEngine
from integration_v2.wind import Wind, sample_wind


def example(**changes):
    cfg = Settings(horizon_steps=4, commit_steps=2, total_steps=8, num_tankers=1,
                   num_scoopers=0, water_cells=((0, 4),), solver_output=False,
                   solver_threads=1, time_limit_s=5)
    cfg = replace(cfg, **changes)
    grid = np.zeros((5, 5), dtype="int8")
    grid[2, 2] = 1
    ref = {"rows": 5, "cols": 5, "cell_size_x": 30., "cell_size_y": 30.,
           "transform": from_origin(0, 150, 30, 30), "crs": CRS.from_epsg(32633)}
    return initial_world(grid, cfg), ref, cfg


def snapshot(world):
    return np.where(world.grid == 1, 0., np.inf)


def solve(scenario, force=None):
    built = build_model(scenario)
    try:
        if force:
            force(built)
        result = solve_model(built)
        assert result["has_solution"], result
        replay = replay_and_validate(scenario, result)
        return result, replay
    finally:
        built.model.dispose()


def test_forecast_arrivals_are_timed_and_old_fire_persists():
    world, ref, cfg = example(num_tankers=0)
    arrival = snapshot(world)
    arrival[2, 3] = 2.2
    scenario = prepare_scenario(world, ref, cfg, arrival, 2)
    result, replay = solve(scenario)
    assert result["burn_cell_steps"] == 6  # 4 old + 2 samples after ceil(2.2).
    assert [int(g[2, 3]) for g in replay["states"]] == [0, 0, 0, 1, 1]
    assert all(g[2, 2] == 1 for g in replay["states"])


def test_unburned_zero_arrival_waits_until_first_boundary():
    world, ref, cfg = example(num_tankers=0)
    arrival = snapshot(world)
    arrival[1, 1] = 0
    scenario = prepare_scenario(world, ref, cfg, arrival, 2)
    _, replay = solve(scenario)
    assert replay["states"][0][1, 1] == 0
    assert replay["states"][1][1, 1] == 1


def test_carry_position_load_and_partial_water_across_windows():
    world, ref, cfg = example(water_demand_l_m2=6.)  # 5400 L requires two hits.
    scenario = prepare_scenario(world, ref, cfg, snapshot(world), 2)
    result, replay = solve(scenario, lambda b: b.model.addConstr(b.drop[0, 0, 1] == 1))
    assert replay["states"][2][2, 2] == 1
    carried = World(replay["states"][2], replay["delivered_history"][2],
                    {"tanker_0": {k: result["routes"]["tanker_0"][2][k] for k in ("row", "col", "water_l")}}, 2)
    assert carried.aircraft["tanker_0"] == {"row": 2, "col": 2, "water_l": 5000}
    next_s = prepare_scenario(carried, ref, cfg, snapshot(carried), 2)
    result2, replay2 = solve(next_s, lambda b: b.model.addConstr(b.drop[0, 0, 0] == 1))
    assert result2["routes"]["tanker_0"][0]["water_l"] == 5000
    assert replay2["states"][1][2, 2] == 2
    assert replay2["delivered_history"][1][2, 2] > replay["delivered_history"][2][2, 2]


def test_no_refill_or_drop_may_straddle_execution_boundary():
    world, ref, cfg = example()
    world.aircraft["tanker_0"]["water_l"] = 5000
    scenario = prepare_scenario(world, ref, cfg, snapshot(world), 2)
    b = build_model(scenario)
    try:
        assert b.refill[0, cfg.airfield, 1].UB == 0  # Would complete at 3, beyond cut=2.
        assert b.refill[0, cfg.airfield, 0].UB == 1
    finally:
        b.model.dispose()


def test_cannot_drop_before_forecast_ignition():
    world, ref, cfg = example()
    arrival = snapshot(world)
    arrival[3, 3] = 3.0
    scenario = prepare_scenario(world, ref, cfg, arrival, 2)
    j = scenario.burning.index((3, 3))
    b = build_model(scenario)
    try:
        assert all(b.drop[0, j, t].UB == 0 for t in (0, 1, 2))
        assert b.drop[0, j, 3].UB == 1
    finally:
        b.model.dispose()


def test_replay_rejects_teleport_and_free_water():
    world, ref, cfg = example()
    scenario = prepare_scenario(world, ref, cfg, snapshot(world), 2)
    result, _ = solve(scenario)
    bad = copy.deepcopy(result)
    bad["routes"]["tanker_0"][0]["water_l"] = 0
    with pytest.raises(ValueError, match="initial aircraft"):
        replay_and_validate(scenario, bad)


def test_no_prewetting_future_cells():
    world, ref, cfg = example()
    arrival = snapshot(world)
    arrival[2, 3] = 3
    scenario = prepare_scenario(world, ref, cfg, arrival, 2)
    # Force an asymmetric footprint to make early splash onto future fire large.
    scenario.footprints[(2, 2)] = {(2, 2): 1000, (2, 3): 1000}
    scenario.footprints[(2, 3)] = {(2, 3): 1000}
    def force(b):
        for key, flag in b.drop.items():
            b.model.addConstr(flag == int(key == (0, 0, 1)))
    _, replay = solve(scenario, force)
    assert replay["delivered_history"][2][2, 3] == 0
    assert replay["states"][3][2, 3] == 1


class RecordingEngine:
    name = "TEST_FORECAST"

    def __init__(self):
        self.seen = []

    def forecast(self, world, ref, settings, wind, output):
        self.seen.append(copy.deepcopy(world))
        arrival = snapshot(world)
        # A new cell in every window demonstrates automatic state updates.
        cell = (3, min(4, len(self.seen)))
        if world.grid[cell] == 0:
            arrival[cell] = 1
        return arrival


def test_end_to_end_feedback_and_executed_prefix_only(tmp_path):
    world, ref, cfg = example(num_tankers=0, total_steps=5)
    engine = RecordingEngine()
    result = run_rolling(world, ref, cfg, engine, tmp_path, make_plots=False)
    assert result["status"] == "LIMIT_REACHED"
    assert result["steps_executed"] == 5
    assert len(result["windows"]) == 3
    assert engine.seen[1].step == 2
    assert engine.seen[1].grid[3, 1] == 1
    assert len(result["fire_history"]) == 6
    assert result["validated"]
    assert (tmp_path / "window_001" / "executed" / "fireline.gpkg").is_file()
    assert json.loads((tmp_path / "result.json").read_text())["burn_cell_steps"] == result["burn_cell_steps"]


def test_unexecuted_actions_do_not_affect_world(tmp_path):
    # Slow aircraft cannot reach the fire inside the first two steps. All drops
    # occur in the unexecuted future and must not alter the checkpoint.
    world, ref, cfg = example(tanker_speed_m_min=30., horizon_steps=10, total_steps=2)
    engine = RecordingEngine()
    result = run_rolling(world, ref, cfg, engine, tmp_path, make_plots=False)
    assert not result["actions"]
    assert result["final_stats"]["extinguished"] == 0
    assert result["final_aircraft"]["tanker_0"]["water_l"] == 10000


def test_extinguished_cells_are_native_and_demo_barriers():
    world, ref, cfg = example()
    world.grid[:, 3] = 2
    world.delivered_l[:, 3] = 900
    arrival = DemoEngine().forecast(world, ref, cfg, Wind(0, 0), None)
    assert np.isinf(arrival[:, 3:]).all()
    assert np.isfinite(arrival[2, 2])


def test_wind_seed_is_reproducible_across_fleets():
    _, _, cfg = example()
    assert sample_wind(cfg, 1) == sample_wind(replace(cfg, num_tankers=3), 1)
    assert sample_wind(cfg, 0) != sample_wind(cfg, 1)


def test_invalid_commit_duration_is_rejected():
    _, _, cfg = example(commit_steps=1)
    with pytest.raises(ValueError, match="service durations"):
        cfg.validate()


def test_slow_demo_spread_does_not_restart_progress_each_window():
    world, ref, cfg = example(num_tankers=0, demo_spread_m_min=6., wind_speed_mean_kph=0.)
    engine, wind = DemoEngine(), Wind(0, 0)
    # A neighbour takes 5 minutes, longer than a 2-minute committed prefix.
    for start in (0, 2):
        world.step = start
        arrival = engine.forecast(world, ref, cfg, wind, None)
        after = copy.deepcopy(world)
        after.step = start + 2
        engine.advance(world, after, ref, cfg, arrival, 2)
        world = after
    arrival = engine.forecast(world, ref, cfg, wind, None)
    assert arrival[2, 3] == pytest.approx(1.)


def test_json_output_recovers_from_transient_windows_file_lock(tmp_path, monkeypatch):
    from pathlib import Path
    from integration_v2.orchestrator import write_json
    original = Path.replace
    count = [0]
    def locked_once(path, target):
        count[0] += 1
        if count[0] == 1:
            error = PermissionError("transient OneDrive lock")
            error.winerror = 32
            raise error
        return original(path, target)
    monkeypatch.setattr(Path, "replace", locked_once)
    path = tmp_path / "progress.json"
    write_json(path, {"step": 2})
    assert json.loads(path.read_text()) == {"step": 2}
    assert count[0] == 2
