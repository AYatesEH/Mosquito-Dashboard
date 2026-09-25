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

This opens the Overview page in your browser, with every other page listed in the left-hand sidebar
(Surveillance, Map, Site Detail, Treatments, Treatment Effectiveness, Dosage Calculator, Products, Complaints,
Hotspots, Species Reference, Environmental, Season Comparison, Data Quality, Field Observations, Reporting).

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
│   ├── 12_Season_Comparison.py
│   ├── 13_Data_Quality.py
│   ├── 14_Field_Observations.py
│   └── 15_Reporting.py
├── core/                         # All logic that isn't page/UI code
│   ├── config.py                 # Constants, SAMPLE thresholds/targets, status colours
│   ├── data_source.py            # Data-access abstraction (the ONLY file that reads CSVs)
│   ├── calculations.py           # Trap-nights, thresholds, effectiveness, hotspots, data quality, KPIs
│   ├── mapping.py                # Folium map builder
│   └── ui.py                     # Cached data loading, global filters, KPI cards, styling
├── data/
│   ├── generate_sample_data.py   # Generates every CSV under data/raw/ (documented, deterministic)
│   └── raw/                      # The CSV files themselves (the prototype's "database")
├── .streamlit/config.toml        # Theme
└── requirements.txt
```

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
| `trap_sites.csv` | Traps installed at a site (a site can have more than one) | `Trap_ID` → `Site_ID` |
| `surveillance_events.csv` | One row per trap deployment/retrieval cycle | `Event_ID` → `Trap_ID`, `Site_ID` |
| `surveillance_results.csv` | One row per species caught in an event (an event can have several) | `Result_ID` → `Event_ID` |
| `treatments.csv` | The treatment register (Planned/Scheduled/Completed/Cancelled) | `Treatment_ID` → `Site_ID`, `Product_ID` |
| `products.csv` | Controlled product/label reference (fictional) | `Product_ID` |
| `complaints.csv` | Resident complaints | `Complaint_ID` → `Site_ID` (optional) |
| `environmental_data.csv` | Daily rainfall/temperature/tidal readings (region-wide in this prototype) | `Env_ID` |
| `species_reference.csv` | Mosquito species reference information | `Species_Code` |
| `site_observations.csv` | Field observations logged against a site | `Observation_ID` → `Site_ID` |
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
- **Hotspot identification** (`identify_hotspots`): four transparent, configurable rules over a lookback window
  - persistent elevated activity (several elevated weeks), a single spike (exactly one), repeated complaints,
  and repeated treatments. No machine learning, nothing hidden - every parameter is a slider on the Hotspots
  page and a constant in `core/config.py`.
- **Data quality** (`data_quality_report`): a fixed set of checks (missing coordinates, orphaned foreign keys,
  retrieval-before-deployment, negative counts, missing species, zero-area completed treatments, and more) that
  only ever **report** - nothing is auto-corrected.

---

## 5. What is sample-only vs. what would be real in production

Marked clearly in the app itself (banners on the relevant pages), but to be explicit:

- **Sample/fictional, must be replaced before any real use:** action thresholds, program targets, all products
  and application rates, the dosage calculator's output, and the descriptive fields on the species reference
  page (breeding habitat, biting behaviour, vector significance).
- **Realistic but synthetic:** every trap result, treatment, complaint, environmental reading and site - none
  of it is real council data, and site names/coordinates are invented.
- **Real (public biological knowledge), used only for realism:** mosquito species scientific/common names.

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
populating those fields from the logged-in user rather than `"data_generator"`, not restructuring anything.
Data-entry forms currently shown on the Treatments and Field Observations pages are intentionally left as
**prototype-only forms that don't persist** (clearly captioned) - the natural next step is wiring their
`st.form_submit_button` handlers to `DataRepository` write methods once a real backend is chosen.

---

## 7. Known prototype limitations (by design, not oversights)

- Data entry forms (new treatment, new observation) don't persist - see above.
- Environmental data is region-wide, not per-site; `Site_ID` is already a column on `environmental_data.csv`
  ready for when a real feed can report per-site conditions.
- Reporting export is CSV today; PDF/formatted-Excel export is a natural near-term addition once report
  layout/branding is confirmed with management.
- No authentication - anyone who can open the app sees everything, which is fine for a single-team prototype
  but is the first thing to add before wider rollout.
