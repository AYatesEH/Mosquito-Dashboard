"""
calculations.py

All business logic / calculations for the dashboard, kept deliberately free of
any Streamlit or plotting code so it can be unit-tested and reused across
pages without duplication.

Every function takes plain pandas DataFrames (as returned by
core.data_source.DataRepository) and returns plain DataFrames, dicts, or
scalars. No page should re-implement any of this logic directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import numpy as np
import pandas as pd

from core.config import (
    VALID_TRAP_STATUSES_FOR_ABUNDANCE,
    INVALID_SAMPLE_VALIDITY,
    STATUS_NORMAL,
    STATUS_ELEVATED,
    STATUS_ACTION,
    STATUS_UNKNOWN,
    DEFAULT_PRE_WINDOW_DAYS,
    DEFAULT_POST_WINDOW_DAYS,
    MIN_EVENTS_FOR_EFFECTIVENESS,
    HOTSPOT_LOOKBACK_WEEKS,
    HOTSPOT_MIN_ELEVATED_WEEKS,
    HOTSPOT_MIN_COMPLAINTS,
    HOTSPOT_MIN_TREATMENTS,
    REDOSE_LEAD_DAYS,
    REDOSE_ON_TRACK,
    REDOSE_DUE_SOON,
    REDOSE_OVERDUE,
    REDOSE_NOT_SCHEDULED,
)


# ===========================================================================
# SURVEILLANCE EFFORT / TRAP-NIGHT CALCULATIONS
# ===========================================================================

def usable_events(events: pd.DataFrame) -> pd.DataFrame:
    """
    Returns only surveillance events whose catch counts are safe to use in
    abundance statistics: trap status Successful or Partial, AND a valid
    sample. 'Missing', 'Failed - Equipment/Battery' events and any event with
    an Invalid sample are excluded so they cannot silently distort
    mosquitoes-per-trap-night figures.
    """
    if events.empty:
        return events
    mask = events["Trap_Status"].isin(VALID_TRAP_STATUSES_FOR_ABUNDANCE) & ~events["Sample_Validity"].isin(
        INVALID_SAMPLE_VALIDITY
    )
    return events.loc[mask].copy()


def compute_trap_nights(events: pd.DataFrame) -> pd.Series:
    """
    Trap-nights per usable event = (Retrieval_DateTime - Deployment_DateTime)
    in whole days, floored at a minimum of 1 night to avoid division by zero
    from same-day retrieval logged in error (such rows are ALSO flagged by
    the data-quality checks - this floor only protects the abundance
    calculation itself from breaking).
    """
    nights = (events["Retrieval_DateTime"] - events["Deployment_DateTime"]).dt.total_seconds() / 86400.0
    nights = nights.clip(lower=1.0)
    return nights


def event_catch_totals(events: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """
    Returns one row per surveillance event with total mosquitoes collected
    (summed across all species, using only usable events and excluding any
    result rows with a negative count or missing species code - those are
    data-quality issues, not abundance).
    """
    clean_results = results.copy()
    clean_results = clean_results[clean_results["Number_Collected"].fillna(-1) >= 0]
    clean_results = clean_results[clean_results["Species_Code"].notna() & (clean_results["Species_Code"] != "")]

    totals = clean_results.groupby("Event_ID", as_index=False)["Number_Collected"].sum()
    totals = totals.rename(columns={"Number_Collected": "Total_Catch"})

    ue = usable_events(events).copy()
    ue["Trap_Nights"] = compute_trap_nights(ue)
    merged = ue.merge(totals, on="Event_ID", how="left")
    merged["Total_Catch"] = merged["Total_Catch"].fillna(0)
    merged["Mosquitoes_Per_Trap_Night"] = merged["Total_Catch"] / merged["Trap_Nights"]
    return merged


def surveillance_program_completion(events: pd.DataFrame, planned_events: int) -> float:
    """Percentage of planned surveillance events that have occurred (any status logged, i.e. attempted)."""
    if not planned_events:
        return 0.0
    return round(100.0 * min(len(events), planned_events) / planned_events, 1)


# ===========================================================================
# ACTION THRESHOLDS / OPERATIONAL STATUS
# ===========================================================================

def get_threshold_for(thresholds: pd.DataFrame, species_code: Optional[str] = None,
                       site_id: Optional[str] = None, trap_type: Optional[str] = None) -> tuple[float, float]:
    """
    Resolves the most specific applicable SAMPLE threshold, in priority order:
    Site-specific > Species-specific > Trap-type-specific > Default.
    Returns (Normal_Max, Elevated_Max).
    """
    if thresholds.empty:
        return (10.0, 30.0)  # hard fallback, should not normally be hit

    def _match(scope_col, value):
        if value is None:
            return pd.DataFrame()
        rows = thresholds[thresholds[scope_col] == value]
        return rows

    for scope_col, value in (("Site_ID", site_id), ("Species_Code", species_code), ("Trap_Type", trap_type)):
        rows = _match(scope_col, value)
        if not rows.empty:
            r = rows.iloc[0]
            return (float(r["Normal_Max"]), float(r["Elevated_Max"]))

    default_rows = thresholds[thresholds["Scope"] == "Default"]
    if not default_rows.empty:
        r = default_rows.iloc[0]
        return (float(r["Normal_Max"]), float(r["Elevated_Max"]))
    r = thresholds.iloc[0]
    return (float(r["Normal_Max"]), float(r["Elevated_Max"]))


def classify_status(value: Optional[float], normal_max: float, elevated_max: float) -> str:
    """Classifies a mosquitoes-per-trap-night value into Normal / Elevated / Action Required."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return STATUS_UNKNOWN
    if value <= normal_max:
        return STATUS_NORMAL
    if value <= elevated_max:
        return STATUS_ELEVATED
    return STATUS_ACTION


