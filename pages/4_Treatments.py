"""Treatments - register, planning workflow (Planned/Scheduled/Completed/Cancelled)."""

import math
from datetime import datetime, time as dt_time

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui
from core import calculations as calc
from core.config import (
    TREATMENT_STATUSES, REDOSE_LEAD_DAYS, REDOSE_ON_TRACK, REDOSE_DUE_SOON,
    REDOSE_OVERDUE, REDOSE_NOT_SCHEDULED, REDOSE_STATUS_COLOURS,
    LABEL_RATE_OPTIONS, QUANTITY_USED_UNITS,
)


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

    tab_register, tab_planning, tab_redose, tab_summary = st.tabs(
        ["Treatment register", "Planning", "Re-dose schedule", "Summary"]
    )

    with tab_register:
        st.subheader("Treatment register")
        status_filter = st.multiselect("Filter by status", TREATMENT_STATUSES, default=TREATMENT_STATUSES)
        t_display = t[t["Treatment_Status"].isin(status_filter)]
        st.dataframe(
            ui.dates_only(t_display[["Treatment_ID", "Site_Name", "Treatment_Status", "Treatment_Type", "Product_Name",
                       "Application_Method", "Area_Treated_M2", "Quantity_Used", "Planned_Date", "Treatment_Date",
                       "Operator", "Reason", "Cancelled_Reason"]].sort_values("Planned_Date", ascending=False),
                          ["Planned_Date", "Treatment_Date"]),
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
                ui.dates_only(upcoming[["Treatment_ID", "Site_Name", "Treatment_Status", "Treatment_Type", "Planned_Date", "Operator", "Reason"]], ["Planned_Date"]),
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
                ui.dates_only(fu_df[["Treatment_ID", "Site_Name", "Treatment_Date", "Treatment_Type", "Operator"]], ["Treatment_Date"]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.success("No completed treatments currently awaiting a follow-up survey.")


    with tab_redose:
        st.subheader("Re-dose schedule")
        st.caption(
            "For each site's MOST RECENT completed larvicide application, estimates when its control window "
            "ends and flags when a re-dose visit is due. This is a planning estimate from the product's labelled "
            "duration-of-control (see Products page) - not a guarantee of ongoing control. Always confirm with "
            "surveillance/field inspection before assuming a site is still protected."
        )

        all_larvicide_treatments = data["treatments"]
        latest_dated = all_larvicide_treatments["Treatment_Date"].dropna()
        as_of_default = latest_dated.max().date() if not latest_dated.empty else pd.Timestamp.now().date()
        with st.expander("Advanced: assess as of a different date"):
            as_of_input = st.date_input(
                "Assess re-dose status as of", value=as_of_default,
                help="Defaults to the most recent completed treatment date in the data (this prototype's sample "
                     "data doesn't extend to today's real date).",
                key="redose_as_of",
            )

        schedule = calc.treatment_redose_schedule(
            data["treatments"], data["products"], as_of=pd.Timestamp(as_of_input), lead_days=REDOSE_LEAD_DAYS
        )
        if schedule.empty:
            st.info("No completed larvicide applications with a recorded product/date found for this data.")
        else:
            schedule = schedule.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")
            counts = schedule["Status"].value_counts()
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Overdue", int(counts.get(REDOSE_OVERDUE, 0)))
            k2.metric("Due soon", int(counts.get(REDOSE_DUE_SOON, 0)))
            k3.metric("On track", int(counts.get(REDOSE_ON_TRACK, 0)))
            k4.metric("Not scheduled", int(counts.get(REDOSE_NOT_SCHEDULED, 0)))

            status_options = schedule["Status"].unique().tolist()
            default_statuses = [s for s in [REDOSE_OVERDUE, REDOSE_DUE_SOON, REDOSE_ON_TRACK] if s in status_options]
            redose_status_filter = st.multiselect(
                "Filter by status", status_options, default=default_statuses or status_options, key="redose_status_filter"
            )
            display = schedule[schedule["Status"].isin(redose_status_filter)].sort_values("Redose_Due")
            display_fmt = ui.dates_only(display, ["Treatment_Date", "Effective_Until", "Redose_Due"])
            display_fmt["Status"] = display_fmt["Status"].apply(lambda s: ui.status_badge_html(s, REDOSE_STATUS_COLOURS))
            st.write(
                display_fmt[["Site_Name", "Product_Name", "Treatment_Date", "Rate_Used", "Rate_Unit",
                              "Duration_Days", "Effective_Until", "Redose_Due", "Status", "Note"]]
                .to_html(escape=False, index=False),
                unsafe_allow_html=True,
            )
            st.download_button(
                "Export re-dose schedule to CSV",
                display[["Site_Name", "Product_Name", "Treatment_Date", "Rate_Used", "Rate_Unit",
                          "Duration_Days", "Effective_Until", "Redose_Due", "Status", "Note"]].to_csv(index=False).encode("utf-8"),
                file_name="redose_schedule.csv", mime="text/csv",
            )

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
                by_type = completed_t.groupby("Treatment_Type", as_index=False)["Area_Treated_M2"].sum()
                fig2 = px.bar(by_type, x="Treatment_Type", y="Area_Treated_M2")
                fig2.update_layout(height=320, xaxis_title="", yaxis_title="Area treated (m²)")
                st.plotly_chart(fig2, use_container_width=True)

            st.subheader("Product usage")
            if not completed_t.empty:
                by_product = completed_t.groupby("Product_Name", as_index=False)["Quantity_Used"].sum().dropna()
                if not by_product.empty:
                    fig3 = px.bar(by_product, x="Product_Name", y="Quantity_Used")
                    fig3.update_layout(height=320, xaxis_title="", yaxis_title="Quantity used (product-specific units)")
                    st.plotly_chart(fig3, use_container_width=True)
                    st.caption(
                        "Quantities are in each product's own recording unit (grams for ProLink Pellets, whole "
                        "briquets for ProLink XR Briquets - see core.config.QUANTITY_USED_UNITS/Products page), "
                        "NOT the product's application rate unit. Not directly comparable across products."
                    )
        else:
            st.info("No treatments recorded for this selection.")


render()
