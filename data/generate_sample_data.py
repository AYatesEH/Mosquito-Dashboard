"""
generate_sample_data.py

Generates realistic DUMMY/SAMPLE data for the Mosquito Season Dashboard prototype.

IMPORTANT:
- All data produced by this script is FICTIONAL. Site names, coordinates, product
  names, application rates, and thresholds are NOT real and must NEVER be used
  operationally.
- Mosquito species names are real (public biological knowledge) so that
  surveillance results are realistic, but all counts, dates, and locations are
  synthetic.
- Run this script once to (re)build the CSV files under data/raw/. Re-running it
  regenerates all files from scratch (same random seed => same data, for
  reproducibility during development).

Relational model (see README.md for full description):
    sites (Site_ID) is the single source of truth for location.
    trap_sites, treatments, complaints, environmental_data and site_observations
    all reference Site_ID rather than duplicating name/lat/long.
"""

import json
import math

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

RNG_SEED = 42
rng = np.random.default_rng(RNG_SEED)

OUT_DIR = Path(__file__).parent / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# REAL City of Vincent LGA boundary (WA Landgate LGATE-233 dataset, supplied
# directly by the person). Used so randomly generated sites are rejection-
# sampled to fall genuinely INSIDE the real council boundary, rather than
# just inside a rough bounding box - see `_point_in_polygon` / `_random_point_
# in_boundary` below.
BOUNDARY_PATH = Path(__file__).parent / "gis" / "city_of_vincent_boundary.geojson"
with open(BOUNDARY_PATH) as _f:
    _boundary_geojson = json.load(_f)
# geometry is a MultiPolygon with one polygon and one ring (verified when
# this file was extracted from the statewide LGATE-233 dataset)
VINCENT_BOUNDARY_RING = _boundary_geojson["features"][0]["geometry"]["coordinates"][0][0]  # list of [lon, lat]
_ring_lons = [c[0] for c in VINCENT_BOUNDARY_RING]
_ring_lats = [c[1] for c in VINCENT_BOUNDARY_RING]
VINCENT_BBOX = (min(_ring_lons), max(_ring_lons), min(_ring_lats), max(_ring_lats))  # lon_min, lon_max, lat_min, lat_max


def _point_in_polygon(lon: float, lat: float, ring: list) -> bool:
    """Standard ray-casting point-in-polygon test against a GeoJSON ring
    (list of [lon, lat] pairs). No extra geo library required."""
    inside = False
    n = len(ring)
    x1, y1 = ring[0]
    for i in range(1, n + 1):
        x2, y2 = ring[i % n]
        if (y1 > lat) != (y2 > lat):
            x_intersect = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_intersect:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def random_point_in_vincent(rng) -> tuple:
    """Rejection-samples a (lat, lon) pair that genuinely falls inside the
    real City of Vincent boundary, instead of just a bounding box."""
    lon_min, lon_max, lat_min, lat_max = VINCENT_BBOX
    for _ in range(200):
        lon = rng.uniform(lon_min, lon_max)
        lat = rng.uniform(lat_min, lat_max)
        if _point_in_polygon(lon, lat, VINCENT_BOUNDARY_RING):
            return lat, lon
    # Should not happen in practice for a bbox this tight around a single
    # simple polygon, but fall back to the centroid rather than fail.
    return CENTER_LAT, CENTER_LON

TODAY = datetime(2026, 9, 25)  # "current" real-world date the prototype is built against

# ---------------------------------------------------------------------------
# SEASON DEFINITIONS
# ---------------------------------------------------------------------------
# A "mosquito season" runs roughly Oct -> Apr (Southern Hemisphere). We model
# three seasons: two fully complete historical seasons, and one "current"
# season that is deliberately left mid-way through (not up to TODAY) so the
# dashboard can demonstrate a genuinely in-progress operational season with
# outstanding surveillance/treatment work. Dates are illustrative only.
SEASONS = {
    "2023-24": {"start": datetime(2023, 10, 1), "end": datetime(2024, 4, 30), "complete": True},
    "2024-25": {"start": datetime(2024, 10, 1), "end": datetime(2025, 4, 30), "complete": True},
    "2025-26": {"start": datetime(2025, 10, 1), "end": datetime(2026, 4, 30), "complete": True},
    "2026-27": {"start": datetime(2026, 10, 1), "end": datetime(2027, 4, 30), "complete": False},
}
# The 2026-27 season hasn't started relative to TODAY (2026-09-25). We treat
# 2025-26 as the "current" season for demo purposes, but stop generating its
# data partway through so the dashboard has a genuinely in-progress season to
# work with (outstanding surveillance/treatment work), alongside two fully
# complete comparison seasons.
CURRENT_SEASON = "2025-26"
CURRENT_SEASON_CUTOFF = datetime(2026, 2, 10)  # data generation stops here for the current season
COMPLETE_SEASONS = ["2023-24", "2024-25"]
ALL_SEASONS = COMPLETE_SEASONS + [CURRENT_SEASON]

# Deliberately generic/obviously-fictional placeholder labels, NOT name-shaped
# ("Firstname Surname") - a name-shaped placeholder risks coincidentally
# resembling (or being mistaken for) a real person, which happened with an
# earlier version of this list and was flagged and removed. Do not replace
# these with anything that looks like a real name.
OFFICERS = ["Officer A", "Officer B", "Officer C", "Officer D", "Officer E", "Officer F"]
SYSTEM_USER = "data_generator"


def season_effective_end(season):
    if season == CURRENT_SEASON:
        return CURRENT_SEASON_CUTOFF
    return SEASONS[season]["end"]


# ---------------------------------------------------------------------------
# 1. SITES  (the unified/central location model)
# ---------------------------------------------------------------------------
SITE_TYPES = ["Saltmarsh", "Freshwater Wetland", "Tidal Drain", "Retention Basin",
              "Urban Stormwater", "Estuarine Fringe", "Rural Drain", "Parkland Lake"]
# Real site type added specifically for the Swan River bank site below (see
# "Fixed, real-world site" section) - larvae dipping/larviciding along the
# Swan River foreshore is a distinct, regularly-worked site type from the
# randomly generated inland sites above. NOTE: this string is intentionally
# duplicated in core/config.py (also named RIVER_SITE_TYPE, used by pages to
# find "the river site" e.g. for the tide indicator) rather than imported,
# since this script must stay runnable standalone via
# `python3 data/generate_sample_data.py` without the project root on
# PYTHONPATH - if you change one, change the other.
RIVER_SITE_TYPE = "Swan River Foreshore"