def site_current_status(site_id: str, catch_totals: pd.DataFrame, thresholds: pd.DataFrame,
                         as_of: Optional[pd.Timestamp] = None) -> dict:
    """
    Returns the current operational status for one site, based on its most
    recent usable surveillance event (optionally as-of a given date, for
    historical/testing purposes).
    """
    site_events = catch_totals[catch_totals["Site_ID"] == site_id].copy()
    if as_of is not None:
        site_events = site_events[site_events["Deployment_DateTime"] <= as_of]
    if site_events.empty:
        return {"Site_ID": site_id, "Status": STATUS_UNKNOWN, "Latest_MPTN": None,
                "Latest_Sample_Date": None, "Dominant_Species": None}

    site_events = site_events.sort_values("Deployment_DateTime")
    latest = site_events.iloc[-1]
    normal_max, elevated_max = get_threshold_for(thresholds, site_id=site_id)
    status = classify_status(latest["Mosquitoes_Per_Trap_Night"], normal_max, elevated_max)
    return {
        "Site_ID": site_id,
        "Status": status,
        "Latest_MPTN": round(float(latest["Mosquitoes_Per_Trap_Night"]), 1),
        "Latest_Sample_Date": latest["Deployment_DateTime"],
        "Latest_Event_ID": latest["Event_ID"],
    }


# ===========================================================================
# TREATMENT EFFECTIVENESS
# ===========================================================================

@dataclass
class EffectivenessResult:
    treatment_id: str
    site_id: str
    treatment_date: pd.Timestamp
    pre_abundance: Optional[float]
    post_abundance: Optional[float]
    pct_change: Optional[float]
    pre_events: int
    post_events: int
    sufficient_data: bool
    note: str


