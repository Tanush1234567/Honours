"""Parameters for the fixed-fire experiment; distances and volumes have units."""
from dataclasses import dataclass
from pathlib import Path
import math

ROOT = Path(__file__).resolve().parent
LANDSCAPE_TIF = ROOT / "inputs" / "landscape.tif"
IGNITION_SHP = ROOT / "inputs" / "ignition.shp"
OUTPUT_DIR = ROOT / "outputs"
STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED = 0, 1, 2


@dataclass(frozen=True)
class Settings:
    horizon_steps: int = 15
    step_minutes: float = 1.0
    num_tankers: int = 2
    num_scoopers: int = 1
    airfield: tuple[int, int] = (0, 0)
    water_cells: tuple[tuple[int, int], ...] = ((0, 229), (81, 0))
    tanker_capacity_l: int = 10_000
    scooper_capacity_l: int = 5_000
    drop_volume_l: int = 5_000
    tanker_speed_m_min: float = 10_000.0
    scooper_speed_m_min: float = 6_000.0
    drop_steps: int = 1
    tanker_refill_steps: int = 2
    scooper_refill_steps: int = 1
    # Heading is explicit: 0=north, 90=east. No ambiguous wind-from conversion.
    drop_heading_deg: float = 45.0
    drop_k: float = 0.05
    drop_height_m: float = 40.0
    drop_ramp_m: float = 20.0
    drop_plateau_m: float = 40.0
    # Demonstration threshold, NOT an empirically calibrated suppression law.
    water_demand_l_m2: float = 1.0
    ignition_area_fraction: float = 0.5
    time_limit_s: float = 60.0
    primary_time_fraction: float = 0.8
    solver_seed: int = 42
    solver_threads: int = 0
    solver_output: bool = True
    return_scoopers: bool = False
    write_model: bool = False

    def validate(self):
        positive_ints = ("horizon_steps", "drop_steps", "tanker_refill_steps",
                         "scooper_refill_steps", "tanker_capacity_l",
                         "scooper_capacity_l", "drop_volume_l")
        for name in positive_ints:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("num_tankers", "num_scoopers", "solver_seed", "solver_threads"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        for name in ("step_minutes", "tanker_speed_m_min", "scooper_speed_m_min",
                     "drop_k", "drop_height_m", "drop_ramp_m", "drop_plateau_m",
                     "water_demand_l_m2", "time_limit_s"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(self.drop_heading_deg):
            raise ValueError("drop_heading_deg must be finite")
        if not 0 < self.primary_time_fraction < 1:
            raise ValueError("primary_time_fraction must be between zero and one")
        if not 0 < self.ignition_area_fraction <= 1:
            raise ValueError("ignition_area_fraction must be in (0, 1]")
        if self.drop_volume_l > min(self.tanker_capacity_l, self.scooper_capacity_l):
            raise ValueError("A drop cannot exceed either aircraft's capacity")
        if self.num_scoopers and not self.water_cells:
            raise ValueError("Configure at least one water source for scoopers")
        if len(set(self.water_cells)) != len(self.water_cells):
            raise ValueError("Duplicate water source cells")


DEFAULTS = Settings()
