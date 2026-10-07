"""Surveillance - trap results, effort/failure tracking, abundance analysis."""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc
from core.config import TRAP_TYPES, HIGH_LARVAE_COUNT_PER_DIP

TRAP_OUTCOMES = ["Successful", "Partial", "Failed - Equipment/Battery", "Missing"]
DEFAULT_VALIDITY = {"Successful": "Valid", "Partial": "Valid", "Failed - Equipment/Battery": "Invalid", "Missing": "N/A"}


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Surveillance")
    ui.sample_data_banner()

    events_f = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    events_f = ui.filter_by_sites(events_f, filters)
    ct = calc.event_catch_totals(events_f, data["surv_results"])

    tab_overview, tab_dip, tab_log = st.tabs(["Overview", "Dip Log", "Event Log"])

    with tab_overview:
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

        st.caption(
            f"{len(ct)} of {len(events_f)} logged events ({(100*len(ct)/len(events_f)):.0f}%) are usable "
            f"for abundance statistics." if len(events_f) else "No surveillance events logged for this selection."
        )

        st.divider()

        # --- Abundance over time, with species/site filters already applied via ct ---
        st.subheader("Abundance over time")
        if not ct.empty:
            atab1, atab2 = st.tabs(["Total catch", "Catch per night"])
            with atab1:
                daily = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Total_Catch"].sum()
                daily.columns = ["Date", "Total_Catch"]
                fig = px.line(daily, x="Date", y="Total_Catch", markers=True)
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)
            with atab2:
                st.caption("Mosquitoes in the trap divided by the number of nights it was out, so traps left out for different lengths of time can be compared fairly. Example: 60 mosquitoes over 2 nights = 30 per night.")
                daily2 = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Mosquitoes_Per_Trap_Night"].mean()
                daily2.columns = ["Date", "Catch per night"]
                fig2 = px.line(daily2, x="Date", y="Catch per night", markers=True)
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
                Catch_Per_Night=("Mosquitoes_Per_Trap_Night", "mean"),
                Events=("Event_ID", "count"),
            )
            by_site = by_site.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")
            by_site = by_site.sort_values("Catch_Per_Night", ascending=False)
            fig3 = px.bar(by_site, x="Site_Name", y="Catch_Per_Night", hover_data=["Total_Catch", "Events"])
            fig3.update_layout(height=380, xaxis_title="", yaxis_title="Average mosquitoes caught per night")
            st.plotly_chart(fig3, use_container_width=True)
            with st.expander("View underlying site comparison table"):
                st.dataframe(by_site[["Site_ID", "Site_Name", "Events", "Total_Catch", "Catch_Per_Night"]],
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
            by_species = by_species.merge(data["species"][["Species_Code", "Scientific_Name"]], on="Species_Code", how="left")
            by_species = by_species.sort_values("Number_Collected", ascending=False)
            fig4 = px.bar(by_species, x="Scientific_Name", y="Number_Collected")
            fig4.update_layout(height=350, xaxis_title="", yaxis_title="Total collected")
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("No species results for the current filter selection.")

        st.divider()

        # --- Unusually high trap counts / persistent increases -----------------
        st.subheader("Unusually high trap counts")
        st.caption(
            "A trap-night result is flagged here if it is more than 2x the site's own median mosquitoes caught per night "
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
                        columns={"Deployment_DateTime": "Deployment Date", "Site_Median": "Site's typical catch per night"}),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.success("No unusually high trap counts flagged for this selection.")
        else:
            st.info("No usable surveillance data available.")

    with tab_dip:
        st.subheader("Dip log")
        dips_f = ui.filter_by_season_date(data["larvae_dips"], filters, date_col="DateTime")
        dips_f = ui.filter_by_sites(dips_f, filters)
        if dips_f.empty:
            st.info("No larvae dip data logged for the current filter selection.")
        else:
            display_dips = dips_f.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")
            display_dips["High count"] = display_dips["Larvae_Count"] > HIGH_LARVAE_COUNT_PER_DIP
            st.dataframe(
                display_dips[["Dip_ID", "Site_Name", "DateTime", "Larvae_Count", "High count", "Officer"]]
                .sort_values("DateTime", ascending=False),
                use_container_width=True, hide_index=True, height=350,
            )

    with tab_log:
        # --- Raw trap results table with filters ---------------------------------
        st.subheader("Surveillance event log")
        display_events = events_f.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")
        st.dataframe(
            display_events[["Event_ID", "Site_Name", "Deployment_DateTime", "Retrieval_DateTime",
                             "Trap_Type", "Trap_Status", "Sample_Validity", "Officer"]].sort_values(
                "Deployment_DateTime", ascending=False),
            use_container_width=True, hide_index=True, height=420,
        )


render()