def assess_treatment_effectiveness(
    treatment_row: pd.Series,
    catch_totals: pd.DataFrame,
    pre_days: int = DEFAULT_PRE_WINDOW_DAYS,
    post_days: int = DEFAULT_POST_WINDOW_DAYS,
) -> EffectivenessResult:
    """
    Compares mean mosquitoes-per-trap-night at the treatment's site in the
    `pre_days` window immediately before the treatment date against the
    `post_days` window immediately after it, using only usable surveillance
    events at that same Site_ID.

    This is an OBSERVED ASSOCIATION, not a causal claim: weather, tides,
    surveillance effort and other factors can also change abundance across
    the same window. Callers (UI) must present this framing to the user.
    """
    site_id = treatment_row["Site_ID"]
    treatment_date = treatment_row["Treatment_Date"]
    if pd.isna(treatment_date):
        return EffectivenessResult(treatment_row["Treatment_ID"], site_id, treatment_date,
                                    None, None, None, 0, 0, False,
                                    "No completed treatment date recorded.")

    site_events = catch_totals[catch_totals["Site_ID"] == site_id]
    pre_start = treatment_date - timedelta(days=pre_days)
    post_end = treatment_date + timedelta(days=post_days)

    pre_window = site_events[(site_events["Deployment_DateTime"] >= pre_start) &
                              (site_events["Deployment_DateTime"] < treatment_date)]
    post_window = site_events[(site_events["Deployment_DateTime"] > treatment_date) &
                               (site_events["Deployment_DateTime"] <= post_end)]

    n_pre, n_post = len(pre_window), len(post_window)
    sufficient = n_pre >= MIN_EVENTS_FOR_EFFECTIVENESS and n_post >= MIN_EVENTS_FOR_EFFECTIVENESS

    if not sufficient:
        return EffectivenessResult(
            treatment_row["Treatment_ID"], site_id, treatment_date, None, None, None,
            n_pre, n_post, False,
            "Insufficient surveillance data in the comparison window to assess effectiveness."
        )

    pre_mean = float(pre_window["Mosquitoes_Per_Trap_Night"].mean())
    post_mean = float(post_window["Mosquitoes_Per_Trap_Night"].mean())
    pct_change = None
    if pre_mean > 0:
        pct_change = round(100.0 * (post_mean - pre_mean) / pre_mean, 1)

    return EffectivenessResult(
        treatment_row["Treatment_ID"], site_id, treatment_date,
        round(pre_mean, 1), round(post_mean, 1), pct_change, n_pre, n_post, True,
        "Observed change associated with the treatment window; not a causal claim. "
        "Weather, tides and surveillance effort may also have contributed."
    )


# ===========================================================================
# RE-DOSE / EFFECTIVENESS-WINDOW SCHEDULING
# ===========================================================================
# A larvicide's labelled rate is a RANGE (see products.csv Rate_Min/Rate_Max),
# and the real duration of control genuinely depends on where in that range
# the officer actually dosed (see Duration_Min_Days/Duration_Max_Days on the
# same row) - so the estimated re-dose date is calculated per treatment, not
# looked up as one fixed number per product.

@dataclass
class ControlWindowResult:
    duration_days: Optional[float]
    effective_until: Optional[pd.Timestamp]     # estimated date control lapses
    redose_due: Optional[pd.Timestamp]          # effective_until minus the lead buffer
    status: str
    note: str


