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

# Named suburbs within the City of Vincent LGA, each with an approximate
# reference coordinate (Wikipedia infobox coordinates for that suburb),
# used to let the live weather feed be shown for a specific part of Vincent
# (e.g. Leederville, East Perth, Mount Hawthorn) rather than only one
# LGA-wide centroid - see core/ui.py's vincent_area_picker, used by the
# Environmental Conditions and Dosage Calculator pages. Suburbs marked
# "(part)" are shared with a neighbouring council (per Wikipedia's "City of
# Vincent" article) - only the portion within Vincent is relevant here.
# Coolbinia is deliberately NOT included: Wikipedia's suburb list names it as
# shared with the City of Stirling, but per direct confirmation it is not
# actually part of the City of Vincent.
# Open-Meteo's weather grid is coarser than the whole LGA (~9 km^2), so
# figures may come back identical or near-identical between nearby suburbs -
# this still shows the correct area name, just don't expect large numeric
# differences over such a small area.
VINCENT_AREAS = {
    "Leederville": (-31.936, 115.834),
    "Highgate": (-31.94, 115.869),
    "Mount Hawthorn": (-31.921, 115.838),
    "North Perth": (-31.928, 115.853),
    "East Perth (part)": (-31.957, 115.876),
    "West Perth (part)": (-31.94528, 115.84556),
    "Perth (part)": (-31.95, 115.85),
    "Mount Lawley (part)": (-31.9301, 115.8746),
    "Osborne Park (part)": (-31.898, 115.812),
}

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

# Starting-point guidance for the Dosage Calculator's "Guided dosage
# calculator" tab (pages/6_Dosage_Calculator.py): given a plain-language water body/location
# type, suggests which real product and which LABEL_RATE_OPTIONS condition
# (index 0 = shallow/clean/low-larval, index 1 = deep/organic-rich/
# high-larval) an officer would typically start from. Where possible the
# suggestion is drawn directly from the site-type examples named in each
# product's own APVMA label text (see each product's Rate_Basis/Notes in
# products.csv) - "reasoning" says explicitly which parts are label wording
# and which are this app's own practical judgement (e.g. no label names
# "Swan River foreshore" specifically). THIS IS A STARTING SUGGESTION ONLY,
# not a determination: the label's actual, operative criteria are the
# measured water depth, organic content and larval count observed on site,
# never the location's name, so the calculator always leaves the product and
# condition fully overridable and never saves/locks anything.
LOCATION_TYPE_GUIDANCE = {
    "Salt marsh / mangrove / estuarine wetland": {
        "product_id": "PRD-01", "condition_index": 0,
        "reasoning": "Named directly on the ProLink Pellets label as an example of a 3 kg/ha 'temporary water "
                     "site' (shallow, clean, low larval counts) - see its Rate_Basis.",
    },
    "Woodland pool / natural water-holding feature": {
        "product_id": "PRD-01", "condition_index": 0,
        "reasoning": "Named directly on the ProLink Pellets label alongside marshes, under the same 3 kg/ha "
                     "'temporary water site' example.",
    },
    "Temporary/ephemeral pool (verge, construction site, roadside)": {
        "product_id": "PRD-01", "condition_index": 0,
        "reasoning": "Not a named label example - this app's judgement: fits the label's shallow/clean/low-larval "
                     "'temporary water site' category, and Pellets' 30-day duration suits water expected to dry "
                     "out sooner than a 150-day briquet's residual life.",
    },
    "Stormwater drain / pit / catch basin": {
        "product_id": "PRD-02", "condition_index": 1,
        "reasoning": "Named directly on the ProLink XR Briquets label's typical-use list ('storm drains, catch "
                     "basins'). Drains typically accumulate sediment/organic debris, matching the label's "
                     "higher-rate (deep/organic-rich) condition.",
    },
    "Abandoned / neglected swimming pool": {
        "product_id": "PRD-02", "condition_index": 1,
        "reasoning": "Named directly on the ProLink XR Briquets label's typical-use list ('abandoned pools'). A "
                     "stagnant, untreated pool is typically deep and organic/algae-rich, matching the label's "
                     "higher-rate condition. A pool still in active use/chlorinated is not usually a breeding "
                     "risk and would not normally need larvicide.",
    },
    "Ornamental pond / water feature": {
        "product_id": "PRD-02", "condition_index": 1,
        "reasoning": "Named on BOTH products' labels (Pellets' higher-rate 'permanent water site' example, and "
                     "Briquets' chronic/semi-permanent site list) - defaults to Briquets as the better fit for a "
                     "single discrete, semi-permanent feature, at the label's higher-rate (deep/organic) "
                     "condition consistent with the Pellets label's own categorisation of ornamental ponds.",
    },
    "Swan River foreshore / river bank": {
        "product_id": "PRD-02", "condition_index": 1,
        "reasoning": "Not a named label example for either product - this app's judgement: bank-edge water "
                     "re-floods on the tide and typically carries river sediment/organic matter, and an "
                     "extended-release briquet suits water that keeps returning rather than a one-off broadacre "
                     "spread. Check the tide indicator shown alongside this calculator before timing application.",
    },
    "Other / not listed": {
        "product_id": None, "condition_index": None,
        "reasoning": "No default for this location type - select a product and site condition manually below, "
                     "based on the water depth, organic content and larval counts actually observed on site.",
    },
}

