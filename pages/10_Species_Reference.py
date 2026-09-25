"""Species Reference - interpret surveillance results by species rather than treating all mosquitoes as equivalent."""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Species Reference")
    st.info(
        "Breeding habitat, biting behaviour, seasonal characteristics and vector-significance fields below are "
        "SAMPLE, simplified descriptions for prototype demonstration - not verified scientific or public-health "
        "reference material. Scientific/common names are real for realism; the descriptive fields are not "
        "authoritative and should be replaced with verified content before any operational use."
    )

    species = data["species"][data["species"]["Species_Code"] != "OTHER"]

    events_f = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    ct = calc.event_catch_totals(events_f, data["surv_results"])
    results_f = data["surv_results"][data["surv_results"]["Event_ID"].isin(ct["Event_ID"])]
    results_f = results_f[results_f["Number_Collected"].fillna(-1) >= 0]

    st.subheader("Abundance by species this period")
    if not results_f.empty:
        by_sp = results_f.groupby("Species_Code", as_index=False)["Number_Collected"].sum()
        by_sp = by_sp.merge(species[["Species_Code", "Common_Name", "Scientific_Name"]], on="Species_Code", how="left")
        by_sp = by_sp.sort_values("Number_Collected", ascending=False)
        fig = px.bar(by_sp, x="Common_Name", y="Number_Collected", hover_data=["Scientific_Name"])
        fig.update_layout(height=340, xaxis_title="")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No species results for the current filter selection.")

    st.divider()
    st.subheader("Species reference")
    for _, sp in species.iterrows():
        with st.expander(f"{sp['Common_Name']} ({sp['Scientific_Name']})"):
            st.markdown(f"**Typical breeding habitat:** {sp['Typical_Breeding_Habitat']}")
            st.markdown(f"**Biting behaviour:** {sp['Biting_Behaviour']}")
            st.markdown(f"**Seasonal characteristics:** {sp['Seasonal_Characteristics']}")
            st.markdown(f"**Vector significance:** {sp['Vector_Significance']}")
            if sp["Notes"]:
                st.caption(sp["Notes"])


render()