def estimate_control_window(
    product_row: pd.Series,
    rate_used: Optional[float],
    treatment_date: pd.Timestamp,
    as_of: Optional[pd.Timestamp] = None,
    lead_days: int = REDOSE_LEAD_DAYS,
) -> ControlWindowResult:
    """
    Estimates when a single larvicide application's control window ends and
    when the site should be re-dosed, by linearly interpolating between the
    product's Duration_Min_Days (at Rate_Min) and Duration_Max_Days (at
    Rate_Max) for the rate actually used.

    Returns REDOSE_NOT_SCHEDULED (no duration/date maths attempted) when the
    product has no meaningful residual window (Duration_Min/Max_Days both 0,
    e.g. an adulticide) or when required inputs are missing - callers should
    treat that as "re-treatment is a surveillance/complaint decision, not a
    scheduled one", not as an error.
    """
    if pd.isna(treatment_date):
        return ControlWindowResult(None, None, None, REDOSE_NOT_SCHEDULED,
                                    "No treatment date recorded.")

    dur_min = product_row.get("Duration_Min_Days")
    dur_max = product_row.get("Duration_Max_Days")
    rate_min = product_row.get("Rate_Min")
    rate_max = product_row.get("Rate_Max")
    if pd.isna(dur_min) or pd.isna(dur_max) or (float(dur_min) == 0 and float(dur_max) == 0):
        return ControlWindowResult(None, None, None, REDOSE_NOT_SCHEDULED,
                                    "This product has no meaningful residual control window (e.g. an adulticide) "
                                    "- re-treatment should be driven by surveillance/complaints, not a timer.")

    dur_min, dur_max = float(dur_min), float(dur_max)
    if rate_used is None or pd.isna(rate_used) or pd.isna(rate_min) or pd.isna(rate_max) or float(rate_max) == float(rate_min):
        duration_days = (dur_min + dur_max) / 2.0  # can't interpolate - use the midpoint
    else:
        rate_min, rate_max, rate_used = float(rate_min), float(rate_max), float(rate_used)
        frac = (rate_used - rate_min) / (rate_max - rate_min)
        frac = min(max(frac, 0.0), 1.0)  # clamp - a rate outside the labelled range doesn't extrapolate duration
        duration_days = dur_min + frac * (dur_max - dur_min)

    effective_until = treatment_date + timedelta(days=duration_days)
    redose_due = effective_until - timedelta(days=lead_days)
    if redose_due < treatment_date:
        redose_due = treatment_date  # never recommend re-dosing before the treatment even happened

    reference = as_of if as_of is not None else pd.Timestamp.now().normalize()
    if reference >= effective_until:
        status = REDOSE_OVERDUE
    elif reference >= redose_due:
        status = REDOSE_DUE_SOON
    else:
        status = REDOSE_ON_TRACK

    return ControlWindowResult(
        round(duration_days, 1), effective_until, redose_due, status,
        f"Estimated {duration_days:.0f}-day control window from the rate used, interpolated between this "
        f"product's labelled Rate_Min/Rate_Max. CONFIRM against the current APVMA label and site conditions - "
        f"this is a planning estimate, not a guarantee of ongoing control."
    )


def treatment_redose_schedule(
    treatments: pd.DataFrame,
    products: pd.DataFrame,
    as_of: pd.Timestamp,
    lead_days: int = REDOSE_LEAD_DAYS,
) -> pd.DataFrame:
    """
    For every site, looks at its MOST RECENT completed 'Larvicide Application'
    treatment only (an older one is superseded once a newer one is logged)
    and estimates its control window. Returns one row per site that has at
    least one completed larvicide treatment, with columns: Site_ID,
    Treatment_ID, Product_ID, Product_Name, Treatment_Date, Rate_Used,
    Rate_Unit, Duration_Days, Effective_Until, Redose_Due, Status, Note.
    Sites where the product has no residual window (REDOSE_NOT_SCHEDULED)
    are still included, since that's operationally meaningful ("no timer
    applies here"), not an absence of data - callers can filter them out.
    """
    larvicide = treatments[
        (treatments["Treatment_Type"] == "Larvicide Application") &
        (treatments["Treatment_Status"] == "Completed") &
        treatments["Treatment_Date"].notna() &
        treatments["Product_ID"].notna() & (treatments["Product_ID"] != "")
    ].copy()
    if larvicide.empty:
        return pd.DataFrame(columns=["Site_ID", "Treatment_ID", "Product_ID", "Product_Name", "Treatment_Date",
                                      "Rate_Used", "Rate_Unit", "Duration_Days", "Effective_Until", "Redose_Due",
                                      "Status", "Note"])

    latest_idx = larvicide.sort_values("Treatment_Date").groupby("Site_ID")["Treatment_Date"].idxmax()
    latest = larvicide.loc[latest_idx]

    rows = []
    for _, t in latest.iterrows():
        prod_rows = products[products["Product_ID"] == t["Product_ID"]]
        if prod_rows.empty:
            continue
        prod = prod_rows.iloc[0]
        rate_used = t.get("Application_Rate")
        result = estimate_control_window(prod, rate_used, t["Treatment_Date"], as_of=as_of, lead_days=lead_days)
        rows.append({
            "Site_ID": t["Site_ID"], "Treatment_ID": t["Treatment_ID"], "Product_ID": t["Product_ID"],
            "Product_Name": prod["Product_Name"], "Treatment_Date": t["Treatment_Date"],
            "Rate_Used": rate_used, "Rate_Unit": t.get("Rate_Unit"),
            "Duration_Days": result.duration_days, "Effective_Until": result.effective_until,
            "Redose_Due": result.redose_due, "Status": result.status, "Note": result.note,
        })
    return pd.DataFrame(rows)


