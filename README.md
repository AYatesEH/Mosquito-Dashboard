# Mosquito Season Dashboard (Prototype)

A working prototype operational dashboard for an Environmental Health team to manage, analyse and report on
mosquito management activity across a season - surveillance, treatments, complaints, hotspots, environmental
conditions, data quality and season-end reporting.

**This is a prototype.** All data, thresholds, products, application rates and program targets are
**SAMPLE/FICTIONAL** and clearly labelled throughout the app. Nothing here should be used to make a real
treatment decision. See "What is sample-only vs. real" below.

---

## 1. Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

This opens the Overview page in your browser, with every other page listed in the left-hand sidebar (To Do
List, Surveillance, Map, Site Detail, Treatments, Treatment Effectiveness, Dosage Calculator, Products,
Complaints, Hotspots, Species Reference, Environmental, Data Quality, Reporting).

Season Comparison and Field Observations are currently **hidden** from the sidebar (not needed day-to-day) -
their code is unchanged and untouched, just moved to `pages_hidden/` so Streamlit's automatic page discovery
(which only scans `pages/`) doesn't pick them up. To bring either back, move its file back into `pages/`:

```bash
mv pages_hidden/12_Season_Comparison.py pages/
mv pages_hidden/14_Field_Observations.py pages/
```

The one thing Field Observations was needed for - logging a "Larvae dip / inspection" so a matching To Do List
task clears itself - now has its own quick-log action directly on the To Do List page, so hiding it doesn't
break that.

The mosquito season runs **October to May** app-wide (`core.config.MOSQUITO_SEASON_START_MONTH`/
`MOSQUITO_SEASON_END_MONTH`, `core.calculations.is_in_mosquito_season`) - June-September is the off-season the
program doesn't operate in, and the sample data deliberately contains none for those months.

The sample data already exists under `data/raw/`. If you want to regenerate it (e.g. after changing the
generator, or to get a clean slate), run:

```bash
python data/generate_sample_data.py
```

This is deterministic (fixed random seed) - re-running it produces the same data every time, so it's safe to
re-run without worrying about breaking anything you were looking at.

### A note on this environment

This prototype was built and its **data and business logic were fully tested** in a sandboxed development
environment that has no internet access, so Streamlit/Plotly/Folium could not be installed or actually run
there to click through the UI. Everything in `core/data_source.py` and `core/calculations.py` (all the
numbers the app actually reports) was verified directly against the generated dataset - trap-night maths,
threshold classification, hotspot rules, treatment-effectiveness comparisons and every data-quality check were
run and their output inspected. The Streamlit page code was additionally smoke-tested against lightweight
stand-ins for Streamlit/Plotly/Folium (not shipped with this project) that mimic their real APIs closely enough
to catch import errors, wrong column references and broken call chains, across several different filter
combinations (different seasons, site selections, and the one site with a deliberately missing coordinate).
What **could not** be verified in that environment is visual polish and real browser interaction - so on your
first run, look over the layout and colours and let me know if anything needs adjusting; the underlying numbers
should already be correct.

---

## 2. Project structure

```
mosquito_dashboard/
├── app.py                        # Overview page - Streamlit entry point
├── pages/                        # One file per page (Streamlit's native multipage mechanism)
│   ├── 0_To_Do_List.py           # Auto-generated weekly priority list - sorts just below the "App" entry point
│   ├── 1_Surveillance.py
│   ├── 2_Map.py
│   ├── 3_Site_Detail.py
│   ├── 4_Treatments.py
│   ├── 5_Treatment_Effectiveness.py
│   ├── 6_Dosage_Calculator.py
│   ├── 7_Products.py
│   ├── 8_Complaints.py
│   ├── 9_Hotspots.py
│   ├── 10_Species_Reference.py
│   ├── 11_Environmental.py
│   ├── 13_Data_Quality.py
│   └── 15_Reporting.py
├── pages_hidden/                 # Pages hidden from the sidebar (unchanged code, not deleted - see Section 1)
│   ├── 12_Season_Comparison.py
│   └── 14_Field_Observations.py
├── core/                         # All logic that isn't page/UI code
│   ├── config.py                 # Constants, SAMPLE thresholds/targets, status colours
│   ├── data_source.py            # Data-access abstraction (the ONLY file that reads CSVs)
│   ├── calculations.py           # Trap-nights, thresholds, effectiveness, hotspots, data quality, KPIs
│   ├── mapping.py                # Folium map builder
│   └── ui.py                     # Cached data loading, global filters, KPI cards, styling
├── data/
│   ├── generate_sample_data.py   # Generates every CSV under data/raw/ (documented, deterministic)
│   ├── raw/                      # The CSV files themselves (the prototype's "database")
│   └── gis/
│       └── city_of_vincent_boundary.geojson   # REAL City of Vincent LGA boundary (see note below)
├── .streamlit/config.toml        # Theme
└── requirements.txt
```