# Real, named public open spaces within the City of Vincent - sourced from
# vincent.wa.gov.au's own Parks & Facilities directory (community facilities,
# sportsgrounds, and parks/reserves lists) plus a Google Places lookup for
# each name's real coordinates, each one then verified with
# `_point_in_polygon` against the actual LGA boundary above (all 21 confirmed
# inside). This replaces the earlier fully-invented site names/positions so
# the prototype is easier for exec/EHOs to recognise and sanity-check.
# Site_Type is an inference of the kind of breeding habitat an EHO would
# monitor at that park (stormwater drainage/low points, retention basin,
# etc.) - NOT a claim about that park's actual drainage infrastructure, which
# would need to be confirmed against Vincent's own asset/GIS data. Hyde Park
# and Smiths Lake Reserve are the two exceptions: both have a real, permanent
# lake (Smiths Lake Reserve is a former drainage reservoir), so those are
# real breeding-habitat features, not an inference.
REAL_SITES = [
    ("Hyde Park", -31.93807, 115.86240, "Parkland Lake",
     "North Perth/Highgate. Ornamental lake at the centre of Hyde Park - a well-known permanent water body and bird habitat."),
    ("Robertson Park", -31.94126, 115.85620, "Urban Stormwater",
     "North Perth (Fitzgerald St). Public open space monitored for stormwater drainage/low-lying breeding habitat."),
    ("Braithwaite Park", -31.91968, 115.83479, "Freshwater Wetland",
     "Mount Hawthorn (Scarborough Beach Rd). Public open space monitored for low-lying/wetland-type breeding habitat."),
    ("Beatty Park Reserve", -31.93573, 115.85144, "Retention Basin",
     "North Perth. Reserve adjoining Beatty Park Leisure Centre; monitored for stormwater retention/breeding habitat."),
    ("Smiths Lake Reserve", -31.93279, 115.85074, "Parkland Lake",
     "North Perth (Kayle St/Bourke St). Former drainage reservoir; a real, permanent (murky) lake with reported mosquito activity."),
    ("Birdwood Square", -31.94286, 115.86585, "Urban Stormwater",
     "Perth/Highgate (Beaufort St). Public open space monitored for stormwater drainage/low-lying breeding habitat."),
    ("Britannia Reserve", -31.93170, 115.83744, "Freshwater Wetland",
     "Leederville/Mount Hawthorn (Bourke St). Bushland-edge reserve monitored for wetland-type breeding habitat."),
    ("Britannia Road Reserve", -31.92832, 115.83631, "Retention Basin",
     "Mount Hawthorn. Sportsground/reserve monitored for stormwater retention/breeding habitat."),
    ("Charles Veryard Reserve", -31.93108, 115.84995, "Urban Stormwater",
     "North Perth (Bourke St). Sportsground monitored for stormwater drainage/low-lying breeding habitat."),
    ("Dorrien Gardens", -31.93841, 115.85438, "Retention Basin",
     "West Perth (Britannia Rd). Sports venue monitored for stormwater retention/breeding habitat."),
    ("Forrest Park", -31.93800, 115.87473, "Retention Basin",
     "Leederville/Mount Lawley border (Walcott St/Curtis St). Large sportsground monitored for stormwater retention/breeding habitat."),
    ("Les Lilleyman Reserve", -31.91793, 115.84515, "Freshwater Wetland",
     "North Perth/Mount Hawthorn border (Gill St). Public open space monitored for wetland-type breeding habitat."),
    ("Litis Stadium", -31.92728, 115.83353, "Urban Stormwater",
     "Leederville (Britannia Rd). Sports venue monitored for stormwater drainage/breeding habitat."),
    ("Menzies Park", -31.91887, 115.83126, "Retention Basin",
     "Mount Hawthorn (Purslowe St). Sportsground monitored for stormwater retention/breeding habitat."),
    ("Woodville Reserve", -31.92708, 115.85826, "Urban Stormwater",
     "North Perth (Namur St). Public open space monitored for stormwater drainage/low-lying breeding habitat."),
    ("Weld Square", -31.94731, 115.86477, "Urban Stormwater",
     "Perth/Highgate (Beaufort St). Public open space monitored for stormwater drainage/low-lying breeding habitat."),
    ("Hyde Street Reserve", -31.93272, 115.86442, "Urban Stormwater",
     "Highgate/Mount Lawley border (Forrest St). Small reserve monitored for stormwater drainage/breeding habitat."),
    ("Stuart Street Reserve", -31.94339, 115.85874, "Urban Stormwater",
     "Perth/West Perth (Church St). Public open space monitored for stormwater drainage/breeding habitat."),
    ("Loftus Recreation Centre", -31.93520, 115.84546, "Urban Stormwater",
     "Leederville (Loftus St). Recreation centre grounds monitored for stormwater drainage/breeding habitat."),
    ("Loton Park", -31.94567, 115.87133, "Urban Stormwater",
     "Perth/Highgate (Lord St & Bulwer St). Public open space monitored for stormwater drainage/breeding habitat."),
    ("Redfern Street Reserve", -31.92263, 115.85586, "Urban Stormwater",
     "North Perth (Redfern St). Small local reserve monitored for stormwater drainage/breeding habitat."),
]
N_SITES = len(REAL_SITES)

# Region center point: the real centroid of the City of Vincent LGA boundary
# (computed from the actual boundary polygon above, WA Landgate LGATE-233).
CENTER_LAT = round(sum(_ring_lats) / len(_ring_lats), 5)
CENTER_LON = round(sum(_ring_lons) / len(_ring_lons), 5)

# Real, named location: Claisebrook Cove / Swan River foreshore, just east of
# Vincent's Highgate/East Perth boundary. Added because larvae dipping and
# larviciding along the Swan River bank is a regular, named part of the
# program (saltmarsh/estuarine species disperse well beyond the immediate
# riverbank, so it's tracked even though it sits just outside the LGA line).
RIVER_SITE_LAT, RIVER_SITE_LON = -31.9522, 115.8791

sites = []
# The N_SITES real, named City of Vincent parks/reserves defined in
# REAL_SITES above - each one's coordinates were already verified to fall
# inside the real Vincent boundary polygon.
for i, (name, lat, lon, site_type, description) in enumerate(REAL_SITES, start=1):
    site_id = f"ST-{i:03d}"
    status = rng.choice(["Active", "Active", "Active", "Active", "Inactive"], p=[0.55, 0.2, 0.15, 0.05, 0.05])
    created_dt = SEASONS["2023-24"]["start"] - timedelta(days=int(rng.integers(30, 900)))
    sites.append({
        "Site_ID": site_id,
        "Site_Name": name,
        "Site_Type": site_type,
        "Latitude": round(lat, 5),
        "Longitude": round(lon, 5),
        "Status": status,
        "Description": description,
        "Notes": "Real, named public open space (City of Vincent) - Latitude/Longitude approximate the "
                 "park/reserve's location; Site_Type is an inferred likely breeding habitat, not a confirmed "
                 "asset record. Confirm actual monitored feature/coordinates on the ground before operational use.",
        "Created_By": SYSTEM_USER,
        "Created_Date": created_dt.strftime("%Y-%m-%d"),
        "Modified_By": SYSTEM_USER,
        "Modified_Date": created_dt.strftime("%Y-%m-%d"),
    })

# Deliberately introduce a couple of realistic data-quality issues for the
# Data Quality page to detect (clearly a subset, not pervasive):
sites[3]["Latitude"] = None       # missing coordinate
sites[3]["Longitude"] = None