# ===========================================================================
# HOTSPOT IDENTIFICATION (transparent, rule-based, configurable)
# ===========================================================================

def identify_hotspots(catch_totals: pd.DataFrame, complaints: pd.DataFrame, treatments: pd.DataFrame,
                       thresholds: pd.DataFrame, as_of: pd.Timestamp,
                       lookback_weeks: int = HOTSPOT_LOOKBACK_WEEKS,
                       min_elevated_weeks: int = HOTSPOT_MIN_ELEVATED_WEEKS,
                       min_complaints: int = HOTSPOT_MIN_COMPLAINTS,
                       min_treatments: int = HOTSPOT_MIN_TREATMENTS) -> pd.DataFrame:
    """
    Rule-based (not predictive) hotspot flagging. For each site with any
    usable surveillance in the lookback window, flags:
      - 'Persistent elevated activity': >= min_elevated_weeks distinct weeks
         at/above the Elevated threshold in the lookback window.
      - 'Single elevated spike': exactly one week at/above Elevated in the
         window (flagged separately from persistent activity so officers can
         tell the two apart).
      - 'Repeated complaints': >= min_complaints complaints at the site in
         the lookback window.
      - 'Repeatedly treated': >= min_treatments completed treatments at the
         site in the lookback window.
      - 'Confirmed hotspot (trap + complaint)': added on top of the above
         when a site is flagged by BOTH the trap-based rule (persistent
         activity or a spike) AND the complaint-based rule at the same time
         - the two independent signals corroborate each other, rather than
         one input alone driving the flag.
    A site can carry more than one flag. Also returns `Trap_Flagged` and
    `Complaint_Flagged` boolean columns (independent of `Flags`' text) so a
    caller can filter sites by which signal(s) actually triggered - e.g. the
    Hotspots page's "trap only / complaint only / both" filter. All rule
    parameters are configurable (see core/config.py) rather than hard-coded
    thresholds on model output.
    """
    window_start = as_of - timedelta(weeks=lookback_weeks)
    window = catch_totals[(catch_totals["Deployment_DateTime"] >= window_start) &
                           (catch_totals["Deployment_DateTime"] <= as_of)].copy()

    rows = []
    for site_id, site_df in window.groupby("Site_ID"):
        normal_max, elevated_max = get_threshold_for(thresholds, site_id=site_id)
        site_df = site_df.copy()
        site_df["Status"] = site_df["Mosquitoes_Per_Trap_Night"].apply(
            lambda v: classify_status(v, normal_max, elevated_max))
        site_df["Week"] = site_df["Deployment_DateTime"].dt.to_period("W")
        elevated_weeks = site_df.loc[site_df["Status"].isin([STATUS_ELEVATED, STATUS_ACTION]), "Week"].nunique()

        site_complaints = complaints[(complaints["Site_ID"] == site_id) &
                                      (complaints["Date_Received"] >= window_start) &
                                      (complaints["Date_Received"] <= as_of)]
        site_treatments = treatments[(treatments["Site_ID"] == site_id) &
                                      (treatments["Treatment_Status"] == "Completed") &
                                      (treatments["Treatment_Date"] >= window_start) &
                                      (treatments["Treatment_Date"] <= as_of)]

        trap_flagged = elevated_weeks >= min_elevated_weeks or elevated_weeks == 1
        complaint_flagged = len(site_complaints) >= min_complaints

        flags = []
        if elevated_weeks >= min_elevated_weeks:
            flags.append("Persistent elevated activity")
        elif elevated_weeks == 1:
            flags.append("Single elevated spike")
        if complaint_flagged:
            flags.append("Repeated complaints")
        if len(site_treatments) >= min_treatments:
            flags.append("Repeatedly treated")
        if trap_flagged and complaint_flagged:
            flags.append("Confirmed hotspot (trap + complaint)")

        if flags:
            rows.append({
                "Site_ID": site_id,
                "Flags": flags,
                "Elevated_Weeks": elevated_weeks,
                "Complaints_In_Window": len(site_complaints),
                "Treatments_In_Window": len(site_treatments),
                "Trap_Flagged": trap_flagged,
                "Complaint_Flagged": complaint_flagged,
            })

    return pd.DataFrame(rows)


