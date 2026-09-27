# =============================================================================
# grid_utils.py  (static_test — same as integration except log_iteration
# no longer requires a 'wind' dict, since wind is fixed/unused here)
# =============================================================================

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import mapping
import json
import os

from config.config import (
    GRID_ROWS, GRID_COLS, CELL_SIZE_M,
    GRID_ORIGIN_X, GRID_ORIGIN_Y,
    GRID_CRS,
    STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED,
    BURN_FRACTION_THRESHOLD,
)

GRID_TRANSFORM = from_origin(
    west  = GRID_ORIGIN_X,
    north = GRID_ORIGIN_Y + GRID_ROWS * CELL_SIZE_M,
    xsize = CELL_SIZE_M,
    ysize = CELL_SIZE_M,
)


# ---------------------------------------------------------------------------
# 1. Initialise grid from ignition shapefile
# ---------------------------------------------------------------------------
def grid_from_ignition_shp(shp_path: str) -> np.ndarray:
    """
    Rasterise the ignition shapefile onto the configured grid.
    Cells with >BURN_FRACTION_THRESHOLD area inside the polygon → STATE_BURNING.
    """
    gdf = gpd.read_file(shp_path)
    if gdf.crs is not None and str(gdf.crs) != GRID_CRS:
        gdf = gdf.to_crs(GRID_CRS)

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
# 2. Apply drop schedule to grid
# ---------------------------------------------------------------------------
def apply_drop_schedule(
    grid: np.ndarray,
    drop_schedule: list,
    drop_heading_deg: float,
) -> tuple:
    from drop_pattern import apply_drop_to_grid
    updated = grid.copy()
    all_ext = []
    for (aircraft_id, ac_type, abs_time, r, c) in drop_schedule:
        updated, ext_cells = apply_drop_to_grid(updated, r, c, drop_heading_deg)
        all_ext.extend(ext_cells)
    all_ext = list(set(all_ext))
    return updated, all_ext


# ---------------------------------------------------------------------------
# 3. Extinguished mask
# ---------------------------------------------------------------------------
def build_extinguished_mask(grid: np.ndarray) -> np.ndarray:
    return grid == STATE_EXTINGUISHED


# ---------------------------------------------------------------------------
# 4. Statistics
# ---------------------------------------------------------------------------
def fire_stats(grid: np.ndarray) -> dict:
    return {
        'unburned':     int(np.sum(grid == STATE_UNBURNED)),
        'burning':      int(np.sum(grid == STATE_BURNING)),
        'extinguished': int(np.sum(grid == STATE_EXTINGUISHED)),
        'total':        int(grid.size),
    }


def is_fire_out(grid: np.ndarray) -> bool:
    return not np.any(grid == STATE_BURNING)


# ---------------------------------------------------------------------------
# 5. Save / load grid as GeoTIFF
# ---------------------------------------------------------------------------
def save_grid(grid: np.ndarray, path: str) -> None:
    """Save 3-state grid as a GeoTIFF (viewable in QGIS)."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
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
    with rasterio.open(path) as src:
        return src.read(1).astype(int)


# ---------------------------------------------------------------------------
# 6. Coordinate conversions
# ---------------------------------------------------------------------------
def cell_to_utm(row: int, col: int) -> tuple:
    x = GRID_ORIGIN_X + (col + 0.5) * CELL_SIZE_M
    y = GRID_ORIGIN_Y + (GRID_ROWS - row - 0.5) * CELL_SIZE_M
    return x, y


def utm_to_cell(easting: float, northing: float) -> tuple:
    col = int((easting  - GRID_ORIGIN_X) / CELL_SIZE_M)
    row = int((GRID_ORIGIN_Y + GRID_ROWS * CELL_SIZE_M - northing) / CELL_SIZE_M)
    row = int(np.clip(row, 0, GRID_ROWS - 1))
    col = int(np.clip(col, 0, GRID_COLS - 1))
    return row, col


# ---------------------------------------------------------------------------
# 7. Log result as JSON  (wind removed — not applicable in static test)
# ---------------------------------------------------------------------------
def log_result(
    log_dir: str,
    grid_before: np.ndarray,
    grid_after: np.ndarray,
    drop_schedule: list,
    opt_result: dict,
) -> None:
    stats_before = fire_stats(grid_before)
    stats_after  = fire_stats(grid_after)
    record = {
        'stats_before': stats_before,
        'stats_after':  stats_after,
        'opt_status':   opt_result.get('status'),
        'opt_obj':      opt_result.get('obj'),
        'opt_gap':      opt_result.get('gap'),
        'Z':            opt_result.get('Z'),
        'n_drops':      len(drop_schedule),
        'drops': [
            {'aircraft': a, 'type': tp, 'time': t, 'row': r, 'col': c}
            for (a, tp, t, r, c) in drop_schedule
        ],
    }
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, 'result.json')
    with open(path, 'w') as f:
        json.dump(record, f, indent=2)
    print(f"[log] Result saved → {path}")