# Fixed, real-world site: Swan River bank at Claisebrook Cove. Larvae dipping
# and larviciding along the Swan River foreshore is a regular, named part of
# the program, so - unlike the randomly generated inland sites above - this
# one is a specific real location rather than an invented name/position.
river_site_id = f"ST-{N_SITES + 1:03d}"
sites.append({
    "Site_ID": river_site_id,
    "Site_Name": "Claisebrook Cove Foreshore (Swan River)",
    "Site_Type": RIVER_SITE_TYPE,
    "Latitude": round(RIVER_SITE_LAT, 5),
    "Longitude": round(RIVER_SITE_LON, 5),
    "Status": "Active",
    "Description": "Swan River bank/foreshore at Claisebrook Cove - tidal, brackish estuarine fringe. Regular "
                    "larvae dipping and larviciding location given its estuarine mosquito breeding habitat.",
    "Notes": "Real, named location (approximate coordinates for Claisebrook Cove) - sits just east of Vincent's "
             "Highgate/East Perth boundary; tracked because saltmarsh/estuarine species disperse well beyond "
             "the immediate riverbank.",
    "Created_By": SYSTEM_USER,
    "Created_Date": SEASONS["2023-24"]["start"].strftime("%Y-%m-%d"),
    "Modified_By": SYSTEM_USER,
    "Modified_Date": SEASONS["2023-24"]["start"].strftime("%Y-%m-%d"),
})

sites_df = pd.DataFrame(sites)
sites_df.to_csv(OUT_DIR / "sites.csv", index=False)


# ---------------------------------------------------------------------------
# 2. TRAP SITES  (a trap is deployed AT a site; a site may host >1 trap)
# ---------------------------------------------------------------------------
TRAP_TYPES = ["EVS (CO2-baited)", "BG-Sentinel", "CDC Light Trap", "Gravid Trap"]

trap_sites = []
trap_counter = 1
active_site_ids = sites_df.loc[sites_df["Status"] == "Active", "Site_ID"].tolist()
# Give most active sites one trap; a few get two traps (different trap types)
for site_id in active_site_ids:
    n_traps = 2 if rng.random() < 0.2 else 1
    for _ in range(n_traps):
        trap_id = f"TRP-{trap_counter:03d}"
        trap_counter += 1
        trap_sites.append({
            "Trap_ID": trap_id,
            "Site_ID": site_id,
            "Trap_Type": rng.choice(TRAP_TYPES),
            "Trap_Status": "Active",
            "Install_Date": (SEASONS["2023-24"]["start"] - timedelta(days=int(rng.integers(10, 400)))).strftime("%Y-%m-%d"),
            "Notes": "",
            "Created_By": SYSTEM_USER,
            "Created_Date": SEASONS["2023-24"]["start"].strftime("%Y-%m-%d"),
        })
trap_sites_df = pd.DataFrame(trap_sites)
trap_sites_df.to_csv(OUT_DIR / "trap_sites.csv", index=False)


# ---------------------------------------------------------------------------
# 3. SPECIES REFERENCE
# ---------------------------------------------------------------------------
# Real species and ecology data for the mosquitoes actually relevant to the
# Perth metropolitan area / City of Vincent, sourced from WA Department of
# Health public guidance:
#   - "Common mosquitoes in Western Australia" - health.wa.gov.au/Articles/A_E/
#     Common-mosquitoes-in-Western-Australia (breeding habitat, biting
#     behaviour, disease significance quoted/paraphrased directly from this
#     page for each species below)
#   - "South-West adult mosquito photographic key" (WA Health, PDF) - broader
#     identification reference covering additional local species; linked from
#     the Species Reference page for officers who need to ID a specimen beyond
#     the six operationally-tracked species below.
# Aedes notoscriptus is the dominant species in an inner-urban council like
# Vincent (container/backyard breeder); Aedes vigilax/camptorhynchus are
# included because they disperse well beyond their saltmarsh/estuarine
# breeding sites (WA Health: Ae. vigilax "can travel tens of kilometres"),
# which is also why the Swan River foreshore site below is tracked even
# though it sits just outside the LGA boundary.
species_reference = [
    {
        "Species_Code": "AEDNOT", "Scientific_Name": "Aedes notoscriptus", "Common_Name": "Container Mosquito",
        "Typical_Breeding_Habitat": "Clean water within the domestic environment; artificial containers such as "
                                     "water ponds, bird baths, pet water bowls, gutters, pot plant drip trays, leaf axils.",
        "Biting_Behaviour": "Vicious biter; active dawn and dusk, occasionally at night and daytime; prefers shade.",
        "Seasonal_Characteristics": "Present year-round in the Perth metro area; breeds readily in backyard "
                                     "containers after rain or irrigation, so numbers track closely with resident "
                                     "watering/container habits as much as season.",
        "Vector_Significance": "Ross River virus (RRV).",
        "Notes": "The dominant species in inner-urban council areas such as Vincent - most resident complaints "
                 "and backyard breeding-site inspections relate to this species. Source: WA Dept of Health, "
                 "'Common mosquitoes in Western Australia'.",
    },
    {
        "Species_Code": "AEDVIG", "Scientific_Name": "Aedes vigilax", "Common_Name": "Saltmarsh Mosquito",
        "Typical_Breeding_Habitat": "Coastal saltmarshes and brackish swamps.",
        "Biting_Behaviour": "Vicious biter; bites at all times of day and night.",
        "Seasonal_Characteristics": "Builds after tidal inundation of saltmarsh in the warmer months; a strong "
                                     "flier that can disperse tens of kilometres from its breeding site, so it is "
                                     "tracked well beyond the immediate saltmarsh/river fringe.",
        "Vector_Significance": "Ross River virus (RRV) and Barmah Forest virus (BFV).",
        "Notes": "Source: WA Dept of Health, 'Common mosquitoes in Western Australia' and WA Health mosquito "
                 "management plan template (2020).",
    },
    {
        "Species_Code": "AEDCAM", "Scientific_Name": "Aedes camptorhynchus", "Common_Name": "Southern Saltmarsh Mosquito",
        "Typical_Breeding_Habitat": "Coastal or inland brackish water; tidal saltmarshes, especially sites with samphire.",
        "Biting_Behaviour": "Vicious biter; bites at all times of day and night.",
        "Seasonal_Characteristics": "Often the dominant species in WA trap collections between September and "
                                     "December, associated with saltmarsh/estuarine tidal inundation.",
        "Vector_Significance": "Ross River virus (RRV) and Barmah Forest virus (BFV).",
        "Notes": "Relevant to the Swan River foreshore site given its estuarine/brackish habitat. Source: WA Dept "
                 "of Health, 'Common mosquitoes in Western Australia' and WA Health mosquito management plan "
                 "template (2020).",
    },
    {
        "Species_Code": "CULANN", "Scientific_Name": "Culex annulirostris", "Common_Name": "Common Banded Mosquito",
        "Typical_Breeding_Habitat": "Permanent/semi-permanent freshwater bodies; also mildly brackish water, "
                                     "man-made lakes and containers.",
        "Biting_Behaviour": "Active at dawn, dusk and night.",
        "Seasonal_Characteristics": "Builds through summer in warm, wet conditions; common in retention basins "
                                     "and freshwater wetlands.",
        "Vector_Significance": "Murray Valley encephalitis (MVE), West Nile virus Kunjin strain (WNVKUN), Ross "
                                "River virus (RRV) and Barmah Forest virus (BFV).",
        "Notes": "Source: WA Dept of Health, 'Common mosquitoes in Western Australia'.",
    },
    {
        "Species_Code": "CULQUI", "Scientific_Name": "Culex quinquefasciatus", "Common_Name": "Southern House Mosquito",
        "Typical_Breeding_Habitat": "Clean or polluted water in the domestic environment and artificial containers "
                                     "(stormwater, blocked drains, catch basins).",
        "Biting_Behaviour": "Active at dawn, dusk and night.",
        "Seasonal_Characteristics": "Present year-round, closely associated with urban stormwater infrastructure.",
        "Vector_Significance": "A significant nuisance/pest species but a poor disease vector in WA.",
        "Notes": "Source: WA Dept of Health, 'Common mosquitoes in Western Australia'.",
    },
    {
        "Species_Code": "ANOANN", "Scientific_Name": "Anopheles annulipes", "Common_Name": "Common Anopheles Mosquito",
        "Typical_Breeding_Habitat": "Permanent and semi-permanent fresh water.",
        "Biting_Behaviour": "Night-time; occasionally bites during the day.",
        "Seasonal_Characteristics": "Present alongside Culex species in freshwater wetlands and drains.",
        "Vector_Significance": "None - not considered a disease vector in WA.",
        "Notes": "Included for identification completeness. Source: WA Dept of Health, 'Common mosquitoes in "
                 "Western Australia'.",
    },
    {
        "Species_Code": "OTHER", "Scientific_Name": "Other / unidentified", "Common_Name": "Other species",
        "Typical_Breeding_Habitat": "Not applicable.", "Biting_Behaviour": "Not applicable.",
        "Seasonal_Characteristics": "Not applicable.", "Vector_Significance": "Not applicable.",
        "Notes": "Catch-all for low-count incidental species not separately identified. WA's South-West adult "
                 "mosquito photographic key (health.wa.gov.au) lists many further species present in the region "
                 "(e.g. Culex globocoxitus, Culex molestus, Coquillettidia sp. nr. linealis) for officers "
                 "identifying a specimen that doesn't match the six species tracked above.",
    },
]
species_df = pd.DataFrame(species_reference)
species_df.to_csv(OUT_DIR / "species_reference.csv", index=False)
SPECIES_CODES = [s for s in species_df["Species_Code"].tolist() if s != "OTHER"]

