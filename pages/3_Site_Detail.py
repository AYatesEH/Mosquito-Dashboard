"""Site Detail - complete operational history for a single site."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from core import ui, calculations as calc, mapping
from core.config import RIVER_SITE_TYPE


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Site Detail")
    ui.sample_data_banner()

    site_id = ui.site_picker(data["sites"], key="site_detail_picker")
    if not site_id:
        st.stop()

    site_row = data["sites"][data["sites"]["Site_ID"] == site_id].iloc[0]

    # All history is season/date-range scoped by the global filter, but the
    # site itself is chosen independently of the site multiselect filter -
    # this page is explicitly about ONE site's full history.
    events_season = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    events_site = events_season[events_season["Site_ID"] == site_id]
    ct_all = calc.event_catch_totals(data["surv_events"], data["surv_results"])  # unfiltered, for trend/previous lookups
    ct_site_period = calc.event_catch_totals(events_site, data["surv_results"])
    ct_site_all = ct_all[ct_all["Site_ID"] == site_id].sort_values("Deployment_DateTime")

    treatments_site = data["treatments"][data["treatments"]["Site_ID"] == site_id].sort_values("Planned_Date")
    complaints_site = data["complaints"][data["complaints"]["Site_ID"] == site_id].sort_values("Date_Received")
    observations_site = data["observations"][data["observations"]["Site_ID"] == site_id].sort_values("DateTime")

    # --- Header / current status --------------------------------------------
    status_info = calc.site_current_status(site_id, ct_all, data["thresholds"])
    st.subheader(f"{site_row['Site_Name']} ({site_id})")
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        st.write(f"**Type:** {site_row['Site_Type']}  |  **Status:** {site_row['Status']}")
        st.write(site_row["Description"])
    with c2:
        st.markdown(f"**Operational status:** {ui.status_badge_html(status_info['Status'])}", unsafe_allow_html=True)
    with c3:
        if pd.notna(site_row["Latitude"]) and pd.notna(site_row["Longitude"]):
            mini_map = mapping.build_operational_map(
                data["sites"][data["sites"]["Site_ID"] == site_id],
                pd.DataFrame([status_info]), show_treatments=False, show_complaints=False,
            )
            st_folium(mini_map, width=280, height=220)
        else:
            st.warning("Coordinates missing for this site (see Data Quality).")

    # --- Tide indicator (Swan River foreshore site only) --------------------
    if site_row["Site_Type"] == RIVER_SITE_TYPE and pd.notna(site_row["Latitude"]) and pd.notna(site_row["Longitude"]):
        with st.expander("Tide indicator (rough approximation only - read before using to time river-bank work)"):
            tide = ui.get_tide_indicator(site_row["Latitude"], site_row["Longitude"])
            if "error" in tide:
                st.info(f"Tide indicator unavailable right now: {tide['error']}")
            else:
                st.error(tide["caveat"])
                tc1, tc2, tc3 = st.columns(3)
                tc1.metric("Sea level (rough)", f"{tide['sea_level_m']:g} m" if tide["sea_level_m"] is not None else "-")
                tc2.metric("Trend", tide["trend"] or "-")
                tc3.metric(
                    f"Next {tide['next_turn_type'] or 'turn'}",
                    tide["next_turn_time"].split("T")[-1] if tide["next_turn_time"] else "-",
                )
                st.caption(f"Observed at {tide['observed_at']} (Open-Meteo Marine API, live).")

    st.divider()

    # --- Trend: latest vs previous ------------------------------------------
    st.subheader("Trend")
    if len(ct_site_all) >= 1:
        latest = ct_site_all.iloc[-1]
        previous = ct_site_all.iloc[-2] if len(ct_site_all) >= 2 else None
        pct_change = None
        if previous is not None and previous["Mosquitoes_Per_Trap_Night"] > 0:
            pct_change = 100 * (latest["Mosquitoes_Per_Trap_Night"] - previous["Mosquitoes_Per_Trap_Night"]) / previous["Mosquitoes_Per_Trap_Night"]

        dominant_species = None
        site_results = data["surv_results"][data["surv_results"]["Event_ID"].isin(ct_site_all["Event_ID"])]
        site_results = site_results[site_results["Number_Collected"].fillna(-1) >= 0]
        if not site_results.empty:
            top = site_results.groupby("Species_Code")["Number_Collected"].sum().idxmax()
            sp_row = data["species"][data["species"]["Species_Code"] == top]
            dominant_species = sp_row["Scientific_Name"].iloc[0] if not sp_row.empty else top

        completed_treatments_site = treatments_site[treatments_site["Treatment_Status"] == "Completed"]
        last_treatment_date = (
            completed_treatments_site["Treatment_Date"].max()
            if not completed_treatments_site.empty else pd.NaT
        )

        ui.kpi_row([
            ("Latest MPTN", f"{latest['Mosquitoes_Per_Trap_Night']:.1f}", None),
            ("Previous MPTN", f"{previous['Mosquitoes_Per_Trap_Night']:.1f}" if previous is not None else "N/A", None),
            ("Change", f"{pct_change:+.0f}%" if pct_change is not None else "N/A", None),
            ("Dominant species", dominant_species or "N/A", None),
            ("Last treatment", last_treatment_date.strftime("%Y-%m-%d") if pd.notna(last_treatment_date) else "None recorded", None),
        ])
    else:
        st.info("No usable surveillance history recorded for this site yet.")

    st.divider()

    # --- Follow-up / recent complaints ---------------------------------------
    open_followups = observations_site[observations_site["Observation_Category"] == "Follow-up required"]
    open_complaints = complaints_site[complaints_site["Investigation_Status"] != "Closed"]
    colf1, colf2 = st.columns(2)
    colf1.metric("Open follow-up observations", len(open_followups))
    colf2.metric("Open complaints", len(open_complaints))

    st.divider()

    # --- Graphs: abundance over time with treatments overlaid --------------
    st.subheader("Mosquito abundance over time (with treatments overlaid)")
    if not ct_site_period.empty:
        daily = ct_site_period.groupby(ct_site_period["Deployment_DateTime"].dt.date, as_index=False)["Mosquitoes_Per_Trap_Night"].mean()
        daily.columns = ["Date", "MPTN"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=daily["Date"], y=daily["MPTN"], mode="lines+markers", name="Mosquitoes/trap-night"))
        completed = treatments_site[(treatments_site["Treatment_Status"] == "Completed") & treatments_site["Treatment_Date"].notna()]
        for _, t in completed.iterrows():
            t_date = t["Treatment_Date"]
            if pd.notna(t_date) and filters["date_range"][0] <= t_date.date() <= filters["date_range"][1]:
                fig.add_vline(x=t_date, line_dash="dash", line_color="#C62828")
        fig.update_layout(height=380, yaxis_title="Mosquitoes / trap-night")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Dashed red lines mark completed treatments in the selected period.")
    else:
        st.info("No usable surveillance data for this site in the selected period.")

    # --- Species composition ---------------------------------------------
    st.subheader("Species composition at this site")
    site_results_period = data["surv_results"][data["surv_results"]["Event_ID"].isin(ct_site_period["Event_ID"])]
    site_results_period = site_results_period[site_results_period["Number_Collected"].fillna(-1) >= 0]
    if not site_results_period.empty:
        by_sp = site_results_period.groupby("Species_Code", as_index=False)["Number_Collected"].sum()
        by_sp = by_sp.merge(data["species"][["Species_Code", "Scientific_Name"]], on="Species_Code", how="left")
        fig_sp = px.bar(by_sp.sort_values("Number_Collected", ascending=False), x="Scientific_Name", y="Number_Collected")
        fig_sp.update_layout(height=320, xaxis_title="")
        st.plotly_chart(fig_sp, use_container_width=True)
    else:
        st.info("No species results recorded for this site in the selected period.")

    st.divider()

    # --- Activity timeline ---------------------------------------------------
    st.subheader("Activity timeline")
    timeline_rows = []
    for _, r in events_site.iterrows():
        timeline_rows.append({"Date": r["Deployment_DateTime"], "Type": "Trap deployed",
                               "Detail": f"{r['Trap_ID']} ({r['Trap_Type']}) - {r['Trap_Status']}"})
        if pd.notna(r["Retrieval_DateTime"]):
            timeline_rows.append({"Date": r["Retrieval_DateTime"], "Type": "Trap collected",
                                   "Detail": f"{r['Trap_ID']} - sample {r['Sample_Validity']}"})
    for _, r in treatments_site.iterrows():
        date = r["Treatment_Date"] if pd.notna(r["Treatment_Date"]) else r["Planned_Date"]
        timeline_rows.append({"Date": date, "Type": f"Treatment ({r['Treatment_Status']})",
                               "Detail": f"{r['Treatment_Type']} - {r['Treatment_ID']}"})
    for _, r in complaints_site.iterrows():
        timeline_rows.append({"Date": r["Date_Received"], "Type": "Complaint",
                               "Detail": f"{r['Category']} - {r['Investigation_Status']}"})
    for _, r in observations_site.iterrows():
        timeline_rows.append({"Date": r["DateTime"], "Type": "Field observation",
                               "Detail": f"{r['Observation_Category']} ({r['Officer']})"})

    if timeline_rows:
        timeline_df = pd.DataFrame(timeline_rows).sort_values("Date", ascending=False)
        timeline_df = timeline_df[
            (timeline_df["Date"].dt.date >= filters["date_range"][0]) &
            (timeline_df["Date"].dt.date <= filters["date_range"][1])
        ]
        st.dataframe(timeline_df, use_container_width=True, hide_index=True, height=350)
    else:
        st.info("No recorded activity for this site.")

    st.divider()
    st.subheader("Notes / observations")
    if not observations_site.empty:
        st.dataframe(
            observations_site[["DateTime", "Observation_Category", "Officer", "Notes"]].sort_values("DateTime", ascending=False),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No field observations recorded for this site.")


render()
