# =============================================================================
# drop_pattern.py
# Implements the water drop pattern from the problem statement (Section 2.0.3).
#
# The pattern is hexagonal, approximated by a normal distribution laterally
# and a piecewise-linear profile longitudinally:
#
#   λ(x, h) = k·h^1.5 · x/l1           if x < l1
#            = k·h^1.5                   if l1 ≤ x ≤ l1+l2
#            = k·h^1.5 · (2l1+l2-x)/l1  if l1+l2 < x ≤ 2l1+l2
#
#   η(x, y) = λ / sqrt(2πσ²) · exp(-y² / 2σ²),   σ = λ/6
#
# Given an aircraft heading and drop-start cell, this module:
#   1. Computes η for every cell covered by the footprint.
#   2. Returns a dict {(row,col): coverage_fraction} for cells with η > threshold.
#   3. Determines which cells flip from BURNING → EXTINGUISHED based on DROP_PHI.
# =============================================================================


#! Currently only uses instantaneous probability of extingusihing a fire. 
#! does not have memory of accumulation (eta threshold does not decrease) with the amount of 
#!times water has been received by the cell. Will need to update this using salabim

import numpy as np
from config.config import (
    DROP_K, DROP_L1, DROP_L2, DROP_H,
    DROP_PHI, DROP_PHI_DECAY,
    CELL_SIZE_M, STATE_BURNING, STATE_EXTINGUISHED
)


def _lambda(x: float, h: float = DROP_H) -> float:
    """Longitudinal width profile λ(x, h) [m]."""
    k, l1, l2 = DROP_K, DROP_L1, DROP_L2
    max_x = 2 * l1 + l2 #longitudinal max drop (all water within this limit)
    if x < 0 or x > max_x:
        return 0.0
    if x < l1:
        return k * (h ** 1.5) * (x / l1)
    elif x <= l1 + l2:
        return k * (h ** 1.5)
    else:
        return k * (h ** 1.5) * ((2 * l1 + l2 - x) / l1)


def eta(x: float, y: float, h: float = DROP_H) -> float:
    """
    Water density η(x, y) at longitudinal offset x [m] and lateral offset y [m]
    from the drop centreline, at release altitude h [m].
    Returns a dimensionless coverage value in [0, 1].
    """
    lam = _lambda(x, h)
    if lam <= 0:
        return 0.0
    sigma = lam / 6.0
    return (lam / np.sqrt(2 * np.pi * sigma ** 2)) * np.exp(-(y ** 2) / (2 * sigma ** 2))


def sigma_at_centre(h: float = DROP_H) -> float:
    """
    Returns σ at the centre of the drop (x = l1->l1+l2, maximum λ).
    This is what the problem statement recommends as the grid cell size guide.
    """
    lam_centre = DROP_K * (h ** 1.5)
    return lam_centre / 6.0


def compute_drop_footprint(
    drop_row: int,
    drop_col: int,
    heading_deg: float,
    grid_rows: int,
    grid_cols: int,
    h: float = DROP_H,
    eta_threshold: float = 0.01 #! can tune this as well
) -> dict:
    """
    Compute the set of grid cells affected by one water drop.

    Parameters
    ----------
    drop_row, drop_col : int
        Grid cell where the drop centreline starts (nose of the footprint).
    heading_deg : float
        Aircraft heading in degrees (0 = North, 90 = East).
    grid_rows, grid_cols : int
        Grid dimensions (for bounds checking).
    h : float
        Release altitude [m].
    eta_threshold : float
        Minimum η value for a cell to count as affected.

    Returns
    -------
    dict : {(row, col): eta_value}
        Only cells with eta_value > eta_threshold are included.
    """
    heading_rad = np.deg2rad(heading_deg)
    # Unit vectors along (longitudinal) and across (lateral) the heading
    # heading_deg is measured from North clockwise, so:
    #   longitudinal: (sin θ, cos θ) in (east, north) = (col, row) space
    along_col =  np.sin(heading_rad)
    along_row = -np.cos(heading_rad)   # row increases downward
    cross_col =  np.cos(heading_rad)
    cross_row =  np.sin(heading_rad)

    max_x = 2 * DROP_L1 + DROP_L2
    max_y = 3 * DROP_K * (h ** 1.5)   # generous lateral bound (3σ at centre)

    # Search radius in cells
    r_cells = int(np.ceil(max(max_x, max_y) / CELL_SIZE_M)) + 1

    footprint = {}
    for dr in range(-r_cells, r_cells + 1):
        for dc in range(-r_cells, r_cells + 1):
            r = drop_row + dr
            c = drop_col + dc
            if r < 0 or r >= grid_rows or c < 0 or c >= grid_cols:
                continue
            # World offset [m] from drop origin
            dy_m = dr * CELL_SIZE_M   # positive = south (row increases downward)
            dx_m = dc * CELL_SIZE_M
            # Project onto longitudinal / lateral axes
            x_proj = dx_m * along_col + (-dy_m) * along_row   # along-track
            y_proj = dx_m * cross_col + (-dy_m) * cross_row   # cross-track
            val = eta(x_proj, y_proj, h)
            if val > eta_threshold:
                footprint[(r, c)] = val
    return footprint


def apply_drop_to_grid(
    grid: np.ndarray,
    drop_row: int,
    drop_col: int,
    heading_deg: float,
    h: float = DROP_H
) -> tuple:
    """
    Apply one water drop to the fire state grid.

    A cell transitions BURNING → EXTINGUISHED if:
      - It is directly hit (η above threshold) AND
      - A uniform random draw < DROP_PHI  (direct-hit suppression probability)

    Neighbouring cells in the footprint have their effective suppression
    probability reduced by f(φ, d) = DROP_PHI * exp(-DROP_PHI_DECAY * d/CELL_SIZE_M).

    Parameters
    ----------
    grid : np.ndarray (dtype int, shape [rows, cols])
        Current fire state grid (values: 0 unburned, 1 burning, 2 extinguished).
    drop_row, drop_col : int
        Drop centreline start cell.
    heading_deg : float
        Aircraft heading [degrees].
    h : float
        Release altitude [m].

    Returns
    -------
    updated_grid : np.ndarray
        New grid after applying suppression.
    extinguished_cells : list of (row, col)
        Cells that changed from BURNING to EXTINGUISHED in this drop.
    """
    rows, cols = grid.shape
    footprint = compute_drop_footprint(drop_row, drop_col, heading_deg, rows, cols, h)
    updated = grid.copy()
    extinguished = []

    for (r, c), eta_val in footprint.items():
        if updated[r, c] != STATE_BURNING:
            continue
        # Distance from drop centre in cells
        dist_cells = np.hypot(r - drop_row, c - drop_col)
        # Suppression probability decays with distance
        suppress_prob = DROP_PHI * np.exp(-DROP_PHI_DECAY * dist_cells)
        if np.random.rand() < suppress_prob:
            updated[r, c] = STATE_EXTINGUISHED
            extinguished.append((r, c))

    return updated, extinguished