# Relative abundance weighting per species (drives realistic composition).
SPECIES_WEIGHTS = {"AEDNOT": 0.15, "AEDVIG": 0.30, "AEDCAM": 0.12, "CULANN": 0.25, "CULQUI": 0.13, "ANOANN": 0.05}

# Assign each site a dominant-species tendency based on its type, so results
# are internally consistent (saltmarsh sites -> Aedes vigilax, urban drains ->
# Culex quinquefasciatus, the Swan River foreshore -> Aedes camptorhynchus etc.)
SITE_TYPE_SPECIES_BIAS = {
    "Saltmarsh": "AEDVIG", "Estuarine Fringe": "AEDVIG",
    "Freshwater Wetland": "CULANN", "Parkland Lake": "CULANN",
    "Tidal Drain": "AEDCAM", "Retention Basin": "CULANN",
    "Urban Stormwater": "CULQUI", "Rural Drain": "CULANN",
    RIVER_SITE_TYPE: "AEDCAM",
}


# ---------------------------------------------------------------------------
# 4. PRODUCTS
# ---------------------------------------------------------------------------
# PRD-01 and PRD-02 are REAL, currently APVMA-registered S-methoprene
# larvicides (ProLink Pellets, ProLink XR Briquets) - the two products the
# program will primarily be using, per direct advice, and the ONLY active
# products in this list (the fictional adulticide "MosquiZap ULV" and the
# real secondary/knockdown product "VectoBac G" were both removed from the
# dashboard on request - the program is tracking these two S-methoprene
# larvicides only). Rate/duration data for both is sourced directly from the
# real, current APVMA-approved product labels (supplied directly by the
# person and read in full) rather than retailer pages or third-party plans -
# see each product's Label_Reference and Rate_Basis for exact detail and the
# APVMA approval number. PRD-05 (a fictional withdrawn product) is kept only
# to exercise Withdrawn-status handling in the app; it is not real.
#
# Duration_Min_Days/Duration_Max_Days are the numeric form of Duration_Of_
# Control, added so the Treatments page can calculate an estimated re-dose
# due date (Rate_Min -> Duration_Min_Days, Rate_Max -> Duration_Max_Days;
# interpolated for a rate in between). Where sources disagree (see Notes),
# the more conservative figure is used as the number that actually drives a
# due-date calculation - the wider claim stays visible in Duration_Of_Control
# text and Notes so it's not hidden, just not the one silently trusted.
products = [
    {"Product_ID": "PRD-01", "Product_Name": "ProLink Pellets", "Active_Ingredient": "(S)-methoprene 40 g/kg "
                    "(Group 7A insecticide / insect growth regulator)",
     "Formulation": "Pellet (ready-to-use, 10 kg net contents)",
     "Application_Method": "Ground equipment (broadcast/granular spreader) for good, even coverage at the rates "
                            "below; can also be applied aerially (fixed-wing/helicopter with granular spreaders) "
                            "at the same 3-4 kg/ha rates, checked frequently against area flown.",
     "Rate_Min": 3.0, "Rate_Max": 4.0, "Rate_Unit": "kg/ha (ground or aerial broadacre application)",
     "Rate_Basis": "Per the APVMA-approved label: use 3 kg/ha for temporary water sites (freshwater/salt "
                   "marshes, mangrove swamps, estuarine areas, woodland pools, natural water-holding features) "
                   "where water is shallow (<30cm), clean, and larval counts are low (<10/dip). Use 4 kg/ha for "
                   "permanent water sites (ornamental ponds/pools, birdbaths, troughs, gutters, other artificial "
                   "or manmade water-holding depressions, tree holes, cesspools/septic tanks, sewage settling "
                   "ponds) where water is deep (>30cm), rich in organic matter/sediment, larval counts are high "
                   "(>10/dip), or the target is specifically Culex sitiens. Restraint: DO NOT use in areas "
                   "grazed by livestock. SEPARATE hand-treatment method for small containers only (water tanks, "
                   "pot-plant trays, tyres, gutters, catch basins) uses a different rate: 1 pellet per L or m2 "
                   "for control up to 3 months, 3 pellets per L or m2 for control up to 6 months - not the rate "
                   "modelled by this row; use the label directly if hand-treating a small container.",
     "Duration_Of_Control": "Label: 'release (S)-methoprene for at least 30 days' once submerged, for the "
                            "broadacre kg/ha rate above (this is the figure driving the re-dose calculator - a "
                            "conservative floor, not a fixed window, since the label gives no upper bound for "
                            "this application method). The separate small-container pellet-count method can "
                            "achieve up to 3-6 months (see Rate_Basis) but is not what this row models.",
     "Duration_Min_Days": 30, "Duration_Max_Days": 30,
     "Status": "Active",
     "Label_Reference": "ProLink Pellets APVMA-approved label, Approval No. 58064/1/0705 (Wellmark "
                         "International; distributed in Australia by Pacific BioLogics Pty Ltd, Kippa Ring QLD, "
                         "(07) 3283 5077) - label supplied directly by the person and read in full.",
     "Notes": "Primary larvicide - standing water, catch basins, ponds, and drains in parks/reserves (broadacre "
              "kg/ha method). The earlier 'confirm against APVMA' caveat has been resolved by reading the actual "
              "label directly - approval number above can still be cross-checked on APVMA's PubCRIS database "
              "(portal.apvma.gov.au/pubcris) if desired, though PubCRIS is a live keyword search tool, not "
              "fetchable by approval number directly. NOTE: the re-dose due date now uses the real, more "
              "conservative 30-day label figure (previously an incorrect 90-180 day estimate) - this will surface "
              "re-dose reminders much sooner than before."},
    {"Product_ID": "PRD-02", "Product_Name": "ProLink XR Briquets",
     "Active_Ingredient": "(S)-methoprene 18 g/kg, dry weight basis (Group 7A insecticide / insect growth regulator)",
     "Formulation": "Extended-release briquette (100 briquets per 3.66 kg dry-weight carton)",
     "Application_Method": "Hand placement - float/place briquette(s) directly in water. In soft mud/loose "
                            "sediment, place in a mesh bag tied to a stake so the briquet doesn't sink and to "
                            "allow monitoring of breakdown rate. Not effective where briquets can be flushed out "
                            "of the site - must be anchored.",
     "Rate_Min": 10.0, "Rate_Max": 20.0, "Rate_Unit": "m2 of water surface per 1 briquet",
     "Rate_Basis": "Per the APVMA-approved label: 1 briquet per 20 m2 where water is shallow (<30cm), clean, and "
                   "larval counts are low (<10/dip) - labelled specifically for Ochlerotatus/Aedes vigilax. "
                   "1 briquet per 10 m2 where water is deep (>30cm), rich in organic matter/sediment, or larval "
                   "counts are high (>10/dip), and for all other mosquito species regardless of depth. Separately, "
                   "rainwater tanks (including potable): 1 briquet per 5,000 L, retreated every 6-12 months. "
                   "Restraint: DO NOT use in areas grazed by livestock.",
     "Duration_Of_Control": "Up to 150 days, or the rest of the mosquito control season if shorter (per label: "
                            "'one application should last the entire mosquito control season, or at least 150 "
                            "days, whichever is shorter'). Should be applied before/at the start of the season; "
                            "can be pre-placed in dry sites before flooding or rain.",
     "Duration_Min_Days": 150, "Duration_Max_Days": 150,
     "Status": "Active",
     "Label_Reference": "ProLink XR Briquets APVMA-approved label, Approval No. 58061/100/0505 (Wellmark "
                         "International; distributed in Australia by Pacific BioLogics Pty Ltd, Kippa Ring QLD, "
                         "(07) 3283 5077) - label supplied directly by the person and read in full.",
     "Notes": "Primary larvicide for chronic/semi-permanent breeding sites - dams, storm drains, catch basins, "
              "roadside ditches, ornamental ponds/pools, cesspools/septic tanks, sewage settling ponds, abandoned "
              "pools, manmade depressions, freshwater/salt marshes, mangrove swamps, woodland pools, flood "
              "plains, and rainwater tanks. Label explicitly lists control of Aedes, Anopheles, Culex and "
              "Ochlerotatus spp. (Ochlerotatus vigilax = the current name Aedes vigilax was reclassified from/to; "
              "same species). No effect on mosquitoes already at pupal/adult stage at time of treatment. This is "
              "now sourced directly from the real APVMA label (previously an approximation from field practice) "
              "- CONFIRM against the current label before operational use, as labels are periodically reissued."},
    {"Product_ID": "PRD-05", "Product_Name": "OldStock Larvicide (fictional)", "Active_Ingredient": "Fictional-Discontinued-Compound",
     "Formulation": "Granule",
     "Application_Method": "Granular - hand/spreader", "Rate_Min": 4.0, "Rate_Max": 4.0, "Rate_Unit": "kg/ha",
     "Rate_Basis": "", "Duration_Of_Control": "N/A",
     "Duration_Min_Days": 0, "Duration_Max_Days": 0,
     "Status": "Withdrawn", "Label_Reference": "SAMPLE DATA ONLY - NOT FOR OPERATIONAL USE",
     "Notes": "Fictional withdrawn product retained for historical treatment records / Withdrawn-status testing only."},
]
products_df = pd.DataFrame(products)
products_df.to_csv(OUT_DIR / "products.csv", index=False)
# Convenience column used only for simulating realistic sample treatment
# quantities below (Application_Rate = midpoint of the labelled range) - not
# written to products.csv, since the real rate is a range, not one number.
products_df["_Rate_Mid"] = (products_df["Rate_Min"].astype(float) + products_df["Rate_Max"].astype(float)) / 2


