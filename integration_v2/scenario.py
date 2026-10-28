"""An optimisation window includes arrival times and the carried execution state."""
from dataclasses import dataclass
import math
import numpy as np
from .drop_pattern import compute_drop_footprint
from .settings_base import Settings as AircraftSettings


def fleet(settings):
    return ([{"id": f"tanker_{i}", "kind": "tanker", "capacity_l": settings.tanker_capacity_l,
              "speed_m_min": settings.tanker_speed_m_min,
              "refill_steps": settings.tanker_refill_steps, "return_required": True}
             for i in range(settings.num_tankers)] +
            [{"id": f"scooper_{i}", "kind": "scooper", "capacity_l": settings.scooper_capacity_l,
              "speed_m_min": settings.scooper_speed_m_min,
              "refill_steps": settings.scooper_refill_steps,
              "return_required": settings.return_scoopers}
             for i in range(settings.num_scoopers)])


@dataclass
class World:
    grid: np.ndarray
    delivered_l: np.ndarray
    aircraft: dict
    step: int = 0
    fire_geometry: object = None  # Continuous native ignition, including subcell growth.
    ignition_minutes: object = None  # Demo graph's fractional ignition times.


def initial_world(grid, settings):
    return World(np.asarray(grid, dtype=np.int8).copy(), np.zeros_like(grid, dtype=np.int64),
                 {a["id"]: {"row": settings.airfield[0], "col": settings.airfield[1],
                            "water_l": a["capacity_l"]} for a in fleet(settings)})


@dataclass
class Scenario:
    grid: np.ndarray
    georef: dict
    settings: object
    burning: tuple  # Candidate origins: current fire plus forecast arrivals.
    footprints: dict
    demand_l: int
    arrival_steps: dict
    initial_delivered_l: np.ndarray
    initial_aircraft: dict
    commit_steps: int
    site_arrival_steps: dict


def prepare_scenario(world, georef, settings, arrival_minutes, commit_steps):
    # The controller validates the full dynamic configuration once. A final
    # shortened window can legitimately be shorter than a refill duration.
    AircraftSettings.validate(settings)
    grid = np.asarray(world.grid)
    arrival = np.asarray(arrival_minutes, dtype=float).copy()
    expected = (georef["rows"], georef["cols"])
    if grid.shape != expected or arrival.shape != expected or world.delivered_l.shape != expected:
        raise ValueError("Fire, forecast, water and landscape shapes must agree")
    if not np.isin(grid, [0, 1, 2]).all():
        raise ValueError("Fire states must be 0, 1 or 2")
    if np.isnan(arrival).any() or (arrival < 0).any():
        raise ValueError("Use nonnegative arrival minutes or infinity for unreached cells")
    if not 1 <= commit_steps <= settings.horizon_steps:
        raise ValueError("Invalid execution prefix")
    if not np.issubdtype(world.delivered_l.dtype, np.integer) or (world.delivered_l < 0).any():
        raise ValueError("Carried deposition must contain nonnegative integer litres")
    for name in ("cell_size_x", "cell_size_y"):
        if not math.isfinite(georef[name]) or georef[name] <= 0:
            raise ValueError(f"Invalid {name}")
    demand = math.ceil(settings.water_demand_l_m2 * georef["cell_size_x"] * georef["cell_size_y"])
    if np.any((grid == 0) & (world.delivered_l != 0)):
        raise ValueError("This model credits water to burning cells only; no pre-wetting")
    if np.any((grid == 1) & (world.delivered_l >= demand)):
        raise ValueError("A burning cell already meets the suppression threshold")
    if np.any((grid == 2) & (world.delivered_l < demand)):
        raise ValueError("Extinguished cells must have received their required water")
    sites = (((settings.airfield,) if settings.num_tankers + settings.num_scoopers else ())
             + (settings.water_cells if settings.num_scoopers else ()))
    for cell in sites:
        if (len(cell) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) for v in cell)
                or not 0 <= cell[0] < grid.shape[0] or not 0 <= cell[1] < grid.shape[1]):
            raise ValueError(f"Service site {cell} is outside the integer grid")
        if grid[cell] == 1:
            raise ValueError(f"Service site {cell} is burning; relocate it before continuing")
    ac = fleet(settings)
    if set(world.aircraft) != {a["id"] for a in ac}:
        raise ValueError("Carried aircraft do not match the configured fleet")
    occupied = set()
    for a in ac:
        p = world.aircraft[a["id"]]
        if any(isinstance(p[k], bool) or not isinstance(p[k], int) for k in ("row", "col", "water_l")):
            raise ValueError("Carried aircraft coordinates and loads must be integers")
        cell = p["row"], p["col"]
        if not (0 <= cell[0] < grid.shape[0] and 0 <= cell[1] < grid.shape[1]
                and 0 <= p["water_l"] <= a["capacity_l"]):
            raise ValueError("Invalid carried aircraft position/load")
        if cell != settings.airfield and cell in occupied:
            raise ValueError("Carried aircraft share a non-depot cell")
        occupied.add(cell)
    arrival[grid == 1] = 0.0
    arrival[grid == 2] = np.inf
    eligible = np.isfinite(arrival) & (arrival <= settings.horizon_steps * settings.step_minutes + 1e-9)
    cells = tuple(map(tuple, np.argwhere(eligible).tolist()))
    releases = {cell: max(0 if grid[cell] == 1 else 1,
                          math.ceil(arrival[cell] / settings.step_minutes - 1e-9)) for cell in cells}
    footprints = {cell: compute_drop_footprint(*cell, georef, settings) for cell in cells}
    if any(not fp for fp in footprints.values()):
        raise ValueError("A drop has no credited water; check geometry and volume")
    return Scenario(grid.copy(), dict(georef), settings, cells, footprints, demand, releases,
                    world.delivered_l.copy(), {k: dict(v) for k, v in world.aircraft.items()},
                    commit_steps, {cell: releases.get(cell, math.inf) for cell in sites})
