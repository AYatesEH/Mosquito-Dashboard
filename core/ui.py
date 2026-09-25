"""
ui.py

Shared UI building blocks used by every page: cached data loading, global
filter controls (persisted in st.session_state so they carry across pages),
KPI card rendering, and app-wide styling.

This is the ONLY module that should import streamlit AND core.data_source /
core.calculations together - individual pages should call into here rather
than re-implementing filter widgets or cache decorators themselves.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from core.data_source import get_repository
from core import calculations as calc
from core import weather_api
from core.config import (
    APP_TITLE, SAMPLE_DATA_BANNER, STATUS_COLOURS, STATUS_UNKNOWN,
)

SEASON_BOUNDS = {
    "2023-24": (pd.Timestamp("2023-10-01"), pd.Timestamp("2024-04-30")),
    "2024-25": (pd.Timestamp("2024-10-01"), pd.Timestamp("2025-04-30")),
    "2025-26": (pd.Timestamp("2025-10-01"), pd.Timestamp("2026-04-30")),
}
DEFAULT_SEASON = "2025-26"


# ===========================================================================
# CACHED DATA LOADING
# ===========================================================================

@st.cache_data(show_spinner=False)
def load_raw_tables(data_version: str = "") -> dict:
    """
    Loads every table once per data version and caches it. This is the single
    point where Streamlit's cache wraps the data-access layer - pages never
    call core.data_source directly. `data_version` is only a cache key (see
    DataRepository.data_version): without it, a running app would keep
    serving tables cached before a data/schema change (e.g. the
    Area_Treated_Ha -> Area_Treated_M2 rename) and pages would hit KeyErrors.
    """
    repo = get_repository()
    return {
        "sites": repo.get_sites(),
        "trap_sites": repo.get_trap_sites(),
        "surv_events": repo.get_surveillance_events(),
        "surv_results": repo.get_surveillance_results(),
        "treatments": repo.get_treatments(),
        "products": repo.get_products(),
        "complaints": repo.get_complaints(),
        "environmental": repo.get_environmental_data(),
        "species": repo.get_species_reference(),
        "observations": repo.get_site_observations(),
        "users": repo.get_users(),
        "thresholds": repo.get_action_thresholds(),
        "targets": repo.get_program_targets(),
    }


@st.cache_data(show_spinner=False)
def load_catch_totals(_surv_events: pd.DataFrame, _surv_results: pd.DataFrame, data_version: str = "") -> pd.DataFrame:
    """Cached wrapper around calc.event_catch_totals (the most expensive/most reused computation)."""
    return calc.event_catch_totals(_surv_events, _surv_results)


def get_data() -> dict:
    """Convenience accessor: raw tables + derived catch_totals in one dict."""
    version = get_repository().data_version()
    data = load_raw_tables(version)
    data["catch_totals"] = load_catch_totals(data["surv_events"], data["surv_results"], version)
    return data


# ===========================================================================
# WRITES (add a new treatment/complaint/surveillance record)
# ===========================================================================
# Every page's "Add ..." form should go through these, never call
# get_repository() directly - this is the one place that also clears the
# cache afterward, so the write shows up everywhere on the very next rerun
# (Streamlit reruns the whole script after a form submit/button click, so no
# extra refresh step is needed). See the write-method docstrings in
# core/data_source.py for the current CSV backend's single-user/non-durable
# caveat - swapping in a real backend later only touches that one file.

def invalidate_data_cache():
    load_raw_tables.clear()
    load_catch_totals.clear()


def add_treatment(row: dict) -> str:
    new_id = get_repository().add_treatment(row)
    invalidate_data_cache()
    return new_id


def add_complaint(row: dict) -> str:
    new_id = get_repository().add_complaint(row)
    invalidate_data_cache()
    return new_id


def add_surveillance_event(row: dict) -> str:
    new_id = get_repository().add_surveillance_event(row)
    invalidate_data_cache()
    return new_id


def add_surveillance_result(row: dict) -> str:
    new_id = get_repository().add_surveillance_result(row)
    invalidate_data_cache()
    return new_id


def infer_season(d) -> str:
    """Which SEASON_BOUNDS key a date falls in - used to fill the Season
    column on a new record without asking the officer to pick it separately.
    Falls back to the season whose start date is closest, if the date is
    outside every modelled season's range (e.g. mid-winter, between seasons)."""
    ts = pd.Timestamp(d)
    for season, (start, end) in SEASON_BOUNDS.items():
        if start <= ts <= end:
            return season
    return min(SEASON_BOUNDS.items(), key=lambda kv: abs((ts - kv[1][0]).days))[0]