# Site type used for the Swan River foreshore site (Claisebrook Cove) - a
# real, named location tracked because larvae dipping/larviciding along the
# river bank is a regular part of the program. Defined here (not just in
# data/generate_sample_data.py) so pages can identify "the river site" -
# e.g. to show a tide indicator - without hardcoding the string themselves.
RIVER_SITE_TYPE = "Swan River Foreshore"

# --- Mosquito season window ---------------------------------------------
# The program only operates October -> May (Southern Hemisphere); the cooler
# June-September months fall outside the season and get no data or action.
# `data/generate_sample_data.py` never generates a row dated in those months
# (see SEASONS there - it stays standalone/dependency-free by design, so
# this constant is duplicated there rather than imported), and the To Do
# List page (pages/0_To_Do_List.py) uses these bounds to recognise an
# off-season week and show "no action needed" instead of an empty list.
MOSQUITO_SEASON_START_MONTH = 10  # October
MOSQUITO_SEASON_END_MONTH = 5     # May (inclusive)

# --- Weekly To Do List (pages/0_To_Do_List.py) ---------------------------
# Transparent, configurable rules - same philosophy as Hotspot Identification
# (core.calculations.identify_hotspots): no prediction, every threshold here
# and nowhere else. The list itself is never persisted/checked off - it's
# recomputed fresh from current data every time the page loads (see
# calculations.build_weekly_todo_list), so once the treatment/trap placement/
# observation that a task is asking for has actually been logged, the rule
# that generated it just stops firing and the task naturally isn't on the
# next computed list - there is no separate "mark done" action or state.
TODO_TASK_TRAPPING = "Trap placement"
TODO_TASK_TREATMENT = "Larvicide treatment"
TODO_TASK_DIPPING = "Larvae dipping / inspection"

TODO_PRIORITY_HIGH = "High"
TODO_PRIORITY_MEDIUM = "Medium"
TODO_PRIORITY_COLOURS = {
    TODO_PRIORITY_HIGH: "#C62828",    # red
    TODO_PRIORITY_MEDIUM: "#F2A900",  # amber
}

# Only this many physical CO2 traps are actually owned/deployed each week
# (set out for one night, picked up the next morning, then moved) - so the
# To Do List doesn't track individual traps on a per-check cycle, it instead
# recommends which this-many sites should get this week's traps, ranked by
# hotspot priority (core.calculations.identify_hotspots) with the
# least-recently-trapped sites used as a rotation fallback. See
# calculations.build_weekly_todo_list.
WEEKLY_TRAP_COUNT = 3

# Trap types an officer can pick from on the Surveillance page's "Add Trap
# Data" form. Traps are portable equipment, not fixed installations - a trap
# is moved to whichever site needs it that week (see WEEKLY_TRAP_COUNT and
# trap_sites.csv, which is a plain equipment register with no location of its
# own) - so the form asks for "Trap location" (any active site) and "Trap
# type" as two independent dropdowns, rather than a single fixed trap-at-site
# pick. Kept here as the single source of truth for the option list;
# duplicated (not imported) in data/generate_sample_data.py, which stays a
# standalone, dependency-free script by design - see the note on
# RIVER_SITE_TYPE above.
TRAP_TYPES = ["EVS (CO2-baited)", "BG-Sentinel", "CDC Light Trap", "Gravid Trap"]

# An unresolved complaint (Investigation_Status not yet Site Inspected/
# Closed) becomes a High-priority inspection task once it's been open at
# least this many days; a freshly received one is Medium.
COMPLAINT_INSPECTION_AGE_HIGH_DAYS = 7

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

# Field Observations categories. OBSERVATION_CATEGORY_DIP is the category an
# officer picks to log that they actually dipped/inspected a water body for
# larvae - this is what the To Do List's "Larvae dipping / inspection" tasks
# look for to know a site has been checked (see
# calculations.build_weekly_todo_list and the quick-log action on the To Do
# List page itself). Kept here as the single source of truth for the
# category text everywhere it's compared/displayed; duplicated (not
# imported) in data/generate_sample_data.py, which stays a standalone,
# dependency-free script by design - see the note on RIVER_SITE_TYPE above.
OBSERVATION_CATEGORY_DIP = "Larvae dip / inspection"
OBSERVATION_CATEGORIES = [
    OBSERVATION_CATEGORY_DIP, "Standing water observed", "Access issue", "Breeding habitat present",
    "Treatment access restricted", "Environmental change", "Equipment issue", "Follow-up required",
]

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

# A single dip's larvae count above this is treated as "high" - reusing the
# real APVMA-label wording already used above in LABEL_RATE_OPTIONS/
# LOCATION_TYPE_GUIDANCE ("high larval counts (>10/dip)") rather than
# inventing a separate threshold.
HIGH_LARVAE_COUNT_PER_DIP = 10
HOTSPOT_MIN_HIGH_DIPS = 2           # high-count dips in the lookback window to flag "Elevated larvae dip counts"

# --- App metadata -------------------------------------------------------
APP_TITLE = "Mosquito Season Dashboard"
APP_SUBTITLE = "Environmental Health - Mosquito Management (Prototype)"
SAMPLE_DATA_BANNER = (
    "PROTOTYPE - all data, thresholds, products, application rates and targets shown are "
    "SAMPLE/FICTIONAL and must not be used for operational decisions."
)
