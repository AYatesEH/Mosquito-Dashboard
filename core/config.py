"""
config.py

Central place for constants and settings that are NOT business logic and NOT
raw data, but configuration that an administrator should eventually be able to
change without touching application code.

Anything here that is operationally sensitive (thresholds, targets, product
rates) is sample-only and loaded from CSV so it can later move to an admin
screen or database table without code changes.
"""

import json
from pathlib import Path

# --- Paths -------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"
GIS_DIR = PROJECT_ROOT / "data" / "gis"
# Real City of Vincent LGA boundary (WA Landgate LGATE-233 dataset).
VINCENT_BOUNDARY_PATH = GIS_DIR / "city_of_vincent_boundary.geojson"

# Real centroid of the Vincent LGA boundary above - used as a stable
# "region-wide" coordinate for the live weather feed (core/weather_api.py),
# since environmental_data.csv models weather as region-wide rather than
# per-site. Computed the same way data/generate_sample_data.py derives its
# CENTER_LAT/CENTER_LON, so the two stay consistent.
with open(VINCENT_BOUNDARY_PATH) as _f:
    _boundary_geojson = json.load(_f)
_boundary_ring = _boundary_geojson["features"][0]["geometry"]["coordinates"][0][0]
VINCENT_CENTER_LAT = round(sum(c[1] for c in _boundary_ring) / len(_boundary_ring), 5)
VINCENT_CENTER_LON = round(sum(c[0] for c in _boundary_ring) / len(_boundary_ring), 5)

# Discrete, LABEL-DEFINED rate options for the two real S-methoprene
# products, transcribed exactly from the APVMA-approved labels (see each
# product's Rate_Basis/Label_Reference in products.csv for the full text).
# Both labels define the rate as a straight choice between exactly two site
# conditions - never a number in between - so the Treatments "Record a
# treatment" form uses this to make an officer pick the site condition and
# get the exact labelled rate, rather than typing a free-form number that
# might not actually be on the label. Keyed by Product_ID; each value is a
# list of (site-condition description, exact rate) tuples in the product's
# own Rate_Unit.
LABEL_RATE_OPTIONS = {
    "PRD-01": [  # ProLink Pellets - kg/ha
        ("Shallow (<30cm), clean water, low larval counts (<10/dip)", 3.0),
        ("Deep (>30cm), organic/sediment-rich water, high larval counts (>10/dip), "
         "or the target is specifically Culex sitiens", 4.0),
    ],
    "PRD-02": [  # ProLink XR Briquets - m2 of water surface per 1 briquet
        ("Shallow (<30cm), clean water, low larval counts (<10/dip) - Ochlerotatus/Aedes vigilax", 20.0),
        ("Deep (>30cm), organic/sediment-rich water, high larval counts (>10/dip), "
         "or all other mosquito species", 10.0),
    ],
}

# Unit that Quantity_Used is RECORDED in for each active real product -
# chosen to match how officers actually count/measure product in the field
# (whole briquets, grams of pellets), which is deliberately NOT the same as
# the product's Rate_Unit above (a per-area/per-water-surface APPLICATION
# RATE, e.g. "kg/ha" or "m2 of water surface per 1 briquet"). Used to label
# the Quantity_Used input/auto-suggestion on the Treatments "Record a
# treatment" form, and anywhere Quantity_Used is displayed, so the two
# different-looking units for the same product are never mistaken for one
# another. Keyed by Product_ID; a product not listed here (e.g. the
# fictional withdrawn product) has no fixed recording unit and is entered as
# a plain number.
QUANTITY_USED_UNITS = {
    "PRD-01": "g",           # ProLink Pellets - grams of product applied
    "PRD-02": "briquet(s)",  # ProLink XR Briquets - whole briquets used
}

# Site type used for the Swan River foreshore site (Claisebrook Cove) - a
# real, named location tracked because larvae dipping/larviciding along the
# river bank is a regular part of the program. Defined here (not just in
# data/generate_sample_data.py) so pages can identify "the river site" -
# e.g. to show a tide indicator - without hardcoding the string themselves.
RIVER_SITE_TYPE = "Swan River Foreshore"

# --- Trap effort ---------------------------------------------------------
# A "trap night" is counted only for events where the trap was deployed,
# retrieved, and produced a valid sample. See core/calculations.py for the
# exact rule. This constant is the assumed number of nights a trap is left
# out for a "standard" deployment, used only as a fallback when deployment/
# retrieval timestamps are inconsistent (flagged by Data Quality instead of
# silently guessed wherever possible).
DEFAULT_TRAP_NIGHTS_FALLBACK = 2

# --- Statuses --------------------------------------------------------
VALID_TRAP_STATUSES_FOR_ABUNDANCE = {"Successful", "Partial"}
INVALID_SAMPLE_VALIDITY = {"Invalid", "N/A"}

TREATMENT_STATUSES = ["Planned", "Scheduled", "Completed", "Cancelled"]

# --- Operational status labels (see calculations.classify_status) ------
STATUS_NORMAL = "Normal"
STATUS_ELEVATED = "Elevated"
STATUS_ACTION = "Action Required"
STATUS_UNKNOWN = "Insufficient Data"

STATUS_COLOURS = {
    STATUS_NORMAL: "#2E7D32",       # green
    STATUS_ELEVATED: "#F2A900",     # amber
    STATUS_ACTION: "#C62828",       # red
    STATUS_UNKNOWN: "#9E9E9E",      # grey
}

# --- Treatment effectiveness ------------------------------------------
DEFAULT_PRE_WINDOW_DAYS = 7
DEFAULT_POST_WINDOW_DAYS = 7
MIN_EVENTS_FOR_EFFECTIVENESS = 1  # minimum valid surveillance events required on EACH side of a treatment

# --- Re-dose scheduling (see calculations.estimate_control_window) -----
# How many days before a treatment's estimated effectiveness window ends it
# should surface as "due soon" rather than "on track" - lets officers plan
# the next visit ahead of the larvicide actually lapsing, not after.
REDOSE_LEAD_DAYS = 14

REDOSE_ON_TRACK = "On track"
REDOSE_DUE_SOON = "Re-dose due soon"
REDOSE_OVERDUE = "Re-dose overdue"
REDOSE_NOT_SCHEDULED = "Not scheduled"  # product has no meaningful residual window (e.g. adulticide, Bti knockdown)

REDOSE_STATUS_COLOURS = {
    REDOSE_ON_TRACK: "#2E7D32",       # green
    REDOSE_DUE_SOON: "#F2A900",       # amber
    REDOSE_OVERDUE: "#C62828",        # red
    REDOSE_NOT_SCHEDULED: "#9E9E9E",  # grey
}

# --- Hotspot rules (SAMPLE - configurable, transparent, not predictive) --
# A site is flagged a "persistent hotspot" if in the last N weeks it recorded
# at least MIN_ELEVATED_WEEKS weeks at/above the Elevated threshold.
HOTSPOT_LOOKBACK_WEEKS = 6
HOTSPOT_MIN_ELEVATED_WEEKS = 3
HOTSPOT_MIN_COMPLAINTS = 3          # complaints in lookback window to flag "repeated complaints"
HOTSPOT_MIN_TREATMENTS = 2          # completed treatments in lookback window to flag "repeatedly treated"

# --- App metadata -------------------------------------------------------
APP_TITLE = "Mosquito Season Dashboard"
APP_SUBTITLE = "Environmental Health - Mosquito Management (Prototype)"
SAMPLE_DATA_BANNER = (
    "PROTOTYPE - all data, thresholds, products, application rates and targets shown are "
    "SAMPLE/FICTIONAL and must not be used for operational decisions."
)