def compute_quantity_used(rate_mid, rate_unit, area_ha):
    """Rough sample-data proxy for how much product a completed treatment
    used, given the product's rate and the treated area. Handles the two
    real rate structures now in products.csv (see the products list above),
    each recorded in the unit an officer would actually count/measure in the
    field (see core.config.QUANTITY_USED_UNITS) rather than the rate's own
    unit:
      - "...kg/ha..." (ProLink Pellets broadacre rate): quantity = rate *
        area_ha, converted kg -> GRAMS and rounded to a whole gram.
      - "...per 1 briquet" (ProLink XR Briquets - rate is AREA COVERED PER
        BRIQUET, i.e. inverse of the other products: a BIGGER rate number
        means FEWER briquets needed): briquets = ceil((area_ha * 10,000
        m2/ha) / rate) - a whole number, since you can't place half a
        briquet (matches the Dosage Calculator's rounding).
      - anything else (the fictional withdrawn placeholder): falls back to a
        generic rate * area proxy for backward compatibility only.
    """
    if rate_mid is None:
        return ""
    rate_unit_str = str(rate_unit)
    if "ha" in rate_unit_str:
        kg = float(rate_mid) * area_ha
        return round(kg * 1000)  # grams, whole number
    if "briquet" in rate_unit_str:
        area_m2 = area_ha * 10000
        return math.ceil(area_m2 / float(rate_mid))  # whole briquets
    return round(float(rate_mid) * max(area_ha * 100, 1) / 10, 1)  # generic fallback proxy


