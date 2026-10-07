"""Data-entry forms, all in one place (shown on the Enter Data page).

Each form takes the dict from ui.get_data() and writes through the ui.add_*
wrappers. After a successful save the message is kept in session state and
re-shown after the rerun, so the officer sees confirmation (st.success followed
by st.rerun would be wiped immediately). Budget forms live on the Budget page.
"""

import math
from datetime import datetime, time as dt_time

import pandas as pd
import streamlit as st

from core import ui
from core import calculations as calc
from core.config import (
    TRAP_TYPES, HIGH_LARVAE_COUNT_PER_DIP, OBSERVATION_CATEGORIES, QUANTITY_USED_UNITS,
    REDOSE_LEAD_DAYS, REDOSE_NOT_SCHEDULED, REDOSE_STATUS_COLOURS, LABEL_RATE_OPTIONS,
    TREATMENT_STATUSES,
)

TRAP_OUTCOMES = ["Successful", "Partial", "Failed - Equipment/Battery", "Missing"]
DEFAULT_VALIDITY = {"Successful": "Valid", "Partial": "Valid", "Failed - Equipment/Battery": "Invalid", "Missing": "N/A"}
COMPLAINT_CATEGORIES = ["Biting nuisance", "Swarming/adult numbers", "Suspected breeding site",
                        "Standing water on property", "General enquiry"]
INVESTIGATION_STATUSES = ["Received", "Under Investigation", "Site Inspected", "Closed"]
OUTCOMES = ["No breeding found", "Breeding site identified and treated", "Referred to property owner"]

FLASH_KEY = "_flash_saved"


def _saved(message: str):
    st.session_state[FLASH_KEY] = message
    st.rerun()


def show_flash():
    msg = st.session_state.pop(FLASH_KEY, None)
    if msg:
        st.success(msg)


