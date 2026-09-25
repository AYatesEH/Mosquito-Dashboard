"""Dosage Calculator - transparent product-quantity calculation. SAMPLE DATA ONLY."""

import streamlit as st

from core import ui


def render():
    ui.apply_page_style()
    data = ui.get_data()
    ui.render_global_filters(data)

    st.title("Dosage Calculator")
    st.warning(
        "ProLink Pellets and ProLink XR Briquets below use real, currently APVMA-registered application data "
        "(sourced from product labels/SDS - see Label_Reference for each product). The remaining products are "
        "still fictional placeholders and are clearly marked. Rates genuinely vary by site/water-body condition "
        "(depth, vegetation, pollution) - this calculator shows a range, not a single fixed number, and an "
        "officer must always confirm the exact current APVMA-approved label before any real application."
    )

    products = data["products"]
    active_products = products[products["Status"] == "Active"]

    st.subheader("1. Select a product and method")
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.selectbox("Mosquito control product", active_products["Product_Name"].tolist())
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

    c3, c4 = st.columns(2)
    with c3:
        if is_area_based:
            if "ha" in rate_unit:
                area_value = st.number_input("Treatment area (hectares)", min_value=0.0, value=1.0, step=0.1)
                area_unit_label = "ha"
            else:
                area_value = st.number_input("Treatment area (m²)", min_value=0.0, value=100.0, step=10.0)
                area_unit_label = "m2"
        else:
            area_value = st.number_input("Treatment volume/quantity (as applicable)", min_value=0.0, value=1.0, step=0.1)
            area_unit_label = "unit"
    with c4:
        rate_override = st.number_input(
            f"Application rate to use ({rate_unit}) - editable, defaults to the midpoint of the labelled range",
            min_value=0.0, value=float((product["Rate_Min"] + product["Rate_Max"]) / 2), step=0.1,
        )
        if not (product["Rate_Min"] <= rate_override <= product["Rate_Max"]):
            st.caption(f"⚠️ Outside the labelled range ({product['Rate_Min']:g}-{product['Rate_Max']:g}).")

    st.subheader("3. Calculation")
    if area_value <= 0 or rate_override <= 0:
        st.warning("Enter a treatment area/volume and an application rate greater than zero to calculate.")
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
