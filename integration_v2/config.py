"""Dynamic settings; the copied static aircraft/footprint settings retain units."""
from dataclasses import dataclass
from pathlib import Path
import math
from .settings_base import Settings as AircraftSettings

ROOT = Path(__file__).resolve().parent
LANDSCAPE = ROOT / "inputs" / "landscape.tif"
IGNITION = ROOT / "inputs" / "ignition.shp"
OUTPUT_DIR = ROOT / "outputs"


@dataclass(frozen=True)
class Settings(AircraftSettings):
    time_limit_s: float = 60.0
    total_steps: int = 60
    commit_steps: int = 3
    wind_seed: int = 42
    wind_speed_mean_kph: float = 10.0
    wind_speed_std_kph: float = 3.0
    wind_from_mean_deg: float = 225.0
    wind_from_std_deg: float = 15.0
    heading_mode: str = "fixed"  # fixed, or downwind (wind-from + 180 degrees)
    demo_spread_m_min: float = 6.0

    def validate(self):
        super().validate()
        for name in ("total_steps", "commit_steps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        # Service cannot cross a committed boundary. This avoids resetting or
        # discarding a partly completed refill/drop when the next model starts.
        durations = [self.drop_steps]
        if self.num_tankers:
            durations.append(self.tanker_refill_steps)
        if self.num_scoopers:
            durations.append(self.scooper_refill_steps)
        if not max(durations) <= self.commit_steps <= self.horizon_steps:
            raise ValueError("Require max(active service durations) <= commit_steps <= horizon_steps")
        if self.heading_mode not in ("fixed", "downwind"):
            raise ValueError("heading_mode must be fixed or downwind")
        if isinstance(self.wind_seed, bool) or not isinstance(self.wind_seed, int) or self.wind_seed < 0:
            raise ValueError("wind_seed must be a nonnegative integer")
        for name in ("wind_speed_mean_kph", "wind_speed_std_kph", "wind_from_std_deg"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not math.isfinite(self.wind_from_mean_deg):
            raise ValueError("wind_from_mean_deg must be finite")
        if not math.isfinite(self.demo_spread_m_min) or self.demo_spread_m_min <= 0:
            raise ValueError("demo_spread_m_min must be positive")


DEFAULTS = Settings()
