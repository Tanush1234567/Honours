# =============================================================================
# wind.py
# Stochastic wind sampling for each rolling-horizon window.
#
# Problem statement §2.0.5:
#   Wind is held constant within a window and sampled independently each window.
#   Direction and speed follow normal distributions with user-specified mean/std.
#   The SAME sample is written to both the FARSITE input and the Gurobi model
#   so they operate under identical conditions.
#
# For Monte Carlo fleet comparison runs, a new RNG is seeded per simulation so
# every fleet option experiences the same sequence of wind events.
# =============================================================================

import numpy as np
from config.config import (
    WIND_SPEED_MEAN, WIND_SPEED_STD,
    WIND_DIR_MEAN, WIND_DIR_STD,
    RANDOM_SEED
)


class WindSampler:
    """
    Samples wind speed and direction independently for each window.

    Parameters
    ----------
    seed : int or None
        Fixed seed for reproducible Monte Carlo runs.
        Pass None for non-reproducible (live) runs.
    """

    def __init__(self, seed=RANDOM_SEED):
        self.rng = np.random.default_rng(seed)

    def sample(self, iteration: int) -> dict:
        """
        Draw one wind sample for the given window iteration.

        Returns
        -------
        dict with keys:
            'speed_kph'   : float  [km/h]
            'dir_deg'     : float  [degrees, 0=N, 90=E, clockwise]
            'speed_ms'    : float  [m/s]  convenience for FARSITE .wnd files
            'drop_heading': float  [degrees] aircraft heading during drops
                            (180° opposite to wind — aircraft flies into wind)
        """
        speed = float(np.clip(
            self.rng.normal(WIND_SPEED_MEAN, WIND_SPEED_STD),
            0.0, None   # speed cannot be negative
        ))
        direction = float(self.rng.normal(WIND_DIR_MEAN, WIND_DIR_STD) % 360.0)
        drop_heading = (direction + 180.0) % 360.0 #* Flight against the wind (Might need to revise this)

        return {
            'speed_kph':    speed,
            'speed_ms':     speed / 3.6,
            'dir_deg':      direction,
            'drop_heading': drop_heading,
            'iteration':    iteration,
        }

    def sample_sequence(self, n_windows: int) -> list:
        """Pre-sample a full sequence of n_windows wind events (for Monte Carlo)."""
        return [self.sample(i) for i in range(n_windows)]


def write_wind_file(wind_samples: list, path: str) -> None:
    """
    Write a FARSITE-compatible .wnd wind stream file covering all windows.

    FARSITE .wnd format (one row per record):
        Day  Hour  Speed[m/min]  Direction[deg]  CloudCover[%]  Precipitation[mm/h]

    Speed is stored in m/min per FARSITE convention.
    """
    from config.config import SIM_START_TIME, WINDOW_MINUTES

    lines = []
    for w in wind_samples:
        t_start_min = SIM_START_TIME + w['iteration'] * WINDOW_MINUTES
        #! 200 days -> July 19th
        base_day    = 200   # Julian day matching FARSITE_START_TIME in farsite_interface.py
        abs_min     = t_start_min
        day  = base_day + abs_min // (24 * 60)
        hour = (abs_min % (24 * 60)) // 60
        speed_mmin = w['speed_ms'] * 60.0   # m/s → m/min
        lines.append(f"{day} {hour:04d} {speed_mmin:.1f} {w['dir_deg']:.0f} 0 0")

    with open(path, 'w') as f:
        f.write("\n".join(lines) + "\n")


def write_weather_file(path: str, n_windows: int) -> None:
    """
    Write a minimal FARSITE .wtr weather stream file (constant conditions).
    Fuel moisture values are fixed; extend this for dynamic moisture if needed.

    .wtr format:
        Day  Hour  Temp[F]  RH[%]  Precip[in]  mois1h  mois10h  mois100h
    """
    from config.config import SIM_START_TIME, WINDOW_MINUTES

    lines = []
    base_day = 200
    for i in range(n_windows + 1):
        abs_min = SIM_START_TIME + i * WINDOW_MINUTES
        day  = base_day + abs_min // (24 * 60)
        hour = (abs_min % (24 * 60)) // 60
        lines.append(f"{day} {hour:04d} 85 20 0.00 6 8 10") #! Randomly written right now. Change later

    with open(path, 'w') as f:
        f.write("\n".join(lines) + "\n")
