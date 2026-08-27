# =============================================================================
# grid_utils.py
# All helper functions for working with the 3-state fire grid.
#
# Grid convention (matches problem statement):
#   grid[r, c] in {STATE_UNBURNED=0, STATE_BURNING=1, STATE_EXTINGUISHED=2}
#   Row 0 is the NORTH edge; col 0 is the WEST edge.
#   World coordinate of cell (r,c) top-left corner:
#       x = GRID_ORIGIN_X + c * CELL_SIZE_M
#       y = GRID_ORIGIN_Y + (GRID_ROWS - r) * CELL_SIZE_M   (y decreases southward)
# =============================================================================

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import mapping, box
import json
import os

from config.config import (
    GRID_ROWS, GRID_COLS, CELL_SIZE_M,
    GRID_ORIGIN_X, GRID_ORIGIN_Y,
    STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED,
    BURN_FRACTION_THRESHOLD,
)


# Canonical rasterio transform for the grid (used consistently everywhere)
GRID_TRANSFORM = from_origin(
    west  = GRID_ORIGIN_X,
    north = GRID_ORIGIN_Y + GRID_ROWS * CELL_SIZE_M,
    xsize = CELL_SIZE_M,
    ysize = CELL_SIZE_M,
)
GRID_CRS = "EPSG:32633"   # ← match to your LCP projection


# ---------------------------------------------------------------------------
# 1. Initialise grid from ignition shapefile
# ---------------------------------------------------------------------------
def grid_from_ignition_shp(shp_path: str) -> np.ndarray:
    """
    Create the initial 3-state grid from the ignition perimeter shapefile.

    Cells whose area is > BURN_FRACTION_THRESHOLD covered by the ignition
    polygon are set to STATE_BURNING; all others are STATE_UNBURNED.

    Parameters
    ----------
    shp_path : str  Path to the ignition perimeter .shp

    Returns
    -------
    np.ndarray shape (GRID_ROWS, GRID_COLS), dtype int
    """
    gdf = gpd.read_file(shp_path)
    if gdf.crs is not None and str(gdf.crs) != GRID_CRS:
        gdf = gdf.to_crs(GRID_CRS)

    # Rasterise at 10× resolution for accurate fractional coverage
    scale = 10
    fine_transform = from_origin(
        west  = GRID_ORIGIN_X,
        north = GRID_ORIGIN_Y + GRID_ROWS * CELL_SIZE_M,
        xsize = CELL_SIZE_M / scale,
        ysize = CELL_SIZE_M / scale,
    )
    fine_mask = rasterize(
        [(mapping(geom), 1) for geom in gdf.geometry],
        out_shape=(GRID_ROWS * scale, GRID_COLS * scale),
        transform=fine_transform,
        fill=0,
        dtype=np.uint8,
    )
    frac = fine_mask.reshape(GRID_ROWS, scale, GRID_COLS, scale).mean(axis=(1, 3))
    grid = np.where(frac > BURN_FRACTION_THRESHOLD,
                    STATE_BURNING, STATE_UNBURNED).astype(int)
    return grid


# ---------------------------------------------------------------------------
# 2. Apply the optimiser's drop schedule to the grid
# ---------------------------------------------------------------------------
def apply_drop_schedule(
    grid: np.ndarray,
    drop_schedule: list,
    drop_heading_deg: float,
) -> tuple:
    """
    Apply all drops returned by the optimiser to the grid for the current window.

    For each drop (aircraft_id, type, abs_time, row, col) in drop_schedule:
      - Compute the drop footprint using drop_pattern.compute_drop_footprint
      - For each burning cell in the footprint, flip to STATE_EXTINGUISHED
        with probability proportional to η (handled inside drop_pattern.apply_drop_to_grid)

    Parameters
    ----------
    grid : np.ndarray  current 3-state grid
    drop_schedule : list of (aircraft_id, type, abs_time, row, col)
    drop_heading_deg : float  aircraft heading during all drops this window

    Returns
    -------
    updated_grid : np.ndarray
    all_extinguished : list of (row, col)  unique cells extinguished this window
    """
    from drop_pattern import apply_drop_to_grid

    updated = grid.copy()
    all_ext = []

    for (aircraft_id, ac_type, abs_time, r, c) in drop_schedule:
        updated, ext_cells = apply_drop_to_grid(updated, r, c, drop_heading_deg)
        all_ext.extend(ext_cells)

    # Deduplicate
    all_ext = list(set(all_ext))
    return updated, all_ext


