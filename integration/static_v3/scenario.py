"""Shared scenario data: fixed burning cells, footprints, and water demand."""
from dataclasses import dataclass
import math
import numpy as np
from .config import Settings, STATE_BURNING
from .drop_pattern import compute_drop_footprint


@dataclass
class Scenario:
    grid: np.ndarray
    georef: dict
    settings: Settings
    burning: tuple
    footprints: dict
    demand_l: int


def prepare_scenario(grid, georef, settings):
    settings.validate()
    grid = np.asarray(grid)
    if grid.ndim != 2 or grid.shape != (georef["rows"], georef["cols"]):
        raise ValueError("Grid shape does not match landscape georeferencing")
    if not np.isin(grid, [0, 1, 2]).all():
        raise ValueError("Grid states must be 0, 1, or 2")
    for name in ("cell_size_x", "cell_size_y"):
        if not math.isfinite(georef[name]) or georef[name] <= 0:
            raise ValueError(f"Invalid {name}")
    sites = [("airfield", settings.airfield)] + [
        ("water source", cell) for cell in settings.water_cells]
    for label, cell in sites:
        if (len(cell) != 2 or any(not isinstance(v, (int, np.integer)) for v in cell)
                or not 0 <= cell[0] < grid.shape[0] or not 0 <= cell[1] < grid.shape[1]):
            raise ValueError(f"{label} {cell} is outside the integer grid")
        if grid[cell] == STATE_BURNING:
            raise ValueError(f"{label} {cell} is burning; choose a usable service site")
    burning = tuple(map(tuple, np.argwhere(grid == STATE_BURNING).tolist()))
    footprints = {cell: compute_drop_footprint(*cell, georef, settings) for cell in burning}
    if any(not fp for fp in footprints.values()):
        raise ValueError("A drop has no credited water; check geometry and volume")
    demand = math.ceil(settings.water_demand_l_m2 * georef["cell_size_x"] * georef["cell_size_y"])
    return Scenario(grid.astype(np.int8, copy=True), dict(georef), settings,
                    burning, footprints, demand)


def fleet(settings):
    """Stable aircraft records used by the solver and independent validator."""
    return ([{"id": f"tanker_{i}", "kind": "tanker", "capacity_l": settings.tanker_capacity_l,
              "speed_m_min": settings.tanker_speed_m_min,
              "refill_steps": settings.tanker_refill_steps, "return_required": True}
             for i in range(settings.num_tankers)] +
            [{"id": f"scooper_{i}", "kind": "scooper", "capacity_l": settings.scooper_capacity_l,
              "speed_m_min": settings.scooper_speed_m_min,
              "refill_steps": settings.scooper_refill_steps,
              "return_required": settings.return_scoopers}
             for i in range(settings.num_scoopers)])
