"""Complaints - register and trend comparison against trap counts/species/treatments/hotspots."""

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc

COMPLAINT_CATEGORIES = ["Biting nuisance", "Swarming/adult numbers", "Suspected breeding site",
                         "Standing water on property", "General enquiry"]
INVESTIGATION_STATUSES = ["Received", "Under Investigation", "Site Inspected", "Closed"]
OUTCOMES = ["No breeding found", "Breeding site identified and treated", "Referred to property owner"]


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
    with st.expander("+ Log a new complaint"):
        st.caption(
            "Saves to this prototype's CSV data store - fine for a single-user demo/pilot, see README Section 6 "
            "for moving to a real backend before relying on this for a live season."
        )
        cc1, cc2 = st.columns(2)
        with cc1:
            new_date_received = st.date_input("Date received", value=pd.Timestamp.now().date(), key="new_complaint_date")
            site_options = ["No specific site / general area"] + (
                data["sites"].sort_values("Site_Name")["Site_Name"] + " (" + data["sites"]["Site_ID"] + ")"
            ).tolist()
            new_site_choice = st.selectbox("Site (if known)", site_options, key="new_complaint_site")
            new_category = st.selectbox("Category", COMPLAINT_CATEGORIES, key="new_complaint_category")
        with cc2:
            new_status = st.selectbox("Investigation status", INVESTIGATION_STATUSES, key="new_complaint_status")
            new_officer = st.selectbox("Officer", data["users"]["Name"].tolist(), key="new_complaint_officer")
            new_outcome = st.selectbox("Outcome (if closed)", [""] + OUTCOMES, key="new_complaint_outcome") if new_status == "Closed" else ""
        new_description = st.text_area("Description", key="new_complaint_description")

        if st.button("Save complaint", type="primary"):
            if new_site_choice == "No specific site / general area":
                site_id, lat, lon = "", "", ""
            else:
                site_id = new_site_choice.split("(")[-1].rstrip(")")
                srow = data["sites"][data["sites"]["Site_ID"] == site_id].iloc[0]
                lat = srow["Latitude"] if pd.notna(srow["Latitude"]) else ""
                lon = srow["Longitude"] if pd.notna(srow["Longitude"]) else ""
            new_id = ui.add_complaint({
                "Date_Received": new_date_received.strftime("%Y-%m-%d"),
                "Season": ui.infer_season(new_date_received),
                "Site_ID": site_id,
                "Approx_Latitude": lat,
                "Approx_Longitude": lon,
                "Category": new_category,
                "Description": new_description or "No description provided.",
                "Investigation_Status": new_status,
                "Outcome": new_outcome,
                "Officer": new_officer,
                "Created_By": new_officer,
                "Created_Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
            })
            st.success(f"Saved {new_id}. The KPIs, charts and register below now include it.")
            st.rerun()

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
