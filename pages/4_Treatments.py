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
        ["Treatment register", "Planning board", "Re-dose schedule", "Summary"]
    )

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
        st.subheader("Record a treatment")
        st.caption(
            "Saves to this prototype's CSV data store - fine for a single-user demo/pilot, but not durable on "
            "Streamlit Community Cloud (its filesystem resets on redeploy/restart) and not safe for several "
            "people saving at once. See README Section 6 for moving to a real backend. Enter the date/time, "
            "product and dosage below and the estimated re-dose due date and live weather at the site are "
            "computed and shown automatically. Plain widgets (not a Streamlit form) are used deliberately here "
            "so the preview below updates as soon as you change an entry, rather than only after a submit."
        )
        fc1, fc2 = st.columns(2)
        with fc1:
            new_site_id = ui.site_picker(data["sites"], key="new_treatment_site")
            new_type = st.selectbox(
                "Treatment type",
                ["Larvicide Application", "Adulticide Application", "Source Reduction / Habitat Modification"],
                key="new_treatment_type",
            )
            new_product_name = st.selectbox("Product used", data["products"]["Product_Name"].tolist(), key="new_treatment_product")
            new_product = data["products"][data["products"]["Product_Name"] == new_product_name].iloc[0]
        with fc2:
            new_date = st.date_input("Treatment date", value=pd.Timestamp.now().date(), key="new_treatment_date")
            new_time = st.time_input("Treatment time", value=dt_time(9, 0), key="new_treatment_time")
            new_officer = st.selectbox("Assigned officer", data["users"]["Name"].tolist(), key="new_treatment_officer")

        rate_unit_str = str(new_product.get("Rate_Unit", ""))
        rate_options = LABEL_RATE_OPTIONS.get(new_product["Product_ID"])
        has_rate_range = pd.notna(new_product.get("Rate_Min")) and pd.notna(new_product.get("Rate_Max"))
        new_rate = None
        if new_type == "Larvicide Application" and rate_options:
            # Both real products' labels define the rate as a straight choice
            # between exactly two site conditions, never a number in between -
            # so this is a locked selectbox, not an editable number, and an
            # officer can't enter a rate that isn't actually on the label.
            rate_labels = [f"{desc} → {val:g} {rate_unit_str}" for desc, val in rate_options]
            rate_lookup = dict(zip(rate_labels, [v for _, v in rate_options]))
            new_rate_label = st.selectbox(
                "Site condition (sets the exact labelled dosage/application rate)",
                rate_labels, key="new_treatment_rate_choice",
            )
            new_rate = rate_lookup[new_rate_label]
            st.caption(f"Rate is locked to the product's APVMA label: **{new_rate:g} {rate_unit_str}** - not editable.")
        elif new_type == "Larvicide Application" and has_rate_range:
            # Fallback for a product with no discrete label options on file
            # (e.g. the fictional withdrawn product, kept only for historical
            # records) - no real label to lock to, so this stays a free entry.
            default_rate = float((new_product["Rate_Min"] + new_product["Rate_Max"]) / 2)
            new_rate = st.number_input(
                f"Dosage/application rate used ({rate_unit_str})",
                min_value=0.0, value=default_rate, step=0.1, key="new_treatment_rate",
            )
            st.caption("No discrete label options on file for this product - enter the rate manually and verify against the label.")
            if not (new_product["Rate_Min"] <= new_rate <= new_product["Rate_Max"]):
                st.caption(f"⚠️ Outside the labelled range ({new_product['Rate_Min']:g}-{new_product['Rate_Max']:g}).")

        # The area input's unit follows the selected product's own label
        # rate: ProLink XR Briquets is labelled per m2 of water surface, not
        # per hectare, so entering area in ha there would force awkward
        # decimals (e.g. 0.002 ha for a 20 m2 puddle). Area_Treated_Ha in the
        # data store is always hectares (other pages sum it directly for
        # cross-product area totals), so an m2 entry is converted before
        # saving; the raw, as-entered value is kept separately for the
        # quantity-used calculation below, since that must divide the actual
        # m2 figure, not a rounded ha conversion.
        area_is_m2 = new_type == "Larvicide Application" and "m2" in rate_unit_str and "ha" not in rate_unit_str
        fc3, fc4, fc5 = st.columns(3)
        with fc3:
            new_status = st.selectbox("Treatment status", TREATMENT_STATUSES, index=TREATMENT_STATUSES.index("Completed"), key="new_treatment_status")
        with fc4:
            new_area_ha = None
            new_area_raw = None
            if new_type != "Source Reduction / Habitat Modification":
                if area_is_m2:
                    new_area_raw = st.number_input(
                        "Area/water surface treated (m²)", min_value=0.0, value=100.0, step=10.0, key="new_treatment_area_m2",
                    )
                    new_area_ha = round(new_area_raw / 10000, 4)
                    st.caption(f"= {new_area_ha:g} ha (converted for area-treated totals elsewhere in the app).")
                else:
                    new_area_ha = st.number_input("Area treated (ha)", min_value=0.0, value=1.0, step=0.1, key="new_treatment_area")
                    new_area_raw = new_area_ha
        with fc5:
            # Quantity used is recorded in whatever unit an officer actually
            # counts/measures in the field for that product - NOT the same
            # unit as the rate above (see core.config.QUANTITY_USED_UNITS) -
            # and defaults to the amount the locked rate and entered area
            # imply, rounded to a whole unit, while staying editable in case
            # actual field usage differed.
            qty_unit = QUANTITY_USED_UNITS.get(new_product["Product_ID"])
            suggested_qty = None
            if new_rate and new_area_raw:
                if qty_unit == "g":  # kg/ha rate -> total kg -> grams
                    suggested_qty = round(new_rate * new_area_ha * 1000)
                elif qty_unit == "briquet(s)":  # m2-per-briquet rate (inverse) -> briquet count
                    suggested_qty = math.ceil(new_area_raw / new_rate)
            if qty_unit:
                new_quantity = st.number_input(
                    f"Quantity used ({qty_unit})",
                    min_value=0, value=int(suggested_qty) if suggested_qty else 0, step=1, key="new_treatment_quantity",
                )
                st.caption(f"Defaults to the amount the rate and area above imply, in whole {qty_unit} - editable.")
            else:
                new_quantity = st.number_input(
                    "Quantity used (leave 0 if not applicable/not yet known)",
                    min_value=0.0, value=0.0, step=0.1, key="new_treatment_quantity",
                )
        new_reason = st.selectbox(
            "Reason", ["Surveillance threshold exceeded", "Complaint-triggered inspection",
                       "Routine scheduled treatment", "Follow-up after prior treatment"],
            key="new_treatment_reason",
        )
        new_cancelled_reason = ""
        if new_status == "Cancelled":
            new_cancelled_reason = st.selectbox(
                "Cancelled reason", ["Site access restricted", "Weather unsuitable", "Insufficient surveillance trigger",
                                      "Resourcing/staff availability", "Product unavailable"],
                key="new_treatment_cancelled_reason",
            )
        new_notes = st.text_area("Notes", key="new_treatment_notes")

        st.markdown("**Live preview** _(computed from the entries above - not yet saved)_")
        pcol1, pcol2 = st.columns(2)

        with pcol1:
            st.markdown("Estimated re-dose due date")
            if new_type == "Larvicide Application" and new_rate:
                treatment_ts = pd.Timestamp(datetime.combine(new_date, new_time))
                window = calc.estimate_control_window(new_product, new_rate, treatment_ts, lead_days=REDOSE_LEAD_DAYS)
                if window.status == REDOSE_NOT_SCHEDULED:
                    st.info(window.note)
                else:
                    st.markdown(
                        ui.status_badge_html(window.status, REDOSE_STATUS_COLOURS) +
                        f"&nbsp;&nbsp;control window ~{window.duration_days:g} days &middot; "
                        f"effective until **{window.effective_until.date()}** &middot; "
                        f"re-dose due **{window.redose_due.date()}**",
                        unsafe_allow_html=True,
                    )
                    st.caption(window.note)
            else:
                st.caption("Select a Larvicide Application product with a dosage entered to preview a re-dose due date.")

        with pcol2:
            st.markdown("Weather at site/date")
            if new_site_id is None:
                st.caption("Select a site to auto-populate weather.")
            else:
                site_row = data["sites"][data["sites"]["Site_ID"] == new_site_id].iloc[0]
                if pd.isna(site_row["Latitude"]) or pd.isna(site_row["Longitude"]):
                    st.caption("This site has no recorded coordinates, so weather can't be auto-populated (see Data Quality).")
                else:
                    weather = ui.get_weather_for_date(site_row["Latitude"], site_row["Longitude"], new_date)
                    if "error" in weather:
                        st.caption(f"Weather lookup unavailable right now: {weather['error']}")
                    else:
                        wc1, wc2 = st.columns(2)
                        wc1.metric("Rainfall", f"{weather['rainfall_mm']:g} mm" if weather["rainfall_mm"] is not None else "-")
                        wc2.metric(
                            "Temp (max/min)",
                            f"{weather['temp_max_c']:g}° / {weather['temp_min_c']:g}°C"
                            if weather["temp_max_c"] is not None else "-",
                        )
                        st.caption(f"Source: {weather['source']} (Open-Meteo, live) - no API key required.")

                    if site_row["Site_Type"] == "Swan River Foreshore":
                        tide = ui.get_tide_indicator(site_row["Latitude"], site_row["Longitude"])
                        if "error" not in tide:
                            st.caption(
                                f"⚠️ Tide (rough approximation only - see Site Detail/Environmental page for the "
                                f"full caveat): {tide['trend'] or '-'}, next {tide['next_turn_type'] or 'turn'} "
                                f"~{tide['next_turn_time'].split('T')[-1] if tide['next_turn_time'] else '-'}."
                            )

        if st.button("Save treatment", type="primary"):
            if new_site_id is None:
                st.error("Select a site before saving.")
            else:
                is_completed = new_status == "Completed"
                treatment_date_val = new_date.strftime("%Y-%m-%d") if is_completed else ""
                new_id = ui.add_treatment({
                    "Site_ID": new_site_id,
                    "Season": ui.infer_season(new_date),
                    "Planned_Date": new_date.strftime("%Y-%m-%d"),
                    "Treatment_Date": treatment_date_val,
                    "Treatment_Status": new_status,
                    "Treatment_Type": new_type,
                    "Product_ID": new_product["Product_ID"] if new_type != "Source Reduction / Habitat Modification" else "",
                    "Application_Method": new_product["Application_Method"] if new_type != "Source Reduction / Habitat Modification" else "",
                    "Application_Rate": new_rate if new_rate else "",
                    "Rate_Unit": new_product["Rate_Unit"] if new_rate else "",
                    "Area_Treated_Ha": new_area_ha if new_area_ha else "",
                    "Quantity_Used": new_quantity if new_quantity else "",
                    "Operator": new_officer,
                    "Reason": new_reason,
                    "Cancelled_Reason": new_cancelled_reason,
                    "Notes": new_notes,
                    "Created_By": new_officer,
                    "Created_Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                    "Modified_By": new_officer,
                    "Modified_Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                })
                st.success(f"Saved {new_id}. The register, planning board and re-dose schedule below now include it.")
                st.rerun()

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
            display_fmt = display.copy()
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
                    st.caption(
                        "Quantities are in each product's own recording unit (grams for ProLink Pellets, whole "
                        "briquets for ProLink XR Briquets - see core.config.QUANTITY_USED_UNITS/Products page), "
                        "NOT the product's application rate unit. Not directly comparable across products."
                    )
        else:
            st.info("No treatments recorded for this selection.")


render()
