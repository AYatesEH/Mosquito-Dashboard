"""Products - controlled products reference dataset. SAMPLE/FICTIONAL data only."""

import streamlit as st

from core import ui
from core.config import QUANTITY_USED_UNITS


def render():
    ui.apply_page_style()
    data = ui.get_data()
    ui.render_global_filters(data)

    st.title("Products")
    st.warning(
        "ProLink Pellets and ProLink XR Briquets (the program's two S-methoprene larvicides) are the only active "
        "products tracked here - rate, duration and label data is sourced directly from the real, current "
        "APVMA-approved product labels (see Label_Reference and the APVMA approval number for each). The "
        "remaining row (OldStock Larvicide) is a fictional withdrawn placeholder, clearly marked 'SAMPLE DATA "
        "ONLY' in Label_Reference, kept only to exercise Withdrawn-status handling. In production this table "
        "would be replaced by a centrally managed, verified product/label database maintained by an authorised "
        "administrator, so officers are never manually entering application rates themselves - and every rate "
        "here should still be checked against the current APVMA-approved label before operational use."
    )

    products = data["products"]
    treatments = data["treatments"]

    status_filter = st.multiselect("Status", products["Status"].unique().tolist(), default=products["Status"].unique().tolist())
    filtered = products[products["Status"].isin(status_filter)]

    st.dataframe(
        filtered[["Product_ID", "Product_Name", "Active_Ingredient", "Formulation", "Application_Method",
                  "Rate_Min", "Rate_Max", "Rate_Unit", "Rate_Basis", "Duration_Of_Control", "Status",
                  "Label_Reference", "Notes"]],
        use_container_width=True, hide_index=True,
    )

    st.divider()
    st.subheader("Usage history for a product")
    product_name = st.selectbox("Select a product", products["Product_Name"].tolist())
    product_id = products[products["Product_Name"] == product_name]["Product_ID"].iloc[0]
    used = treatments[(treatments["Product_ID"] == product_id) & (treatments["Treatment_Status"] == "Completed")]
    c1, c2, c3 = st.columns(3)
    c1.metric("Times used (completed treatments)", len(used))
    c2.metric("Total area treated (m²)", f"{used['Area_Treated_M2'].fillna(0).sum():,.0f}")
    qty_unit = QUANTITY_USED_UNITS.get(product_id, "")
    qty_total = used["Quantity_Used"].fillna(0).sum()
    qty_fmt = f"{qty_total:.0f}" if qty_unit else f"{qty_total:.1f}"
    c3.metric(f"Total quantity used{f' ({qty_unit})' if qty_unit else ''}", qty_fmt)
    if not used.empty:
        st.dataframe(
            used.merge(data["sites"][["Site_ID", "Site_Name"]], on="Site_ID", how="left")[
                ["Treatment_ID", "Site_Name", "Treatment_Date", "Area_Treated_M2", "Quantity_Used", "Operator"]
            ].sort_values("Treatment_Date", ascending=False),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No completed treatments recorded using this product.")


render()
