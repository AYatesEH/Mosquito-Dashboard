"""Complaints - register and trend comparison against trap counts/species/treatments/hotspots."""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Complaints")
    ui.sample_data_banner()

    complaints_f = ui.filter_by_season_date(data["complaints"], filters, date_col="Date_Received")
    complaints_f = ui.filter_by_sites(complaints_f, filters)

    with_site_id = int(((complaints_f["Site_ID"].notna()) & (complaints_f["Site_ID"] != "")).sum())
    ui.kpi_row([
        ("Complaints received", str(len(complaints_f)), None),
        ("Open / under investigation", str(int((complaints_f["Investigation_Status"] != "Closed").sum())), None),
        ("With a site identified", str(with_site_id), None),
        ("Most common category", complaints_f["Category"].mode().iloc[0] if not complaints_f.empty else "N/A", None),
    ])

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Complaints over time")
        if not complaints_f.empty:
            daily = complaints_f.groupby(complaints_f["Date_Received"].dt.date, as_index=False).size()
            daily.columns = ["Date", "Complaints"]
            fig = px.bar(daily, x="Date", y="Complaints")
            fig.update_layout(height=340)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No complaints for this selection.")
    with col2:
        st.subheader("By category")
        if not complaints_f.empty:
            by_cat = complaints_f["Category"].value_counts().reset_index()
            by_cat.columns = ["Category", "Count"]
            fig2 = px.bar(by_cat, x="Category", y="Count")
            fig2.update_layout(height=340, xaxis_title="")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No complaints for this selection.")

    st.divider()
    st.subheader("Complaints vs. trap counts and treatments")
    st.caption("Visual comparison only - a rise in complaints and a rise in trap counts or treatments in the same "
               "window does not by itself prove one caused the other.")
    events_f = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    ct = calc.event_catch_totals(events_f, data["surv_results"])

    if not complaints_f.empty and not ct.empty:
        c_daily = complaints_f.groupby(complaints_f["Date_Received"].dt.date, as_index=False).size()
        c_daily.columns = ["Date", "Complaints"]
        t_daily = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Total_Catch"].sum()
        t_daily.columns = ["Date", "Total_Catch"]
        merged = c_daily.merge(t_daily, on="Date", how="outer").fillna(0).sort_values("Date")
        fig3 = px.bar(merged, x="Date", y="Complaints")
        fig3.add_scatter(x=merged["Date"], y=merged["Total_Catch"], mode="lines", name="Total catch (right axis)")
        fig3.update_layout(height=360)
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("Insufficient data to compare complaints with trap counts for this selection.")

    st.divider()
    st.subheader("Complaint register")
    site_names = data["sites"][["Site_ID", "Site_Name"]]
    display = complaints_f.merge(site_names, on="Site_ID", how="left")
    st.dataframe(
        display[["Complaint_ID", "Date_Received", "Site_Name", "Category", "Investigation_Status", "Outcome", "Officer"]]
        .sort_values("Date_Received", ascending=False),
        use_container_width=True, hide_index=True, height=380,
    )
    st.download_button("Export complaints to CSV", display.to_csv(index=False).encode("utf-8"),
                        file_name="complaints_export.csv", mime="text/csv")


render()
