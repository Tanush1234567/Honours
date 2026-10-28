"""Parameters for the fixed-fire experiment; distances and volumes have units."""
from dataclasses import dataclass
from pathlib import Path
import math

ROOT = Path(__file__).resolve().parent  # Package directory used to resolve default paths.
LANDSCAPE_TIF = ROOT / "inputs" / "landscape.tif"  # Raster supplying grid size and georeferencing.
IGNITION_SHP = ROOT / "inputs" / "ignition.shp"  # Polygons defining initially burning cells.
OUTPUT_DIR = ROOT / "outputs"  # Parent directory for each run's results and diagnostics.
# Grid codes: 0 = unburned, 1 = burning, 2 = extinguished.
STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED = 0, 1, 2


@dataclass(frozen=True)
class Settings:
    horizon_steps: int = 15  # Number of scheduling intervals; states have one extra boundary.
    step_minutes: float = 1.0  # Minutes per step; scales travel limits and reported times.
    num_tankers: int = 2  # Number of airfield-refilling aircraft in the fleet.
    num_scoopers: int = 1  # Number of water-source-refilling aircraft in the fleet.
    airfield: tuple[int, int] = (0, 0)  # Zero-based (row, col): fleet start and tanker refill/return site.
    water_cells: tuple[tuple[int, int], ...] = ((0, 229), (81, 0))  # Zero-based scooper refill sites.
    tanker_capacity_l: int = 10_000  # Maximum and initial water load per tanker, in litres.
    scooper_capacity_l: int = 5_000  # Maximum and initial water load per scooper, in litres.
    drop_volume_l: int = 5_000  # Litres discharged by either aircraft type in each drop.
    tanker_speed_m_min: float = 10_000.0  # Tanker travel limit in metres per minute (Manhattan distance).
    scooper_speed_m_min: float = 6_000.0  # Scooper travel limit in metres per minute (Manhattan distance).
    drop_steps: int = 1  # Stationary drop duration; deposited water is credited at completion.
    tanker_refill_steps: int = 2  # Steps spent stationary at the airfield to refill a tanker fully.
    scooper_refill_steps: int = 1  # Steps spent stationary at a water source to refill a scooper fully.
    # Heading is explicit: 0=north, 90=east. No ambiguous wind-from conversion.
    drop_heading_deg: float = 45.0  # Drop footprint orientation clockwise from north, in degrees.
    drop_k: float = 0.05  # Width coefficient: footprint width = drop_k * drop_height_m**1.5.
    drop_height_m: float = 40.0  # Release height in metres, used to calculate footprint width.
    drop_ramp_m: float = 20.0  # Length of each tapered end of the footprint, in metres.
    drop_plateau_m: float = 40.0  # Length of the footprint's full-width centre, in metres.
    # Demonstration threshold, NOT an empirically calibrated suppression law.
    water_demand_l_m2: float = 1.0  # Cumulative litres/m2 needed to extinguish a burning cell.
    ignition_area_fraction: float = 0.5  # Minimum cell area fraction covered by ignition to mark it burning.
    time_limit_s: float = 500.0  # Shared time budget in seconds for both solver passes.
    primary_time_fraction: float = 0.8  # Budget fraction for minimising burning cell-steps; remaining time reduces travel.
    solver_seed: int = 42  # Gurobi random seed influencing the optimisation search.
    solver_threads: int = 0  # Gurobi worker threads; 0 lets the solver choose automatically.
    solver_output: bool = True  # Enable Gurobi output, including console and file logging.
    return_scoopers: bool = False  # Require scoopers at the airfield at horizon end when True.
    write_model: bool = False  # Save model.lp before solving when an output directory is supplied.

    def validate(self):
        # Settings that require whole-number values greater than zero.
        positive_ints = ("horizon_steps", "drop_steps", "tanker_refill_steps",
                         "scooper_refill_steps", "tanker_capacity_l",
                         "scooper_capacity_l", "drop_volume_l")
        for name in positive_ints:  # Attribute name of the setting being checked.
            value = getattr(self, name)  # Current setting value checked for type and range.
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


DEFAULTS = Settings()  # Immutable default settings used by the runner and CLI.