# ===========================================================================
# DATA QUALITY
# ===========================================================================

def data_quality_report(sites, trap_sites, surv_events, surv_results, treatments, complaints) -> pd.DataFrame:
    """
    Runs a fixed set of transparent, explainable data-quality checks and
    returns one row per issue found: Dataset, Record_ID, Severity,
    Description. Nothing is auto-corrected - this is a detection report only.
    """
    issues = []

    def add(dataset, record_id, severity, description):
        issues.append({"Dataset": dataset, "Record_ID": record_id, "Severity": severity, "Description": description})

    # Sites: missing coordinates
    for _, r in sites.iterrows():
        if pd.isna(r["Latitude"]) or pd.isna(r["Longitude"]):
            add("sites", r["Site_ID"], "High", "Missing latitude/longitude.")

    # Trap sites: orphaned Site_ID reference
    valid_site_ids = set(sites["Site_ID"])
    for _, r in trap_sites.iterrows():
        if r["Site_ID"] not in valid_site_ids:
            add("trap_sites", r["Trap_ID"], "High", f"References Site_ID '{r['Site_ID']}' not found in sites.")

    # Surveillance events: retrieval before deployment; orphaned site/trap refs
    valid_trap_ids = set(trap_sites["Trap_ID"])
    for _, r in surv_events.iterrows():
        if pd.notna(r["Deployment_DateTime"]) and pd.notna(r["Retrieval_DateTime"]):
            if r["Retrieval_DateTime"] < r["Deployment_DateTime"]:
                add("surveillance_events", r["Event_ID"], "High", "Retrieval date/time is before deployment date/time.")
            elif (r["Retrieval_DateTime"] - r["Deployment_DateTime"]).days > 14:
                add("surveillance_events", r["Event_ID"], "Medium",
                    "Implausibly long trap deployment (> 14 days).")
        if r["Site_ID"] not in valid_site_ids:
            add("surveillance_events", r["Event_ID"], "High", f"References Site_ID '{r['Site_ID']}' not found in sites.")
        if r["Trap_ID"] not in valid_trap_ids:
            add("surveillance_events", r["Event_ID"], "High", f"References Trap_ID '{r['Trap_ID']}' not found in trap_sites.")

    # Surveillance results: negative counts, missing species, orphaned event refs
    valid_event_ids = set(surv_events["Event_ID"])
    for _, r in surv_results.iterrows():
        if pd.notna(r["Number_Collected"]) and r["Number_Collected"] < 0:
            add("surveillance_results", r["Result_ID"], "High", "Negative mosquito count.")
        if pd.isna(r["Species_Code"]) or str(r["Species_Code"]).strip() == "":
            add("surveillance_results", r["Result_ID"], "Medium", "Missing species code.")
        if r["Event_ID"] not in valid_event_ids:
            add("surveillance_results", r["Result_ID"], "High", f"References Event_ID '{r['Event_ID']}' not found.")

    # Duplicate result rows (same event + species logged twice)
    dupe_mask = surv_results.duplicated(subset=["Event_ID", "Species_Code"], keep=False)
    for _, r in surv_results[dupe_mask].iterrows():
        add("surveillance_results", r["Result_ID"], "Low",
            "Duplicate Event_ID + Species_Code combination (possible double entry).")

    # Treatments: missing product for non-source-reduction, zero area, missing operator, orphaned site
    for _, r in treatments.iterrows():
        if r["Site_ID"] not in valid_site_ids:
            add("treatments", r["Treatment_ID"], "High", f"References Site_ID '{r['Site_ID']}' not found in sites.")
        if r["Treatment_Status"] == "Completed":
            if r["Treatment_Type"] != "Source Reduction / Habitat Modification" and (
                    pd.isna(r["Product_ID"]) or str(r["Product_ID"]).strip() == ""):
                add("treatments", r["Treatment_ID"], "High", "Completed treatment is missing a Product_ID.")
            if pd.isna(r["Area_Treated_M2"]) or r["Area_Treated_M2"] == 0:
                if r["Treatment_Type"] != "Source Reduction / Habitat Modification":
                    add("treatments", r["Treatment_ID"], "Medium", "Completed treatment has zero/blank area treated.")
            if pd.isna(r["Operator"]) or str(r["Operator"]).strip() == "":
                add("treatments", r["Treatment_ID"], "Medium", "Missing operator.")
        if r["Treatment_Status"] == "Cancelled" and (pd.isna(r["Cancelled_Reason"]) or str(r["Cancelled_Reason"]).strip() == ""):
            add("treatments", r["Treatment_ID"], "Low", "Cancelled treatment has no reason recorded.")

    # Complaints: orphaned site refs where a Site_ID was provided
    for _, r in complaints.iterrows():
        if pd.notna(r["Site_ID"]) and str(r["Site_ID"]).strip() != "" and r["Site_ID"] not in valid_site_ids:
            add("complaints", r["Complaint_ID"], "High", f"References Site_ID '{r['Site_ID']}' not found in sites.")

    # Invalid samples that would otherwise sneak into abundance stats if not excluded upstream
    invalid_but_nonzero = surv_events[(surv_events["Sample_Validity"].isin(INVALID_SAMPLE_VALIDITY))]
    for _, r in invalid_but_nonzero.iterrows():
        add("surveillance_events", r["Event_ID"], "Low",
            "Invalid/NA sample - correctly excluded from abundance statistics (informational only).")

    return pd.DataFrame(issues)


