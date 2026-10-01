from dataclasses import replace
import copy
import numpy as np
import pytest
from integration.static_v3.config import Settings
from integration.static_v3.scenario import prepare_scenario
from integration.static_v3.drop_pattern import compute_drop_footprint
from integration.static_v3.replay import replay_and_validate


def scenario(fires=((2, 2),), shape=(5, 5), **kwargs):
    cfg = Settings(horizon_steps=kwargs.pop("horizon_steps", 5),
                   num_tankers=kwargs.pop("num_tankers", 1),
                   num_scoopers=kwargs.pop("num_scoopers", 0),
                   water_cells=kwargs.pop("water_cells", ((0, 4),)),
                   solver_output=False, time_limit_s=10, solver_threads=1, **kwargs)
    grid = np.zeros(shape, dtype=np.int8)
    for cell in fires:
        grid[cell] = 1
    return prepare_scenario(grid, {"rows": shape[0], "cols": shape[1],
                                  "cell_size_x": 30., "cell_size_y": 30.}, cfg)


@pytest.fixture
def solver():
    gp = pytest.importorskip("gurobipy")
    try:
        with gp.Env(empty=True) as env:
            env.setParam("OutputFlag", 0)
            env.start()
    except gp.GurobiError as e:
        pytest.skip(f"Gurobi licence unavailable: {e}")
    from integration.static_v3.optimisation import build_model, solve_model
    return build_model, solve_model


def checked_solve(s, solver, force=None):
    build, solve = solver
    b = build(s)
    try:
        if force:
            force(b)
        result = solve(b)
        assert result["has_solution"]
        replay = replay_and_validate(s, result)
        return result, replay
    finally:
        b.model.dispose()


def disable_drops(b):
    for v in b.drop.values():
        b.model.addConstr(v == 0)


def test_no_aircraft_cannot_extinguish_or_unburn(solver):
    s = scenario(fires=((1, 1), (2, 2)), num_tankers=0)
    result, replay = checked_solve(s, solver)
    assert result["burn_cell_steps"] == 10
    assert all(np.array_equal(g, s.grid) for g in replay["states"])
    assert result["last_drop_completion_min"] is None


def test_parked_aircraft_has_zero_distance_and_no_suppression(solver):
    s = scenario()
    result, replay = checked_solve(s, solver, disable_drops)
    assert result["flight_distance_m"] == 0
    assert np.array_equal(replay["states"][-1], s.grid)


def test_default_fleet_can_share_depot(solver):
    s = scenario(num_tankers=2, num_scoopers=1, horizon_steps=3)
    result, _ = checked_solve(s, solver, disable_drops)
    assert len(result["routes"]) == 3
    assert result["flight_distance_m"] == 0


def test_known_single_fire_optimum_and_distance(solver):
    s = scenario()
    result, replay = checked_solve(s, solver)
    assert result["status"] == "OPTIMAL"
    assert result["burn_cell_steps"] == 1
    assert result["flight_distance_m"] == 240
    assert result["last_drop_completion_min"] == 2
    assert replay["states"][-1][2, 2] == 2


def test_terminal_drop_has_effect_and_costs_water(solver):
    s = scenario(fires=((0, 1),), num_tankers=0, num_scoopers=1, horizon_steps=2)
    result, replay = checked_solve(s, solver)
    drop = next(a for a in result["actions"] if a["kind"] == "drop")
    assert (drop["start_step"], drop["end_step"]) == (1, 2)
    assert result["routes"]["scooper_0"][-1]["water_l"] == 0
    assert replay["states"][-1][0, 1] == 2


def test_scooper_cannot_refill_by_waiting_even_for_terminal_drop(solver):
    s = scenario(fires=((1, 1), (3, 3)), num_tankers=0, num_scoopers=1, horizon_steps=4)
    build, _ = solver
    b = build(s)
    try:
        b.model.addConstr(b.drop[0, 0, 1] == 1)
        b.model.addConstr(b.drop[0, 1, 3] == 1)
        for v in b.refill.values():
            b.model.addConstr(v == 0)
        b.model.optimize()
        assert b.model.Status == 3
    finally:
        b.model.dispose()


def test_scooper_refill_requires_service_and_conserves_water(solver):
    s = scenario(fires=((1, 1), (3, 3)), num_tankers=0, num_scoopers=1, horizon_steps=6)
    def force(b):
        b.model.addConstr(b.drop[0, 0, 1] == 1)
        b.model.addConstr(b.refill[0, (0, 4), 3] == 1)
        b.model.addConstr(b.drop[0, 1, 5] == 1)
    result, _ = checked_solve(s, solver, force)
    route = result["routes"]["scooper_0"]
    assert route[2]["water_l"] == 0
    assert route[4]["water_l"] == 5000
    assert route[6]["water_l"] == 0


