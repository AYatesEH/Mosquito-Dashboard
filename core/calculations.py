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
    HIGH_LARVAE_COUNT_PER_DIP,
    HOTSPOT_MIN_HIGH_DIPS,
    REDOSE_LEAD_DAYS,
    REDOSE_ON_TRACK,
    REDOSE_DUE_SOON,
    REDOSE_OVERDUE,
    REDOSE_NOT_SCHEDULED,
    MOSQUITO_SEASON_START_MONTH,
    MOSQUITO_SEASON_END_MONTH,
    TODO_TASK_TRAPPING,
    TODO_TASK_TREATMENT,
    TODO_TASK_DIPPING,
    TODO_PRIORITY_HIGH,
    TODO_PRIORITY_MEDIUM,
    WEEKLY_TRAP_COUNT,
    COMPLAINT_INSPECTION_AGE_HIGH_DAYS,
    OBSERVATION_CATEGORY_DIP,
    TIME_ACTIVITY_TRAPPING,
    TIME_ACTIVITY_TREATMENT,
    TIME_ACTIVITY_COMPLAINT,
    TIME_ACTIVITY_DIPPING,
    COST_CATEGORY_DRY_ICE,
    COST_CATEGORY_LARVICIDE,
    BUDGET_CATEGORIES,
    BUDGET_CATEGORY_OFFICER_TIME,
    BUDGET_KEY_OFFICER_RATE,
    BUDGET_KEY_DRY_ICE_PRICE,
    BUDGET_KEY_DRY_ICE_KG_PER_NIGHT,
    BUDGET_KEY_BUDGET_PREFIX,
    QUANTITY_USED_UNITS,
)


# ===========================================================================
# MOSQUITO SEASON WINDOW (October -> May; see core/config.py)
# ===========================================================================

def is_in_mosquito_season(date, start_month: int = MOSQUITO_SEASON_START_MONTH,
                           end_month: int = MOSQUITO_SEASON_END_MONTH) -> bool:
    """True if `date` falls in an Oct-May mosquito-season month - i.e. NOT
    one of the June-September off-season months, when the program does not
    operate. `start_month > end_month` (10 > 5) models the wrap across the
    calendar year end; this still works correctly if either boundary is
    ever reconfigured to a range that doesn't wrap."""
    month = pd.Timestamp(date).month
    if start_month <= end_month:
        return start_month <= month <= end_month
    return month >= start_month or month <= end_month


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


_STATUS_SEVERITY = {
    STATUS_UNKNOWN: -1,
    STATUS_NORMAL: 0,
    STATUS_ELEVATED: 1,
    STATUS_ACTION: 2,
}


