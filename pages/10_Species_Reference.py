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
        "The six species below are sourced from WA Department of Health public guidance ('Common mosquitoes in "
        "Western Australia'), chosen for relevance to an inner-Perth council area like Vincent - Aedes "
        "notoscriptus (the dominant urban/backyard-container species), the saltmarsh/estuarine species Aedes "
        "vigilax and Aedes camptorhynchus (relevant given the Swan River foreshore site and their long dispersal "
        "range), and the freshwater/urban species Culex annulirostris, Culex quinquefasciatus and Anopheles "
        "annulipes. For identifying a specimen that doesn't match one of these, see WA Health's "
        "[South-West adult mosquito photographic key](https://www.health.wa.gov.au/~/media/Corp/Documents/"
        "Health-for/Mosquitoes/PDF/South-West-adult-mosquito-photographic-key.pdf), which covers the broader "
        "range of species present in the region. Always confirm current guidance directly with WA Health for "
        "anything operationally significant."
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
        fig = px.bar(by_sp, x="Scientific_Name", y="Number_Collected", hover_data=["Common_Name"])
        fig.update_layout(height=340, xaxis_title="")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No species results for the current filter selection.")

    st.divider()
    st.subheader("Species reference")
    for _, sp in species.iterrows():
        with st.expander(f"*{sp['Scientific_Name']}*"):
            st.caption(f"Common name: {sp['Common_Name']}")
            st.markdown(f"**Typical breeding habitat:** {sp['Typical_Breeding_Habitat']}")
            st.markdown(f"**Biting behaviour:** {sp['Biting_Behaviour']}")
            st.markdown(f"**Seasonal characteristics:** {sp['Seasonal_Characteristics']}")
            st.markdown(f"**Vector significance:** {sp['Vector_Significance']}")
            if sp["Notes"]:
                st.caption(sp["Notes"])


render()