**The City of Vincent boundary is real, not sample data.** `data/gis/city_of_vincent_boundary.geojson` is the
actual City of Vincent LGA polygon, extracted from WA Landgate's public "Local Government Area (LGA) Boundaries"
dataset (LGATE-233, GDA2020, supplied directly as a download from data.wa.gov.au). It's drawn as an outline on
the Map page. `random_point_in_vincent()` in `data/generate_sample_data.py` (a point-in-polygon rejection
sampler against this boundary) is still used for a couple of incidental random points (the "no site" complaint
fallback location), but the 21 monitored sites themselves are no longer randomly generated inside the boundary -
see below.

**Sites are real, named City of Vincent parks/reserves, not invented names.** `REAL_SITES` in
`data/generate_sample_data.py` lists 21 real public open spaces (Hyde Park, Robertson Park, Smiths Lake Reserve,
Braithwaite Park, Beatty Park Reserve, and so on), sourced from vincent.wa.gov.au's own Parks & Facilities
directory, with coordinates from a places lookup and each one verified to fall inside the real LGA boundary
above. `Site_Type` per park is an *inferred* likely breeding-habitat category (stormwater drainage, retention
basin, etc.) for demo purposes - not a confirmed council asset record - except for Hyde Park and Smiths Lake
Reserve, which both have a real, permanent lake (Smiths Lake Reserve is a former drainage reservoir). The
Swan River site (Claisebrook Cove) remains the one site deliberately placed just outside the LGA boundary,
matching its real position. All trap results, treatments, complaints, and observations tied to these sites are
still entirely synthetic - only the site names/locations are real.

**Why it's split this way:** a page file only ever calls into `core/` - it never reads a CSV, computes a
trap-night figure, or decides whether a site is "Elevated" itself. That logic lives once, in `core/`, so every
page (and any future page) gets the same answer, and so it can be tested independently of Streamlit (which is
exactly how it was verified during development - see the section above).

---

## 3. Data model

Every dataset lives in its own CSV under `data/raw/`, and (per the brief) they're relational rather than
duplicating location details:

| File | What it holds | Key(s) |
|---|---|---|
| `sites.csv` | **The single source of truth for every physical location** - name, type, lat/long, status, description | `Site_ID` |
| `trap_sites.csv` | A **portable equipment register** (Trap_ID, Trap_Type, Trap_Status) - no `Site_ID`, since only a handful of physical CO2 traps exist and they're moved to a new site each week rather than permanently installed (see `WEEKLY_TRAP_COUNT` in `core/config.py` and the Surveillance page's Add Trap Data tab) | `Trap_ID` |
| `surveillance_events.csv` | One row per trap deployment/retrieval cycle, with its own `Site_ID` and `Trap_Type` (independent of `trap_sites.csv`, since that's where a trap actually went that week) | `Event_ID` → `Trap_ID`, `Site_ID` |
| `surveillance_results.csv` | One row per species caught in an event (an event can have several) | `Result_ID` → `Event_ID` |
| `treatments.csv` | The treatment register (Planned/Scheduled/Completed/Cancelled) | `Treatment_ID` → `Site_ID`, `Product_ID` |
| `products.csv` | Controlled product/label reference (fictional) | `Product_ID` |
| `complaints.csv` | Resident complaints | `Complaint_ID` → `Site_ID` (optional) |
| `environmental_data.csv` | Daily rainfall/temperature/tidal readings (region-wide in this prototype) | `Env_ID` |
| `species_reference.csv` | Mosquito species reference information | `Species_Code` |
| `site_observations.csv` | Field observations logged against a site | `Observation_ID` → `Site_ID` |
| `larvae_dips.csv` | Larvae dip counts - a manual inspection (no trap/equipment involved) recording how many larvae were found in a single dip at a site; feeds into the hotspot calculation as its own signal (see Section 4) | `Dip_ID` → `Site_ID` |
| `users.csv` | Officers (for prototype attribution only) | `User_ID` |
| `action_thresholds.csv` | SAMPLE configurable action thresholds | `Threshold_ID` |
| `program_targets.csv` | SAMPLE configurable program targets, per season | keyed by `Season` |

`Site_ID` is the thread that ties everything together: a trap, a treatment, a complaint, an observation and an
environmental reading can all point at the same site, which is what lets the **Site Detail** page assemble one
complete history instead of several slightly different versions of "the same place." The sites table also
carries `Created_By`/`Created_Date`/`Modified_By`/`Modified_Date` (as do treatments), so a real audit trail can
be layered on later without changing the shape of the data - see Section 6.

Future GIS polygons, photos and attachments all have an obvious home: they'd be new tables keyed by `Site_ID`
(or `Observation_ID` for photos on an observation), following the same pattern.

---

## 4. How the calculations work (`core/calculations.py`)

This is the module to read if you want to understand exactly how any number on the dashboard was produced -
every function has a docstring and nothing here talks to Streamlit.

- **Trap-nights & mosquitoes-per-trap-night** (`usable_events`, `compute_trap_nights`, `event_catch_totals`):
  an event only counts toward abundance statistics if its trap status is `Successful` or `Partial` **and** its
  sample validity is not `Invalid`/`N/A`. Missing traps, equipment failures and invalid samples are excluded
  everywhere, rather than being averaged in as zero catches (which would understate abundance) or dropped
  inconsistently page-to-page.
- **Action thresholds** (`get_threshold_for`, `classify_status`): resolves the most specific SAMPLE threshold
  (site > species > trap type > default) and classifies a mosquitoes-per-trap-night value as Normal / Elevated
  / Action Required. Thresholds live in `action_thresholds.csv`, completely separate from this logic, so
  verified organisational thresholds can replace the sample values without touching any code.
- **Treatment effectiveness** (`assess_treatment_effectiveness`): compares mean mosquitoes-per-trap-night in a
  configurable window before vs. after a treatment, at the same site. If there isn't at least one usable
  surveillance event on each side of the window, it says so explicitly rather than guessing. Every result is
  worded as an **observed change associated with** the treatment - never a causal claim - because weather,
  tides and surveillance effort can move in the same window.
- **Hotspot identification** (`identify_hotspots`): transparent, configurable rules over a lookback window,
  drawing on three independent signals - persistent elevated trap activity (several elevated weeks) or a single
  spike (exactly one), repeated complaints, and elevated larvae dip counts (>= a configurable number of dips
  above `HIGH_LARVAE_COUNT_PER_DIP` - the real APVMA-label "high larval count (>10/dip)" threshold already used
  on the Dosage Calculator page) - plus repeated treatments, tracked separately. No machine learning, nothing
  hidden - every parameter is a slider on the Hotspots page and a constant in `core/config.py`. A site flagged
  by at least 2 of the 3 independent signals in the same window also gets a "Confirmed hotspot (...)" flag
  naming which ones agree (e.g. "trap + complaint", "trap + dip"), and the function returns
  `Trap_Flagged`/`Complaint_Flagged`/`Dip_Flagged` booleans so the Hotspots page can filter to all flagged
  sites, only the confirmed (2+ signal) ones, or just one signal on its own.
- **Data quality** (`data_quality_report`): a fixed set of checks (missing coordinates, orphaned foreign keys,
  retrieval-before-deployment, negative counts, missing species, zero-area completed treatments, negative
  larvae dip counts, and more) that only ever **report** - nothing is auto-corrected.
- **Weekly To Do List** (`build_weekly_todo_list`, To Do List page - just below the entry-point "App" page in
  the sidebar): an auto-generated, priority-ranked list of weekly trap placement, larvicide treatments and
  larvae dipping/inspection tasks for a chosen Monday-Sunday week, built entirely by reusing existing functions
  rather than duplicating their logic.
    - **Trap placement**: only `WEEKLY_TRAP_COUNT` (3) physical CO2 traps are actually owned - set out for one
      night and picked up the next morning, then moved - so instead of tracking individual traps on a fixed
      check cycle, this recommends WHICH sites should get this week's traps. Sites are ranked by hotspot
      priority (reusing `identify_hotspots`): a confirmed trap+complaint hotspot first, then persistent
      elevated activity, then any other flag, then - once flagged sites run out - whichever candidate sites
      have gone longest without a trap (or have never had one), so the whole network still gets rotated through
      over time rather than only ever trapping the same few sites. It only ever asks for as many sites as there
      are traps still unplaced that week: once `WEEKLY_TRAP_COUNT` distinct sites have an actual surveillance
      event logged for the week, the recommendation clears itself.
    - **Larvicide treatment**: from `treatment_redose_schedule` (re-dose due/overdue) plus `identify_hotspots`
      (a new hotspot site with persistent trap activity or a confirmed (2+ signal) flag and no tracked
      treatment yet, plus any site with an elevated larvae dip count on its own - a measured high count is
      already actionable, with no need for trap/complaint corroboration first).
    - **Dipping/inspection**: from unresolved complaints aged past `COMPLAINT_INSPECTION_AGE_HIGH_DAYS` and
      single-signal hotspot sites (a lone trap spike or a complaint with no matching trap activity), which are
      asked to be confirmed by dipping before a treatment is scheduled. Logging either the qualitative "Larvae
      dip / inspection" field observation OR an actual dip count (Surveillance page's Add Dip Data tab) clears
      the task.

  **This is a pure, stateless view, recomputed fresh from current data every time the page loads - there is no
  persisted "to-do" table and no manual "mark done" action.** A task stops being generated, and so disappears
  from the list on its own, the moment the data it's asking for is actually logged elsewhere in the app: a new
  surveillance event (trap placement), a completed/tracked treatment, or a "Larvae dip / inspection" field
  observation (see the next bullet) - verified directly by logging each of these against a running instance of
  the list and confirming the matching task drops off. This only ever runs within the Oct-May season window
  above; a week that falls entirely in the off-season shows an explicit "nothing due" message instead of an
  empty list, so it's clear the absence of tasks is by design, not a bug.
- **`add_site_observation` write path**: same CSV-append pattern as the Treatments/Complaints/Surveillance forms
  (same non-durable-on-Streamlit-Cloud caveat - see Section 6). `core.config.OBSERVATION_CATEGORY_DIP` ("Larvae
  dip / inspection") is the single source of truth for the one category the rest of the app actually depends
  on - it's what the Weekly To Do List's dipping/inspection tasks look for to know a site has been checked, and
  that list has its own "+ Log a larvae dip / inspection" quick-log action calling this same write path. The
  full Field Observations page (every category, a log/filter view) still exists with a working "+ Record a new
  observation" form, but is currently hidden from the sidebar - see Section 1.
- **`add_site` write path** (Operational Map page, "+ Add a new site" expander below the site summary): same
  CSV-append pattern as the other forms. Click a point on the map above to drop a pin and pre-fill Latitude/
  Longitude (via `st_folium`'s `last_clicked`), or type coordinates directly; Site_Type offers the existing
  types plus a free-text "Other (specify)" so a genuinely new site type isn't blocked. `sites.csv`'s `Site_ID`
  is the thread the whole data model hangs off (see Section 3), so a newly-added site is immediately usable
  everywhere - trap placement candidates, every site picker, the map, Data Quality - with no separate step.
- **Re-dose scheduling** (`estimate_control_window`, `treatment_redose_schedule`): for a larvicide treatment,
  linearly interpolates a control-window duration between the product's `Duration_Min_Days` (at `Rate_Min`) and
  `Duration_Max_Days` (at `Rate_Max`) for the rate actually used, then works out an effective-until date and a
  re-dose-due date (`REDOSE_LEAD_DAYS` before that, configurable in `core/config.py`). `treatment_redose_schedule`
  runs this for every site's most recent completed larvicide application and is surfaced on the Treatments page's
  "Re-dose schedule" tab (KPIs + sortable table) and as a live preview on the "Record a treatment" form. This is
  a genuinely working feature (not sample/fictional), but its output is only as good as the underlying product
  duration data - see Section 5. **Note:** because both real products now have a fixed (not rate-dependent)
  labelled duration (30 days for ProLink Pellets, 150 for XR Briquets - see Section 5), the interpolation always
  resolves to that fixed number; the machinery still supports a genuine rate-dependent range if a future product
  needs it.
- **Area and quantity units** (`Area_Treated_M2` in `treatments.csv`; `core.config.QUANTITY_USED_UNITS`):
  treated area is recorded and entered in **m² everywhere in this app** (Treatments "Record a treatment", both
  Dosage Calculator tabs, Products/Season Comparison/Reporting totals) - not hectares - because it's a far
  easier figure to estimate for the small, discrete water bodies this program mostly treats (a puddle, a
  drain, a garden pond) than fractions of a hectare. ProLink Pellets' real label rate is still "kg/ha" (the
  actual label wording, not something this app changes); an entered m² figure is converted to hectares
  internally only for that one multiplication. Quantity used is separately recorded in whichever unit an
  officer actually counts/measures in the field - whole **grams** for ProLink Pellets, whole **briquets** for
  ProLink XR Briquets - deliberately not the same unit as the rate itself; the Treatments form's dosage rate is
  also a **locked selectbox** of the exact discrete site-condition options each real label defines, not a
  free-form number, so an officer can't enter a rate that isn't actually on the label.
- **Guided dosage calculator** (Dosage Calculator page, "Guided dosage calculator" tab; suggestions in
  `core.config.LOCATION_TYPE_GUIDANCE`) - not to be confused with logging a "Larvae dip / inspection"
  (the field-inspection activity, logged via the To Do List's quick-log action): enter a water body's area (m²), date/time and a
  plain-language location type (salt marsh, Swan River foreshore/bank, stormwater drain, neglected pool,
  ornamental pond, temporary/ephemeral pool, etc.) and it suggests a starting product and site condition, then
  computes the same locked-label dosage as the Treatments form. Where possible the suggestion is drawn directly
  from the site-type examples named in each product's own APVMA label (e.g. the Pellets label itself names
  "freshwater/salt marshes, mangrove swamps, estuarine areas" as its low-rate example); where the label doesn't
  name a site type (Swan River foreshore, abandoned pools not literally on the Pellets label, etc.) it's this
  app's own practical judgement, and the code/UI both say so explicitly. **This is a starting suggestion only,
  never a determination** - the label's actual, operative criteria are the water depth, organic content and
  larval count observed on site, not the location's name, so the product and site condition stay fully
  overridable and nothing is saved from this calculator. The manual verification calculator tab (the original
  Dosage Calculator) is unchanged in spirit - pick a product, enter area/rate directly, see the raw
  area-times-rate arithmetic - and both tabs now take area in m² only (see the Area unit note below).
- **Live weather** (`core/weather_api.py`, wrapped/cached in `core/ui.py`): calls the free, no-API-key
  Open-Meteo API to auto-populate current conditions (Environmental Conditions page) and historical/forecast
  weather for a specific site/date (Treatments form preview, Dosage Calculator) - no manual searching or data
  entry needed. Written and syntax-checked against Open-Meteo's published API docs, but **could not be
  exercised against the live API from the sandbox this was built in** (its outbound network is restricted to
  GitHub/package registries only) - the deployed Streamlit Cloud app has normal internet access, so this needs
  its first real run there to confirm the response shape matches. Every call checks for an `"error"` key before
  reading fields and degrades to a plain message rather than crashing the page if the lookup fails.
- **Weather by area, not just one city-wide point** (`core.config.VINCENT_AREAS`, `core.ui.vincent_area_picker`):
  the Treatments form and Site Detail page already look up live weather/tide using a SITE's own coordinates
  (`sites.csv` Latitude/Longitude), so those were already area-specific. The Environmental Conditions page's
  "Live conditions now" panel and the Dosage Calculator's guided tab used to always call one fixed Vincent LGA
  centroid regardless of where the officer actually cared about - both now have an "Area" picker (Leederville,
  Highgate, Mount Hawthorn, North Perth, and the parts of East Perth/West Perth/Perth/Mount Lawley/Osborne Park
  that fall inside Vincent, plus a "City of Vincent (LGA-wide)" default) backed by real per-suburb reference
  coordinates. The Dosage Calculator's tide lookup was also switched from the LGA centroid to the real
  Claisebrook Cove Foreshore site's own coordinates, consistent with Site Detail/Environmental Conditions.
  Suburb list and coordinates are sourced from Wikipedia's "City of Vincent" article and each suburb's own
  infobox - Coolbinia is deliberately excluded from that list despite Wikipedia naming it as shared with the
  City of Stirling, per direct confirmation it isn't actually part of Vincent. Note Open-Meteo's forecast grid
  is coarser than the ~9 km² LGA, so nearby suburbs can return identical or near-identical figures - the picker
  still shows the correct area name, it just won't always differ numerically over such a small area.
- **Tide indicator** (`weather_api.fetch_tide_indicator`): a rough rising/falling sea-level indicator for the
  Swan River foreshore site, via Open-Meteo's free Marine Weather API - added because there is **no free,
  no-API-key source of accurate real Swan River tide data**. WA Dept of Transport publishes only an interactive
  real-time chart and static annual PDF tables (not a queryable API) for its Perth (Barrack St) station, and
  BOM has no official public API either. Open-Meteo's marine model is ~8km-resolution open ocean data and is
  explicitly documented as not accurate for narrow estuaries like the Swan River (which is tidally dampened and
  lagged behind the ocean entrance at Fremantle) - so this is shown ONLY as a rough trend/next-turn indicator,
  with a prominent on-screen caveat every time it's displayed (Site Detail and Environmental Conditions pages),
  never as an authoritative water level. An officer timing river-bank work should confirm against WA DoT's real
  station before acting on it.

---

## 5. What is sample-only vs. what would be real in production

Marked clearly in the app itself (banners on the relevant pages), but to be explicit:

- **Real, sourced directly from the actual APVMA-approved product labels (supplied by the person), WA Dept of
  Health and other cited entomology sources - confirm current details before operational use:** the eleven
  mosquito species on the Species Reference page (breeding habitat, biting behaviour, seasonal characteristics
  and vector significance). Six are sourced from WA Health's "Common mosquitoes in Western Australia" (Aedes
  notoscriptus, Aedes vigilax, Aedes camptorhynchus, Culex annulirostris, Culex quinquefasciatus, Anopheles
  annulipes); the other five - Aedes alboannulatus, Culex globocoxitus, Culex molestus, Culex australicus and
  Aedes sagax - aren't on WA Health's own species page but are named on its South-West adult mosquito
  photographic key as further species present in the region, so their entries are instead sourced from
  Wikipedia, University of Sydney Medical Entomology, Rutgers University Center for Vector Biology and
  iNaturalist (cited per-species in each entry's `Notes` field); the two products tracked on the
  Products/Dosage Calculator pages - ProLink Pellets (Active Constituent 40 g/kg (S)-methoprene, APVMA Approval
  No. 58064/1/0705) and ProLink XR Briquets (18 g/kg (S)-methoprene, APVMA Approval No. 58061/100/0505) - whose
  rate, duration-of-control and application-method fields are transcribed directly from the real labels, not a
  retailer/third-party approximation. Rates are shown as ranges (not one fixed number) because the real labelled
  rate genuinely depends on site conditions (water depth, organic load, larval counts) - see each product's
  `Rate_Basis` and always verify the exact current APVMA-approved label before any real application, since
  labels are periodically reissued. Note: ProLink XR Briquets' labelled rate is area-covered-per-briquet
  (inverse of the other product's product-per-area rate) - the Dosage Calculator divides rather than multiplies
  for this product accordingly. The Dosage Calculator's guided-mode location-type suggestions (Section 4)
  are this app's own starting-point guidance built from the labels' own wording where possible, not a third
  label data source.
- **Removed from the dashboard on request:** the fictional adulticide ("MosquiZap ULV") and the real
  secondary/knockdown product ("VectoBac G") were both deliberately removed - the program tracks only the two
  S-methoprene ProLink products above.
- **Sample/fictional, must be replaced before any real use:** action thresholds, program targets, the one
  remaining placeholder product (a withdrawn product, kept only to exercise Withdrawn-status handling), and the
  dosage calculator's arithmetic itself (a plain area x rate multiplication/division, with no safety margins or
  label conditions applied).
- **Real, named locations - synthetic activity data:** the 21 inland sites are real, named City of Vincent
  parks and reserves (Hyde Park, Robertson Park, Smiths Lake Reserve, Braithwaite Park, Beatty Park Reserve, and
  so on - see `REAL_SITES` in `data/generate_sample_data.py`), sourced from vincent.wa.gov.au's own Parks &
  Facilities directory with coordinates from a places lookup, each verified to fall inside the real LGA
  boundary. `Site_Type` (the inferred breeding-habitat category monitored there) is a plausible inference for
  demo purposes, not a confirmed council asset record, except for Hyde Park and Smiths Lake Reserve, which both
  have a real, permanent lake. Every trap result, treatment, complaint, environmental reading, observation and
  larvae dip count tied to these sites is still entirely synthetic - only the site names/locations are real.
- **Real, specific location:** one site, "Claisebrook Cove Foreshore (Swan River)", uses real coordinates for
  a real, named Swan River bank location - added because larvae dipping/larviciding along the river bank is a
  regular, named part of the program.
- **Real geographic boundary:** the City of Vincent LGA outline shown on the Map page is the actual council
  boundary (WA Landgate LGATE-233), not an approximation - see the note in Section 2.
- **Real, live (not sample) data:** the "Live conditions now" panel (Environmental Conditions page) and the
  weather auto-populated on the Treatments form are genuine live API calls to Open-Meteo, not sample data - see
  Section 4. The tide indicator is also a live API call, but is explicitly a rough approximation, not accurate
  real data - see Section 4's caveat before relying on it for anything.

---

## 6. Moving from CSV to a real corporate data source

This is the reason `core/data_source.py` exists as its own file. Every page and every calculation reaches data
through `core.data_source.get_repository()`, which currently returns a `CSVDataRepository`. To move to SQL
Server, SharePoint Lists or Dataverse:

1. Write a new class (e.g. `SqlDataRepository`) that implements the same methods as `DataRepository`
   (`get_sites()`, `get_surveillance_events()`, etc.), returning pandas DataFrames with the **same column
   names** the CSV version returns (each method's docstring/the table above says what's expected).
2. Change the one line in `get_repository()` to return your new class instead (a config flag or environment
   variable is a natural way to choose between them).
3. Nothing in `core/calculations.py`, `core/ui.py`, `core/mapping.py` or any page needs to change.

The same principle applies to authentication, permissions and audit trail: `Created_By`/`Modified_By` fields
are already on the sites and treatments tables, so wiring up Microsoft/organisational sign-in later means
populating those fields from the logged-in user rather than an officer picked from a dropdown, not
restructuring anything.

**Data entry now actually saves - to the CSV files, as an interim step.** The Treatments, Complaints,
Surveillance and Map pages each have a "+ Log/Record/Add..." form (`DataRepository.add_treatment`/
`add_complaint`/`add_surveillance_event`/`add_surveillance_result`/`add_site`/`add_site_observation`/
`add_larvae_dip` in `core/data_source.py`, called via `core/ui.py`'s `add_*`/`invalidate_data_cache` wrappers)
that appends a row
and clears the cache, so the new record shows up everywhere on the very next rerun - KPIs, charts, the re-dose
schedule, all of it, no separate refresh step.
**This is genuinely useful for a single-user demo or pilot, but it is NOT the real answer for a live season**:
`CSVDataRepository`'s writes are plain file appends with no locking, so two people saving at the same moment
can corrupt a file; and Streamlit Community Cloud's filesystem is wiped on every redeploy and on restart after
the app sleeps from inactivity, so anything written would eventually vanish. Moving to a real backend (Section
6's numbered steps above) is what makes this safe to rely on - the `add_*` methods just need the same
treatment as the `get_*` methods: implement them on the new repository class, and every "+ Log..." form keeps
working unchanged, because pages call `core.ui.add_*`, never `data_source` directly.

---

## 7. Known prototype limitations (by design, not oversights)

- Data entry forms (Treatments, Complaints, Surveillance - including its Add Dip Data tab, Map's "Add a new
  site", and the To Do List's qualitative dip-logging quick action) save to the CSV files - genuinely working,
  but not durable on Streamlit Community Cloud and not safe for concurrent multi-user writes - see Section 6.
- Season Comparison and Field Observations are hidden from the sidebar (Section 1) - their code and data are
  untouched, so re-enabling either later is a one-line `mv`.
- The Weekly To Do List (Section 4) has no photo/attachment support and doesn't yet let an officer add a manual,
  ad-hoc task outside its automatic rules - both natural near-term additions, same "+ Record..." form pattern.
- Environmental data is region-wide, not per-site; `Site_ID` is already a column on `environmental_data.csv`
  ready for when a real feed can report per-site conditions.
- Reporting export is CSV today; PDF/formatted-Excel export is a natural near-term addition once report
  layout/branding is confirmed with management.
- No authentication - anyone who can open the app sees everything, which is fine for a single-team prototype
  but is the first thing to add before wider rollout.
