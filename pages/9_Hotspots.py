"""Hotspot Identification - transparent, rule-based (not predictive), configurable."""

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from core import ui, calculations as calc, mapping
from core.config import (
    HOTSPOT_LOOKBACK_WEEKS, HOTSPOT_MIN_ELEVATED_WEEKS, HOTSPOT_MIN_COMPLAINTS, HOTSPOT_MIN_TREATMENTS,
)


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Hotspot Identification")
    ui.sample_data_banner()
    st.info(
        "Hotspot flags below use simple, transparent, configurable rules - not a predictive model. A site can "
        "carry more than one flag. Adjust the rule parameters below to see how the results change."
    )

    ct_all = calc.event_catch_totals(data["surv_events"], data["surv_results"])
    as_of = pd.Timestamp(filters["date_range"][1])

    with st.expander("Rule parameters (configurable, SAMPLE defaults)", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            lookback_weeks = st.slider("Lookback window (weeks)", 2, 12, HOTSPOT_LOOKBACK_WEEKS)
            min_elevated_weeks = st.slider("Min. weeks at/above Elevated to flag 'persistent'", 2, 8, HOTSPOT_MIN_ELEVATED_WEEKS)
        with c2:
            min_complaints = st.slider("Min. complaints in window to flag 'repeated complaints'", 1, 10, HOTSPOT_MIN_COMPLAINTS)
            min_treatments = st.slider("Min. completed treatments in window to flag 'repeatedly treated'", 1, 6, HOTSPOT_MIN_TREATMENTS)

    hotspots = calc.identify_hotspots(
        ct_all, data["complaints"], data["treatments"], data["thresholds"], as_of=as_of,
        lookback_weeks=lookback_weeks, min_elevated_weeks=min_elevated_weeks,
        min_complaints=min_complaints, min_treatments=min_treatments,
    )

    ui.kpi_row([
        ("Sites flagged", str(len(hotspots)), None),
        ("Persistent elevated activity", str(int(hotspots["Flags"].apply(lambda f: "Persistent elevated activity" in f).sum())) if not hotspots.empty else "0", None),
        ("Repeated complaints", str(int(hotspots["Flags"].apply(lambda f: "Repeated complaints" in f).sum())) if not hotspots.empty else "0", None),
        ("Repeatedly treated", str(int(hotspots["Flags"].apply(lambda f: "Repeatedly treated" in f).sum())) if not hotspots.empty else "0", None),
    ])

    st.divider()

    if hotspots.empty:
        st.success(f"No sites meet the current hotspot criteria as of {as_of.date()}.")
        st.stop()

    display = hotspots.merge(data["sites"][["Site_ID", "Site_Name", "Site_Type"]], on="Site_ID", how="left")
    display["Flags"] = display["Flags"].apply(lambda f: ", ".join(f))

    col_map, col_table = st.columns([2, 3])
    with col_map:
        st.markdown("**Hotspots on the map**")
        statuses = [calc.site_current_status(sid, ct_all, data["thresholds"]) for sid in data["sites"]["Site_ID"]]
        status_df = pd.DataFrame(statuses)
        fmap = mapping.build_operational_map(
            data["sites"], status_df, hotspot_site_ids=set(hotspots["Site_ID"]),
            show_traps=True, show_complaints=False, show_treatments=False, show_hotspots_only=True,
        )
        st_folium(fmap, width=None, height=420)

    with col_table:
        st.markdown("**Flagged sites**")
        st.dataframe(
            display[["Site_ID", "Site_Name", "Site_Type", "Flags", "Elevated_Weeks", "Complaints_In_Window", "Treatments_In_Window"]]
            .sort_values("Elevated_Weeks", ascending=False),
            use_container_width=True, hide_index=True, height=420,
        )

    st.divider()
    st.subheader("Distinguishing spikes from persistence")
    st.caption(
        "A site with exactly one elevated week in the lookback window is a single spike; a site with several "
        "elevated weeks is persistent activity. Repeated complaints and repeated treatments are tracked separately "
        "since they can occur independently of the surveillance-based status."
    )


render()
