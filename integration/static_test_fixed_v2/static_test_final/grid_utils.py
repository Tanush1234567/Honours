# =============================================================================
# grid_utils.py  (static_test)
#
# CRS/origin/grid dimensions come from load_landscape_georef(), NOT from
# hand-typed config constants — see the note in config.py.
# =============================================================================

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from shapely.geometry import mapping
import json
import os

from config.config import (
    STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED,
    BURN_FRACTION_THRESHOLD,
)


# ---------------------------------------------------------------------------
# 0. Derive grid georeferencing from the landscape GeoTIFF
# ---------------------------------------------------------------------------
def load_landscape_georef(landscape_tif: str) -> dict:
    """
    Read CRS, transform, resolution and dimensions directly from the
    landscape GeoTIFF. Single source of truth for the grid.
    """
    with rasterio.open(landscape_tif) as src:
        if src.crs is None:
            raise ValueError(
                f"[load_landscape_georef] '{landscape_tif}' has no CRS defined. "
                "Re-export the landscape from FlamMap6."
            )
        georef = {
            'crs':          src.crs,
            'transform':    src.transform,
            'rows':         src.height,
            'cols':         src.width,
            'cell_size_x':  abs(src.transform.a),
            'cell_size_y':  abs(src.transform.e),
        }
    print(f"[grid_utils] Landscape georef loaded: "
          f"{georef['rows']} rows x {georef['cols']} cols, "
          f"{georef['cell_size_x']:.1f}m resolution")
    return georef


def _grid_bounds(georef: dict) -> tuple:
    """Return (minx, miny, maxx, maxy) of the grid in its own CRS."""
    minx = georef['transform'].c
    maxy = georef['transform'].f
    maxx = minx + georef['cols'] * georef['cell_size_x']
    miny = maxy - georef['rows'] * georef['cell_size_y']
    return minx, miny, maxx, maxy


# ---------------------------------------------------------------------------
# 1. Initialise grid from ignition shapefile
# ---------------------------------------------------------------------------
def grid_from_ignition_shp(shp_path: str, georef: dict) -> np.ndarray:
    """
    Rasterise the ignition shapefile onto the same grid as the landscape
    file. Cells with >BURN_FRACTION_THRESHOLD area inside the polygon
    become STATE_BURNING.
    """
    gdf = gpd.read_file(shp_path)

    if len(gdf) == 0:
        raise ValueError(
            f"[grid_from_ignition_shp] '{shp_path}' contains no geometry."
        )

    if gdf.crs is None:
        raise ValueError(
            f"[grid_from_ignition_shp] '{shp_path}' has no CRS (missing .prj "
            "sidecar?). Place ignition.shp, .shx, .dbf, .prj together, then re-run. "
            f"Expected CRS (from landscape): {georef['crs'].to_string()[:100]}"
        )

    if gdf.crs != georef['crs']:
        # Distinguish "reprojectable" from "genuinely a different place".
        # Compare the underlying projection parameters where possible.
        print(f"[grid_from_ignition_shp] Ignition CRS differs from landscape CRS "
              f"— attempting reprojection...")
        gdf_reproj = gdf.to_crs(georef['crs'])
    else:
        gdf_reproj = gdf

    minx, miny, maxx, maxy = gdf_reproj.total_bounds
    grid_minx, grid_miny, grid_maxx, grid_maxy = _grid_bounds(georef)

    overlap = not (maxx < grid_minx or minx > grid_maxx or
                   maxy < grid_miny or miny > grid_maxy)

    if not overlap:
        raise ValueError(
            "[grid_from_ignition_shp] The ignition polygon does not overlap "
            "the landscape grid at all, even after reprojection.\n"
            f"  Ignition bounds (in landscape CRS): "
            f"({minx:.0f}, {miny:.0f}) to ({maxx:.0f}, {maxy:.0f})\n"
            f"  Landscape grid bounds:              "
            f"({grid_minx:.0f}, {grid_miny:.0f}) to ({grid_maxx:.0f}, {grid_maxy:.0f})\n"
            "This most commonly means the ignition shapefile and landscape "
            "file were generated from DIFFERENT FlamMap6 sessions/areas — "
            "reprojection alone cannot fix that. Re-export both the ignition "
            "perimeter and the landscape from the SAME FlamMap6 project so "
            "they describe the same physical area."
        )

    # Rasterise at 10x sub-resolution for accurate area-fraction, then downsample
    scale = 10
    fine_transform = rasterio.transform.Affine(
        georef['cell_size_x'] / scale, 0, grid_minx,
        0, -georef['cell_size_y'] / scale, grid_maxy,
    )
    fine_mask = rasterize(
        [(mapping(geom), 1) for geom in gdf_reproj.geometry],
        out_shape=(georef['rows'] * scale, georef['cols'] * scale),
        transform=fine_transform,
        fill=0,
        dtype=np.uint8,
    )
    frac = fine_mask.reshape(
        georef['rows'], scale, georef['cols'], scale
    ).mean(axis=(1, 3))

    grid = np.where(frac > BURN_FRACTION_THRESHOLD,
                    STATE_BURNING, STATE_UNBURNED).astype(int)

    n_burning = int(np.sum(grid == STATE_BURNING))
    if n_burning == 0:
        print("[grid_from_ignition_shp] WARNING: 0 burning cells despite "
              "polygon overlapping grid bounds. The polygon may be smaller "
              "than BURN_FRACTION_THRESHOLD requires for a single cell — "
              "try lowering BURN_FRACTION_THRESHOLD in config.py.")
    else:
        print(f"[grid_from_ignition_shp] {n_burning} burning cells identified.")

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
def save_grid(grid: np.ndarray, path: str, georef: dict) -> None:
    """Save 3-state grid as a GeoTIFF, aligned with the landscape file."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with rasterio.open(
        path, 'w',
        driver='GTiff',
        height=georef['rows'], width=georef['cols'],
        count=1, dtype=rasterio.int8,
        crs=georef['crs'],
        transform=georef['transform'],
    ) as dst:
        dst.write(grid.astype(np.int8), 1)


def load_grid(path: str) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1).astype(int)


# ---------------------------------------------------------------------------
# 6. Coordinate conversions
# ---------------------------------------------------------------------------
def cell_to_utm(row: int, col: int, georef: dict) -> tuple:
    x = georef['transform'].c + (col + 0.5) * georef['cell_size_x']
    y = georef['transform'].f - (row + 0.5) * georef['cell_size_y']
    return x, y


def utm_to_cell(easting: float, northing: float, georef: dict) -> tuple:
    col = int((easting - georef['transform'].c) / georef['cell_size_x'])
    row = int((georef['transform'].f - northing) / georef['cell_size_y'])
    row = int(np.clip(row, 0, georef['rows'] - 1))
    col = int(np.clip(col, 0, georef['cols'] - 1))
    return row, col


def check_cell_in_bounds(name: str, cell: tuple, georef: dict) -> None:
    """Warn (don't crash) if a configured cell falls outside the grid."""
    r, c = cell
    if not (0 <= r < georef['rows'] and 0 <= c < georef['cols']):
        print(f"[grid_utils] WARNING: {name} = {cell} is OUTSIDE the grid "
              f"({georef['rows']} rows x {georef['cols']} cols). "
              "Update this in config.py.")


# ---------------------------------------------------------------------------
# 7. Log result as JSON
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
