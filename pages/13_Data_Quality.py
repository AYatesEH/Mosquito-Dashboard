"""Data Quality - detection only, never silent correction."""

import streamlit as st

from core import ui, calculations as calc


def render():
    ui.apply_page_style()
    data = ui.get_data()
    ui.render_global_filters(data)

    st.title("Data Quality")
    st.info(
        "This page only DETECTS and reports issues - nothing here is corrected automatically. Officers should "
        "locate and fix flagged records at the source (or via a future data-entry workflow)."
    )

    dq = calc.data_quality_report(
        data["sites"], data["trap_sites"], data["surv_events"], data["surv_results"],
        data["treatments"], data["complaints"],
    )

    ui.kpi_row([
        ("Total issues", str(len(dq)), None),
        ("High severity", str(int((dq["Severity"] == "High").sum())) if not dq.empty else "0", None),
        ("Medium severity", str(int((dq["Severity"] == "Medium").sum())) if not dq.empty else "0", None),
        ("Low severity", str(int((dq["Severity"] == "Low").sum())) if not dq.empty else "0",
         "Includes informational items such as invalid samples correctly excluded from stats."),
    ])

    if dq.empty:
        st.success("No data quality issues detected.")
        st.stop()

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        severity_filter = st.multiselect("Severity", sorted(dq["Severity"].unique()), default=sorted(dq["Severity"].unique()))
    with c2:
        dataset_filter = st.multiselect("Dataset", sorted(dq["Dataset"].unique()), default=sorted(dq["Dataset"].unique()))

    filtered = dq[dq["Severity"].isin(severity_filter) & dq["Dataset"].isin(dataset_filter)]
    severity_order = {"High": 0, "Medium": 1, "Low": 2}
    filtered = filtered.assign(_ord=filtered["Severity"].map(severity_order)).sort_values("_ord").drop(columns="_ord")

    st.subheader(f"Issues ({len(filtered)})")
    st.dataframe(
        filtered[["Severity", "Dataset", "Record_ID", "Description"]],
        use_container_width=True, hide_index=True, height=450,
    )
    st.download_button("Export data quality report to CSV", filtered.to_csv(index=False).encode("utf-8"),
                        file_name="data_quality_report.csv", mime="text/csv")

    st.divider()
    st.subheader("Checks performed")
    st.markdown(
        "- Missing coordinates on sites\n"
        "- Orphaned Site_ID / Trap_ID / Event_ID references across trap_sites, surveillance_events, "
        "surveillance_results, treatments and complaints\n"
        "- Retrieval date/time before deployment date/time\n"
        "- Implausibly long trap deployments (> 14 days)\n"
        "- Negative mosquito counts\n"
        "- Missing species codes\n"
        "- Duplicate Event_ID + Species_Code result rows\n"
        "- Completed treatments missing a product, with zero/blank area treated, or missing an operator\n"
        "- Cancelled treatments with no reason recorded\n"
        "- Complaints referencing a Site_ID not found in the sites table\n"
        "- Invalid/NA samples (flagged as low-severity/informational - these are already correctly excluded "
        "from all abundance statistics elsewhere in the dashboard, see core/calculations.py)"
    )


render()
