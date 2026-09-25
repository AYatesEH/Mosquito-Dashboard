"""Products - controlled products reference dataset. SAMPLE/FICTIONAL data only."""

import streamlit as st

from core import ui


def render():
    ui.apply_page_style()
    data = ui.get_data()
    ui.render_global_filters(data)

    st.title("Products")
    st.error(
        "SAMPLE DATA ONLY - NOT FOR OPERATIONAL USE. All products, active ingredients and application rates shown "
        "are fictional placeholders for prototype demonstration. In production, this table would be replaced by a "
        "centrally managed, verified product/label database maintained by an authorised administrator, so "
        "officers are never manually entering application rates themselves."
    )

    products = data["products"]
    treatments = data["treatments"]

    status_filter = st.multiselect("Status", products["Status"].unique().tolist(), default=products["Status"].unique().tolist())
    filtered = products[products["Status"].isin(status_filter)]

    st.dataframe(
        filtered[["Product_ID", "Product_Name", "Active_Ingredient", "Application_Method",
                  "Approved_Rate", "Rate_Unit", "Status", "Label_Reference", "Notes"]],
        use_container_width=True, hide_index=True,
    )

    st.divider()
    st.subheader("Usage history for a product")
    product_name = st.selectbox("Select a product", products["Product_Name"].tolist())
    product_id = products[products["Product_Name"] == product_name]["Product_ID"].iloc[0]
    used = treatments[(treatments["Product_ID"] == product_id) & (treatments["Treatment_Status"] == "Completed")]
    c1, c2, c3 = st.columns(3)
    c1.metric("Times used (completed treatments)", len(used))
    c2.metric("Total area treated (ha)", f"{used['Area_Treated_Ha'].fillna(0).sum():.1f}")
    c3.metric("Total quantity used", f"{used['Quantity_Used'].fillna(0).sum():.1f}")
    if not used.empty:
        st.dataframe(
            used.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")[
                ["Treatment_ID", "Site_Name", "Treatment_Date", "Area_Treated_Ha", "Quantity_Used", "Operator"]
            ].sort_values("Treatment_Date", ascending=False),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No completed treatments recorded using this product.")


render()
