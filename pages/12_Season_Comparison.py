"""Season Comparison - compares seasons using effort-normalised statistics, not raw totals alone."""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc


def _season_stats(season, data):
    events = data["surv_events"][data["surv_events"]["Season"] == season]
    ct = calc.event_catch_totals(events, data["surv_results"])
    treatments = data["treatments"][data["treatments"]["Season"] == season]
    complaints = data["complaints"][data["complaints"]["Season"] == season]
    completed = treatments[treatments["Treatment_Status"] == "Completed"]

    total_catch = ct["Total_Catch"].sum() if not ct.empty else 0
    trap_nights = ct["Trap_Nights"].sum() if not ct.empty else 0
    mptn = (total_catch / trap_nights) if trap_nights else None

    as_of = events["Deployment_DateTime"].max() if not events.empty else pd.Timestamp.now()
    hotspots = calc.identify_hotspots(ct, data["complaints"], data["treatments"], data["thresholds"], as_of=as_of) \
        if pd.notna(as_of) else pd.DataFrame()

    results = data["surv_results"][data["surv_results"]["Event_ID"].isin(ct["Event_ID"])]
    results = results[results["Number_Collected"].fillna(-1) >= 0]
    species_comp = results.groupby("Species_Code")["Number_Collected"].sum()
    species_comp_pct = (species_comp / species_comp.sum() * 100).round(1) if species_comp.sum() else species_comp

    targets_row = data["targets"][data["targets"]["Season"] == season]
    planned_events = int(targets_row["Planned_Surveillance_Events"].iloc[0]) if not targets_row.empty else 0

    return {
        "Season": season,
        "Total mosquitoes": int(total_catch),
        "Mosquitoes/trap-night": round(mptn, 2) if mptn is not None else None,
        "Successful trap-nights": round(float(trap_nights), 0),
        "Surveillance events logged": len(events),
        "Surveillance completion %": calc.surveillance_program_completion(events, planned_events) if planned_events else None,
        "Treatments completed": len(completed),
        "Area treated (m²)": round(float(completed["Area_Treated_M2"].fillna(0).sum()), 0),
        "Product used (sum, mixed units)": round(float(completed["Quantity_Used"].fillna(0).sum()), 1),
        "Complaints received": len(complaints),
        "Sites flagged as hotspots": len(hotspots) if not hotspots.empty else 0,
        "_species_comp_pct": species_comp_pct,
    }


def render():
    ui.apply_page_style()
    data = ui.get_data()
    ui.render_global_filters(data)

    st.title("Season Comparison")
    ui.sample_data_banner()
    st.caption(
        "Comparisons use mosquitoes-PER-TRAP-NIGHT and completion percentages, not raw totals alone, because "
        "surveillance effort (number of trap-nights) can differ between seasons and would otherwise make raw "
        "totals misleading."
    )

    seasons = ["2023-24", "2024-25", "2025-26"]
    stats = [_season_stats(s, data) for s in seasons]
    stats_df = pd.DataFrame(stats)
    species_by_season = {s["Season"]: s["_species_comp_pct"] for s in stats}
    display_df = stats_df.drop(columns=["_species_comp_pct"])

    st.subheader("Headline comparison")
    st.dataframe(display_df.set_index("Season").T, use_container_width=True)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Mosquitoes per trap-night by season")
        fig = px.bar(display_df, x="Season", y="Mosquitoes/trap-night")
        fig.update_layout(height=340)
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader("Surveillance completion by season")
        if display_df["Surveillance completion %"].notna().any():
            fig2 = px.bar(display_df, x="Season", y="Surveillance completion %")
            fig2.update_layout(height=340)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No program targets configured for these seasons.")

    st.divider()
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Treatments and area treated")
        fig3 = px.bar(display_df, x="Season", y="Area treated (m²)")
        fig3.update_layout(height=340)
        st.plotly_chart(fig3, use_container_width=True)
    with col4:
        st.subheader("Complaints and hotspots")
        melt = display_df.melt(id_vars="Season", value_vars=["Complaints received", "Sites flagged as hotspots"],
                                var_name="Metric", value_name="Count")
        fig4 = px.bar(melt, x="Season", y="Count", color="Metric", barmode="group")
        fig4.update_layout(height=340)
        st.plotly_chart(fig4, use_container_width=True)

    st.divider()
    st.subheader("Species composition by season")
    species_ref = data["species"][["Species_Code", "Scientific_Name"]]
    comp_rows = []
    for season, comp in species_by_season.items():
        for code, pct in comp.items():
            comp_rows.append({"Season": season, "Species_Code": code, "Percent": pct})
    if comp_rows:
        comp_df = pd.DataFrame(comp_rows).merge(species_ref, on="Species_Code", how="left")
        fig5 = px.bar(comp_df, x="Season", y="Percent", color="Scientific_Name", barmode="stack")
        fig5.update_layout(height=380, yaxis_title="% of total catch")
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("No species composition data available across these seasons.")

    st.caption(
        "The current season (2025-26 in this prototype) may show lower totals simply because it is not yet "
        "complete - the completion percentages above are the fairer basis for comparison until the season ends."
    )


render()
