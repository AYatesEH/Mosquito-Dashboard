"""Dosage Calculator - a guided Larvae Dip Calculator (by water body/location type) plus a manual
verification calculator. Rate/label data for the two selectable products (ProLink Pellets, ProLink XR
Briquets) is real, sourced from their APVMA-approved labels - the arithmetic itself (area x rate, no
safety margins or label conditions applied) and the guided mode's location-type suggestions are still
what an officer must independently verify on site, not a substitute for the product data or the label."""

import math
from datetime import time as dt_time

import pandas as pd
import streamlit as st

from core import ui
from core.config import (
    LABEL_RATE_OPTIONS, LOCATION_TYPE_GUIDANCE, QUANTITY_USED_UNITS,
    VINCENT_CENTER_LAT, VINCENT_CENTER_LON,
)


def _compute_quantity(product_id, rate, area_m2):
    """Same convention as the Treatments 'Record a treatment' form (core.config.QUANTITY_USED_UNITS):
    whole grams for ProLink Pellets (kg/ha rate - area converted to hectares only for this
    multiplication) and whole briquets for ProLink XR Briquets (m2-per-briquet rate, already m2)."""
    qty_unit = QUANTITY_USED_UNITS.get(product_id)
    if not rate or not area_m2:
        return None, qty_unit
    if qty_unit == "g":
        return round(rate * (area_m2 / 10000) * 1000), qty_unit
    if qty_unit == "briquet(s)":
        return math.ceil(area_m2 / rate), qty_unit
    return None, qty_unit