def site_map_status(site_id: str, catch_totals: pd.DataFrame, thresholds: pd.DataFrame,
                     hotspots_by_site: Optional[dict] = None,
                     as_of: Optional[pd.Timestamp] = None) -> dict:
    """
    Combines the raw trap-based current status (site_current_status) with this
    site's hotspot flags for MAP / AT-A-GLANCE DISPLAY: a site already flagged
    as a hotspot (from the combined trap + complaint + larvae dip signal model
    in identify_hotspots) shows at least that severity, even if its single
    most-recent trap reading alone wouldn't have triggered it - e.g. heavy
    complaint or larvae dip activity between trap visits, or a quiet latest
    trap night at an otherwise-active site. Never downgrades below the raw
    trap-based status. site_current_status's own return value (the literal
    latest-reading numbers used elsewhere, e.g. Site Detail) is untouched -
    this is purely an additional, display-oriented view built on top of it.

    hotspots_by_site: dict of Site_ID -> hotspot row (dict-like with a
    "Flags" list), as produced from identify_hotspots()'s output, e.g.
    {row["Site_ID"]: row for row in hotspots_df.to_dict("records")}.
    """
    info = site_current_status(site_id, catch_totals, thresholds, as_of=as_of)
    hotspots_by_site = hotspots_by_site or {}
    h = hotspots_by_site.get(site_id)
    if not h:
        return info

    flags = h.get("Flags") or []
    if any(f.startswith("Confirmed hotspot") for f in flags):
        target = STATUS_ACTION
    elif flags:
        target = STATUS_ELEVATED
    else:
        return info

    current_rank = _STATUS_SEVERITY.get(info["Status"], -1)
    if _STATUS_SEVERITY[target] > current_rank:
        info = {**info, "Status": target}
    return info


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
                       min_treatments: int = HOTSPOT_MIN_TREATMENTS,
                       larvae_dips: Optional[pd.DataFrame] = None,
                       min_high_dips: int = HOTSPOT_MIN_HIGH_DIPS) -> pd.DataFrame:
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
      - 'Elevated larvae dip counts': >= min_high_dips larvae dips above
         HIGH_LARVAE_COUNT_PER_DIP (core/config.py - the real APVMA-label
         ">10/dip" threshold) at the site in the lookback window. `larvae_dips`
         is optional (defaults to none, for callers that don't have the table
         to hand) so this stays backwards compatible.
      - 'Confirmed hotspot (<signals>)': added on top of the above whenever
         at least 2 of the 3 independent signals (trap, complaint, dip) fire
         for the same site in the same window - the signals corroborate each
         other, rather than one input alone driving the flag. <signals> lists
         which ones (e.g. 'trap + complaint', 'trap + dip',
         'trap + complaint + dip').
    A site can carry more than one flag. Also returns `Trap_Flagged`,
    `Complaint_Flagged` and `Dip_Flagged` boolean columns (independent of
    `Flags`' text) so a caller can filter sites by which signal(s) actually
    triggered - e.g. the Hotspots page's signal filter. All rule parameters
    are configurable (see core/config.py) rather than hard-coded thresholds
    on model output.
    """
    window_start = as_of - timedelta(weeks=lookback_weeks)
    window = catch_totals[(catch_totals["Deployment_DateTime"] >= window_start) &
                           (catch_totals["Deployment_DateTime"] <= as_of)].copy()
    if larvae_dips is None:
        larvae_dips = pd.DataFrame(columns=["Site_ID", "DateTime", "Larvae_Count"])

    all_site_ids = set(window["Site_ID"].unique().tolist())
    if not larvae_dips.empty:
        dips_window = larvae_dips[(larvae_dips["DateTime"] >= window_start) & (larvae_dips["DateTime"] <= as_of)]
        all_site_ids |= set(dips_window["Site_ID"].unique().tolist())
    else:
        dips_window = larvae_dips

    rows = []
    for site_id in all_site_ids:
        site_df = window[window["Site_ID"] == site_id]
        elevated_weeks = 0
        if not site_df.empty:
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
        site_dips = dips_window[dips_window["Site_ID"] == site_id] if not dips_window.empty else dips_window
        high_dips = site_dips[site_dips["Larvae_Count"] > HIGH_LARVAE_COUNT_PER_DIP] if not site_dips.empty else site_dips

        trap_flagged = elevated_weeks >= min_elevated_weeks or elevated_weeks == 1
        complaint_flagged = len(site_complaints) >= min_complaints
        dip_flagged = len(high_dips) >= min_high_dips

        flags = []
        if elevated_weeks >= min_elevated_weeks:
            flags.append("Persistent elevated activity")
        elif elevated_weeks == 1:
            flags.append("Single elevated spike")
        if complaint_flagged:
            flags.append("Repeated complaints")
        if len(site_treatments) >= min_treatments:
            flags.append("Repeatedly treated")
        if dip_flagged:
            flags.append("Elevated larvae dip counts")

        signals_flagged = []
        if trap_flagged:
            signals_flagged.append("trap")
        if complaint_flagged:
            signals_flagged.append("complaint")
        if dip_flagged:
            signals_flagged.append("dip")
        if len(signals_flagged) >= 2:
            flags.append(f"Confirmed hotspot ({' + '.join(signals_flagged)})")

        if flags:
            rows.append({
                "Site_ID": site_id,
                "Flags": flags,
                "Elevated_Weeks": elevated_weeks,
                "Complaints_In_Window": len(site_complaints),
                "Treatments_In_Window": len(site_treatments),
                "High_Dips_In_Window": len(high_dips),
                "Trap_Flagged": trap_flagged,
                "Complaint_Flagged": complaint_flagged,
                "Dip_Flagged": dip_flagged,
            })

    return pd.DataFrame(rows)


# ===========================================================================
# WEEKLY TO-DO LIST (stateless - recomputed fresh every time, see core/config.py)
# ===========================================================================

def _merge_duplicate_tasks(rows: list) -> list:
    """Combines multiple task rows for the same (Task_Type, Site_ID) into a
    single row, rather than showing several near-identical entries for the
    same site side by side - e.g. a site with two separate open complaints
    used to get two separate "Larvae dipping / inspection" tasks, one per
    complaint. The merged row keeps the higher priority, the earliest due
    date, every distinct Ref_ID (comma-separated) and every distinct reason
    (so nothing about why it was raised is lost). Rows with no Site_ID (there
    is nothing to key the merge on) are passed through unchanged."""
    groups: dict = {}
    order = []
    passthrough = []
    for row in rows:
        site_id = row.get("Site_ID")
        if site_id is None or site_id == "":
            passthrough.append(row)
            continue
        key = (row["Task_Type"], site_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    merged = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        task_type, site_id = key
        priority = TODO_PRIORITY_HIGH if any(r["Priority"] == TODO_PRIORITY_HIGH for r in group) \
            else TODO_PRIORITY_MEDIUM
        ref_ids = sorted({str(r["Ref_ID"]) for r in group if r.get("Ref_ID")})
        due_dates = [r["Due_Date"] for r in group if pd.notna(r.get("Due_Date"))]
        due_date = min(due_dates) if due_dates else None
        reasons = []
        for r in group:
            if r["Reason"] not in reasons:
                reasons.append(r["Reason"])
        merged.append({
            "Task_Type": task_type,
            "Site_ID": site_id,
            "Ref_ID": ", ".join(ref_ids) if ref_ids else None,
            "Priority": priority,
            "Reason": f"{len(group)} combined tasks - " + " | ".join(reasons),
            "Due_Date": due_date,
        })
    return merged + passthrough


def build_weekly_todo_list(
    week_start: pd.Timestamp,
    sites: pd.DataFrame,
    surv_events: pd.DataFrame,
    catch_totals: pd.DataFrame,
    complaints: pd.DataFrame,
    treatments: pd.DataFrame,
    products: pd.DataFrame,
    thresholds: pd.DataFrame,
    site_observations: pd.DataFrame,
    larvae_dips: pd.DataFrame,
    n_traps: int = WEEKLY_TRAP_COUNT,
) -> pd.DataFrame:
    """
    Builds the operational priority list (weekly trap placement, larvicide
    treatments, larvae dipping/inspection) for the week starting `week_start`
    (a Monday).

    This is deliberately a PURE, STATELESS view, computed fresh from current
    data every time it's called - like treatment_redose_schedule and
    identify_hotspots, which it reuses rather than duplicating. There is no
    persisted "to-do" table and no manual "mark done" action: each row is
    produced by a rule ("this many of this week's traps still need a site",
    "this site's control window has lapsed", "this complaint/hotspot hasn't
    been inspected yet"), and a task simply stops being generated the moment
    new data makes its rule false. That's why logging the related surveillance
    event, treatment, or field observation IS how a task clears itself - there
    is nothing else to click.

    Returns columns: Task_Type, Site_ID, Ref_ID, Priority, Reason, Due_Date.
    """
    week_start = pd.Timestamp(week_start).normalize()
    week_end = week_start + timedelta(days=6)
    as_of = week_end

    rows = []

    # identify_hotspots is reused by both the trap-placement and treatment
    # sections below, so it's computed once, here, rather than twice.
    hotspots = identify_hotspots(catch_totals, complaints, treatments, thresholds, as_of=as_of,
                                  larvae_dips=larvae_dips)
    hotspot_by_site = {h["Site_ID"]: h for h in hotspots.to_dict("records")} if not hotspots.empty else {}

    def _dipped_since(site_id: str, since: pd.Timestamp, until: Optional[pd.Timestamp] = None) -> bool:
        """True if either a qualitative 'Larvae dip / inspection' field
        observation OR an actual larvae_dips.csv count has been logged for
        this site on/after `since` (and, if given, on/before `until`) - the
        two are independent write paths (Surveillance page's Add Dip Data
        tab vs. the To Do List's quick-log action) that both count as "this
        site has been checked"."""
        obs = site_observations[
            (site_observations["Site_ID"] == site_id) &
            (site_observations["Observation_Category"] == OBSERVATION_CATEGORY_DIP) &
            (site_observations["DateTime"] >= since)
        ]
        dips = larvae_dips[(larvae_dips["Site_ID"] == site_id) & (larvae_dips["DateTime"] >= since)] \
            if not larvae_dips.empty else larvae_dips
        if until is not None:
            obs = obs[obs["DateTime"] <= until]
            if not dips.empty:
                dips = dips[dips["DateTime"] <= until]
        return not obs.empty or not dips.empty

    # --- 1. TRAP PLACEMENT ---------------------------------------------------
    # Only `n_traps` physical CO2 traps are available (set out for one night
    # and picked up the next morning) - they're moved to new sites each week
    # rather than left permanently installed, so this recommends WHICH sites
    # should get this week's traps rather than tracking a per-trap "overdue
    # for a check" cycle. Sites are ranked by hotspot priority (reusing
    # identify_hotspots above): a confirmed trap+complaint hotspot first,
    # then persistent elevated activity, then any other flag, then - for the
    # remaining slots once flagged sites run out - the least-recently-trapped
    # candidate sites, so the whole network still gets rotated through over
    # time rather than only ever trapping the same few sites. The list only
    # ever asks for as many sites as there are traps still unplaced THIS
    # week: once `n_traps` distinct sites have an actual surveillance event
    # logged for the week, the recommendation clears itself completely -
    # there's nothing to click, logging the trap catch IS what clears it.
    # Candidate sites are ALL active sites, not a fixed trap-site list - the
    # traps themselves are portable equipment (trap_sites.csv has no
    # Site_ID), so any active site is a fair place to put one this week.
    candidate_sites = sorted(
        sites.loc[sites["Status"] == "Active", "Site_ID"].dropna().unique().tolist()
    )
    week_events = surv_events[(surv_events["Deployment_DateTime"] >= week_start) &
                               (surv_events["Deployment_DateTime"] <= as_of)]
    trapped_this_week = set(week_events["Site_ID"].dropna().unique().tolist())
    remaining_slots = max(n_traps - len(trapped_this_week), 0)

    if remaining_slots > 0:
        def _trap_priority_tier(site_id: str) -> int:
            h = hotspot_by_site.get(site_id)
            if h is None:
                return 3
            flags = h["Flags"]
            if any(f.startswith("Confirmed hotspot") for f in flags):
                return 0
            if "Persistent elevated activity" in flags:
                return 1
            return 2

        def _last_trapped(site_id: str) -> pd.Timestamp:
            # Only events UP TO this week (as_of) count as "last trapped" - a week
            # being assessed in the past must ignore events that hadn't happened
            # yet at that point, or the rotation fallback would rank sites using
            # trapping that's actually still in their future.
            site_events = surv_events.loc[
                (surv_events["Site_ID"] == site_id) & (surv_events["Deployment_DateTime"] <= as_of),
                "Deployment_DateTime",
            ]
            return site_events.max() if not site_events.empty and site_events.notna().any() else pd.Timestamp.min

        ranked = sorted(
            (s for s in candidate_sites if s not in trapped_this_week),
            key=lambda s: (_trap_priority_tier(s), _last_trapped(s)),
        )
        for site_id in ranked[:remaining_slots]:
            h = hotspot_by_site.get(site_id)
            if h is not None:
                high = (any(f.startswith("Confirmed hotspot") for f in h["Flags"]) or
                        "Persistent elevated activity" in h["Flags"])
                rows.append({
                    "Task_Type": TODO_TASK_TRAPPING, "Site_ID": site_id, "Ref_ID": None,
                    "Priority": TODO_PRIORITY_HIGH if high else TODO_PRIORITY_MEDIUM,
                    "Reason": f"Priority site for this week's {n_traps} traps - " + "; ".join(h["Flags"]) + ".",
                    "Due_Date": as_of,
                })
            else:
                last_trapped = _last_trapped(site_id)
                last_str = "never" if last_trapped == pd.Timestamp.min else str(last_trapped.date())
                rows.append({
                    "Task_Type": TODO_TASK_TRAPPING, "Site_ID": site_id, "Ref_ID": None,
                    "Priority": TODO_PRIORITY_MEDIUM,
                    "Reason": f"No current hotspot signal - selected on rotation (last trapped: {last_str}).",
                    "Due_Date": as_of,
                })

    # --- 2. LARVICIDE TREATMENT ---------------------------------------------
    # Re-dose an existing, tracked treatment once its control window is due
    # soon or has lapsed (reuses treatment_redose_schedule directly); on top
    # of that, flag a FIRST treatment for hotspot sites with persistent trap
    # activity (or a confirmed hotspot), or with an elevated larvae dip count
    # on its own - a real measured larval count above the label's "high"
    # threshold is itself an actionable signal, not something that needs
    # trap/complaint corroboration first - that don't already have a tracked
    # treatment covering them.
    redose = treatment_redose_schedule(treatments, products, as_of=as_of)
    sites_with_current_treatment = set(redose["Site_ID"].tolist()) if not redose.empty else set()
    if not redose.empty:
        for _, r in redose.iterrows():
            if r["Status"] == REDOSE_OVERDUE:
                rows.append({
                    "Task_Type": TODO_TASK_TREATMENT, "Site_ID": r["Site_ID"], "Ref_ID": r["Treatment_ID"],
                    "Priority": TODO_PRIORITY_HIGH,
                    "Reason": f"Control window from the last treatment ({r['Treatment_Date'].date()}) "
                              f"has lapsed - re-dose overdue.",
                    "Due_Date": r["Redose_Due"],
                })
            elif r["Status"] == REDOSE_DUE_SOON:
                due_str = r["Redose_Due"].date() if pd.notna(r["Redose_Due"]) else "soon"
                rows.append({
                    "Task_Type": TODO_TASK_TREATMENT, "Site_ID": r["Site_ID"], "Ref_ID": r["Treatment_ID"],
                    "Priority": TODO_PRIORITY_MEDIUM,
                    "Reason": f"Control window closing soon - re-dose due {due_str}.",
                    "Due_Date": r["Redose_Due"],
                })

    if not hotspots.empty:
        for _, h in hotspots.iterrows():
            if h["Site_ID"] in sites_with_current_treatment:
                continue  # already has a tracked treatment - the re-dose rule above covers it
            confirmed = any(f.startswith("Confirmed hotspot") for f in h["Flags"])
            persistent = h["Elevated_Weeks"] >= HOTSPOT_MIN_ELEVATED_WEEKS
            if (h["Trap_Flagged"] and (persistent or confirmed)) or h["Dip_Flagged"]:
                rows.append({
                    "Task_Type": TODO_TASK_TREATMENT, "Site_ID": h["Site_ID"], "Ref_ID": None,
                    "Priority": TODO_PRIORITY_HIGH if (confirmed or h["Dip_Flagged"]) else TODO_PRIORITY_MEDIUM,
                    "Reason": "Flagged hotspot with no current tracked treatment - " + "; ".join(h["Flags"]) + ".",
                    "Due_Date": as_of,
                })

    # --- 3. LARVAE DIPPING / INSPECTION -------------------------------------
    # Unresolved complaints become an inspection task once they've been open
    # a while (High past COMPLAINT_INSPECTION_AGE_HIGH_DAYS); the task clears
    # the moment a "Larvae dip / inspection" field observation is logged for
    # that site on or after the complaint's received date.
    unresolved = complaints[
        complaints["Investigation_Status"].isin(["Received", "Under Investigation"]) &
        complaints["Date_Received"].notna() &
        (complaints["Date_Received"] <= as_of)
    ]
    dipping_sites_covered = set()
    for _, c in unresolved.iterrows():
        site_id = c["Site_ID"] if pd.notna(c.get("Site_ID")) and c.get("Site_ID") != "" else None
        if site_id is not None and _dipped_since(site_id, c["Date_Received"]):
            continue  # already inspected since the complaint came in
        age_days = (as_of - c["Date_Received"]).days
        priority = TODO_PRIORITY_HIGH if age_days >= COMPLAINT_INSPECTION_AGE_HIGH_DAYS else TODO_PRIORITY_MEDIUM
        rows.append({
            "Task_Type": TODO_TASK_DIPPING, "Site_ID": site_id, "Ref_ID": c["Complaint_ID"],
            "Priority": priority,
            "Reason": f"Complaint received {c['Date_Received'].date()} ({age_days}d ago), not yet inspected.",
            "Due_Date": c["Date_Received"] + timedelta(days=COMPLAINT_INSPECTION_AGE_HIGH_DAYS),
        })
        if site_id is not None:
            dipping_sites_covered.add(site_id)

    # Hotspot sites flagged by only ONE signal (a single trap spike with no
    # complaint, or a complaint alone with no trap activity) get a dipping/
    # inspection task first, to confirm before a treatment is scheduled -
    # unless they're already covered by a treatment task above or a
    # complaint-driven dipping task just added, or a dip/inspection has
    # already been logged there within the hotspot lookback window.
    if not hotspots.empty:
        already_treatment_sites = {row["Site_ID"] for row in rows if row["Task_Type"] == TODO_TASK_TREATMENT}
        window_start = as_of - timedelta(weeks=HOTSPOT_LOOKBACK_WEEKS)
        for _, h in hotspots.iterrows():
            site_id = h["Site_ID"]
            if site_id in already_treatment_sites or site_id in dipping_sites_covered:
                continue
            single_spike_only = h["Elevated_Weeks"] == 1 and not h["Complaint_Flagged"]
            complaint_only = h["Complaint_Flagged"] and not h["Trap_Flagged"]
            if not (single_spike_only or complaint_only):
                continue
            if _dipped_since(site_id, window_start, until=as_of):
                continue
            rows.append({
                "Task_Type": TODO_TASK_DIPPING, "Site_ID": site_id, "Ref_ID": None,
                "Priority": TODO_PRIORITY_MEDIUM,
                "Reason": "Flagged by a single signal - confirm by dipping/inspecting before scheduling "
                          "treatment: " + "; ".join(h["Flags"]) + ".",
                "Due_Date": as_of,
            })

    rows = _merge_duplicate_tasks(rows)

    columns = ["Task_Type", "Site_ID", "Ref_ID", "Priority", "Reason", "Due_Date"]
    todo = pd.DataFrame(rows, columns=columns)
    if todo.empty:
        return todo
    priority_order = {TODO_PRIORITY_HIGH: 0, TODO_PRIORITY_MEDIUM: 1}
    todo["_priority_sort"] = todo["Priority"].map(priority_order)
    todo = todo.sort_values(["_priority_sort", "Task_Type", "Site_ID"]).drop(columns="_priority_sort")
    return todo.reset_index(drop=True)


def resolve_trap_id(trap_sites: pd.DataFrame, trap_type: str) -> Optional[str]:
    """
    Picks a Trap_ID to record against a new surveillance event, given only
    the trap TYPE an officer selected on the "Add Trap Data" form.

    trap_sites.csv is a plain equipment register (Trap_ID, Trap_Type,
    Trap_Status, ...) with no location of its own - traps are portable and
    moved to whichever site needs one each week, so the form never asks an
    officer to pick a specific trap code (e.g. "TRP-001"), only a location
    and a type. Trap_ID still exists behind the scenes purely so
    surveillance_events keeps a valid equipment reference (see
    data_quality_report's Trap_ID check) - it's an internal key, never shown.

    Prefers an Active trap of the requested type; falls back to any Active
    trap if none of that exact type is registered; returns None if there is
    no active equipment at all.
    """
    active = trap_sites[trap_sites["Trap_Status"] == "Active"]
    if active.empty:
        return None
    matching = active[active["Trap_Type"] == trap_type]
    pool = matching if not matching.empty else active
    return str(pool.iloc[0]["Trap_ID"])


# ===========================================================================
# DATA QUALITY
# ===========================================================================

def data_quality_report(sites, trap_sites, surv_events, surv_results, treatments, complaints,
                         larvae_dips: Optional[pd.DataFrame] = None) -> pd.DataFrame:
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

    valid_site_ids = set(sites["Site_ID"])

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

    # Larvae dips: negative counts, orphaned site refs
    if larvae_dips is not None:
        for _, r in larvae_dips.iterrows():
            if r["Site_ID"] not in valid_site_ids:
                add("larvae_dips", r["Dip_ID"], "High", f"References Site_ID '{r['Site_ID']}' not found in sites.")
            if pd.notna(r["Larvae_Count"]) and r["Larvae_Count"] < 0:
                add("larvae_dips", r["Dip_ID"], "High", "Negative larvae count.")

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


# ===========================================================================
# BUDGET: OFFICER TIME, DRY ICE, LARVICIDE
# ===========================================================================
# Pure functions over the three budget tables (time_entries, cost_entries,
# budget_settings) plus the operational tables they're correlated with
# (surveillance events, treatments, complaints, dips). Everything is scoped to
# ONE season, because budgets are per season. Costs are whatever basis finance
# uses (the app labels them ex-GST); officer time is an internal allocation
# (hours x hourly rate), not cash out of the door - the Budget page says so.

def latest_budget_settings(settings: pd.DataFrame, season: str) -> dict:
    """{Key: float} for one season. Settings are append-only, so for each key
    the most recently created row wins (ties broken by Setting_ID, which is
    sequential)."""
    if settings is None or settings.empty:
        return {}
    df = settings[settings["Season"] == season].dropna(subset=["Key", "Value"])
    if df.empty:
        return {}
    df = df.sort_values(["Created_Date", "Setting_ID"], kind="stable")
    return {k: float(v) for k, v in df.groupby("Key")["Value"].last().items()}


def season_elapsed_fraction(season_start: pd.Timestamp, season_end: pd.Timestamp, as_of: pd.Timestamp) -> float:
    total = (season_end - season_start).total_seconds()
    if total <= 0:
        return 1.0
    return float(min(max((as_of - season_start).total_seconds() / total, 0.0), 1.0))


def officer_time_summary(time_entries: pd.DataFrame, season: str, hourly_rate: float) -> dict:
    """Hours and (hours x rate) cost for one season, broken down by activity,
    officer and week (week = the Monday starting it)."""
    empty = {"total_hours": 0.0, "total_cost": 0.0,
             "by_activity": pd.DataFrame(columns=["Activity", "Hours", "Cost"]),
             "by_officer": pd.DataFrame(columns=["Officer", "Hours", "Cost"]),
             "by_week": pd.DataFrame(columns=["Week", "Hours", "Cost"])}
    if time_entries is None or time_entries.empty:
        return empty
    df = time_entries[time_entries["Season"] == season].dropna(subset=["Hours"]).copy()
    if df.empty:
        return empty
    rate = float(hourly_rate or 0.0)

    def _agg(col):
        out = df.groupby(col, as_index=False)["Hours"].sum()
        out["Cost"] = out["Hours"] * rate
        return out.sort_values("Hours", ascending=False).reset_index(drop=True)

    df["Week"] = df["Date"].dt.to_period("W-SUN").dt.start_time
    by_week = df.groupby("Week", as_index=False)["Hours"].sum()
    by_week["Cost"] = by_week["Hours"] * rate
    return {"total_hours": float(df["Hours"].sum()), "total_cost": float(df["Hours"].sum()) * rate,
            "by_activity": _agg("Activity"), "by_officer": _agg("Officer"), "by_week": by_week}


def season_spend(season: str, settings: dict, time_entries: pd.DataFrame, cost_entries: pd.DataFrame) -> dict:
    """{budget category: spend to date}. Officer time = hours x the season's
    hourly rate; the rest = the sum of logged purchases/invoices."""
    spend = {c: 0.0 for c in BUDGET_CATEGORIES}
    spend[BUDGET_CATEGORY_OFFICER_TIME] = officer_time_summary(
        time_entries, season, settings.get(BUDGET_KEY_OFFICER_RATE, 0.0))["total_cost"]
    if cost_entries is not None and not cost_entries.empty:
        ce = cost_entries[cost_entries["Season"] == season]
        for cat, total in ce.groupby("Category")["Total_Cost"].sum().items():
            if cat in spend:
                spend[cat] = float(total)
    return spend


# Categories whose spend is steady enough that a straight-line run-rate is a
# fair rough projection. Larvicide is bought in lumps early and used according
# to rainfall/breeding, so a run-rate would mislead - no projection shown.
_PROJECTABLE = {BUDGET_CATEGORY_OFFICER_TIME, COST_CATEGORY_DRY_ICE}
MIN_ELAPSED_FOR_PROJECTION = 0.15


def budget_summary(season: str, settings: dict, time_entries: pd.DataFrame, cost_entries: pd.DataFrame,
                   season_start: pd.Timestamp, season_end: pd.Timestamp, as_of: pd.Timestamp) -> pd.DataFrame:
    """One row per budget category: Budget, Spent, Remaining, Pct_Used and
    (officer time + dry ice only, once >=15% of the season has elapsed) a
    rough straight-line Projected season-end figure."""
    spend = season_spend(season, settings, time_entries, cost_entries)
    elapsed = season_elapsed_fraction(season_start, season_end, as_of)
    rows = []
    for cat in BUDGET_CATEGORIES:
        budget = settings.get(BUDGET_KEY_BUDGET_PREFIX + cat)
        spent = spend[cat]
        projected = (spent / elapsed) if (cat in _PROJECTABLE and elapsed >= MIN_ELAPSED_FOR_PROJECTION) else None
        rows.append({
            "Category": cat,
            "Budget": budget,
            "Spent": spent,
            "Remaining": (budget - spent) if budget is not None else None,
            "Pct_Used": (100.0 * spent / budget) if budget else None,
            "Projected": projected,
            "Projected_Over_Budget": (projected > budget) if (projected is not None and budget) else None,
        })
    return pd.DataFrame(rows)


def dry_ice_analysis(season: str, surv_events: pd.DataFrame, cost_entries: pd.DataFrame, settings: dict) -> dict:
    """Dry ice purchased vs what the season's trapping implies it needed.
    Trap-nights here are ALL deployed traps (a failed or invalid trap still
    burned its dry ice), unlike abundance statistics which use only usable
    events. Only purchases recorded in kg count towards the kg figures."""
    ev = surv_events[surv_events["Season"] == season] if surv_events is not None and not surv_events.empty \
        else pd.DataFrame(columns=["Deployment_DateTime", "Retrieval_DateTime"])
    nights = float(compute_trap_nights(ev).fillna(1.0).clip(lower=1.0).sum()) if len(ev) else 0.0
    purchases = pd.DataFrame(columns=["Quantity", "Quantity_Unit", "Total_Cost"])
    if cost_entries is not None and not cost_entries.empty:
        purchases = cost_entries[(cost_entries["Season"] == season) & (cost_entries["Category"] == COST_CATEGORY_DRY_ICE)]
    kg_bought = float(purchases.loc[purchases["Quantity_Unit"].str.lower() == "kg", "Quantity"].sum())
    spend = float(purchases["Total_Cost"].sum())
    kg_per_night = settings.get(BUDGET_KEY_DRY_ICE_KG_PER_NIGHT)
    price = settings.get(BUDGET_KEY_DRY_ICE_PRICE)
    est_kg = nights * kg_per_night if kg_per_night else None
    return {
        "trap_events": int(len(ev)), "trap_nights": nights,
        "kg_bought": kg_bought, "spend": spend,
        "est_kg_needed": est_kg,
        "est_cost": (est_kg * price) if (est_kg is not None and price) else None,
        "kg_surplus": (kg_bought - est_kg) if est_kg is not None else None,
        "actual_kg_per_trap_night": (kg_bought / nights) if nights else None,
        "actual_cost_per_trap_night": (spend / nights) if nights else None,
        "avg_price_per_kg": (spend / kg_bought) if kg_bought else None,
        "non_kg_rows": int((purchases["Quantity_Unit"].str.lower() != "kg").sum()),
    }


def larvicide_analysis(season: str, cost_entries: pd.DataFrame, treatments: pd.DataFrame,
                       products: pd.DataFrame) -> pd.DataFrame:
    """Per product: what was bought, what treatments used, the value of what
    was used (at that product's average purchase price), and an estimate of
    stock on hand. Quantities are only comparable when the purchase unit
    matches how treatments record use (QUANTITY_USED_UNITS: g for pellets,
    briquets for briquets); purchases in any other unit are excluded and
    counted in Excluded_Rows so a unit mix-up is visible, not silent."""
    cols = ["Product_ID", "Product_Name", "Unit", "Purchased_Qty", "Purchased_Cost", "Unit_Cost",
            "Used_Qty", "Used_Value", "On_Hand_Est", "Area_Treated_M2", "Cost_Per_1000_M2", "Excluded_Rows"]
    rows = []
    ce = cost_entries[(cost_entries["Season"] == season) & (cost_entries["Category"] == COST_CATEGORY_LARVICIDE)] \
        if cost_entries is not None and not cost_entries.empty else pd.DataFrame(columns=["Product_ID"])
    tr = treatments[(treatments["Season"] == season) & (treatments["Treatment_Status"] == "Completed")] \
        if treatments is not None and not treatments.empty else pd.DataFrame(columns=["Product_ID"])
    product_ids = [p for p in products["Product_ID"].tolist() if p in QUANTITY_USED_UNITS]
    for pid in product_ids:
        unit = QUANTITY_USED_UNITS[pid]
        name = products.loc[products["Product_ID"] == pid, "Product_Name"].iloc[0]
        pc = ce[ce["Product_ID"] == pid] if "Product_ID" in ce.columns and len(ce) else ce.iloc[0:0]
        ok = pc[pc["Quantity_Unit"] == unit] if len(pc) else pc
        qty, cost = float(ok["Quantity"].sum()) if len(ok) else 0.0, float(ok["Total_Cost"].sum()) if len(ok) else 0.0
        unit_cost = (cost / qty) if qty else None
        pt = tr[tr["Product_ID"] == pid] if len(tr) else tr
        used = float(pt["Quantity_Used"].fillna(0).sum()) if len(pt) else 0.0
        area = float(pt["Area_Treated_M2"].fillna(0).sum()) if len(pt) else 0.0
        value = (used * unit_cost) if unit_cost is not None else None
        rows.append({
            "Product_ID": pid, "Product_Name": name, "Unit": unit,
            "Purchased_Qty": qty, "Purchased_Cost": cost, "Unit_Cost": unit_cost,
            "Used_Qty": used, "Used_Value": value, "On_Hand_Est": qty - used,
            "Area_Treated_M2": area,
            "Cost_Per_1000_M2": (value / area * 1000.0) if (value is not None and area) else None,
            "Excluded_Rows": int(len(pc) - len(ok)),
        })
    return pd.DataFrame(rows, columns=cols)


def cost_per_activity(season: str, hourly_rate: float, time_entries: pd.DataFrame, surv_events: pd.DataFrame,
                      complaints: pd.DataFrame, treatments: pd.DataFrame, larvae_dips: pd.DataFrame,
                      dry_ice: dict, larvicide: pd.DataFrame) -> pd.DataFrame:
    """Ties officer hours and materials back to the work they paid for -
    cost per trap deployment, per complaint investigated, per completed
    treatment, per dip - so a budget conversation can be about unit costs,
    not just totals. Rows with nothing to divide by are omitted."""
    def hours(activity):
        if time_entries is None or time_entries.empty:
            return 0.0
        te = time_entries[(time_entries["Season"] == season) & (time_entries["Activity"] == activity)]
        return float(te["Hours"].fillna(0).sum())

    def count(df, status_col=None, status=None):
        if df is None or df.empty:
            return 0
        d = df[df["Season"] == season]
        if status_col:
            d = d[d[status_col] == status]
        return int(len(d))

    rate = float(hourly_rate or 0.0)
    rows = []
    n = count(surv_events)
    if n:
        h = hours(TIME_ACTIVITY_TRAPPING)
        rows.append({"Activity": "Per trap deployment", "Count": n, "Officer_Hours": h,
                     "Hours_Each": h / n, "Officer_Cost_Each": h * rate / n,
                     "Materials_Cost_Each": dry_ice["spend"] / n,
                     "Materials": "dry ice"})
    n = count(complaints)
    if n:
        h = hours(TIME_ACTIVITY_COMPLAINT)
        rows.append({"Activity": "Per complaint investigated", "Count": n, "Officer_Hours": h,
                     "Hours_Each": h / n, "Officer_Cost_Each": h * rate / n,
                     "Materials_Cost_Each": 0.0, "Materials": "-"})
    n = count(treatments, "Treatment_Status", "Completed")
    if n:
        h = hours(TIME_ACTIVITY_TREATMENT)
        used_value = float(larvicide["Used_Value"].fillna(0).sum()) if len(larvicide) else 0.0
        rows.append({"Activity": "Per completed larvicide treatment", "Count": n, "Officer_Hours": h,
                     "Hours_Each": h / n, "Officer_Cost_Each": h * rate / n,
                     "Materials_Cost_Each": used_value / n, "Materials": "larvicide used (at purchase price)"})
    n = count(larvae_dips)
    if n:
        h = hours(TIME_ACTIVITY_DIPPING)
        rows.append({"Activity": "Per larvae dip", "Count": n, "Officer_Hours": h,
                     "Hours_Each": h / n, "Officer_Cost_Each": h * rate / n,
                     "Materials_Cost_Each": 0.0, "Materials": "-"})
    return pd.DataFrame(rows, columns=["Activity", "Count", "Officer_Hours", "Hours_Each",
                                        "Officer_Cost_Each", "Materials_Cost_Each", "Materials"])
