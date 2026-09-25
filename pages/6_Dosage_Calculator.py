"""Dosage Calculator - transparent product-quantity calculation. SAMPLE DATA ONLY."""

import streamlit as st

from core import ui


def render():
    ui.apply_page_style()
    data = ui.get_data()
    ui.render_global_filters(data)

    st.title("Dosage Calculator")
    st.error(
        "SAMPLE DATA ONLY - NOT FOR OPERATIONAL USE. All products and application rates in this prototype are "
        "fictional. This calculator must not be used to plan or conduct a real treatment. When verified label "
        "rates are entered into a controlled product database, this page can be pointed at that data instead."
    )

    products = data["products"]
    active_products = products[products["Status"] == "Active"]

    st.subheader("1. Select a product and method")
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.selectbox("Mosquito control product (fictional)", active_products["Product_Name"].tolist())
        product = active_products[active_products["Product_Name"] == product_name].iloc[0]
    with c2:
        st.text_input("Application method", value=product["Application_Method"], disabled=True)

    st.caption(f"Active ingredient (fictional): {product['Active_Ingredient']} | "
               f"Approved rate (SAMPLE): {product['Approved_Rate']} {product['Rate_Unit']}")

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
            f"Approved application rate ({rate_unit}) - editable, defaults to SAMPLE rate above",
            min_value=0.0, value=float(product["Approved_Rate"]), step=0.1,
        )

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
        st.success(f"Estimated product required: **{result:,.2f} {rate_unit.split('/')[0]}** (SAMPLE calculation only)")
        st.caption(
            "This figure is a direct multiplication of area/volume by rate - no adjustments, safety margins or "
            "label conditions have been applied. An officer must independently verify against the actual, "
            "current, verified product label before any real application."
        )

    st.divider()
    st.subheader("Unit reference (this product)")
    st.dataframe(
        active_products[["Product_ID", "Product_Name", "Active_Ingredient", "Application_Method",
                         "Approved_Rate", "Rate_Unit", "Label_Reference"]],
        use_container_width=True, hide_index=True,
    )


render()
