"""Interactive operational map - trap sites, treatments, complaints, hotspots."""

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from core import ui, calculations as calc, mapping
from core.config import VINCENT_CENTER_LAT, VINCENT_CENTER_LON


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

    as_of = ui.as_of_date(filters)
    hotspots = calc.identify_hotspots(ct, data["complaints"], data["treatments"], data["thresholds"], as_of=as_of,
                                       larvae_dips=data["larvae_dips"])
    hotspot_ids = set(hotspots["Site_ID"]) if not hotspots.empty else set()
    hotspot_by_site = {row["Site_ID"]: row for row in hotspots.to_dict("records")}

    # Current status per site (based on latest usable event within the filtered window,
    # upgraded to reflect complaint/larvae-dip hotspot signals - see site_map_status)
    statuses = [calc.site_map_status(sid, ct, data["thresholds"], hotspots_by_site=hotspot_by_site)
                for sid in data["sites"]["Site_ID"]]
    status_df = pd.DataFrame(statuses)

    col_map, col_controls = st.columns([3, 1])
    with col_controls:
        st.markdown("**Layers**")
        show_traps = st.checkbox("Trap sites", value=True)
        show_treatments = st.checkbox("Recent treatments", value=True)
        show_complaints = st.checkbox("Complaints", value=True)
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
        status_info = calc.site_map_status(site_id, ct, data["thresholds"], hotspots_by_site=hotspot_by_site)
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
            dominant_species = sp_row["Scientific_Name"].iloc[0] if not sp_row.empty else top

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"**{site_row['Site_Name']}** ({site_id})")
        c1.markdown(ui.status_badge_html(status_info["Status"]), unsafe_allow_html=True)
        c2.metric("Mosquitoes caught per night (latest trap)", status_info["Latest_MPTN"] if status_info["Latest_MPTN"] is not None else "N/A",
                  help="Mosquitoes in the trap divided by the number of nights it was out, so traps left out for different lengths of time can be compared fairly. Example: 60 mosquitoes over 2 nights = 30 per night.")
        c3.metric("Dominant species", dominant_species or "N/A")
        c4.metric("Last treatment", site_treatments["Treatment_Date"].max().strftime("%Y-%m-%d")
                  if not site_treatments.empty and pd.notna(site_treatments["Treatment_Date"].max()) else "None recorded")
        st.caption(f"Recent complaints (last 6 weeks from end of selected range): {len(site_complaints_recent)}")
        st.caption("For full history, open this site on the Site Detail page.")

    st.divider()
    with st.expander("+ Add a new site"):
        st.caption(
            "Saves to this prototype's CSV data store - fine for a single-user demo/pilot, see README Section 6 "
            "for moving to a real backend before relying on this for a live season. Click a point on the map "
            "above first to drop a pin and pre-fill the coordinates below, or enter them directly."
        )
        clicked = map_state.get("last_clicked") if map_state else None
        default_lat = clicked["lat"] if clicked else VINCENT_CENTER_LAT
        default_lon = clicked["lng"] if clicked else VINCENT_CENTER_LON
        if clicked:
            st.caption(f"Using the point you clicked on the map: {default_lat:.5f}, {default_lon:.5f}")

        existing_types = sorted(data["sites"]["Site_Type"].dropna().unique().tolist())
        nc1, nc2 = st.columns(2)
        with nc1:
            new_site_name = st.text_input("Site name", key="new_site_name")
            new_site_type_choice = st.selectbox(
                "Site type", existing_types + ["Other (specify)"], key="new_site_type_choice",
            )
            new_site_type = (
                st.text_input("New site type", key="new_site_type_other")
                if new_site_type_choice == "Other (specify)" else new_site_type_choice
            )
            new_site_status = st.selectbox("Status", ["Active", "Inactive"], key="new_site_status")
        with nc2:
            new_site_lat = st.number_input("Latitude", value=float(default_lat), format="%.5f", key="new_site_lat")
            new_site_lon = st.number_input("Longitude", value=float(default_lon), format="%.5f", key="new_site_lon")
            new_site_officer = st.selectbox("Added by", data["users"]["Name"].tolist(), key="new_site_officer")

        new_site_description = st.text_area("Description", key="new_site_description")
        new_site_notes = st.text_area("Notes", key="new_site_notes")

        if st.button("Save new site", type="primary", key="new_site_save"):
            if not new_site_name.strip():
                st.error("Enter a site name.")
            elif not new_site_type or not str(new_site_type).strip():
                st.error("Enter a site type.")
            else:
                today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
                new_id = ui.add_site({
                    "Site_Name": new_site_name.strip(),
                    "Site_Type": str(new_site_type).strip(),
                    "Latitude": new_site_lat,
                    "Longitude": new_site_lon,
                    "Status": new_site_status,
                    "Description": new_site_description,
                    "Notes": new_site_notes,
                    "Created_By": new_site_officer,
                    "Created_Date": today_str,
                    "Modified_By": new_site_officer,
                    "Modified_Date": today_str,
                })
                st.success(f"Saved {new_id} ({new_site_name.strip()}). It now appears on the map and every site picker.")
                st.rerun()

    st.caption(
        "Corporate GIS layers, shapefiles, GeoJSON boundaries and treatment polygons can be added as additional "
        "toggleable layers in core/mapping.py without changing this page."
    )


render()
