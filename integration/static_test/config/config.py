# =============================================================================
# config.py  (static_test version)
# All FARSITE / wind / Monte Carlo parameters removed.
# The only inputs are the ignition shapefile and (optionally) a landscape GeoTIFF.
# =============================================================================

import numpy as np

# -----------------------------------------------------------------------------
# PATHS
# -----------------------------------------------------------------------------
IGNITION_SHP    = r"inputs\ignition.shp"   # initial fire perimeter shapefile
OUTPUT_DIR      = r"outputs"
LOG_DIR         = r"logs"

# -----------------------------------------------------------------------------
# GRID / DISCRETISATION
# Must match the coordinate system and extent of your ignition shapefile.
# Run:  gdalinfo inputs\landscape.lcp   (or inspect in QGIS) to get these.
# -----------------------------------------------------------------------------
CELL_SIZE_M     = 500        # [m] cell side length
GRID_ROWS       = 50         # number of rows
GRID_COLS       = 50         # number of columns
GRID_ORIGIN_X   = 0.0        # [m] UTM easting  of top-left corner  ← FILL IN
GRID_ORIGIN_Y   = 0.0        # [m] UTM northing of top-left corner  ← FILL IN
GRID_CRS        = "EPSG:32633"   # ← match to your ignition .shp projection

# Cell states
STATE_UNBURNED      = 0
STATE_BURNING       = 1
STATE_EXTINGUISHED  = 2

BURN_FRACTION_THRESHOLD = 0.50   # >50% cell area inside ignition polygon → BURNING

# -----------------------------------------------------------------------------
# TIME  (static: just one solve window, no rolling loop)
# -----------------------------------------------------------------------------
WINDOW_MINUTES  = 15    # [min] length of the single planning horizon

# -----------------------------------------------------------------------------
# FLEET  — one configuration for the static test
# -----------------------------------------------------------------------------
NUM_TANKERS  = 2
NUM_SCOOPERS = 1

# Aircraft capacities [litres]
Ck = 10_000   # tanker water capacity
Cp =  5_000   # scooper water capacity

# Cruise speeds [km/min]
CRUISE_K = 10.0   # tanker
CRUISE_P =  6.0   # scooper

# Processing times [min]
R  = 1   # time to execute one drop manoeuvre
RD = 0   # airfield refill time

# Gurobi time limit per optimisation call [seconds]
GUROBI_TIME_LIMIT = 300

# -----------------------------------------------------------------------------
# AIRFIELD AND WATER SOURCE LOCATIONS  (grid indices, not UTM)
# -----------------------------------------------------------------------------
AIRFIELD_CELL   = (0,  0)
WATER_CELLS     = [(0, 49), (49, 0)]

# -----------------------------------------------------------------------------
# DROP PATTERN  (problem statement Section 2.0.3)
# -----------------------------------------------------------------------------
DROP_K        = 0.05
DROP_L1       = 20.0    # [m]
DROP_L2       = 40.0    # [m]
DROP_H        = 40.0    # [m] release altitude
DROP_PHI      = 0.8
DROP_PHI_DECAY = 0.3

# -----------------------------------------------------------------------------
# WIND  (fixed for static test — no stochastic sampling)
# These values are used only by the drop pattern (heading = dir + 180).
# They do NOT feed into any FARSITE run.
# -----------------------------------------------------------------------------
WIND_SPEED_KPH = 10.0    # [km/h]
WIND_DIR_DEG   = 225.0   # [degrees]  SW wind → fire spreads NE

# -----------------------------------------------------------------------------
# BIG-M
# -----------------------------------------------------------------------------
M_BIG = 1000.0
