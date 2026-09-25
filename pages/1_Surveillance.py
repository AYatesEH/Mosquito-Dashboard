"""Surveillance - trap results, effort/failure tracking, abundance analysis."""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Surveillance")
    ui.sample_data_banner()

    events_f = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    events_f = ui.filter_by_sites(events_f, filters)

    # --- Trap effort summary (based on ALL logged events, not just usable ones) ---
    st.subheader("Trap effort this period")
    effort_counts = events_f["Trap_Status"].value_counts()
    ui.kpi_row([
        ("Successful", str(int(effort_counts.get("Successful", 0))), None),
        ("Partial", str(int(effort_counts.get("Partial", 0))), "Lower catch expected - excluded from being read as 'low abundance'."),
        ("Failed (equipment/battery)", str(int(effort_counts.get("Failed - Equipment/Battery", 0))), None),
        ("Missing", str(int(effort_counts.get("Missing", 0))), None),
        ("Invalid samples", str(int((events_f["Sample_Validity"] == "Invalid").sum())), "Excluded from all abundance statistics."),
    ])

    ct = calc.event_catch_totals(events_f, data["surv_results"])
    st.caption(
        f"{len(ct)} of {len(events_f)} logged events ({(100*len(ct)/len(events_f)):.0f}%) are usable "
        f"for abundance statistics." if len(events_f) else "No surveillance events logged for this selection."
    )

    st.divider()

    # --- Abundance over time, with species/site filters already applied via ct ---
    st.subheader("Abundance over time")
    if not ct.empty:
        tab1, tab2 = st.tabs(["Total catch", "Mosquitoes per trap-night"])
        with tab1:
            daily = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Total_Catch"].sum()
            daily.columns = ["Date", "Total_Catch"]
            fig = px.line(daily, x="Date", y="Total_Catch", markers=True)
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)
        with tab2:
            daily2 = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Mosquitoes_Per_Trap_Night"].mean()
            daily2.columns = ["Date", "MPTN"]
            fig2 = px.line(daily2, x="Date", y="MPTN", markers=True)
            fig2.update_layout(height=350)
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No usable surveillance data for the current filter selection.")

    st.divider()

    # --- Compare trap sites ---
    st.subheader("Compare trap sites")
    if not ct.empty:
        by_site = ct.groupby("Site_ID", as_index=False).agg(
            Total_Catch=("Total_Catch", "sum"),
            Mean_MPTN=("Mosquitoes_Per_Trap_Night", "mean"),
            Events=("Event_ID", "count"),
        )
        by_site = by_site.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")
        by_site = by_site.sort_values("Mean_MPTN", ascending=False)
        fig3 = px.bar(by_site, x="Site_Name", y="Mean_MPTN", hover_data=["Total_Catch", "Events"])
        fig3.update_layout(height=380, xaxis_title="", yaxis_title="Mean mosquitoes / trap-night")
        st.plotly_chart(fig3, use_container_width=True)
        with st.expander("View underlying site comparison table"):
            st.dataframe(by_site[["Site_ID", "Site_Name", "Events", "Total_Catch", "Mean_MPTN"]],
                         use_container_width=True, hide_index=True)
    else:
        st.info("No usable surveillance data to compare sites.")

    st.divider()

    # --- Compare species ---
    st.subheader("Compare species")
    results_f = data["surv_results"][data["surv_results"]["Event_ID"].isin(ct["Event_ID"])].copy()
    results_f = results_f[results_f["Number_Collected"].fillna(-1) >= 0]
    results_f = results_f[results_f["Species_Code"].notna() & (results_f["Species_Code"] != "")]
    if filters["species_codes"]:
        results_f = results_f[results_f["Species_Code"].isin(filters["species_codes"])]
    if not results_f.empty:
        by_species = results_f.groupby("Species_Code", as_index=False)["Number_Collected"].sum()
        by_species = by_species.merge(data["species"][["Species_Code", "Common_Name"]], on="Species_Code", how="left")
        by_species = by_species.sort_values("Number_Collected", ascending=False)
        fig4 = px.bar(by_species, x="Common_Name", y="Number_Collected")
        fig4.update_layout(height=350, xaxis_title="", yaxis_title="Total collected")
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("No species results for the current filter selection.")

    st.divider()

    # --- Unusually high trap counts / persistent increases -----------------
    st.subheader("Unusually high trap counts")
    st.caption(
        "A trap-night result is flagged here if it is more than 2x the site's own median mosquitoes-per-trap-night "
        "over the selected period - a simple, transparent statistical flag, not a predictive model."
    )
    if not ct.empty:
        site_medians = ct.groupby("Site_ID")["Mosquitoes_Per_Trap_Night"].median().rename("Site_Median")
        ct_flagged = ct.merge(site_medians, on="Site_ID", how="left")
        ct_flagged["Flagged"] = ct_flagged["Mosquitoes_Per_Trap_Night"] > (2 * ct_flagged["Site_Median"].clip(lower=0.5))
        flagged = ct_flagged[ct_flagged["Flagged"]].merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")
        if not flagged.empty:
            flagged = flagged.sort_values("Mosquitoes_Per_Trap_Night", ascending=False)
            st.dataframe(
                flagged[["Event_ID", "Site_ID", "Site_Name", "Deployment_DateTime", "Total_Catch",
                         "Mosquitoes_Per_Trap_Night", "Site_Median"]].rename(
                    columns={"Deployment_DateTime": "Deployment Date", "Site_Median": "Site's typical (median) MPTN"}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.success("No unusually high trap counts flagged for this selection.")
    else:
        st.info("No usable surveillance data available.")

    st.divider()

    # --- Raw trap results table with filters ---------------------------------
    st.subheader("Surveillance event log")
    display_events = events_f.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")
    st.dataframe(
        display_events[["Event_ID", "Site_Name", "Trap_ID", "Deployment_DateTime", "Retrieval_DateTime",
                         "Trap_Type", "Trap_Status", "Sample_Validity", "Officer"]].sort_values(
            "Deployment_DateTime", ascending=False),
        use_container_width=True, hide_index=True, height=320,
    )


render()
