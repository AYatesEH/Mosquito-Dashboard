"""Field Observations - officer-recorded observations against a Site_ID."""

import pandas as pd
import streamlit as st

from core import ui
from core.config import OBSERVATION_CATEGORIES


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Field Observations")
    ui.sample_data_banner()

    obs = ui.filter_by_season_date(data["observations"], filters, date_col="DateTime")
    obs = ui.filter_by_sites(obs, filters)
    obs = obs.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")

    ui.kpi_row([
        ("Observations this period", str(len(obs)), None),
        ("Follow-up required", str(int((obs["Observation_Category"] == "Follow-up required").sum())), None),
        ("Access issues", str(int((obs["Observation_Category"] == "Access issue").sum())), None),
        ("Breeding habitat present", str(int((obs["Observation_Category"] == "Breeding habitat present").sum())), None),
    ])

    st.divider()
    category_filter = st.multiselect(
        "Filter by category", sorted(data["observations"]["Observation_Category"].unique()),
        default=sorted(data["observations"]["Observation_Category"].unique()),
    )
    obs_display = obs[obs["Observation_Category"].isin(category_filter)]

    st.subheader("Observation log")
    st.dataframe(
        obs_display[["DateTime", "Site_Name", "Observation_Category", "Officer", "Notes"]].sort_values(
            "DateTime", ascending=False),
        use_container_width=True, hide_index=True, height=420,
    )

    st.divider()
    st.caption(
        "Photos/attachments are not yet supported in this prototype, but the data model (Observation_ID + "
        "Site_ID) is designed so they can be associated with an observation later without restructuring the table."
    )


render()
