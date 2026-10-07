"""Hotspot Identification - transparent, rule-based (not predictive), configurable."""

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from core import ui, calculations as calc, mapping
from core.config import (
    HOTSPOT_LOOKBACK_WEEKS, HOTSPOT_MIN_ELEVATED_WEEKS, HOTSPOT_MIN_COMPLAINTS, HOTSPOT_MIN_TREATMENTS,
    HOTSPOT_MIN_HIGH_DIPS, HIGH_LARVAE_COUNT_PER_DIP,
)


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Hotspot Identification")
    ui.sample_data_banner()
    st.info(
        "Hotspot flags below use simple, transparent, configurable rules - not a predictive model, drawing on "
        "three independent signals: trap catch data, complaints, and larvae dip counts. A site can carry more "
        "than one flag, and a site flagged by at least 2 of the 3 signals at the same time also gets a "
        "'Confirmed hotspot (...)' flag naming which ones agree - e.g. 'Confirmed hotspot (trap + complaint)' or "
        "'Confirmed hotspot (trap + dip)'. Use the signal filter below to view all flagged sites, only the "
        "confirmed ones, or just the trap-, complaint-, or dip-driven ones. Adjust the rule parameters below to "
        "see how the results change."
    )

    ct_all = calc.event_catch_totals(data["surv_events"], data["surv_results"])
    as_of = pd.Timestamp(filters["date_range"][1])

    with st.expander("Advanced: hotspot rules", expanded=False):
        st.caption("These set how many weeks, complaints, treatments and high dip counts it takes to flag a site. "
                   "The defaults are fine for normal use; change them only to test how sensitive the flags are. "
                   "Defaults are SAMPLE values pending your program's own criteria.")
        c1, c2, c3 = st.columns(3)
        with c1:
            lookback_weeks = st.slider("Lookback window (weeks)", 2, 12, HOTSPOT_LOOKBACK_WEEKS)
            min_elevated_weeks = st.slider("Min. weeks at/above Elevated to flag 'persistent'", 2, 8, HOTSPOT_MIN_ELEVATED_WEEKS)
        with c2:
            min_complaints = st.slider("Min. complaints in window to flag 'repeated complaints'", 1, 10, HOTSPOT_MIN_COMPLAINTS)
            min_treatments = st.slider("Min. completed treatments in window to flag 'repeatedly treated'", 1, 6, HOTSPOT_MIN_TREATMENTS)
        with c3:
            min_high_dips = st.slider(
                "Min. high-count dips in window to flag 'elevated larvae dip counts'", 1, 6, HOTSPOT_MIN_HIGH_DIPS,
                help=f"A dip counts as 'high' above {HIGH_LARVAE_COUNT_PER_DIP} larvae - the real APVMA-label "
                     f"threshold already used on the Dosage Calculator page.",
            )

    hotspots_all = calc.identify_hotspots(
        ct_all, data["complaints"], data["treatments"], data["thresholds"], as_of=as_of,
        lookback_weeks=lookback_weeks, min_elevated_weeks=min_elevated_weeks,
        min_complaints=min_complaints, min_treatments=min_treatments,
        larvae_dips=data["larvae_dips"], min_high_dips=min_high_dips,
    )
    if hotspots_all.empty:
        hotspots_all["Trap_Flagged"] = pd.Series(dtype=bool)
        hotspots_all["Complaint_Flagged"] = pd.Series(dtype=bool)
        hotspots_all["Dip_Flagged"] = pd.Series(dtype=bool)

    st.markdown("**Filter by signal**")
    signal_view = st.radio(
        "Filter by signal",
        ["All flagged sites", "Confirmed (2+ signals)", "Trap data only", "Complaint data only", "Dip data only"],
        horizontal=True, label_visibility="collapsed", key="hotspot_signal_filter",
    )
    st.caption(
        "'Trap data only', 'Complaint data only' and 'Dip data only' show sites flagged by that signal and NOT "
        "either of the other two (even if also flagged as 'Repeatedly treated', which is tracked separately). "
        "'Confirmed (2+ signals)' shows only sites where at least 2 of the 3 independent signals corroborate "
        "each other."
    )
    trap, comp, dip = hotspots_all["Trap_Flagged"], hotspots_all["Complaint_Flagged"], hotspots_all["Dip_Flagged"]
    signal_count = trap.astype(int) + comp.astype(int) + dip.astype(int)
    if signal_view == "Confirmed (2+ signals)":
        hotspots = hotspots_all[signal_count >= 2]
    elif signal_view == "Trap data only":
        hotspots = hotspots_all[trap & ~comp & ~dip]
    elif signal_view == "Complaint data only":
        hotspots = hotspots_all[comp & ~trap & ~dip]
    elif signal_view == "Dip data only":
        hotspots = hotspots_all[dip & ~trap & ~comp]
    else:
        hotspots = hotspots_all

    ui.kpi_row([
        ("Sites flagged (this view)", str(len(hotspots)), None),
        ("Confirmed - 2+ signals", str(int((signal_count >= 2).sum())), "Flagged by at least 2 of trap/complaint/dip at the same time."),
        ("Trap data only", str(int((trap & ~comp & ~dip).sum())), None),
        ("Complaint data only", str(int((comp & ~trap & ~dip).sum())), None),
        ("Dip data only", str(int((dip & ~trap & ~comp).sum())), None),
        ("Repeatedly treated", str(int(hotspots_all["Flags"].apply(lambda f: "Repeatedly treated" in f).sum())) if not hotspots_all.empty else "0", "Tracked separately from the signal filter."),
    ])

    st.divider()

    if hotspots.empty:
        if hotspots_all.empty:
            st.success(f"No sites meet the current hotspot criteria as of {as_of.date()}.")
        else:
            st.info("No sites match this signal filter for the current criteria - try 'All flagged sites'.")
        st.stop()

    display = hotspots.merge(data["sites"][["Site_ID", "Site_Name", "Site_Type"]], on="Site_ID", how="left")
    display["Flags"] = display["Flags"].apply(lambda f: ", ".join(f))

    col_map, col_table = st.columns([2, 3])
    with col_map:
        st.markdown("**Hotspots on the map**")
        hotspot_by_site_all = {row["Site_ID"]: row for row in hotspots_all.to_dict("records")}
        statuses = [
            calc.site_map_status(sid, ct_all, data["thresholds"], hotspots_by_site=hotspot_by_site_all)
            for sid in data["sites"]["Site_ID"]
        ]
        status_df = pd.DataFrame(statuses)
        fmap = mapping.build_operational_map(
            data["sites"], status_df, hotspot_site_ids=set(hotspots["Site_ID"]),
            show_traps=True, show_complaints=False, show_treatments=False, show_hotspots_only=True,
        )
        st_folium(fmap, width=None, height=420)

    with col_table:
        st.markdown("**Flagged sites**")
        st.dataframe(
            display[["Site_ID", "Site_Name", "Site_Type", "Flags", "Elevated_Weeks", "Complaints_In_Window",
                     "Treatments_In_Window", "High_Dips_In_Window"]]
            .sort_values("Elevated_Weeks", ascending=False),
            use_container_width=True, hide_index=True, height=420,
        )

    st.divider()
    st.subheader("Distinguishing spikes from persistence")
    st.caption(
        "A site with exactly one elevated week in the lookback window is a single spike; a site with several "
        "elevated weeks is persistent activity. Repeated complaints, repeated treatments and elevated larvae dip "
        "counts are all tracked separately since they can occur independently of the surveillance-based status. "
        "A 'Confirmed hotspot (...)' flag is added only when at least 2 of the 3 independent signals (trap, "
        "complaint, dip) both fire for the same site in the same window - it doesn't require any extra data "
        "beyond what's already shown, it just calls out when signals agree, and names which ones."
    )


render()
