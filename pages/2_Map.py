"""Interactive operational map - trap sites, treatments, complaints, hotspots."""

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from core import ui, calculations as calc, mapping


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Operational Map")
    ui.sample_data_banner()

    events_f = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    ct = calc.event_catch_totals(events_f, data["surv_results"])

    treatments_f = ui.filter_by_season_date(data["treatments"], filters, date_col="Treatment_Date")
    treatments_f = treatments_f[treatments_f["Treatment_Status"] == "Completed"]

    complaints_f = ui.filter_by_season_date(data["complaints"], filters, date_col="Date_Received")

    # Current status per site (based on latest usable event within the filtered window)
    statuses = [calc.site_current_status(sid, ct, data["thresholds"]) for sid in data["sites"]["Site_ID"]]
    status_df = pd.DataFrame(statuses)

    as_of = pd.Timestamp(filters["date_range"][1])
    hotspots = calc.identify_hotspots(ct, data["complaints"], data["treatments"], data["thresholds"], as_of=as_of)
    hotspot_ids = set(hotspots["Site_ID"]) if not hotspots.empty else set()

    col_map, col_controls = st.columns([3, 1])
    with col_controls:
        st.markdown("**Layers**")
        show_traps = st.checkbox("Trap sites", value=True)
        show_treatments = st.checkbox("Recent treatments", value=False)
        show_complaints = st.checkbox("Complaints", value=False)
        hotspots_only = st.checkbox("Hotspots only", value=False)
        st.divider()
        st.markdown("**Status legend**")
        st.markdown(ui.status_badge_html("Normal"), unsafe_allow_html=True)
        st.markdown(ui.status_badge_html("Elevated"), unsafe_allow_html=True)
        st.markdown(ui.status_badge_html("Action Required"), unsafe_allow_html=True)
        st.markdown(ui.status_badge_html("Insufficient Data"), unsafe_allow_html=True)

    with col_map:
        fmap = mapping.build_operational_map(
            data["sites"], status_df, complaints=complaints_f, treatments=treatments_f,
            hotspot_site_ids=hotspot_ids, show_traps=show_traps, show_complaints=show_complaints,
            show_treatments=show_treatments, show_hotspots_only=hotspots_only,
        )
        map_state = st_folium(fmap, width=None, height=560)

    st.divider()
    st.subheader("Site summary (click a marker on the map, or select below)")
    site_id = ui.site_picker(data["sites"], key="map_site_picker")
    if site_id:
        site_row = data["sites"][data["sites"]["Site_ID"] == site_id].iloc[0]
        status_info = calc.site_current_status(site_id, ct, data["thresholds"])
        site_treatments = data["treatments"][
            (data["treatments"]["Site_ID"] == site_id) & (data["treatments"]["Treatment_Status"] == "Completed")
        ].sort_values("Treatment_Date")
        site_complaints_recent = data["complaints"][
            (data["complaints"]["Site_ID"] == site_id) &
            (data["complaints"]["Date_Received"] >= (as_of - pd.Timedelta(weeks=6)))
        ]
        dominant_species = None
        site_events_ids = ct[ct["Site_ID"] == site_id]["Event_ID"]
        site_results = data["surv_results"][data["surv_results"]["Event_ID"].isin(site_events_ids)]
        site_results = site_results[site_results["Number_Collected"].fillna(-1) >= 0]
        if not site_results.empty:
            top = site_results.groupby("Species_Code")["Number_Collected"].sum().idxmax()
            sp_row = data["species"][data["species"]["Species_Code"] == top]
            dominant_species = sp_row["Common_Name"].iloc[0] if not sp_row.empty else top

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"**{site_row['Site_Name']}** ({site_id})")
        c1.markdown(ui.status_badge_html(status_info["Status"]), unsafe_allow_html=True)
        c2.metric("Latest mosquitoes/trap-night", status_info["Latest_MPTN"] if status_info["Latest_MPTN"] is not None else "N/A")
        c3.metric("Dominant species", dominant_species or "N/A")
        c4.metric("Last treatment", site_treatments["Treatment_Date"].max().strftime("%Y-%m-%d")
                  if not site_treatments.empty and pd.notna(site_treatments["Treatment_Date"].max()) else "None recorded")
        st.caption(f"Recent complaints (last 6 weeks from end of selected range): {len(site_complaints_recent)}")
        st.caption("For full history, open this site on the Site Detail page.")

    st.caption(
        "Corporate GIS layers, shapefiles, GeoJSON boundaries and treatment polygons can be added as additional "
        "toggleable layers in core/mapping.py without changing this page."
    )


render()