# ---------------------------------------------------------------------------
# 3. Build the permanent extinguished mask
# ---------------------------------------------------------------------------
def build_extinguished_mask(grid: np.ndarray) -> np.ndarray:
    """Return a boolean mask of all cells currently in STATE_EXTINGUISHED."""
    return grid == STATE_EXTINGUISHED


# ---------------------------------------------------------------------------
# 4. Statistics helpers
# ---------------------------------------------------------------------------
def fire_stats(grid: np.ndarray) -> dict:
    """Return a dict of cell counts per state."""
    return {
        'unburned':     int(np.sum(grid == STATE_UNBURNED)),
        'burning':      int(np.sum(grid == STATE_BURNING)),
        'extinguished': int(np.sum(grid == STATE_EXTINGUISHED)),
        'total':        int(grid.size),
    }


def is_fire_out(grid: np.ndarray) -> bool:
    """True when no cells remain in STATE_BURNING."""
    return not np.any(grid == STATE_BURNING)


# ---------------------------------------------------------------------------
# 5. Serialise / deserialise grid state  (for checkpointing)
# ---------------------------------------------------------------------------
def save_grid(grid: np.ndarray, path: str) -> None:
    """Save grid as a GeoTIFF for inspection in QGIS / ArcGIS."""
    with rasterio.open(
        path, 'w',
        driver='GTiff',
        height=GRID_ROWS, width=GRID_COLS,
        count=1, dtype=rasterio.int8,
        crs=GRID_CRS,
        transform=GRID_TRANSFORM,
    ) as dst:
        dst.write(grid.astype(np.int8), 1)


def load_grid(path: str) -> np.ndarray:
    """Load a grid previously saved with save_grid()."""
    with rasterio.open(path) as src:
        return src.read(1).astype(int)


# ---------------------------------------------------------------------------
# 6. Convert cell (row,col) ↔ UTM coordinates
# ---------------------------------------------------------------------------
def cell_to_utm(row: int, col: int) -> tuple:
    """Return (easting, northing) of the centre of cell (row, col)."""
    x = GRID_ORIGIN_X + (col + 0.5) * CELL_SIZE_M
    y = GRID_ORIGIN_Y + (GRID_ROWS - row - 0.5) * CELL_SIZE_M
    return x, y


def utm_to_cell(easting: float, northing: float) -> tuple:
    """Return (row, col) for a UTM coordinate. Clips to grid bounds."""
    col = int((easting  - GRID_ORIGIN_X) / CELL_SIZE_M)
    row = int((GRID_ORIGIN_Y + GRID_ROWS * CELL_SIZE_M - northing) / CELL_SIZE_M)
    row = int(np.clip(row, 0, GRID_ROWS - 1))
    col = int(np.clip(col, 0, GRID_COLS - 1))
    return row, col


# ---------------------------------------------------------------------------
# 7. Log iteration state as JSON (for post-processing / plotting)
# ---------------------------------------------------------------------------
def log_iteration(
    log_dir: str,
    iteration: int,
    grid_before: np.ndarray,
    grid_after: np.ndarray,
    drop_schedule: list,
    wind: dict,
    opt_result: dict,
) -> None:
    """Write a JSON snapshot of one iteration to log_dir/iter_NNN.json."""
    stats_before = fire_stats(grid_before)
    stats_after  = fire_stats(grid_after)

    record = {
        'iteration':     iteration,
        'wind':          wind,
        'stats_before':  stats_before,
        'stats_after':   stats_after,
        'opt_status':    opt_result.get('status'),
        'opt_obj':       opt_result.get('obj'),
        'opt_gap':       opt_result.get('gap'),
        'Z':             opt_result.get('Z'),
        'n_drops':       len(drop_schedule),
        'drops':  [
            {'aircraft': a, 'type': tp, 'time': t, 'row': r, 'col': c}
            for (a, tp, t, r, c) in drop_schedule
        ],
    }

    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f'iter_{iteration:03d}.json')
    with open(path, 'w') as f:
        json.dump(record, f, indent=2)
