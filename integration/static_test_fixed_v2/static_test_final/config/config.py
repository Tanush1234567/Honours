# =============================================================================
# config.py  (static_test — grid georeferencing derived from landscape.tif)
# =============================================================================

import numpy as np

# -----------------------------------------------------------------------------
# PATHS
# -----------------------------------------------------------------------------
LANDSCAPE_TIF   = r"inputs/landscape.tif"
IGNITION_SHP    = r"inputs/ignition.shp"
OUTPUT_DIR      = r"outputs"
LOG_DIR         = r"logs"

# -----------------------------------------------------------------------------
# GRID / DISCRETISATION
#
# GRID_ROWS, GRID_COLS, GRID_ORIGIN_X, GRID_ORIGIN_Y, GRID_CRS, CELL_SIZE_M
# are NOT set here. FlamMap landscapes use a custom, landscape-specific
# Albers projection with no EPSG code, so any hand-typed EPSG string here
# would silently mismatch the real projection. Instead these values are
# read directly from LANDSCAPE_TIF at runtime — see grid_utils.load_landscape_georef()
# and run_static.py.
# -----------------------------------------------------------------------------

# Cell states
STATE_UNBURNED      = 0
STATE_BURNING       = 1
STATE_EXTINGUISHED  = 2

BURN_FRACTION_THRESHOLD = 0.50   # >50% cell area inside ignition polygon → BURNING

# -----------------------------------------------------------------------------
# TIME  (static: one solve window, no rolling loop)
# -----------------------------------------------------------------------------
WINDOW_MINUTES  = 15    # [min]

# -----------------------------------------------------------------------------
# FLEET
# -----------------------------------------------------------------------------
NUM_TANKERS  = 2
NUM_SCOOPERS = 1

Ck = 10_000   # tanker water capacity [L]
Cp =  5_000   # scooper water capacity [L]

CRUISE_K = 10.0   # tanker cruise speed [km/min]
CRUISE_P =  6.0   # scooper cruise speed [km/min]

R  = 1   # time to execute one drop manoeuvre [min]
RD = 0   # airfield refill time [min]

GUROBI_TIME_LIMIT = 60   # [s]

# -----------------------------------------------------------------------------
# AIRFIELD AND WATER SOURCE LOCATIONS  (grid indices — row, col)
#
# IMPORTANT: these depend on GRID_ROWS/GRID_COLS, which are only known once
# landscape.tif is read at runtime. Placeholders below assume a landscape
# similar in size to the one you supplied (668 rows x 1640 cols). Check
# run_static.py's startup log — it prints the actual grid size and will
# warn you if AIRFIELD_CELL or WATER_CELLS fall outside it or inside the
# fire perimeter.
# -----------------------------------------------------------------------------
AIRFIELD_CELL   = (0, 0)
WATER_CELLS     = [(0, 229), (81, 0)]   # placeholders — top-right and bottom-left corners of this 82x230 grid

# -----------------------------------------------------------------------------
# DROP PATTERN
# -----------------------------------------------------------------------------
DROP_K        = 0.05
DROP_L1       = 20.0    # [m]
DROP_L2       = 40.0    # [m]
DROP_H        = 40.0    # [m] release altitude
DROP_PHI      = 0.8
DROP_PHI_DECAY = 0.3

# -----------------------------------------------------------------------------
# WIND  (fixed for static test — no stochastic sampling, no FARSITE feed)
# -----------------------------------------------------------------------------
WIND_SPEED_KPH = 10.0
WIND_DIR_DEG   = 225.0

# -----------------------------------------------------------------------------
# BIG-M
# -----------------------------------------------------------------------------
M_BIG = 1000.0
