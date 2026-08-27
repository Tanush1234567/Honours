# =============================================================================
# farsite_interface.py
# Handles everything to do with calling FARSITE:
#   - Writing the .input file for each iteration
#   - Writing the ignition shapefile from the current grid state
#   - Calling TestFarsite.exe via subprocess
#   - Reading the output perimeter shapefile and ROS raster back into the grid
#
# FARSITE is run in ITERATIVE mode: each call simulates exactly WINDOW_MINUTES
# of fire growth starting from the current perimeter, with the same wind that
# was passed to Gurobi for that window.
# =============================================================================

import os
import subprocess
import pathlib
import numpy as np
import geopandas as gpd
import rasterio 
#* Rasterio is a python library to work with georeferenced images (the image represents
#* physical location on earth). Each pixel represents a certain resolution
from rasterio.features import shapes, rasterize
from rasterio.transform import from_origin
from shapely.geometry import shape, mapping, Polygon
from shapely.ops import unary_union

from config.config import (
    FARSITE_EXE, LCP_FILE, WEATHER_FILE, WIND_FILE,
    WINDOW_MINUTES, SIM_START_TIME,
    GRID_ROWS, GRID_COLS, CELL_SIZE_M, GRID_ORIGIN_X, GRID_ORIGIN_Y,
    BURN_FRACTION_THRESHOLD, STATE_BURNING, STATE_UNBURNED, STATE_EXTINGUISHED,
    FARSITE_CROWN_FIRE_METHOD, FARSITE_FOLIAR_MC, FARSITE_SPOT_PROBABILITY,
    FARSITE_TIMESTEP, FARSITE_PERIMETER_RES, FARSITE_DIST_RES,
    OUTPUT_DIR
)


# ---------------------------------------------------------------------------
# Rasterio transform: maps pixel (row, col) → UTM (x, y)
# Origin is top-left; rows go south (y decreasing).
# ---------------------------------------------------------------------------
GRID_TRANSFORM = from_origin(
    west  = GRID_ORIGIN_X,
    north = GRID_ORIGIN_Y + GRID_ROWS * CELL_SIZE_M,  # top edge #! I think top left heading is just GRID_ORIGIN_Y
    xsize = CELL_SIZE_M,
    ysize = CELL_SIZE_M
)
GRID_CRS = "EPSG:32633"   # ← change to match your LCP projection


# ---------------------------------------------------------------------------
# Utility: convert simulation elapsed minutes to FARSITE clock format
# FARSITE uses "day hour minute" counted from the start of the year.
# We simplify to absolute minutes since midnight day 1.
# ---------------------------------------------------------------------------
def _mins_to_farsite_time(minutes: int) -> tuple:
    """Return (day, hour, minute) for FARSITE input from absolute minute offset."""
    base_day  = 200           # Julian day; set to match your weather stream
    total_min = SIM_START_TIME + minutes
    day   = base_day + total_min // (24 * 60)
    hour  = (total_min % (24 * 60)) // 60
    minute = total_min % 60
    return day, hour, minute