def render():
    ui.apply_page_style()
    data = ui.get_data()
    ui.render_global_filters(data)

    st.title("Dosage Calculator")

    products = data["products"]
    active_products = products[products["Status"] == "Active"]

    tab_guided, tab_manual = st.tabs(["Larvae dip calculator (guided)", "Manual verification calculator"])

    with tab_guided:
        st.caption(
            "Enter the water body area, date/time and a location type to get a suggested product, site "
            "condition and dosage to start from. The location-type suggestion is this app's own starting "
            "point - built from each product's own APVMA label wording where possible (see the note shown "
            "below the location type) - it is NOT a label determination. The label's actual, operative "
            "criteria are the water depth, organic content and larval count observed on site, never the "
            "location's name, so always confirm those on site and override the product/condition below if "
            "they don't match what you find."
        )

        gc1, gc2 = st.columns(2)
        with gc1:
            dip_area_m2 = st.number_input(
                "Water body / treatment area (m²)", min_value=0.0, value=100.0, step=10.0, key="dip_area",
            )
            dip_location_type = st.selectbox(
                "Location type", list(LOCATION_TYPE_GUIDANCE.keys()), key="dip_location_type",
            )
        with gc2:
            dip_date = st.date_input("Date", value=pd.Timestamp.now().date(), key="dip_date")
            dip_time = st.time_input("Time", value=dt_time(9, 0), key="dip_time")

        guidance = LOCATION_TYPE_GUIDANCE[dip_location_type]
        st.caption(f"💡 {guidance['reasoning']}")

        active_product_ids = active_products["Product_ID"].tolist()
        product_names = active_products.set_index("Product_ID")["Product_Name"].to_dict()
        default_product_id = guidance["product_id"] if guidance["product_id"] in active_product_ids else active_product_ids[0]

        gc3, gc4 = st.columns(2)
        with gc3:
            dip_product_id = st.selectbox(
                "Suggested product (override if needed)",
                active_product_ids, index=active_product_ids.index(default_product_id),
                format_func=lambda pid: product_names[pid], key="dip_product",
            )
        dip_product = active_products[active_products["Product_ID"] == dip_product_id].iloc[0]
        rate_options = LABEL_RATE_OPTIONS.get(dip_product_id, [])
        default_condition_index = (
            guidance["condition_index"]
            if guidance["product_id"] == dip_product_id and guidance["condition_index"] is not None
            else 0
        )
        dip_rate = None
        with gc4:
            if rate_options:
                rate_labels = [f"{desc} → {val:g} {dip_product['Rate_Unit']}" for desc, val in rate_options]
                dip_condition_idx = st.selectbox(
                    "Site condition (override if it doesn't match what you observe on site)",
                    list(range(len(rate_labels))), index=min(default_condition_index, len(rate_labels) - 1),
                    format_func=lambda i: rate_labels[i], key="dip_condition",
                )
                dip_rate = rate_options[dip_condition_idx][1]
            else:
                st.caption("No discrete label options on file for this product.")

        st.divider()
        if dip_area_m2 > 0 and dip_rate:
            qty, qty_unit = _compute_quantity(dip_product_id, dip_rate, dip_area_m2)
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Suggested product", dip_product["Product_Name"])
            rc2.metric("Labelled rate", f"{dip_rate:g} {dip_product['Rate_Unit']}")
            rc3.metric(
                f"Estimated quantity ({qty_unit})" if qty_unit else "Estimated quantity",
                f"{qty:,}" if qty is not None else "-",
            )
            st.caption(
                f"Direct application of the labelled rate to the entered area, in whole {qty_unit or 'units'} - "
                "no adjustments or safety margins applied. Confirm against the current APVMA-approved label "
                "before any real application - see the Manual verification calculator tab to check the working."
            )
        else:
            st.info("Enter an area greater than zero to see a suggested quantity.")

        st.markdown("**Conditions at the date/time entered**")
        wc1, wc2 = st.columns(2)
        with wc1:
            weather = ui.get_weather_for_date(VINCENT_CENTER_LAT, VINCENT_CENTER_LON, dip_date)
            if "error" in weather:
                st.caption(f"Weather lookup unavailable right now: {weather['error']}")
            else:
                st.metric("Rainfall", f"{weather['rainfall_mm']:g} mm" if weather["rainfall_mm"] is not None else "-")
                st.caption(f"Source: {weather['source']} (Open-Meteo, live) - region-wide (Vincent centroid), not site-specific.")
        with wc2:
            if "Swan River" in dip_location_type:
                tide = ui.get_tide_indicator(VINCENT_CENTER_LAT, VINCENT_CENTER_LON)
                if "error" not in tide:
                    st.caption(
                        f"⚠️ Tide (rough approximation only - see Environmental/Site Detail pages for the full "
                        f"caveat): {tide['trend'] or '-'}, next {tide['next_turn_type'] or 'turn'} "
                        f"~{tide['next_turn_time'].split('T')[-1] if tide['next_turn_time'] else '-'}."
                    )
            else:
                st.caption("A tide indicator is shown here only for Swan River foreshore/bank locations.")

    with tab_manual:
        st.warning(
            "ProLink Pellets and ProLink XR Briquets below use real, currently APVMA-registered application data, "
            "transcribed directly from the actual product labels (see Label_Reference and the APVMA approval number "
            "for each product). Rates genuinely vary by site/water-body condition (depth, vegetation, pollution, "
            "larval counts) - this calculator shows a range, not a single fixed number - and an officer must always "
            "confirm the exact current APVMA-approved label before any real application, since labels are "
            "periodically reissued."
        )

        st.subheader("1. Select a product and method")
        c1, c2 = st.columns(2)
        with c1:
            product_name = st.selectbox("Mosquito control product", active_products["Product_Name"].tolist(), key="manual_product")
            product = active_products[active_products["Product_Name"] == product_name].iloc[0]
        with c2:
            st.text_input("Application method", value=product["Application_Method"], disabled=True)

        is_fictional = "SAMPLE DATA ONLY" in str(product["Label_Reference"])
        st.caption(
            f"Active ingredient: {product['Active_Ingredient']} | "
            f"Labelled rate range: {product['Rate_Min']:g}-{product['Rate_Max']:g} {product['Rate_Unit']} | "
            f"Duration of control: {product['Duration_Of_Control']}"
        )
        if product["Rate_Basis"]:
            st.caption(f"Where in the range to use: {product['Rate_Basis']}")
        if is_fictional:
            st.error("This product is a FICTIONAL placeholder - not for operational use.")
        else:
            st.caption(f"Source: {product['Label_Reference']}")

        st.subheader("2. Enter treatment area / volume and rate")
        rate_unit = product["Rate_Unit"]
        is_area_based = "ha" in rate_unit or "m2" in rate_unit
        # ProLink XR Briquets' real label rate is the INVERSE of the other
        # products: "m2 of water surface per 1 briquet" (area covered per unit of
        # product), not "product per area" like kg/ha. A bigger rate number means
        # FEWER briquets needed, so the calculation below must divide, not
        # multiply, for this product - see the note under "3. Calculation".
        is_inverse_rate = "per 1 briquet" in rate_unit or "per briquet" in rate_unit

        c3, c4 = st.columns(2)
        with c3:
            if is_area_based:
                # Area is always entered in m2 (see README) - consistent with how
                # this app records Area_Treated_M2 everywhere else. ProLink
                # Pellets' real label rate is still kg/ha (the real label unit -
                # not something this app can change), so it's converted to
                # hectares internally, only for the multiplication below.
                area_value = st.number_input("Treatment area / water surface (m²)", min_value=0.0, value=100.0, step=10.0, key="manual_area")
                area_unit_label = "m2"
            else:
                area_value = st.number_input("Treatment volume/quantity (as applicable)", min_value=0.0, value=1.0, step=0.1, key="manual_volume")
                area_unit_label = "unit"
        with c4:
            rate_override = st.number_input(
                f"Application rate to use ({rate_unit}) - editable, defaults to the midpoint of the labelled range",
                min_value=0.0, value=float((product["Rate_Min"] + product["Rate_Max"]) / 2), step=0.1, key="manual_rate",
            )
            if not (product["Rate_Min"] <= rate_override <= product["Rate_Max"]):
                st.caption(f"⚠️ Outside the labelled range ({product['Rate_Min']:g}-{product['Rate_Max']:g}).")

        st.subheader("3. Calculation")
        if area_value <= 0 or rate_override <= 0:
            st.warning("Enter a treatment area/volume and an application rate greater than zero to calculate.")
        elif is_inverse_rate:
            # Rate is "area covered per 1 briquet" - divide area by rate to get
            # the number of briquets, then round UP (you can't place half a
            # briquet); the exact figure is shown alongside for transparency.
            exact_result = area_value / rate_override
            result = math.ceil(exact_result)
            st.markdown(
                f"**Calculation performed (shown for independent verification):**\n\n"
                f"`{area_value:g} {area_unit_label} ÷ {rate_override:g} {rate_unit} = {exact_result:,.2f} briquets "
                f"→ rounded up to {result:,} briquet(s)`\n\n"
                f"(This product's labelled rate is area-covered-per-briquet, not product-per-area, so the area is "
                f"divided by the rate rather than multiplied - see Rate_Basis above for the label's shallow/deep and "
                f"species-based rate selection.)"
            )
            label = "Estimated product required" if not is_fictional else "Estimated product required (SAMPLE calculation only)"
            st.success(f"{label}: **{result:,} briquet(s)**")
            st.caption(
                "This figure is a direct division of area by rate, rounded up to a whole briquet - no adjustments, "
                "safety margins or label conditions have been applied. An officer must independently verify against "
                "the actual, current, verified product label before any real application."
            )
        elif "ha" in rate_unit:
            # Rate is per HECTARE (the real label unit, kept as-is) but area is
            # always entered in m2 in this app - convert before multiplying, then
            # show both the native kg figure and the grams figure officers
            # actually record (see core.config.QUANTITY_USED_UNITS / Treatments
            # "Record a treatment").
            area_ha = area_value / 10000
            result_kg = area_ha * rate_override
            result_g = round(result_kg * 1000)
            st.markdown(
                f"**Calculation performed (shown for independent verification):**\n\n"
                f"`{area_value:g} m2 ÷ 10,000 = {area_ha:.4g} ha`\n\n"
                f"`{area_ha:.4g} ha x {rate_override:g} {rate_unit} = {result_kg:,.3f} kg ({result_g:,} g)`"
            )
            label = "Estimated product required" if not is_fictional else "Estimated product required (SAMPLE calculation only)"
            st.success(f"{label}: **{result_kg:,.3f} kg ({result_g:,} g)**")
            st.caption(
                "This figure is a direct multiplication of area by rate - no adjustments, safety margins or "
                "label conditions have been applied. An officer must independently verify against the actual, "
                "current, verified product label before any real application."
            )
        else:
            result = area_value * rate_override
            st.markdown(
                f"**Calculation performed (shown for independent verification):**\n\n"
                f"`{area_value:g} {area_unit_label} x {rate_override:g} {rate_unit} = {result:,.2f} "
                f"{rate_unit.split('/')[0]}`"
            )
            label = "Estimated product required" if not is_fictional else "Estimated product required (SAMPLE calculation only)"
            st.success(f"{label}: **{result:,.2f} {rate_unit.split('/')[0]}**")
            st.caption(
                "This figure is a direct multiplication of area/volume by rate - no adjustments, safety margins or "
                "label conditions have been applied. An officer must independently verify against the actual, "
                "current, verified product label before any real application."
            )

        st.divider()
        st.subheader("Unit reference (this product)")
        st.dataframe(
            active_products[["Product_ID", "Product_Name", "Active_Ingredient", "Application_Method",
                             "Rate_Min", "Rate_Max", "Rate_Unit", "Duration_Of_Control", "Label_Reference"]],
            use_container_width=True, hide_index=True,
        )


render()