# ===========================================================================
# STYLING
# ===========================================================================

def apply_page_style():
    st.set_page_config(page_title=APP_TITLE, layout="wide", page_icon="\U0001F9DF")
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1300px;}
        div[data-testid="stMetricValue"] {font-size: 1.7rem; font-weight: 600;}
        div[data-testid="stMetric"] {
            background-color: #FAFAFA; border: 1px solid #E5E5E5; border-radius: 8px;
            padding: 0.8rem 1rem 0.4rem 1rem;
        }
        h1, h2, h3 {font-weight: 600; letter-spacing: -0.01em;}
        .status-badge {
            display: inline-block; padding: 0.15rem 0.6rem; border-radius: 12px;
            color: white; font-size: 0.82rem; font-weight: 600;
        }
        .sample-banner {
            background-color: #FFF4E5; border: 1px solid #F2A900; border-radius: 6px;
            padding: 0.5rem 0.9rem; font-size: 0.85rem; color: #6B4E00; margin-bottom: 0.8rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sample_data_banner():
    st.markdown(f'<div class="sample-banner">{SAMPLE_DATA_BANNER}</div>', unsafe_allow_html=True)


def status_badge_html(status: str, colours: Optional[dict] = None) -> str:
    colour_map = colours if colours is not None else STATUS_COLOURS
    colour = colour_map.get(status, STATUS_COLOURS[STATUS_UNKNOWN])
    return f'<span class="status-badge" style="background-color:{colour};">{status}</span>'


# ===========================================================================
# LIVE WEATHER (Open-Meteo, via core/weather_api.py)
# ===========================================================================
# Cached here (not in weather_api.py itself) because caching policy is a UI
# concern - see weather_api.py's module docstring. Short TTL for "current
# conditions" (changes constantly); longer TTL for a specific date's daily
# figures (a past date's rainfall/temperature won't change once reported,
# and even a forecast for a near-future date doesn't need refreshing every
# few seconds). NOTE: this calls the live Open-Meteo API over the network -
# it was written and syntax-checked but could not be exercised end-to-end in
# the sandbox this was built in (outbound network there is restricted to
# GitHub/package registries only) - the deployed Streamlit Cloud app has
# normal internet access, so this needs its first real run there to confirm.
# Every caller MUST check for an "error" key before reading weather fields.

@st.cache_data(show_spinner=False, ttl=600)
def get_current_weather(lat: float, lon: float) -> dict:
    return weather_api.fetch_current_conditions(lat, lon)


@st.cache_data(show_spinner=False, ttl=3600)
def get_weather_for_date(lat: float, lon: float, target_date) -> dict:
    return weather_api.fetch_weather_for_date(lat, lon, target_date)


@st.cache_data(show_spinner=False, ttl=1200)
def get_tide_indicator(lat: float, lon: float) -> dict:
    """Rough rising/falling tide indicator - see weather_api.fetch_tide_indicator's
    docstring for the important accuracy caveat, which is also returned in
    the result under 'caveat' so callers surface it, not just log it."""
    return weather_api.fetch_tide_indicator(lat, lon)


# ===========================================================================
# GLOBAL FILTERS (persisted in session_state, shared across all pages)
# ===========================================================================

def _season_default_end(season: str, surv_events: Optional[pd.DataFrame]) -> "pd.Timestamp":
    """
    The default upper bound for the date-range filter is the LATER of nothing
    and the actual latest surveillance data available for that season, capped
    at the season's nominal end. This matters for an in-progress ("current")
    season: its nominal end (e.g. 30 Apr) is months beyond the last real data
    point, and defaulting the filter to the nominal end would make
    lookback-window features (e.g. Hotspots) anchor "as of" a date with no
    data anywhere near it. The date_input's max_value still allows widening
    to the full nominal season end if the user wants to.
    """
    nominal_start, nominal_end = SEASON_BOUNDS[season]
    if surv_events is None or surv_events.empty:
        return nominal_end
    season_events = surv_events[surv_events["Season"] == season]
    if season_events.empty:
        return nominal_end
    latest = season_events["Deployment_DateTime"].max()
    if pd.isna(latest):
        return nominal_end
    return min(latest, nominal_end)


def _init_filter_state(surv_events: Optional[pd.DataFrame]):
    if "filters" not in st.session_state:
        start, _ = SEASON_BOUNDS[DEFAULT_SEASON]
        default_end = _season_default_end(DEFAULT_SEASON, surv_events)
        st.session_state["filters"] = {
            "season": DEFAULT_SEASON,
            "date_range": (start.date(), default_end.date()),
            "site_ids": [],       # empty = all sites
            "species_codes": [],  # empty = all species
        }


def render_global_filters(data: dict) -> dict:
    """
    Renders the season / date range / site / species filters in the sidebar
    and returns the current filter selections as a dict. Selections persist
    in st.session_state so every page shares the same filter state.

    `data` is the dict returned by ui.get_data() - this function reads
    sites/species/surv_events from it rather than taking them as separate
    parameters, so every page can call `ui.render_global_filters(data)`
    identically.
    """
    sites, species, surv_events = data["sites"], data["species"], data.get("surv_events")
    _init_filter_state(surv_events)
    f = st.session_state["filters"]

    st.sidebar.markdown(f"### {APP_TITLE}")
    st.sidebar.caption("Environmental Health - Prototype")
    st.sidebar.divider()
    st.sidebar.markdown("**Filters**")

    season_options = list(SEASON_BOUNDS.keys())
    season = st.sidebar.selectbox(
        "Season", season_options, index=season_options.index(f["season"]), key="filter_season"
    )
    if season != f["season"]:
        start, _ = SEASON_BOUNDS[season]
        default_end = _season_default_end(season, surv_events)
        f["date_range"] = (start.date(), default_end.date())
        f["season"] = season

    start, end = SEASON_BOUNDS[season]
    date_range = st.sidebar.date_input(
        "Date range", value=f["date_range"], min_value=start.date(), max_value=end.date(), key="filter_dates"
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        f["date_range"] = date_range

    site_names = sites.sort_values("Site_Name")["Site_Name"] + " (" + sites["Site_ID"] + ")"
    site_lookup = dict(zip(site_names, sites["Site_ID"]))
    selected_site_labels = st.sidebar.multiselect(
        "Site(s) - leave blank for all", list(site_lookup.keys()),
        default=[lbl for lbl, sid in site_lookup.items() if sid in f["site_ids"]], key="filter_sites"
    )
    f["site_ids"] = [site_lookup[lbl] for lbl in selected_site_labels]

    species_names = species[species["Species_Code"] != "OTHER"]
    species_lookup = dict(zip(species_names["Scientific_Name"], species_names["Species_Code"]))
    selected_species_labels = st.sidebar.multiselect(
        "Species - leave blank for all", list(species_lookup.keys()),
        default=[lbl for lbl, code in species_lookup.items() if code in f["species_codes"]], key="filter_species"
    )
    f["species_codes"] = [species_lookup[lbl] for lbl in selected_species_labels]

    st.sidebar.divider()
    st.sidebar.caption(SAMPLE_DATA_BANNER)

    st.session_state["filters"] = f
    return f


def filter_by_season_date(df: pd.DataFrame, filters: dict, date_col: str, season_col: str = "Season") -> pd.DataFrame:
    """Generic season + date-range filter, applied only to columns that exist in df."""
    out = df
    if season_col in out.columns:
        out = out[out[season_col] == filters["season"]]
    if date_col in out.columns and len(filters.get("date_range", ())) == 2:
        start, end = filters["date_range"]
        out = out[(out[date_col].dt.date >= start) & (out[date_col].dt.date <= end)]
    return out


def filter_by_sites(df: pd.DataFrame, filters: dict, site_col: str = "Site_ID") -> pd.DataFrame:
    if filters.get("site_ids") and site_col in df.columns:
        return df[df[site_col].isin(filters["site_ids"])]
    return df


def filter_by_species(df: pd.DataFrame, filters: dict, species_col: str = "Species_Code") -> pd.DataFrame:
    if filters.get("species_codes") and species_col in df.columns:
        return df[df[species_col].isin(filters["species_codes"])]
    return df


# ===========================================================================
# KPI CARDS
# ===========================================================================

def kpi_row(items: list[tuple[str, str, Optional[str]]]):
    """items: list of (label, value, help_text_or_None). Renders as equal-width metric columns."""
    cols = st.columns(len(items))
    for col, (label, value, help_text) in zip(cols, items):
        with col:
            st.metric(label, value, help=help_text)


def site_picker(sites: pd.DataFrame, key: str, label: str = "Select a site") -> Optional[str]:
    """Standard site dropdown used on Site Detail / Dosage / other single-site pages."""
    options = (sites.sort_values("Site_Name")["Site_Name"] + " (" + sites["Site_ID"] + ")").tolist()
    if not options:
        st.warning("No sites available.")
        return None
    choice = st.selectbox(label, options, key=key)
    site_id = choice.split("(")[-1].rstrip(")")
    return site_id