# ---------------------------------------------------------------------------
# 1. Write the FARSITE .input file
# ---------------------------------------------------------------------------
def write_farsite_input(
    iteration: int,
    wind_speed_kph: float,
    wind_dir_deg: float,
    ignition_shp: str,
    output_subdir: str
) -> str:
    """
    Write the FARSITE .input control file for one iteration.

    Parameters
    ----------
    iteration : int
    wind_speed_kph, wind_dir_deg : float
        Wind values sampled for this window (same as given to Gurobi).
    ignition_shp : str
        Path to the current ignition perimeter shapefile.
    output_subdir : str
        Directory where FARSITE should write its outputs.

    Returns
    -------
    str : path to the written .input file
    """
    t_start = iteration * WINDOW_MINUTES
    t_end   = t_start + WINDOW_MINUTES

    sd, sh, sm = _mins_to_farsite_time(t_start)
    ed, eh, em = _mins_to_farsite_time(t_end)

    pathlib.Path(output_subdir).mkdir(parents=True, exist_ok=True)

    # FARSITE expects wind speed in m/min internally but .input takes km/h
    lines = [
        f"LANDSCAPE_FILE: {os.path.abspath(LCP_FILE)}",
        f"IGNITION_FILE: {os.path.abspath(ignition_shp)}",
        f"FARSITE_START_TIME: {sd} {sh:02d}{sm:02d}",
        f"FARSITE_END_TIME:   {ed} {eh:02d}{em:02d}",
        f"FARSITE_TIMESTEP: {FARSITE_TIMESTEP}",
        f"FARSITE_DISTANCE_RES: {FARSITE_DIST_RES}",
        f"FARSITE_PERIMETER_RES: {FARSITE_PERIMETER_RES}",
        f"FARSITE_SPOT_PROBABILITY: {FARSITE_SPOT_PROBABILITY}",
        f"FARSITE_CROWN_FIRE_METHOD: {FARSITE_CROWN_FIRE_METHOD}",
        f"FARSITE_FOLIAR_MC: {FARSITE_FOLIAR_MC}",
        # Wind overrides (uniform wind for this window)
        f"WIND_SPEED: {wind_speed_kph:.1f}",
        f"WIND_DIRECTION: {wind_dir_deg:.1f}",
        # Outputs we need: perimeter shapefile + ROS raster
        f"FARSITE_OUTPUT_PERIMETER: 1",
        f"FARSITE_OUTPUT_RASTER_ROS: 1",
        f"FARSITE_OUTPUT_RASTER_FLIN: 0",
        f"OUTPUT_DIR: {os.path.abspath(output_subdir)}",
    ]

    input_path = os.path.join(output_subdir, f"farsite_iter_{iteration:03d}.input")
    with open(input_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return input_path


# ---------------------------------------------------------------------------
# 2. Write ignition perimeter shapefile from the current grid
# ---------------------------------------------------------------------------
def write_ignition_shapefile(grid: np.ndarray, out_path: str) -> str:
    """
    Convert the binary burning-cell grid into a polygon shapefile for FARSITE.

    Only STATE_BURNING cells are included. Extinguished cells (STATE_EXTINGUISHED)
    are explicitly excluded so FARSITE cannot reignite them.

    Parameters
    ----------
    grid : np.ndarray  shape (GRID_ROWS, GRID_COLS), values in {0,1,2}
    out_path : str     path for the output .shp (without extension — geopandas adds it)

    Returns
    -------
    str : path of the written shapefile (.shp)
    """
    burning_mask = (grid == STATE_BURNING).astype(np.uint8)

    # Convert raster mask → vector polygons
    polys = []
    for geom_dict, val in shapes(burning_mask, transform=GRID_TRANSFORM):
        if val == 1:
            polys.append(shape(geom_dict))

    if not polys:
        # No burning cells — write an empty shapefile (FARSITE will exit cleanly)
        gdf = gpd.GeoDataFrame(geometry=[], crs=GRID_CRS)
    else:
        merged = unary_union(polys)
        if merged.geom_type == "Polygon":
            merged = [merged]
        else:
            merged = list(merged.geoms)
        gdf = gpd.GeoDataFrame(geometry=merged, crs=GRID_CRS)

    shp_path = out_path if out_path.endswith(".shp") else out_path + ".shp"
    gdf.to_file(shp_path)
    return shp_path


# ---------------------------------------------------------------------------
# 3. Run FARSITE
# ---------------------------------------------------------------------------
def run_farsite(input_file: str, timeout: int = 600) -> None:
    """
    Call TestFarsite.exe and wait for it to finish.

    Parameters
    ----------
    input_file : str  Path to the .input file
    timeout : int     Maximum seconds to wait before raising an error
    """
    cmd = [FARSITE_EXE, input_file]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"FARSITE failed on {input_file}\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )


# ---------------------------------------------------------------------------
# 4. Parse FARSITE outputs back into the grid
# ---------------------------------------------------------------------------
def parse_farsite_output(
    output_subdir: str,
    iteration: int,
    extinguished_mask: np.ndarray
) -> np.ndarray:
    """
    Read the FARSITE perimeter shapefile (or ROS raster if available) and
    convert back to the 3-state integer grid.

    Cells that are in the FARSITE fire perimeter are marked BURNING.
    Cells previously extinguished (STATE_EXTINGUISHED) stay extinguished —
    they are never overwritten by FARSITE output.
    Cells with less than BURN_FRACTION_THRESHOLD of their area covered by
    the fire perimeter are kept as UNBURNED.

    Parameters
    ----------
    output_subdir : str
    iteration : int
    extinguished_mask : np.ndarray  bool mask of permanently extinguished cells

    Returns
    -------
    np.ndarray : updated grid
    """
    # --- Try ROS raster first (more accurate fractional coverage) ---
    ros_path = _find_file(output_subdir, suffix="_ROS.asc") or \
               _find_file(output_subdir, suffix="_ROS.tif")

    if ros_path:
        grid = _grid_from_ros_raster(ros_path, extinguished_mask)
    else:
        # Fall back to perimeter shapefile
        perim_path = _find_file(output_subdir, suffix="_Perimeter.shp") or \
                     _find_file(output_subdir, suffix="Perimeter.shp")
        if perim_path is None:
            raise FileNotFoundError(
                f"No FARSITE output (ROS raster or perimeter shp) found in {output_subdir}"
            )
        grid = _grid_from_perimeter_shp(perim_path, extinguished_mask)

    return grid


def _find_file(directory: str, suffix: str):
    """Return path of first file in directory whose name ends with suffix, or None."""
    for fname in os.listdir(directory):
        if fname.endswith(suffix):
            return os.path.join(directory, fname)
    return None


def _grid_from_ros_raster(ros_path: str, extinguished_mask: np.ndarray) -> np.ndarray:
    """
    Build the 3-state grid from the FARSITE Rate-of-Spread raster.
    A cell is BURNING if ROS > 0 (the fire reached it).
    """
    with rasterio.open(ros_path) as src:
        ros = src.read(1).astype(float)
        #! Reproject / resample to our grid if necessary
        #! (assume matching resolution for now; add rasterio.warp if not)

    grid = np.where(ros > 0, STATE_BURNING, STATE_UNBURNED).astype(int)
    # Respect extinguished cells: they cannot become burning
    grid[extinguished_mask] = STATE_EXTINGUISHED
    return grid


def _grid_from_perimeter_shp(perim_path: str, extinguished_mask: np.ndarray) -> np.ndarray:
    """
    Build the 3-state grid by rasterising the FARSITE perimeter polygon.
    Applies the >50% area coverage threshold from the problem statement.
    """
    gdf = gpd.read_file(perim_path)
    if gdf.empty:
        grid = np.zeros((GRID_ROWS, GRID_COLS), dtype=int)
        grid[extinguished_mask] = STATE_EXTINGUISHED
        return grid

    # Rasterise at 10× resolution to estimate fractional coverage per cell
    scale = 10
    fine_transform = from_origin(
        west  = GRID_ORIGIN_X,
        north = GRID_ORIGIN_Y + GRID_ROWS * CELL_SIZE_M,
        xsize = CELL_SIZE_M / scale,
        ysize = CELL_SIZE_M / scale
    )
    #!  this assumes the perimeter CRS (Coordinate Reference System) and GRID_ORIGIN_* / CELL_SIZE_M are consistent (same projection).
    # CHECK AND ADD THIS IF NECESSARY: 
    """
    if gdf.crs is None:
        raise ValueError("Perimeter shapefile missing CRS; set it or reproject to GRID_CRS")
    if gdf.crs.to_string() != GRID_CRS:
        gdf = gdf.to_crs(GRID_CRS)
    """
    fine_mask = rasterize(
        [(mapping(geom), 1) for geom in gdf.geometry],
        out_shape=(GRID_ROWS * scale, GRID_COLS * scale),
        transform=fine_transform,
        fill=0,
        dtype=np.uint8
    )
    # Downsample: average over scale×scale blocks → fraction covered
    fine_r = fine_mask.reshape(GRID_ROWS, scale, GRID_COLS, scale)
    frac   = fine_r.mean(axis=(1, 3))
    grid = np.where(frac > BURN_FRACTION_THRESHOLD, STATE_BURNING, STATE_UNBURNED).astype(int)
    grid[extinguished_mask] = STATE_EXTINGUISHED
    return grid
