"""Treatments - register, planning workflow (Planned/Scheduled/Completed/Cancelled)."""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui
from core.config import TREATMENT_STATUSES


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Treatments")
    ui.sample_data_banner()

    treatments = data["treatments"]
    # Include a treatment in the selected period if EITHER its planned date or
    # its actual treatment date falls in range, so upcoming/planned work isn't
    # silently dropped just because it has no Treatment_Date yet.
    in_season = treatments[treatments["Season"] == filters["season"]].copy()
    start, end = filters["date_range"]
    date_ref = in_season["Treatment_Date"].fillna(in_season["Planned_Date"])
    in_period = in_season[(date_ref.dt.date >= start) & (date_ref.dt.date <= end)]
    t = ui.filter_by_sites(in_period, filters).merge(
        data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left"
    ).merge(data["products"][["Product_ID", "Product_Name"]], on="Product_ID", how="left")

    tab_register, tab_planning, tab_summary = st.tabs(["Treatment register", "Planning board", "Summary"])

    with tab_register:
        st.subheader("Treatment register")
        status_filter = st.multiselect("Filter by status", TREATMENT_STATUSES, default=TREATMENT_STATUSES)
        t_display = t[t["Treatment_Status"].isin(status_filter)]
        st.dataframe(
            t_display[["Treatment_ID", "Site_Name", "Treatment_Status", "Treatment_Type", "Product_Name",
                       "Application_Method", "Area_Treated_Ha", "Quantity_Used", "Planned_Date", "Treatment_Date",
                       "Operator", "Reason", "Cancelled_Reason"]].sort_values("Planned_Date", ascending=False),
            use_container_width=True, hide_index=True, height=420,
        )
        st.download_button(
            "Export filtered register to CSV", t_display.to_csv(index=False).encode("utf-8"),
            file_name="treatment_register.csv", mime="text/csv",
        )

    with tab_planning:
        st.subheader("Upcoming treatments")
        upcoming = t[t["Treatment_Status"].isin(["Planned", "Scheduled"])].sort_values("Planned_Date")
        if not upcoming.empty:
            st.dataframe(
                upcoming[["Treatment_ID", "Site_Name", "Treatment_Status", "Treatment_Type", "Planned_Date", "Operator", "Reason"]],
                use_container_width=True, hide_index=True,
            )
        else:
            st.success("No upcoming planned/scheduled treatments in this period.")

        st.subheader("Treatments requiring follow-up")
        st.caption(
            "A completed treatment is flagged for follow-up here if no further surveillance event has been "
            "logged at that site since the treatment date - a simple, transparent rule."
        )
        completed = t[t["Treatment_Status"] == "Completed"]
        events = data["surv_events"]
        followup_rows = []
        for _, tr in completed.iterrows():
            if pd.isna(tr["Treatment_Date"]):
                continue
            later_events = events[(events["Site_ID"] == tr["Site_ID"]) &
                                   (events["Deployment_DateTime"] > tr["Treatment_Date"])]
            if later_events.empty:
                followup_rows.append(tr)
        if followup_rows:
            fu_df = pd.DataFrame(followup_rows)
            st.dataframe(
                fu_df[["Treatment_ID", "Site_Name", "Treatment_Date", "Treatment_Type", "Operator"]],
                use_container_width=True, hide_index=True,
            )
        else:
            st.success("No completed treatments currently awaiting a follow-up survey.")

        st.divider()
        st.subheader("Record a new planned treatment (prototype form)")
        st.caption("Prototype only - does not yet write back to the data store. See README for the data-entry roadmap.")
        with st.form("new_treatment_form"):
            fc1, fc2 = st.columns(2)
            with fc1:
                ui.site_picker(data["sites"], key="new_treatment_site")
                st.selectbox("Treatment type", ["Larvicide Application", "Adulticide Application",
                                                 "Source Reduction / Habitat Modification"], key="new_treatment_type")
                st.selectbox("Proposed product", data["products"]["Product_Name"].tolist(), key="new_treatment_product")
            with fc2:
                st.date_input("Planned date", key="new_treatment_date")
                st.selectbox("Assigned officer", data["users"]["Name"].tolist(), key="new_treatment_officer")
                st.text_area("Notes", key="new_treatment_notes")
            st.form_submit_button("Save planned treatment (prototype - not persisted)")

    with tab_summary:
        st.subheader("Treatments by status")
        if not t.empty:
            by_status = t["Treatment_Status"].value_counts().reset_index()
            by_status.columns = ["Status", "Count"]
            fig = px.bar(by_status, x="Status", y="Count")
            fig.update_layout(height=320)
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Area treated by treatment type")
            completed_t = t[t["Treatment_Status"] == "Completed"]
            if not completed_t.empty:
                by_type = completed_t.groupby("Treatment_Type", as_index=False)["Area_Treated_Ha"].sum()
                fig2 = px.bar(by_type, x="Treatment_Type", y="Area_Treated_Ha")
                fig2.update_layout(height=320, xaxis_title="", yaxis_title="Area treated (ha)")
                st.plotly_chart(fig2, use_container_width=True)

            st.subheader("Product usage")
            if not completed_t.empty:
                by_product = completed_t.groupby("Product_Name", as_index=False)["Quantity_Used"].sum().dropna()
                if not by_product.empty:
                    fig3 = px.bar(by_product, x="Product_Name", y="Quantity_Used")
                    fig3.update_layout(height=320, xaxis_title="", yaxis_title="Quantity used (product-specific units)")
                    st.plotly_chart(fig3, use_container_width=True)
                    st.caption("Quantities are in each product's own rate unit - see Products page. Not directly comparable across products.")
        else:
            st.info("No treatments recorded for this selection.")


render()
