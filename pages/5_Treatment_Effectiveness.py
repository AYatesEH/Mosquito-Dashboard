"""Treatment Effectiveness - observed before/after comparison. Explicitly avoids causal claims."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import ui, calculations as calc
from core.config import DEFAULT_PRE_WINDOW_DAYS, DEFAULT_POST_WINDOW_DAYS


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Treatment Effectiveness")
    ui.sample_data_banner()
    st.info(
        "Results below describe **observed changes associated with** each treatment, not proven cause and effect. "
        "Weather, tides, surveillance effort and other factors may also influence mosquito abundance over the same "
        "window. Always read effectiveness alongside the comparison window sizes and event counts shown."
    )

    ct_all = calc.event_catch_totals(data["surv_events"], data["surv_results"])

    c1, c2 = st.columns(2)
    pre_days = c1.slider("Pre-treatment comparison window (days)", 3, 14, DEFAULT_PRE_WINDOW_DAYS)
    post_days = c2.slider("Post-treatment comparison window (days)", 3, 14, DEFAULT_POST_WINDOW_DAYS)

    treatments = data["treatments"]
    in_season = treatments[(treatments["Season"] == filters["season"]) & (treatments["Treatment_Status"] == "Completed")]
    in_season = ui.filter_by_sites(in_season, filters).merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")

    if in_season.empty:
        st.info("No completed treatments for this selection.")
        st.stop()

    results = []
    for _, row in in_season.iterrows():
        res = calc.assess_treatment_effectiveness(row, ct_all, pre_days=pre_days, post_days=post_days)
        results.append({
            "Treatment_ID": res.treatment_id, "Site_ID": res.site_id,
            "Site_Name": row["Site_Name"], "Treatment_Date": res.treatment_date,
            "Pre_Abundance": res.pre_abundance, "Post_Abundance": res.post_abundance,
            "Pct_Change": res.pct_change, "Pre_Events": res.pre_events, "Post_Events": res.post_events,
            "Sufficient_Data": res.sufficient_data, "Note": res.note,
        })
    results_df = pd.DataFrame(results)

    n_sufficient = int(results_df["Sufficient_Data"].sum())
    st.subheader("Summary")
    ui.kpi_row([
        ("Completed treatments assessed", str(len(results_df)), None),
        ("With sufficient surveillance data", str(n_sufficient), None),
        ("Insufficient data", str(len(results_df) - n_sufficient), "Shown for transparency - not excluded silently."),
        ("Median observed change", f"{results_df['Pct_Change'].median():+.0f}%"
         if results_df["Pct_Change"].notna().any() else "N/A", "Negative = lower abundance after treatment."),
    ])

    st.divider()
    st.subheader("Results by treatment")
    display_df = results_df.copy()
    display_df["Assessment"] = display_df["Sufficient_Data"].map({True: "Assessed", False: "Insufficient data"})
    st.dataframe(
        display_df[["Treatment_ID", "Site_Name", "Treatment_Date", "Pre_Abundance", "Post_Abundance",
                    "Pct_Change", "Pre_Events", "Post_Events", "Assessment"]].sort_values("Treatment_Date", ascending=False),
        use_container_width=True, hide_index=True, height=350,
    )

    st.divider()
    st.subheader("Inspect one treatment")
    options = (display_df["Site_Name"] + " - " + display_df["Treatment_ID"] + " (" +
               display_df["Treatment_Date"].dt.strftime("%Y-%m-%d") + ")").tolist()
    if options:
        choice = st.selectbox("Select a treatment", options)
        chosen_id = choice.split("(")[0].strip().split(" - ")[-1]
        chosen = display_df[display_df["Treatment_ID"] == chosen_id].iloc[0]
        site_id = chosen["Site_ID"]
        treatment_date = chosen["Treatment_Date"]

        site_events = ct_all[ct_all["Site_ID"] == site_id].sort_values("Deployment_DateTime")
        window_events = site_events[
            (site_events["Deployment_DateTime"] >= treatment_date - pd.Timedelta(days=pre_days)) &
            (site_events["Deployment_DateTime"] <= treatment_date + pd.Timedelta(days=post_days))
        ]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=window_events["Deployment_DateTime"], y=window_events["Mosquitoes_Per_Trap_Night"],
                                  mode="lines+markers", name="Mosquitoes/trap-night"))
        fig.add_vline(x=treatment_date, line_color="#C62828", line_dash="dash")
        fig.update_layout(height=380, yaxis_title="Mosquitoes / trap-night",
                           title=f"{chosen['Site_Name']} - {chosen_id}")
        st.plotly_chart(fig, use_container_width=True)

        if chosen["Sufficient_Data"]:
            st.markdown(
                f"Pre-treatment mean: **{chosen['Pre_Abundance']}** mosquitoes/trap-night "
                f"({int(chosen['Pre_Events'])} usable event(s)) | "
                f"Post-treatment mean: **{chosen['Post_Abundance']}** ({int(chosen['Post_Events'])} usable event(s)) | "
                f"Observed change: **{chosen['Pct_Change']:+.0f}%**"
            )
        else:
            st.warning(chosen["Note"])
        if chosen["Sufficient_Data"]:
            st.caption(chosen["Note"])


render()