# ===========================================================================
# KPI HELPERS (Overview page)
# ===========================================================================

def kpi_summary(catch_totals: pd.DataFrame, treatments: pd.DataFrame, complaints: pd.DataFrame,
                 thresholds: pd.DataFrame) -> dict:
    """Rolls up the headline KPI numbers for the Overview page for an already-filtered (season/date) dataset."""
    total_mosquitoes = int(catch_totals["Total_Catch"].sum()) if not catch_totals.empty else 0
    successful_nights = catch_totals["Trap_Nights"].sum() if not catch_totals.empty else 0
    mptn = round(catch_totals["Total_Catch"].sum() / successful_nights, 2) if successful_nights else None
    n_trap_sites = catch_totals["Site_ID"].nunique() if not catch_totals.empty else 0

    completed = treatments[treatments["Treatment_Status"] == "Completed"]
    scheduled = treatments[treatments["Treatment_Status"].isin(["Planned", "Scheduled"])]
    area_treated = completed["Area_Treated_M2"].fillna(0).sum()

    # Sites currently above threshold / needing follow-up, based on latest usable event per site
    site_statuses = []
    for site_id in catch_totals["Site_ID"].dropna().unique():
        site_statuses.append(site_current_status(site_id, catch_totals, thresholds))
    status_df = pd.DataFrame(site_statuses) if site_statuses else pd.DataFrame(columns=["Status"])
    sites_action = int((status_df["Status"] == STATUS_ACTION).sum()) if not status_df.empty else 0
    sites_elevated = int((status_df["Status"] == STATUS_ELEVATED).sum()) if not status_df.empty else 0

    return {
        "total_mosquitoes": total_mosquitoes,
        "mosquitoes_per_trap_night": mptn,
        "successful_trap_nights": round(float(successful_nights), 1),
        "n_trap_sites": int(n_trap_sites),
        "treatments_completed": int(len(completed)),
        "treatments_scheduled": int(len(scheduled)),
        "area_treated_m2": round(float(area_treated), 0),
        "complaints_received": int(len(complaints)),
        "sites_action_required": sites_action,
        "sites_elevated": sites_elevated,
        "site_status_df": status_df,
    }
