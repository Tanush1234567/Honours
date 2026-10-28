"""One reproducible sample per window; directions are meteorological wind-from."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Wind:
    speed_kph: float
    from_deg: float


def sample_wind(settings, index):
    # Index-based seeding makes fleet comparisons independent of solver RNG.
    rng = np.random.default_rng(np.random.SeedSequence([settings.wind_seed, index]))
    return Wind(max(0.0, float(rng.normal(settings.wind_speed_mean_kph, settings.wind_speed_std_kph))),
                float(rng.normal(settings.wind_from_mean_deg, settings.wind_from_std_deg)) % 360)
