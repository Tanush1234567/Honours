"""Synthetic inputs only; optimisation and deposition use the real model."""
from dataclasses import replace

import numpy as np

from ..config import Settings
from ..scenario import prepare_scenario


def make_scenario(name):
    # The entire 80 m long footprint fits inside a 100 m fire cell.
    # Demand is deliberately far from the integer-litre rounding boundary.
    base = Settings(
        horizon_steps=3,
        step_minutes=1.0,
        num_tankers=1,
        num_scoopers=0,
        airfield=(1, 0),
        water_cells=((1, 0),),
        tanker_capacity_l=10_000,
        scooper_capacity_l=5_000,
        drop_volume_l=5_000,
        tanker_speed_m_min=100.0,
        scooper_speed_m_min=100.0,
        drop_steps=1,
        tanker_refill_steps=2,
        scooper_refill_steps=1,
        drop_heading_deg=0.0,
        drop_k=0.05,
        drop_height_m=40.0,
        drop_ramp_m=20.0,
        drop_plateau_m=40.0,
        water_demand_l_m2=0.25,
        ignition_area_fraction=0.5,
        time_limit_s=30.0,
        primary_time_fraction=0.8,
        solver_seed=42,
        solver_threads=1,
        solver_output=False,
        return_scoopers=True,
        write_model=True,
    )
    overrides = {
        "single_drop": {},
        "two_drops": {"horizon_steps": 4, "water_demand_l_m2": 0.75},
        "tanker_refill": {
            "horizon_steps": 8,
            "tanker_capacity_l": 5_000,
            "water_demand_l_m2": 0.75,
        },
        "scooper_refill": {
            "horizon_steps": 7,
            "num_tankers": 0,
            "num_scoopers": 1,
            "water_demand_l_m2": 0.75,
        },
        "unreachable": {"tanker_speed_m_min": 50.0},
    }
    if name not in overrides:
        raise ValueError(f"Unknown validation case: {name}")
    settings = replace(base, **overrides[name])
    grid = np.zeros((3, 3), dtype=np.int8)
    grid[1, 1] = 1
    georef = {
        "rows": 3, "cols": 3,
        "cell_size_x": 100.0, "cell_size_y": 100.0,
    }
    return prepare_scenario(grid, georef, settings)
