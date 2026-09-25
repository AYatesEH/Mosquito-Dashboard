"""Reporting - season-summary rollup suitable for management/end-of-season reporting."""

import pandas as pd
import streamlit as st

from core import ui, calculations as calc
from core.config import STATUS_ACTION, STATUS_ELEVATED


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Reporting")
    ui.sample_data_banner()
    st.caption(f"Season summary for **{filters['season']}** ({filters['date_range'][0]} to {filters['date_range'][1]})")

    events_f = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    ct = calc.event_catch_totals(events_f, data["surv_results"])
    treatments_f = ui.filter_by_season_date(data["treatments"], filters, date_col="Treatment_Date")
    complaints_f = ui.filter_by_season_date(data["complaints"], filters, date_col="Date_Received")
    thresholds = data["thresholds"]

    kpis = calc.kpi_summary(ct, treatments_f, complaints_f, thresholds)
    targets_row = data["targets"][data["targets"]["Season"] == filters["season"]]
    planned_events = int(targets_row["Planned_Surveillance_Events"].iloc[0]) if not targets_row.empty else 0
    planned_treatments = int(targets_row["Planned_Treatments"].iloc[0]) if not targets_row.empty else 0

    as_of = pd.Timestamp(filters["date_range"][1])
    hotspots = calc.identify_hotspots(ct, data["complaints"], data["treatments"], thresholds, as_of=as_of)
    dq = calc.data_quality_report(data["sites"], data["trap_sites"], data["surv_events"],
                                   data["surv_results"], data["treatments"], data["complaints"])

    completed = treatments_f[treatments_f["Treatment_Status"] == "Completed"]
    n_effectiveness_assessed, n_effectiveness_sufficient, pct_changes = 0, 0, []
    for _, row in completed.iterrows():
        res = calc.assess_treatment_effectiveness(row, ct)
        n_effectiveness_assessed += 1
        if res.sufficient_data:
            n_effectiveness_sufficient += 1
            if res.pct_change is not None:
                pct_changes.append(res.pct_change)

    # --- Report sections (built as plain data structures so an Excel/PDF ----
    # export can consume the same content without re-deriving it) -----------
    sections = {
        "Surveillance": {
            "Total mosquitoes trapped": f"{kpis['total_mosquitoes']:,}",
            "Mosquitoes per trap-night": f"{kpis['mosquitoes_per_trap_night']:.2f}" if kpis["mosquitoes_per_trap_night"] is not None else "N/A",
            "Successful trap-nights": f"{kpis['successful_trap_nights']:,.0f}",
            "Surveillance completion (SAMPLE target)": f"{calc.surveillance_program_completion(events_f, planned_events):.0f}%" if planned_events else "N/A",
        },
        "Species": {
            "Most abundant species": (
                data["species"].merge(
                    data["surv_results"][data["surv_results"]["Event_ID"].isin(ct["Event_ID"])]
                    .groupby("Species_Code", as_index=False)["Number_Collected"].sum()
                    .sort_values("Number_Collected", ascending=False).head(1),
                    on="Species_Code", how="inner",
                )["Scientific_Name"].iloc[0]
                if not ct.empty else "N/A"
            ),
        },
        "Hotspots": {
            "Sites currently flagged": str(len(hotspots)),
        },
        "Treatments": {
            "Completed": str(kpis["treatments_completed"]),
            "Planned/Scheduled": str(kpis["treatments_scheduled"]),
            "Total area treated (m²)": f"{kpis['area_treated_m2']:,.0f}",
            "Treatment completion (SAMPLE target)": f"{100*kpis['treatments_completed']/planned_treatments:.0f}%" if planned_treatments else "N/A",
        },
        "Treatment effectiveness": {
            "Completed treatments assessed": str(n_effectiveness_assessed),
            "With sufficient surveillance data": str(n_effectiveness_sufficient),
            "Median observed change (where assessed)": f"{pd.Series(pct_changes).median():+.0f}%" if pct_changes else "N/A",
        },
        "Complaints": {
            "Received": str(kpis["complaints_received"]),
            "Open / under investigation": str(int((complaints_f["Investigation_Status"] != "Closed").sum())),
        },
        "Environmental conditions": {
            "Total rainfall (mm, region-wide sample data)": f"{data['environmental'][(data['environmental']['Date'].dt.date >= filters['date_range'][0]) & (data['environmental']['Date'].dt.date <= filters['date_range'][1])]['Rainfall_mm'].sum():.0f}",
        },
        "Program completion": {
            "Surveillance completion (SAMPLE target)": f"{calc.surveillance_program_completion(events_f, planned_events):.0f}%" if planned_events else "N/A",
            "Treatment completion (SAMPLE target)": f"{100*kpis['treatments_completed']/planned_treatments:.0f}%" if planned_treatments else "N/A",
        },
        "Data quality": {
            "Total issues detected": str(len(dq)),
            "High severity": str(int((dq["Severity"] == "High").sum())) if not dq.empty else "0",
        },
    }

    for section_name, kv in sections.items():
        st.subheader(section_name)
        st.table(pd.DataFrame(list(kv.items()), columns=["Metric", "Value"]).set_index("Metric"))

    st.divider()
    st.subheader("Export")
    st.caption("A full PDF/Excel export template is a natural next increment for this prototype - the flattened "
               "table below is the same content this page shows, in export-ready form.")

    flat_rows = []
    for section_name, kv in sections.items():
        for metric, value in kv.items():
            flat_rows.append({"Section": section_name, "Metric": metric, "Value": value})
    flat_df = pd.DataFrame(flat_rows)
    st.download_button(
        "Export season summary to CSV", flat_df.to_csv(index=False).encode("utf-8"),
        file_name=f"season_summary_{filters['season']}.csv", mime="text/csv",
    )
    st.caption(
        "CSV export is provided now; PDF and formatted-Excel exports are listed in the README as a near-term "
        "extension once report layout/branding requirements are confirmed."
    )


render()