# ---------------------------------------------------------------------------
# 5. ENVIRONMENTAL DATA (daily, region-wide - simplified for prototype)
# ---------------------------------------------------------------------------
env_rows = []
all_days_start = SEASONS["2023-24"]["start"]
all_days_end = season_effective_end(CURRENT_SEASON)
n_days = (all_days_end - all_days_start).days + 1
env_id = 1
# Smooth seasonal rainfall/temperature shape + noise, and a simple tidal cycle
for d in range(n_days):
    date = all_days_start + timedelta(days=d)
    # crude seasonal temperature curve (Southern Hemisphere summer peak ~Jan)
    day_of_season = (date - datetime(date.year if date.month >= 10 else date.year - 1, 10, 1)).days
    seasonal_phase = np.sin((day_of_season / 210.0) * np.pi)  # 0..1..0 across ~Oct-Apr
    temp_max = 22 + 10 * max(seasonal_phase, 0) + rng.normal(0, 2)
    temp_min = temp_max - rng.uniform(6, 10)
    rainfall = max(0, rng.exponential(2.0) - 1.0) if rng.random() < 0.3 else 0.0
    tidal = 0.8 + 0.6 * np.sin(2 * np.pi * d / 14.0) + rng.normal(0, 0.05)
    env_rows.append({
        "Env_ID": f"ENV-{env_id:05d}",
        "Date": date.strftime("%Y-%m-%d"),
        "Site_ID": "",  # region-wide reading; left blank (see README on future site-level feeds)
        "Rainfall_mm": round(float(rainfall), 1),
        "Temp_Min_C": round(float(temp_min), 1),
        "Temp_Max_C": round(float(temp_max), 1),
        "Tidal_Level_m": round(float(tidal), 2),
        "Notes": "",
    })
    env_id += 1
env_df = pd.DataFrame(env_rows)
env_df.to_csv(OUT_DIR / "environmental_data.csv", index=False)
env_df["_date_dt"] = pd.to_datetime(env_df["Date"])


def rainfall_lookup(date):
    row = env_df.loc[env_df["_date_dt"] == pd.Timestamp(date)]
    return float(row["Rainfall_mm"].iloc[0]) if len(row) else 0.0


# ---------------------------------------------------------------------------
# 6. SURVEILLANCE EVENTS + RESULTS
#    Weekly deployment/retrieval cycle per trap across each season.
# ---------------------------------------------------------------------------
surv_events = []
surv_results = []
event_counter = 1
result_counter = 1

# Pre-select a handful of "persistent hotspot" sites that will get an elevated
# baseline abundance all season (for the Hotspot Identification feature),
# distinct from sites that just have one isolated spike.
hotspot_persistent_sites = set(rng.choice(active_site_ids, size=3, replace=False))
remaining_for_spike = [s for s in active_site_ids if s not in hotspot_persistent_sites]
hotspot_spike_sites = set(rng.choice(remaining_for_spike, size=2, replace=False))

