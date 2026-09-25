"""Surveillance - trap results, effort/failure tracking, abundance analysis."""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc

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

    with st.expander("+ Log a trap check (deployment + retrieval + results)"):
        st.caption(
            "Saves to this prototype's CSV data store - fine for a single-user demo/pilot, see README Section 6 "
            "for moving to a real backend before relying on this for a live season. Logged as one entry, after "
            "the trap has been retrieved and read - matching how this is normally done at a desk, not standing "
            "at the trap."
        )
        active_traps = data["trap_sites"][data["trap_sites"]["Trap_Status"] == "Active"].merge(
            data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left"
        )
        if active_traps.empty:
            st.warning("No active traps to log against.")
        else:
            trap_labels = (active_traps["Trap_ID"] + " - " + active_traps["Site_Name"] + " (" + active_traps["Trap_Type"] + ")").tolist()
            trap_lookup = dict(zip(trap_labels, active_traps["Trap_ID"]))

            sc1, sc2 = st.columns(2)
            with sc1:
                new_trap_label = st.selectbox("Trap", trap_labels, key="new_event_trap")
                new_trap_id = trap_lookup[new_trap_label]
                new_trap_row = active_traps[active_traps["Trap_ID"] == new_trap_id].iloc[0]
                new_deploy_date = st.date_input("Deployment date", value=pd.Timestamp.now().date() - pd.Timedelta(days=2), key="new_event_deploy_date")
                new_retrieve_date = st.date_input("Retrieval date", value=pd.Timestamp.now().date(), key="new_event_retrieve_date")
            with sc2:
                new_outcome = st.selectbox("Trap outcome", TRAP_OUTCOMES, key="new_event_outcome")
                new_validity = st.selectbox(
                    "Sample validity", ["Valid", "Invalid", "N/A"],
                    index=["Valid", "Invalid", "N/A"].index(DEFAULT_VALIDITY[new_outcome]), key="new_event_validity",
                )
                new_officer = st.selectbox("Officer", data["users"]["Name"].tolist(), key="new_event_officer")

            counts_df = None
            if new_outcome in ("Successful", "Partial") and new_validity == "Valid":
                st.caption("Enter the number collected per species (leave at 0 for species not caught):")
                species_for_count = data["species"][data["species"]["Species_Code"] != "OTHER"][["Species_Code", "Scientific_Name"]].copy()
                species_for_count["Number_Collected"] = 0
                counts_df = st.data_editor(
                    species_for_count, use_container_width=True, hide_index=True, key="new_event_counts",
                    column_config={
                        "Species_Code": st.column_config.TextColumn(disabled=True),
                        "Scientific_Name": st.column_config.TextColumn(disabled=True),
                        "Number_Collected": st.column_config.NumberColumn(min_value=0, step=1),
                    },
                )

            new_event_notes = st.text_area("Notes", key="new_event_notes")

            if st.button("Save trap check", type="primary"):
                if new_retrieve_date < new_deploy_date:
                    st.error("Retrieval date can't be before the deployment date.")
                else:
                    event_id = ui.add_surveillance_event({
                        "Trap_ID": new_trap_id,
                        "Site_ID": new_trap_row["Site_ID"],
                        "Season": ui.infer_season(new_deploy_date),
                        "Deployment_DateTime": new_deploy_date.strftime("%Y-%m-%d %H:%M"),
                        "Retrieval_DateTime": new_retrieve_date.strftime("%Y-%m-%d %H:%M"),
                        "Trap_Type": new_trap_row["Trap_Type"],
                        "Trap_Status": new_outcome,
                        "Sample_Validity": new_validity,
                        "Officer": new_officer,
                        "Notes": new_event_notes,
                        "Created_By": new_officer,
                        "Created_Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                    })
                    n_results = 0
                    if counts_df is not None:
                        for _, r in counts_df.iterrows():
                            if int(r["Number_Collected"]) > 0:
                                ui.add_surveillance_result({
                                    "Event_ID": event_id,
                                    "Species_Code": r["Species_Code"],
                                    "Number_Collected": int(r["Number_Collected"]),
                                    "Notes": "",
                                })
                                n_results += 1
                    st.success(f"Saved {event_id} ({n_results} species result{'s' if n_results != 1 else ''}). The charts and log below now include it.")
                    st.rerun()

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
