"""
config.py

Central place for constants and settings that are NOT business logic and NOT
raw data, but configuration that an administrator should eventually be able to
change without touching application code.

Anything here that is operationally sensitive (thresholds, targets, product
rates) is sample-only and loaded from CSV so it can later move to an admin
screen or database table without code changes.
"""

from pathlib import Path

# --- Paths -------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"
GIS_DIR = PROJECT_ROOT / "data" / "gis"
# Real City of Vincent LGA boundary (WA Landgate LGATE-233 dataset).
VINCENT_BOUNDARY_PATH = GIS_DIR / "city_of_vincent_boundary.geojson"

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