for season in ALL_SEASONS:
    season_start = SEASONS[season]["start"]
    season_end = season_effective_end(season)
    n_weeks = ((season_end - season_start).days // 7)
    # The seasonal abundance SHAPE is always modelled across the FULL season
    # length (Oct->Apr), even when a season's data generation is truncated
    # early (the current in-progress season). Otherwise a truncated season's
    # sine curve would be artificially compressed and falsely show abundance
    # tapering off near the cutoff date, when in reality a mid-season export
    # simply hasn't reached the seasonal peak/decline yet.
    full_season_end = SEASONS[season]["end"]
    full_n_weeks = ((full_season_end - season_start).days // 7)
    for trap in trap_sites:
        trap_id = trap["Trap_ID"]
        site_id = trap["Site_ID"]
        site_row = sites_df.loc[sites_df["Site_ID"] == site_id].iloc[0]
        site_type = site_row["Site_Type"]
        bias_species = SITE_TYPE_SPECIES_BIAS.get(site_type, "CULANN")
        is_persistent_hotspot = site_id in hotspot_persistent_sites
        is_spike_hotspot = site_id in hotspot_spike_sites
        # random single-trap-night spike week for spike-hotspot sites
        spike_week = int(rng.integers(2, max(n_weeks - 2, 3))) if is_spike_hotspot else -1

        for w in range(n_weeks):
            deploy_date = season_start + timedelta(days=7 * w)
            retrieve_date = deploy_date + timedelta(days=2)  # standard 2-night set

            event_id = f"EVT-{event_counter:05d}"
            event_counter += 1

            # Trap effort outcome
            outcome_roll = rng.random()
            if outcome_roll < 0.04:
                trap_status, sample_validity = "Missing", "N/A"
            elif outcome_roll < 0.08:
                trap_status, sample_validity = "Failed - Equipment/Battery", "Invalid"
            elif outcome_roll < 0.11:
                trap_status, sample_validity = "Partial", "Valid"
            else:
                trap_status, sample_validity = "Successful", "Valid"

            # Deliberately inject one data-quality problem: a retrieval date
            # before deployment date, on a single early record only.
            inject_bad_dates = (event_counter == 42)

            surv_events.append({
                "Event_ID": event_id,
                "Trap_ID": trap_id,
                "Site_ID": site_id,
                "Season": season,
                "Deployment_DateTime": deploy_date.strftime("%Y-%m-%d %H:%M"),
                "Retrieval_DateTime": (deploy_date - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
                                       if inject_bad_dates else retrieve_date.strftime("%Y-%m-%d %H:%M"),
                "Trap_Type": trap["Trap_Type"],
                "Trap_Status": trap_status,
                "Sample_Validity": sample_validity,
                "Officer": rng.choice(OFFICERS),
                "Notes": "",
                "Created_By": SYSTEM_USER,
                "Created_Date": retrieve_date.strftime("%Y-%m-%d"),
            })

            if trap_status in ("Missing",):
                continue  # no results possible

            # Seasonal abundance shape (build-up mid-season, tapering later),
            # always modelled against the full season length - see note above.
            day_of_season = (deploy_date - season_start).days
            seasonal_phase = max(np.sin((day_of_season / (full_n_weeks * 7 + 1)) * np.pi), 0.05)
            rain_boost = 1.0 + min(rainfall_lookup(deploy_date) / 20.0, 1.5)

            baseline = 8 * seasonal_phase * rain_boost
            if is_persistent_hotspot:
                baseline *= 3.0
            if is_spike_hotspot and w == spike_week:
                baseline *= 6.0

            if trap_status == "Partial":
                baseline *= 0.5  # partial sampling => lower catch, must not be treated as "low abundance"

            total_catch = max(0, int(rng.poisson(baseline)))

            if sample_validity == "Invalid" or trap_status == "Missing":
                continue  # invalid samples excluded from abundance stats entirely

            if total_catch == 0:
                continue

            # split total_catch across species using weighted bias toward the
            # site's dominant species
            weights = SPECIES_WEIGHTS.copy()
            weights[bias_species] = weights.get(bias_species, 0.1) + 0.45
            codes = list(weights.keys())
            probs = np.array([weights[c] for c in codes])
            probs = probs / probs.sum()
            counts = rng.multinomial(total_catch, probs)
            for code, cnt in zip(codes, counts):
                if cnt <= 0:
                    continue
                surv_results.append({
                    "Result_ID": f"RES-{result_counter:06d}",
                    "Event_ID": event_id,
                    "Species_Code": code,
                    "Number_Collected": int(cnt),
                    "Notes": "",
                })
                result_counter += 1

# Inject one clearly-flagged negative count and one missing-species row for
# the Data Quality page to surface (kept to a small, traceable handful):
if len(surv_results) > 100:
    surv_results[50]["Number_Collected"] = -3
    surv_results[75]["Species_Code"] = ""

surv_events_df = pd.DataFrame(surv_events)
surv_results_df = pd.DataFrame(surv_results)
surv_events_df.to_csv(OUT_DIR / "surveillance_events.csv", index=False)
surv_results_df.to_csv(OUT_DIR / "surveillance_results.csv", index=False)


# ---------------------------------------------------------------------------
# 7. TREATMENTS
# ---------------------------------------------------------------------------
TREATMENT_TYPES = ["Larvicide Application", "Adulticide Application", "Source Reduction / Habitat Modification"]
treatments = []
treatment_counter = 1

for season in ALL_SEASONS:
    season_start = SEASONS[season]["start"]
    season_end = season_effective_end(season)
    n_treatments = int(rng.integers(16, 24))
    for _ in range(n_treatments):
        site_id = rng.choice(active_site_ids)
        planned_date = season_start + timedelta(days=int(rng.integers(0, max((season_end - season_start).days, 1))))
        treatment_type = rng.choice(TREATMENT_TYPES, p=[0.55, 0.30, 0.15])
        product_id = None
        application_method = ""
        approved_rate = None
        rate_unit = ""
        if treatment_type != "Source Reduction / Habitat Modification":
            candidate_products = products_df[products_df["Status"] == "Active"]
            prod = candidate_products.sample(1, random_state=int(rng.integers(0, 1_000_000))).iloc[0]
            product_id = prod["Product_ID"]
            application_method = prod["Application_Method"]
            approved_rate = prod["_Rate_Mid"]  # midpoint of the labelled Rate_Min-Rate_Max range
            rate_unit = prod["Rate_Unit"]

        status_roll = rng.random()
        if season != CURRENT_SEASON or planned_date < CURRENT_SEASON_CUTOFF - timedelta(days=10):
            if status_roll < 0.08:
                status = "Cancelled"
            else:
                status = "Completed"
        else:
            # near/after the current-season cutoff: mix of planned/scheduled/completed
            if status_roll < 0.35:
                status = "Planned"
            elif status_roll < 0.6:
                status = "Scheduled"
            elif status_roll < 0.92:
                status = "Completed"
            else:
                status = "Cancelled"

        area_ha = round(float(rng.uniform(0.5, 12.0)), 2)
        cancelled_reason = ""
        actual_date = ""
        quantity_used = ""
        if status == "Completed":
            actual_date = (planned_date + timedelta(days=int(rng.integers(0, 3)))).strftime("%Y-%m-%d")
            if approved_rate is not None:
                quantity_used = compute_quantity_used(approved_rate, rate_unit, area_ha)
        elif status == "Cancelled":
            cancelled_reason = rng.choice([
                "Site access restricted", "Weather unsuitable", "Insufficient surveillance trigger",
                "Resourcing/staff availability", "Product unavailable",
            ])

        treatments.append({
            "Treatment_ID": f"TRT-{treatment_counter:05d}",
            "Site_ID": site_id,
            "Season": season,
            "Planned_Date": planned_date.strftime("%Y-%m-%d"),
            "Treatment_Date": actual_date,
            "Treatment_Status": status,
            "Treatment_Type": treatment_type,
            "Product_ID": product_id if product_id else "",
            "Application_Method": application_method,
            "Application_Rate": approved_rate if approved_rate is not None else "",
            "Rate_Unit": rate_unit,
            "Area_Treated_Ha": area_ha if treatment_type != "Source Reduction / Habitat Modification" else "",
            "Quantity_Used": quantity_used,
            "Operator": rng.choice(OFFICERS),
            "Reason": rng.choice([
                "Surveillance threshold exceeded", "Complaint-triggered inspection",
                "Routine scheduled treatment", "Follow-up after prior treatment",
            ]),
            "Cancelled_Reason": cancelled_reason,
            "Notes": "",
            "Created_By": SYSTEM_USER,
            "Created_Date": planned_date.strftime("%Y-%m-%d"),
            "Modified_By": SYSTEM_USER,
            "Modified_Date": (actual_date if actual_date else planned_date.strftime("%Y-%m-%d")),
        })
        treatment_counter += 1

# Ensure the persistent-hotspot sites get several completed treatments across
# the season so the Treatment Effectiveness page has real before/after data
for site_id in hotspot_persistent_sites:
    for season in ALL_SEASONS:
        season_start = SEASONS[season]["start"]
        mid = season_start + timedelta(days=int(rng.integers(40, 100)))
        prod = products_df[products_df["Status"] == "Active"].sample(1, random_state=int(rng.integers(0, 1_000_000))).iloc[0]
        area_ha = round(float(rng.uniform(2.0, 8.0)), 2)
        treatments.append({
            "Treatment_ID": f"TRT-{treatment_counter:05d}",
            "Site_ID": site_id, "Season": season,
            "Planned_Date": mid.strftime("%Y-%m-%d"), "Treatment_Date": mid.strftime("%Y-%m-%d"),
            "Treatment_Status": "Completed", "Treatment_Type": "Larvicide Application",
            "Product_ID": prod["Product_ID"], "Application_Method": prod["Application_Method"],
            "Application_Rate": prod["_Rate_Mid"], "Rate_Unit": prod["Rate_Unit"],
            "Area_Treated_Ha": area_ha,
            "Quantity_Used": compute_quantity_used(prod["_Rate_Mid"], prod["Rate_Unit"], area_ha),
            "Operator": rng.choice(OFFICERS), "Reason": "Surveillance threshold exceeded",
            "Cancelled_Reason": "", "Notes": "Targeted treatment at known persistent hotspot.",
            "Created_By": SYSTEM_USER, "Created_Date": mid.strftime("%Y-%m-%d"),
            "Modified_By": SYSTEM_USER, "Modified_Date": mid.strftime("%Y-%m-%d"),
        })
        treatment_counter += 1

# Inject a couple of clean data-quality issues: zero area, missing product for
# a "Completed" larvicide treatment, missing operator
treatments_df = pd.DataFrame(treatments)
if len(treatments_df) > 5:
    treatments_df.loc[treatments_df.index[3], "Area_Treated_Ha"] = 0
    treatments_df.loc[treatments_df.index[5], "Operator"] = ""
    idx_completed_larv = treatments_df[(treatments_df["Treatment_Status"] == "Completed") &
                                        (treatments_df["Treatment_Type"] == "Larvicide Application")].index
    if len(idx_completed_larv) > 0:
        treatments_df.loc[idx_completed_larv[0], "Product_ID"] = ""
treatments_df.to_csv(OUT_DIR / "treatments.csv", index=False)


# ---------------------------------------------------------------------------
# 8. COMPLAINTS
# ---------------------------------------------------------------------------
COMPLAINT_CATEGORIES = ["Biting nuisance", "Swarming/adult numbers", "Suspected breeding site",
                         "Standing water on property", "General enquiry"]
INVESTIGATION_STATUSES = ["Received", "Under Investigation", "Site Inspected", "Closed"]

complaints = []
complaint_counter = 1
for season in ALL_SEASONS:
    season_start = SEASONS[season]["start"]
    season_end = season_effective_end(season)
    n_complaints = int(rng.integers(20, 35))
    for _ in range(n_complaints):
        date_received = season_start + timedelta(days=int(rng.integers(0, max((season_end - season_start).days, 1))))
        # Bias complaints toward hotspot sites, but allow general ones without a Site_ID
        if rng.random() < 0.65:
            site_id = rng.choice(list(hotspot_persistent_sites) + list(hotspot_spike_sites) + active_site_ids[:6])
            approx_lat = sites_df.loc[sites_df["Site_ID"] == site_id, "Latitude"].iloc[0]
            approx_lon = sites_df.loc[sites_df["Site_ID"] == site_id, "Longitude"].iloc[0]
        else:
            site_id = ""
            approx_lat, approx_lon = random_point_in_vincent(rng)
            approx_lat, approx_lon = round(approx_lat, 5), round(approx_lon, 5)
        status = rng.choice(INVESTIGATION_STATUSES, p=[0.1, 0.15, 0.15, 0.6])
        complaints.append({
            "Complaint_ID": f"CMP-{complaint_counter:05d}",
            "Date_Received": date_received.strftime("%Y-%m-%d"),
            "Season": season,
            "Site_ID": site_id,
            "Approx_Latitude": approx_lat,
            "Approx_Longitude": approx_lon,
            "Category": rng.choice(COMPLAINT_CATEGORIES),
            "Description": "Resident-reported mosquito nuisance (sample description).",
            "Investigation_Status": status,
            "Outcome": "Inspection scheduled" if status != "Closed" else rng.choice(
                ["No breeding found", "Breeding site identified and treated", "Referred to property owner"]),
            "Officer": rng.choice(OFFICERS),
            "Created_By": SYSTEM_USER,
            "Created_Date": date_received.strftime("%Y-%m-%d"),
        })
        complaint_counter += 1
complaints_df = pd.DataFrame(complaints)
complaints_df.to_csv(OUT_DIR / "complaints.csv", index=False)


# ---------------------------------------------------------------------------
# 9. SITE OBSERVATIONS
# ---------------------------------------------------------------------------
OBS_CATEGORIES = ["Standing water observed", "Access issue", "Breeding habitat present",
                   "Treatment access restricted", "Environmental change", "Equipment issue",
                   "Follow-up required"]
observations = []
obs_counter = 1
for season in ALL_SEASONS:
    season_start = SEASONS[season]["start"]
    season_end = season_effective_end(season)
    n_obs = int(rng.integers(15, 25))
    for _ in range(n_obs):
        site_id = rng.choice(active_site_ids)
        obs_date = season_start + timedelta(days=int(rng.integers(0, max((season_end - season_start).days, 1))))
        observations.append({
            "Observation_ID": f"OBS-{obs_counter:05d}",
            "Site_ID": site_id,
            "Season": season,
            "DateTime": obs_date.strftime("%Y-%m-%d %H:%M"),
            "Officer": rng.choice(OFFICERS),
            "Observation_Category": rng.choice(OBS_CATEGORIES),
            "Notes": "Sample field observation note.",
            "Created_By": SYSTEM_USER,
            "Created_Date": obs_date.strftime("%Y-%m-%d"),
        })
        obs_counter += 1
observations_df = pd.DataFrame(observations)
observations_df.to_csv(OUT_DIR / "site_observations.csv", index=False)


# ---------------------------------------------------------------------------
# 10. USERS (operators) - minimal, for prototype attribution only
# ---------------------------------------------------------------------------
users_df = pd.DataFrame([
    {"User_ID": f"U{idx+1:02d}", "Name": name, "Role": rng.choice(["Environmental Health Officer", "Senior EHO", "Team Leader"])}
    for idx, name in enumerate(OFFICERS)
])
users_df.to_csv(OUT_DIR / "users.csv", index=False)


# ---------------------------------------------------------------------------
# 11. ACTION THRESHOLDS (SAMPLE ONLY - configurable, not scientific/regulatory)
# ---------------------------------------------------------------------------
thresholds = [
    {"Threshold_ID": "THR-01", "Scope": "Default", "Site_ID": "", "Species_Code": "",
     "Trap_Type": "", "Metric": "Mosquitoes_Per_Trap_Night",
     "Normal_Max": 10, "Elevated_Max": 30, "Notes": "SAMPLE THRESHOLD - not scientifically or regulatorily validated."},
    {"Threshold_ID": "THR-02", "Scope": "Species", "Site_ID": "", "Species_Code": "AEDVIG",
     "Trap_Type": "", "Metric": "Mosquitoes_Per_Trap_Night",
     "Normal_Max": 8, "Elevated_Max": 25, "Notes": "SAMPLE THRESHOLD - Aedes vigilax (nuisance/vector interest species)."},
    {"Threshold_ID": "THR-03", "Scope": "Species", "Site_ID": "", "Species_Code": "CULANN",
     "Trap_Type": "", "Metric": "Mosquitoes_Per_Trap_Night",
     "Normal_Max": 12, "Elevated_Max": 35, "Notes": "SAMPLE THRESHOLD - Culex annulirostris."},
]
thresholds_df = pd.DataFrame(thresholds)
thresholds_df.to_csv(OUT_DIR / "action_thresholds.csv", index=False)


# ---------------------------------------------------------------------------
# 12. PROGRAM TARGETS / KPIs (SAMPLE ONLY)
# ---------------------------------------------------------------------------
targets = []
for season in ALL_SEASONS:
    n_traps_active = len(trap_sites)
    n_weeks = ((season_effective_end(season) - SEASONS[season]["start"]).days // 7)
    targets.append({
        "Season": season,
        "Planned_Surveillance_Events": n_traps_active * n_weeks,
        "Planned_Treatments": 20,
        "Target_Sites_Inspected": int(N_SITES * 0.8),
        "Notes": "SAMPLE TARGETS - for prototype demonstration only; not organisationally approved KPIs.",
    })
targets_df = pd.DataFrame(targets)
targets_df.to_csv(OUT_DIR / "program_targets.csv", index=False)


print("Sample data generation complete.")
print(f"  sites: {len(sites_df)}")
print(f"  trap_sites: {len(trap_sites_df)}")
print(f"  surveillance_events: {len(surv_events_df)}")
print(f"  surveillance_results: {len(surv_results_df)}")
print(f"  treatments: {len(treatments_df)}")
print(f"  products: {len(products_df)}")
print(f"  complaints: {len(complaints_df)}")
print(f"  environmental_data: {len(env_df)}")
print(f"  species_reference: {len(species_df)}")
print(f"  site_observations: {len(observations_df)}")
print(f"  users: {len(users_df)}")
print(f"  action_thresholds: {len(thresholds_df)}")
print(f"  program_targets: {len(targets_df)}")
print(f"Hotspot persistent sites (for demo): {sorted(hotspot_persistent_sites)}")
print(f"Hotspot spike sites (for demo): {sorted(hotspot_spike_sites)}")
