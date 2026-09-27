# =============================================================================
# drop_pattern.py  (static_test — unchanged logic from integration version)
# =============================================================================

import numpy as np
from config.config import (
    DROP_K, DROP_L1, DROP_L2, DROP_H,
    DROP_PHI, DROP_PHI_DECAY,
    STATE_BURNING, STATE_EXTINGUISHED
)


def _lambda(x: float, h: float = DROP_H) -> float:
    k, l1, l2 = DROP_K, DROP_L1, DROP_L2
    max_x = 2 * l1 + l2
    if x < 0 or x > max_x:
        return 0.0
    if x < l1:
        return k * (h ** 1.5) * (x / l1)
    elif x <= l1 + l2:
        return k * (h ** 1.5)
    else:
        return k * (h ** 1.5) * ((2 * l1 + l2 - x) / l1)


def eta(x: float, y: float, h: float = DROP_H) -> float:
    lam = _lambda(x, h)
    if lam <= 0:
        return 0.0
    sigma = lam / 6.0
    return (lam / np.sqrt(2 * np.pi * sigma ** 2)) * np.exp(-(y ** 2) / (2 * sigma ** 2))


def sigma_at_centre(h: float = DROP_H) -> float:
    lam_centre = DROP_K * (h ** 1.5)
    return lam_centre / 6.0


def compute_drop_footprint(
    drop_row: int,
    drop_col: int,
    heading_deg: float,
    grid_rows: int,
    grid_cols: int,
    cell_size_m: float,
    h: float = DROP_H,
    eta_threshold: float = 0.01
) -> dict:
    """
    NOTE: cell_size_m is now an explicit parameter (previously imported
    from config.CELL_SIZE_M, which no longer exists — cell size is derived
    from the landscape GeoTIFF at runtime, see georef['cell_size_x']).
    """
    heading_rad = np.deg2rad(heading_deg)
    along_col =  np.sin(heading_rad)
    along_row = -np.cos(heading_rad)
    cross_col =  np.cos(heading_rad)
    cross_row =  np.sin(heading_rad)

    max_x = 2 * DROP_L1 + DROP_L2
    max_y = 3 * DROP_K * (h ** 1.5)

    r_cells = int(np.ceil(max(max_x, max_y) / cell_size_m)) + 1

    footprint = {}
    for dr in range(-r_cells, r_cells + 1):
        for dc in range(-r_cells, r_cells + 1):
            r = drop_row + dr
            c = drop_col + dc
            if r < 0 or r >= grid_rows or c < 0 or c >= grid_cols:
                continue
            dy_m = dr * cell_size_m
            dx_m = dc * cell_size_m
            x_proj = dx_m * along_col + (-dy_m) * along_row
            y_proj = dx_m * cross_col + (-dy_m) * cross_row
            val = eta(x_proj, y_proj, h)
            if val > eta_threshold:
                footprint[(r, c)] = val
    return footprint


def apply_drop_to_grid(
    grid: np.ndarray,
    drop_row: int,
    drop_col: int,
    heading_deg: float,
    cell_size_m: float,
    h: float = DROP_H
) -> tuple:
    rows, cols = grid.shape
    footprint = compute_drop_footprint(
        drop_row, drop_col, heading_deg, rows, cols, cell_size_m, h
    )
    updated = grid.copy()
    extinguished = []

    for (r, c), eta_val in footprint.items():
        if updated[r, c] != STATE_BURNING:
            continue
        dist_cells = np.hypot(r - drop_row, c - drop_col)
        suppress_prob = DROP_PHI * np.exp(-DROP_PHI_DECAY * dist_cells)
        if np.random.rand() < suppress_prob:
            updated[r, c] = STATE_EXTINGUISHED
            extinguished.append((r, c))

    return updated, extinguished
