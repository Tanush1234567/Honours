# =============================================================================
# config.py
# Central configuration for the FARSITE <-> Gurobi rolling-horizon integration.
# Every tunable parameter lives here. No other file needs editing for most runs.
# =============================================================================

import numpy as np

# -----------------------------------------------------------------------------
# PATHS
# -----------------------------------------------------------------------------
FARSITE_EXE     = r"C:\Workspace\FlamMap6\FlamMap6.exe" # path to the FARSITE CLI binary
LCP_FILE        = r"inputs\landscape.lcp"           # landscape file (.lcp)
IGNITION_SHP    = r"inputs\ignition.shp"            # initial fire perimeter shapefile
WEATHER_FILE    = r"inputs\weather.wtr"             # .wtr weather stream file
WIND_FILE       = r"inputs\wind.wnd"                # .wnd wind stream file
OUTPUT_DIR      = r"outputs"                        # base dir; per-iteration sub-dirs created automatically
LOG_DIR         = r"logs"

# -----------------------------------------------------------------------------
# GRID / DISCRETISATION
# The grid is defined in the SAME coordinate system as the LCP file (UTM metres).
# Cell size should be roughly equal to the standard deviation σ of the water drop
# pattern (see drop_pattern.py), as stated in the problem statement.
# -----------------------------------------------------------------------------
CELL_SIZE_M     = 3000        # [m] cell side length; tune based on σ of your drop pattern
GRID_ROWS       = 50         # number of rows   (total height = GRID_ROWS * CELL_SIZE_M)
GRID_COLS       = 50         # number of columns (total width  = GRID_COLS * CELL_SIZE_M)
GRID_ORIGIN_X   = 0.0        # [m] UTM easting  of top-left corner of the grid
GRID_ORIGIN_Y   = 0.0        # [m] UTM northing of top-left corner of the grid

# Cell states (match problem statement: S = {0,1,2})
STATE_UNBURNED      = 0
STATE_BURNING       = 1
STATE_EXTINGUISHED  = 2

# Threshold: fraction of cell that must be burning for it to count as STATE_BURNING.
# Problem statement specifies >50%.
BURN_FRACTION_THRESHOLD = 0.50

# -----------------------------------------------------------------------------
# TIME
# -----------------------------------------------------------------------------
WINDOW_MINUTES  = 15    # [min] length of each rolling-horizon window W
MAX_ITERATIONS  = 20    # hard stop on number of windows even if fire not out
#! After this the whole simulation stops. Per iteration is the number of times you will call FARSITE and gurobi
SIM_START_TIME  = 0     # [min since midnight] start of FARSITE simulation clock

# -----------------------------------------------------------------------------
# FLEET
# Each entry is (num_tankers, num_scoopers).
# The loop solves once per entry; useful for Monte Carlo fleet comparison.
# -----------------------------------------------------------------------------
FLEET = [(2, 2)]

# Aircraft capacities [litres]
Ck = 10_000   # tanker water capacity
Cp =  5_000   # scooper water capacity

# Cruise speeds [km/min]
CRUISE_K = 10.0   # tanker
CRUISE_P =  6.0   # scooper

# Max tanker depot-return trips per planning horizon
MAX_TRIPS = 4 #* Does not need to be enforced right now

# Processing times [min]
R  = 1   # time to execute one drop manoeuvre
RD = 0   # airfield refill/processing time (set > 0 if refilling takes time)
#! Will definitely need to increase this

# Gurobi time limit per optimisation call [seconds]
GUROBI_TIME_LIMIT = 300

# -----------------------------------------------------------------------------
# AIRFIELD AND WATER SOURCE LOCATIONS
# Specified as (row, col) indices on the grid, not UTM coordinates.
# These are fixed landmarks; they do NOT change between iterations.
# -----------------------------------------------------------------------------
AIRFIELD_CELL   = (0,  0)     # (row, col) of the airfield / depot
WATER_CELLS     = [(0, 49), (49, 0)]   # list of water source cells (scoopers refill here)

# -----------------------------------------------------------------------------
# DROP PATTERN  (problem statement Section 2.0.3)
# Parameters for the hexagonal / normal distribution water drop model.
# η(x,y) = λ/sqrt(2πσ²) * exp(-y²/2σ²)
# λ(x,h) is the longitudinal profile; σ = λ/6
# -----------------------------------------------------------------------------
DROP_K        = 0.05    # scaling factor k (relates release altitude to max width)
DROP_L1       = 20.0    # [m] longitudinal ramp length l1
DROP_L2       = 40.0    # [m] longitudinal flat length l2
DROP_H        = 40.0    # [m] release altitude h (10–80 m per problem statement)

# Effectiveness: fraction by which fire intensity decreases in a directly hit cell
DROP_PHI      = 0.8     # φ — direct hit reduces intensity by this fraction
DROP_PHI_DECAY = 0.3    # f(φ,d) falloff applied to neighbouring cells

# -----------------------------------------------------------------------------
# WIND (stochastic profile — problem statement Section 2.0.5)
# Wind is sampled once per window and held constant within that window.
# The SAME wind values are written to both the FARSITE input and the Gurobi model.
# -----------------------------------------------------------------------------
WIND_SPEED_MEAN   = 10.0   # [km/h] mean wind speed
WIND_SPEED_STD    =  3.0   # [km/h] standard deviation
WIND_DIR_MEAN     = 225.0  # [degrees] mean direction (SW wind → fire spreads NE)
WIND_DIR_STD      = 15.0   # [degrees] standard deviation

# Random seed (None = non-reproducible; set an int for reproducible Monte Carlo)
RANDOM_SEED = 42

# -----------------------------------------------------------------------------
# FARSITE INPUT FILE TEMPLATE
# These values go into the .input file that controls each FARSITE run.
# Only START_TIME, END_TIME, and IGNITION_FILE are overwritten per iteration;
# everything else is fixed.
# -----------------------------------------------------------------------------
FARSITE_CROWN_FIRE_METHOD  = 1       # 0=Finney, 1=Scott&Reinhardt
FARSITE_FOLIAR_MC          = 100     # foliar moisture content [%]
FARSITE_SPOT_PROBABILITY   = 0.0     # spotting probability (0=off)
FARSITE_TIMESTEP           = 1       # [min] internal FARSITE timestep
FARSITE_PERIMETER_RES      = 60.0    # [m] perimeter resolution
FARSITE_DIST_RES           = 60.0    # [m] distance resolution

# -----------------------------------------------------------------------------
# BIG-M (Gurobi linearisation constant)
# Should be >= total planning horizon. 1000 min >> any realistic scenario.
# -----------------------------------------------------------------------------
M_BIG = 1000.0
