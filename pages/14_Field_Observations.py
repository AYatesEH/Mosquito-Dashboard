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
    with st.expander("+ Record a new observation"):
        st.caption(
            "Saves to this prototype's CSV data store - fine for a single-user demo/pilot, see README Section 6 "
            "for moving to a real backend before relying on this for a live season. Logging a \"Larvae dip / "
            "inspection\" observation here is also what clears a site's dipping/inspection task off the weekly "
            "To Do List."
        )
        fc1, fc2 = st.columns(2)
        with fc1:
            new_obs_site = ui.site_picker(data["sites"], key="new_obs_site")
            new_obs_date = st.date_input("Date", value=pd.Timestamp.now().date(), key="new_obs_date")
            new_obs_category = st.selectbox("Observation category", OBSERVATION_CATEGORIES, key="new_obs_category")
        with fc2:
            new_obs_officer = st.selectbox("Officer", data["users"]["Name"].tolist(), key="new_obs_officer")
            new_obs_notes = st.text_area("Notes", key="new_obs_notes")

        if st.button("Save observation", type="primary"):
            new_id = ui.add_site_observation({
                "Site_ID": new_obs_site or "",
                "Season": ui.infer_season(new_obs_date),
                "DateTime": pd.Timestamp(new_obs_date).strftime("%Y-%m-%d 00:00"),
                "Officer": new_obs_officer,
                "Observation_Category": new_obs_category,
                "Notes": new_obs_notes or "",
                "Created_By": new_obs_officer,
                "Created_Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
            })
            st.success(f"Saved {new_id}. The log, KPIs and any related To Do List tasks now reflect it.")
            st.rerun()
    st.caption(
        "Photos/attachments are not yet supported in this prototype, but the data model (Observation_ID + "
        "Site_ID) is designed so they can be associated with an observation later without restructuring the table."
    )


render()
