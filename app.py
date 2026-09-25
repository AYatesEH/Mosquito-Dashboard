"""
app.py - Overview (landing page)

Entry point for the Mosquito Season Dashboard. Run with:
    streamlit run app.py

See README.md for setup instructions and an explanation of the data model.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc
from core.config import STATUS_ACTION, STATUS_ELEVATED


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Mosquito Season Dashboard")
    ui.sample_data_banner()
    st.caption(f"Season **{filters['season']}** | {filters['date_range'][0]} to {filters['date_range'][1]}")

    # --- Apply global filters to the datasets this page needs ---------------
    events_f = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    events_f = ui.filter_by_sites(events_f, filters)
    ct = calc.event_catch_totals(events_f, data["surv_results"])
    # Note: species filtering is applied at the species-breakdown level (charts/tables
    # below), not to `ct`, because ct is one row per trap EVENT (all species combined) -
    # filtering it by species would incorrectly drop events where the selected species
    # simply wasn't present, distorting trap-night/effort statistics.

    treatments_f = ui.filter_by_season_date(data["treatments"], filters, date_col="Treatment_Date")
    treatments_f = ui.filter_by_sites(treatments_f, filters)
    # Treatments without a Treatment_Date (Planned/Scheduled) fall outside the date filter above;
    # re-include them if they belong to the selected season so upcoming work is still visible.
    planned = data["treatments"][
        (data["treatments"]["Season"] == filters["season"]) &
        (data["treatments"]["Treatment_Status"].isin(["Planned", "Scheduled"]))
    ]
    planned = ui.filter_by_sites(planned, filters)
    treatments_f = pd.concat([treatments_f, planned]).drop_duplicates(subset="Treatment_ID")

    complaints_f = ui.filter_by_season_date(data["complaints"], filters, date_col="Date_Received")
    complaints_f = ui.filter_by_sites(complaints_f, filters)

    thresholds = data["thresholds"]
    targets_row = data["targets"][data["targets"]["Season"] == filters["season"]]
    planned_events = int(targets_row["Planned_Surveillance_Events"].iloc[0]) if not targets_row.empty else 0
    planned_treatments_target = int(targets_row["Planned_Treatments"].iloc[0]) if not targets_row.empty else 0

    kpis = calc.kpi_summary(ct, treatments_f, complaints_f, thresholds)

    # --- KPI cards ------------------------------------------------------------
    st.subheader("Season at a glance")
    ui.kpi_row([
        ("Total mosquitoes trapped", f"{kpis['total_mosquitoes']:,}", "Sum of usable, valid surveillance catches."),
        ("Mosquitoes / trap-night", f"{kpis['mosquitoes_per_trap_night']:.2f}" if kpis["mosquitoes_per_trap_night"] is not None else "N/A",
         "Total catch divided by total successful trap-nights."),
        ("Successful trap-nights", f"{kpis['successful_trap_nights']:,.0f}", "Excludes missing/failed/invalid events."),
        ("Trap sites active", f"{kpis['n_trap_sites']}", None),
        ("Sites: Action required", f"{kpis['sites_action_required']}", "Latest sample above the Action threshold."),
        ("Sites: Elevated", f"{kpis['sites_elevated']}", "Latest sample above Normal but below Action."),
    ])
    ui.kpi_row([
        ("Treatments completed", f"{kpis['treatments_completed']}", None),
        ("Treatments planned/scheduled", f"{kpis['treatments_scheduled']}", None),
        ("Total area treated (ha)", f"{kpis['area_treated_ha']:,.1f}", None),
        ("Complaints received", f"{kpis['complaints_received']}", None),
        ("Surveillance completion", f"{calc.surveillance_program_completion(events_f, planned_events):.0f}%" if planned_events else "N/A",
         "SAMPLE target - see Program Targets in Reporting."),
        ("Treatment completion", f"{100*kpis['treatments_completed']/planned_treatments_target:.0f}%" if planned_treatments_target else "N/A",
         "SAMPLE target - see Program Targets in Reporting."),
    ])

    st.divider()

    # --- Charts -----------------------------------------------------------
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Mosquito abundance over time**")
        if not ct.empty:
            daily = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Total_Catch"].sum()
            daily.columns = ["Date", "Total_Catch"]
            fig = px.line(daily, x="Date", y="Total_Catch", markers=True)
            fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No surveillance data for the current filter selection.")

    with col2:
        st.markdown("**Mosquitoes per trap-night over time**")
        if not ct.empty:
            daily2 = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Mosquitoes_Per_Trap_Night"].mean()
            daily2.columns = ["Date", "MPTN"]
            fig2 = px.line(daily2, x="Date", y="MPTN", markers=True)
            fig2.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No surveillance data for the current filter selection.")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**Species composition**")
        results_f = data["surv_results"][data["surv_results"]["Event_ID"].isin(ct["Event_ID"])]
        results_f = results_f[results_f["Number_Collected"].fillna(-1) >= 0]
        if not results_f.empty:
            by_species = results_f.groupby("Species_Code", as_index=False)["Number_Collected"].sum()
            by_species = by_species.merge(data["species"][["Species_Code", "Scientific_Name"]], on="Species_Code", how="left")
            fig3 = px.pie(by_species, names="Scientific_Name", values="Number_Collected", hole=0.4)
            fig3.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No species results for the current filter selection.")

    with col4:
        st.markdown("**Treatments over time (by status)**")
        if not treatments_f.empty:
            t_plot = treatments_f.copy()
            t_plot["Plot_Date"] = t_plot["Treatment_Date"].fillna(t_plot["Planned_Date"])
            by_status = t_plot.groupby([t_plot["Plot_Date"].dt.date, "Treatment_Status"], as_index=False).size()
            by_status.columns = ["Date", "Status", "Count"]
            fig4 = px.bar(by_status, x="Date", y="Count", color="Status")
            fig4.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("No treatments for the current filter selection.")

    col5, col6 = st.columns(2)
    with col5:
        st.markdown("**Complaints over time**")
        if not complaints_f.empty:
            c_daily = complaints_f.groupby(complaints_f["Date_Received"].dt.date, as_index=False).size()
            c_daily.columns = ["Date", "Complaints"]
            fig5 = px.bar(c_daily, x="Date", y="Complaints")
            fig5.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig5, use_container_width=True)
        else:
            st.info("No complaints for the current filter selection.")

    with col6:
        st.markdown("**Environmental conditions vs. abundance**")
        env_f = data["environmental"][
            (data["environmental"]["Date"].dt.date >= filters["date_range"][0]) &
            (data["environmental"]["Date"].dt.date <= filters["date_range"][1])
        ]
        if not env_f.empty and not ct.empty:
            daily_catch = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Total_Catch"].sum()
            daily_catch.columns = ["Date", "Total_Catch"]
            env_plot = env_f[["Date", "Rainfall_mm"]].copy()
            env_plot["Date"] = env_plot["Date"].dt.date
            merged_env = daily_catch.merge(env_plot, on="Date", how="left")
            fig6 = px.bar(merged_env, x="Date", y="Rainfall_mm")
            fig6.add_scatter(x=merged_env["Date"], y=merged_env["Total_Catch"], mode="lines", name="Total catch")
            fig6.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10),
                                yaxis_title="Rainfall (mm) / Total catch")
            st.plotly_chart(fig6, use_container_width=True)
            st.caption("Visual comparison only - not a statistical test of causation.")
        else:
            st.info("Insufficient environmental or surveillance data for this view.")

    st.divider()

    # --- Sites requiring attention -------------------------------------------
    st.subheader("Sites currently above action thresholds / requiring follow-up")
    status_df = kpis["site_status_df"]
    if not status_df.empty:
        attention = status_df[status_df["Status"].isin([STATUS_ACTION, STATUS_ELEVATED])].copy()
        if not attention.empty:
            attention = attention.merge(data["sites"][["Site_ID", "Site_Name", "Site_Type"]], on="Site_ID", how="left")
            attention = attention.sort_values("Status", ascending=False)
            st.dataframe(
                attention[["Site_ID", "Site_Name", "Site_Type", "Status", "Latest_MPTN", "Latest_Sample_Date"]],
                use_container_width=True, hide_index=True,
            )
        else:
            st.success("No sites currently above the configured action thresholds.")
    else:
        st.info("No surveillance data available to assess site status.")

    st.caption(
        "Thresholds shown are SAMPLE values for prototype demonstration - see the Data Quality and "
        "Reporting pages for full detail, and Season Comparison to see how this season compares with prior seasons."
    )


render()