def test_partial_drops_accumulate_before_extinction(solver):
    s = scenario(water_demand_l_m2=6.0)
    result, replay = checked_solve(s, solver)
    assert sum(a["kind"] == "drop" for a in result["actions"]) == 2
    assert replay["states"][2][2, 2] == 1
    assert replay["states"][3][2, 2] == 2


def test_source_to_target_mapping_not_reversed(solver):
    s = scenario(fires=((1, 1), (1, 2)), horizon_steps=3)
    # Deliberately asymmetric map isolates mapping direction from shape symmetry.
    s.footprints = {(1, 1): {(1, 2): 1000}, (1, 2): {(1, 2): 1000}}
    def force(b):
        for key, var in b.drop.items():
            b.model.addConstr(var == int(key == (0, 0, 1)))
    _, replay = checked_solve(s, solver, force)
    assert replay["states"][-1][1, 1] == 1
    assert replay["states"][-1][1, 2] == 2


def test_existing_extinction_and_unburned_cells_preserved(solver):
    s = scenario(num_tankers=0)
    s.grid[1, 1] = 2
    _, replay = checked_solve(s, solver)
    assert all(g[1, 1] == 2 and g[4, 4] == 0 and g[2, 2] == 1 for g in replay["states"])


def test_empty_fire(solver):
    s = scenario(fires=())
    result, replay = checked_solve(s, solver)
    assert result["burn_cell_steps"] == 0
    assert result["actions"] == []
    assert np.array_equal(replay["states"][-1], s.grid)


def test_no_incumbent_is_not_reported_as_zero_objective(solver):
    s = scenario()
    build, solve = solver
    b = build(s)
    try:
        b.model.addConstr(b.row[0, 0] == 4)
        result = solve(b)
        assert not result["has_solution"]
        assert result["burn_cell_steps"] is None
        with pytest.raises(ValueError, match="no feasible solution"):
            replay_and_validate(s, result)
    finally:
        b.model.dispose()


def test_replay_rejects_fabricated_water(solver):
    s = scenario()
    result, _ = checked_solve(s, solver)
    corrupted = copy.deepcopy(result)
    corrupted["routes"]["tanker_0"][-1]["water_l"] += 1
    with pytest.raises(ValueError, match="Water conservation|capacity"):
        replay_and_validate(s, corrupted)


def test_large_landscape_does_not_create_all_cell_pairs(solver):
    build, _ = solver
    counts = []
    for shape in [(5, 5), (82, 230)]:
        b = build(scenario(shape=shape))
        counts.append((b.model.NumVars, b.model.NumConstrs, b.model.NumGenConstrs))
        b.model.dispose()
    assert counts[0] == counts[1]


def test_speed_below_one_cell_does_not_round_up(solver):
    s = scenario(tanker_speed_m_min=1.0)
    result, replay = checked_solve(s, solver)
    assert result["flight_distance_m"] == 0
    assert replay["states"][-1][2, 2] == 1


def test_drop_service_completion_time(solver):
    s = scenario(drop_steps=2)
    result, replay = checked_solve(s, solver)
    assert result["last_drop_completion_min"] == 3
    assert replay["states"][2][2, 2] == 1
    assert replay["states"][3][2, 2] == 2


def test_footprint_orientation_and_centre():
    s = scenario(shape=(21, 21))
    footprints = {}
    for heading in (0, 45, 90, 135):
        footprints[heading] = compute_drop_footprint(10, 10, s.georef, replace(s.settings, drop_heading_deg=heading))
        assert footprints[heading][10, 10] > 0
        assert 4990 <= sum(footprints[heading].values()) <= 5000
    north = footprints[0]
    east = footprints[90]
    assert all(c == 10 for r, c in north)
    assert all(r == 10 for r, c in east)
    for h, sign in [(45, -1), (135, 1)]:
        cov = sum((r - 10) * (c - 10) * v for (r, c), v in footprints[h].items())
        assert sign * cov > 0


def test_edge_water_is_not_redistributed():
    s = scenario(shape=(21, 21))
    middle = compute_drop_footprint(10, 10, s.georef, s.settings)
    corner = compute_drop_footprint(0, 0, s.georef, s.settings)
    assert sum(corner.values()) < sum(middle.values()) <= 5000
    assert middle[10, 10] == corner[0, 0]


def test_coarse_cells_still_receive_water():
    s = scenario()
    georef = dict(s.georef, cell_size_x=3000., cell_size_y=3000.)
    fp = compute_drop_footprint(2, 2, georef, s.settings)
    assert fp[2, 2] >= 4999
    assert len(fp) == 1


def test_invalid_service_site_rejected():
    with pytest.raises(ValueError, match="outside"):
        scenario(water_cells=((99, 99),))
    with pytest.raises(ValueError, match="burning"):
        scenario(airfield=(2, 2))