def trap_form(data: dict):
    """Record a trap result (one set-and-retrieve event + per-species counts)."""
    st.caption(
        "Trap location and trap type are separate fields - traps are portable CO2 traps moved to a new site "
        "each week (see the Weekly To Do List), not permanently installed, so there's no fixed trap code to "
        "pick. Saves to this prototype's CSV data store - fine for a single-user demo/pilot, see README "
        "Section 6 for moving to a real backend before relying on this for a live season. Logged as one "
        "entry, after the trap has been retrieved and read - matching how this is normally done at a desk, "
        "not standing at the trap."
    )
    active_traps = data["trap_sites"][data["trap_sites"]["Trap_Status"] == "Active"]
    active_sites = data["sites"][data["sites"]["Status"] == "Active"]
    if active_traps.empty or active_sites.empty:
        st.warning("No active traps/sites to log against.")
    else:
        sc1, sc2 = st.columns(2)
        with sc1:
            new_site_id = ui.site_picker(active_sites, key="new_event_site", label="Trap location")
            new_trap_type = st.selectbox("Trap type", TRAP_TYPES, key="new_event_trap_type")
            new_deploy_date = st.date_input("Deployment date", value=pd.Timestamp.now().date() - pd.Timedelta(days=1), key="new_event_deploy_date")
            new_retrieve_date = st.date_input("Retrieval date", value=pd.Timestamp.now().date(), key="new_event_retrieve_date")
        with sc2:
            new_outcome = st.selectbox("Trap outcome", TRAP_OUTCOMES, key="new_event_outcome")
            new_validity = st.selectbox(
                "Sample validity", ["Valid", "Invalid", "N/A"],
                index=["Valid", "Invalid", "N/A"].index(DEFAULT_VALIDITY[new_outcome]), key="new_event_validity",
            )
            new_officer = st.selectbox("Officer", data["users"]["Name"].tolist(), key="new_event_officer")

        counts_df = None
        if new_outcome in ("Successful", "Partial") and new_validity == "Valid":
            st.caption("Enter the number collected per species (leave at 0 for species not caught):")
            species_for_count = data["species"][data["species"]["Species_Code"] != "OTHER"][["Species_Code", "Scientific_Name"]].copy()
            species_for_count["Number_Collected"] = 0
            counts_df = st.data_editor(
                species_for_count, use_container_width=True, hide_index=True, key="new_event_counts",
                column_config={
                    "Species_Code": st.column_config.TextColumn(disabled=True),
                    "Scientific_Name": st.column_config.TextColumn(disabled=True),
                    "Number_Collected": st.column_config.NumberColumn(min_value=0, step=1),
                },
            )

        new_event_notes = st.text_area("Notes", key="new_event_notes")

        if st.button("Save trap result", type="primary"):
            if new_retrieve_date < new_deploy_date:
                st.error("Retrieval date can't be before the deployment date.")
            elif not new_site_id:
                st.error("Select a trap location.")
            else:
                # Trap_ID is resolved automatically from the equipment register (trap_sites.csv) -
                # it's an internal reference only, never shown or picked by the officer (see
                # calc.resolve_trap_id).
                new_trap_id = calc.resolve_trap_id(data["trap_sites"], new_trap_type)
                event_id = ui.add_surveillance_event({
                    "Trap_ID": new_trap_id,
                    "Site_ID": new_site_id,
                    "Season": ui.infer_season(new_deploy_date),
                    "Deployment_DateTime": new_deploy_date.strftime("%Y-%m-%d %H:%M"),
                    "Retrieval_DateTime": new_retrieve_date.strftime("%Y-%m-%d %H:%M"),
                    "Trap_Type": new_trap_type,
                    "Trap_Status": new_outcome,
                    "Sample_Validity": new_validity,
                    "Officer": new_officer,
                    "Notes": new_event_notes,
                    "Created_By": new_officer,
                    "Created_Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                })
                n_results = 0
                if counts_df is not None:
                    for _, r in counts_df.iterrows():
                        if int(r["Number_Collected"]) > 0:
                            ui.add_surveillance_result({
                                "Event_ID": event_id,
                                "Species_Code": r["Species_Code"],
                                "Number_Collected": int(r["Number_Collected"]),
                                "Notes": "",
                            })
                            n_results += 1
                _saved(f"Saved {event_id} ({n_results} species result{'s' if n_results != 1 else ''}). The Surveillance charts and Event Log now include it.")


def dip_form(data: dict):
    """Log a larvae dip with a count."""
    st.caption(
        f"A larvae dip is a manual inspection - no trap or equipment involved, unlike a surveillance event - "
        f"where a sampling cup is dipped into standing water at a site and the larvae in it are counted. A "
        f"count above **{HIGH_LARVAE_COUNT_PER_DIP} larvae/dip** (the real APVMA-label 'high larval count' "
        f"threshold also used on the Dosage Calculator page) feeds into the Hotspot Identification page as "
        f"its own signal, alongside trap catch data and complaints. Saves to this prototype's CSV data "
        f"store - see README Section 6 for the single-user/non-durable-on-Streamlit-Cloud caveat that "
        f"applies to every data-entry form in this app."
    )
    active_sites_dip = data["sites"][data["sites"]["Status"] == "Active"]
    if active_sites_dip.empty:
        st.warning("No active sites to log against.")
    else:
        dp1, dp2 = st.columns(2)
        with dp1:
            new_dip_site = ui.site_picker(active_sites_dip, key="new_dip_site", label="Site")
            new_dip_date = st.date_input("Dip date", value=pd.Timestamp.now().date(), key="new_dip_date")
        with dp2:
            new_dip_count = st.number_input("Larvae count", min_value=0, step=1, key="new_dip_count")
            new_dip_officer = st.selectbox("Officer", data["users"]["Name"].tolist(), key="new_dip_officer")
        new_dip_notes = st.text_area("Notes", key="new_dip_notes")

        if st.button("Save dip data", type="primary", key="new_dip_save"):
            if not new_dip_site:
                st.error("Select a site.")
            else:
                dip_id = ui.add_larvae_dip({
                    "Site_ID": new_dip_site,
                    "Season": ui.infer_season(new_dip_date),
                    "DateTime": pd.Timestamp(new_dip_date).strftime("%Y-%m-%d %H:%M"),
                    "Larvae_Count": int(new_dip_count),
                    "Officer": new_dip_officer,
                    "Notes": new_dip_notes,
                    "Created_By": new_dip_officer,
                    "Created_Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                })
                high_note = " - a high count, will feed into the hotspot calculation" if new_dip_count > HIGH_LARVAE_COUNT_PER_DIP else ""
                _saved(f"Saved {dip_id} ({int(new_dip_count)} larvae{high_note}). Any matching dipping/inspection task on the To Do List clears on the next refresh.")


def treatment_form(data: dict):
    """Record a treatment (live re-dose and weather preview)."""
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

    # Area treated is always entered and stored in m2 (see README) -
    # easier to estimate for the small, discrete water bodies this
    # program mostly treats (a puddle, a drain, a garden pond) than
    # fractions of a hectare. ProLink Pellets' real label rate is still
    # "kg/ha" (transcribed from the actual label - not something this
    # app can change), so the quantity calculation below converts the
    # entered m2 figure to hectares internally, only for that one
    # multiplication.
    fc3, fc4, fc5 = st.columns(3)
    with fc3:
        new_status = st.selectbox("Treatment status", TREATMENT_STATUSES, index=TREATMENT_STATUSES.index("Completed"), key="new_treatment_status")
    with fc4:
        new_area_m2 = (
            st.number_input("Area/water surface treated (m²)", min_value=0.0, value=100.0, step=10.0, key="new_treatment_area")
            if new_type != "Source Reduction / Habitat Modification" else None
        )
    with fc5:
        # Quantity used is recorded in whatever unit an officer actually
        # counts/measures in the field for that product - NOT the same
        # unit as the rate above (see core.config.QUANTITY_USED_UNITS) -
        # and defaults to the amount the locked rate and entered area
        # imply, rounded to a whole unit, while staying editable in case
        # actual field usage differed.
        qty_unit = QUANTITY_USED_UNITS.get(new_product["Product_ID"])
        suggested_qty = None
        if new_rate and new_area_m2:
            if qty_unit == "g":  # kg/ha rate -> convert area to ha -> total kg -> grams
                suggested_qty = round(new_rate * (new_area_m2 / 10000) * 1000)
            elif qty_unit == "briquet(s)":  # m2-per-briquet rate (inverse, already m2) -> briquet count
                suggested_qty = math.ceil(new_area_m2 / new_rate)
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
                "Area_Treated_M2": new_area_m2 if new_area_m2 else "",
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
            _saved(f"Saved {new_id}. The Treatments register, planning board and re-dose schedule now include it.")


def complaint_form(data: dict):
    """Log a complaint."""
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
        _saved(f"Saved {new_id}. The Complaints KPIs, charts and register now include it.")


def observation_form(data: dict):
    """Record a site observation."""
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
        _saved(f"Saved {new_id}. The observation log and any related To Do List tasks now reflect it.")
