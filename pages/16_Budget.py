"""Budget - officer time, dry ice (CO2 traps) and larvicide spend against a season budget.

Costs are ex-GST. Officer time is tracked in HOURS only - the app never stores
or shows wages or pay rates. Prices and budgets are entered on the Settings tab -
nothing here is pre-filled for a live season.
"""

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ui, calculations as calc, edit_forms, forms
from core.config import (
    TIME_ACTIVITIES, COST_CATEGORIES, COST_CATEGORY_DRY_ICE, COST_CATEGORY_LARVICIDE,
    BUDGET_CATEGORIES, BUDGET_KEY_BUDGET_HOURS, BUDGET_KEY_DRY_ICE_PRICE,
    BUDGET_KEY_DRY_ICE_KG_PER_NIGHT, BUDGET_KEY_BUDGET_PREFIX, QUANTITY_USED_UNITS,
)


def _money(v):
    return "-" if v is None or pd.isna(v) else f"${v:,.0f}"


def _overview(data, season, settings, as_of):
    start, end = ui.SEASON_BOUNDS[season]
    te, ce = data["time_entries"], data["cost_entries"]

    if not settings:
        st.info("No budget settings for this season yet. Set the dry ice price and category budgets "
                "(and an optional officer hours budget) on the **Settings** tab.")

    summary = calc.budget_summary(season, settings, ce, start, end, as_of)
    total_budget = summary["Budget"].dropna().sum()
    total_spent = summary["Spent"].sum()
    has_budget = summary["Budget"].notna().any()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total budget (purchases)", _money(total_budget) if has_budget else "Not set")
    c2.metric("Spent to date", _money(total_spent))
    c3.metric("Remaining", _money(total_budget - total_spent) if has_budget else "-")

    shown = summary.copy()
    for col in ("Budget", "Spent", "Remaining", "Projected"):
        shown[col] = shown[col].map(_money)
    shown["Pct_Used"] = shown["Pct_Used"].map(lambda v: "-" if pd.isna(v) else f"{v:.0f}%")
    shown["Projected_Over_Budget"] = shown["Projected_Over_Budget"].map(
        lambda v: "-" if v is None or pd.isna(v) else ("OVER" if v else "ok"))
    st.dataframe(shown.rename(columns={"Pct_Used": "% used", "Projected": "Projected season-end",
                                       "Projected_Over_Budget": "Projection vs budget"}),
                 hide_index=True, use_container_width=True)
    st.caption(f"Costs ex-GST, purchases only. Projection is a straight-line run-rate for dry ice only, shown once "
               f"{calc.MIN_ELAPSED_FOR_PROJECTION:.0%} of the season has elapsed; larvicide is bought in lumps so "
               f"it isn't projected.")

    # --- Officer time (hours only) ---
    st.subheader("Officer time (hours)")
    ot = calc.officer_time_summary(te, season)
    hb = calc.hours_budget_summary(season, settings, te, start, end, as_of)
    if ot["total_hours"] == 0:
        st.caption("No time logged for this season yet.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Hours logged", f"{ot['total_hours']:,.1f}")
        m2.metric("Hours budget", "Not set" if hb["Budget"] is None else f"{hb['Budget']:,.0f}")
        m3.metric("Projected season-end", "-" if hb["Projected"] is None else f"{hb['Projected']:,.0f} h")
        if hb["Projected_Over_Budget"]:
            st.warning("At the current run-rate, officer hours will exceed the season hours budget.")
        a, b = st.columns(2)
        a.plotly_chart(px.bar(ot["by_activity"], x="Hours", y="Activity", orientation="h",
                              title="Hours by activity"), use_container_width=True)
        b.plotly_chart(px.bar(ot["by_week"], x="Week", y="Hours", title="Hours per week"),
                       use_container_width=True)
        st.dataframe(ot["by_officer"], hide_index=True, use_container_width=True)

    # --- Dry ice ---
    st.subheader("Dry ice (CO2 traps)")
    di = calc.dry_ice_analysis(season, data["surv_events"], ce, settings)
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Trap-nights (all deployed)", f"{di['trap_nights']:,.0f}")
    d2.metric("Bought", f"{di['kg_bought']:,.1f} kg")
    d3.metric("Spent", _money(di["spend"]))
    d4.metric("Est. needed", "-" if di["est_kg_needed"] is None else f"{di['est_kg_needed']:,.1f} kg")
    if di["est_kg_needed"] is None:
        st.caption("Set 'dry ice kg per trap-night' in Settings to compare purchases with what trapping implies.")
    elif di["kg_surplus"] is not None:
        st.caption(f"{'Surplus' if di['kg_surplus'] >= 0 else 'Shortfall'} vs estimate: {abs(di['kg_surplus']):,.1f} kg. "
                   "Failed traps still use ice, so all deployed trap-nights count.")
    if di["actual_cost_per_trap_night"] is not None and di["kg_bought"]:
        st.caption(f"Actual: {di['actual_kg_per_trap_night']:.2f} kg and ${di['actual_cost_per_trap_night']:.2f} per trap-night.")
    if di["non_kg_rows"]:
        st.warning(f"{di['non_kg_rows']} dry ice purchase(s) aren't recorded in kg, so aren't in the kg figures.")

    # --- Larvicide ---
    st.subheader("Larvicide")
    lv = calc.larvicide_analysis(season, ce, data["treatments"], data["products"])
    if lv.empty or (lv["Purchased_Qty"].sum() == 0 and lv["Used_Qty"].sum() == 0):
        st.caption("No larvicide purchases or usage recorded for this season.")
    else:
        st.dataframe(lv.drop(columns=["Product_ID"]), hide_index=True, use_container_width=True)
        if lv["Excluded_Rows"].sum():
            st.warning(f"{int(lv['Excluded_Rows'].sum())} larvicide purchase(s) use a unit that doesn't match how "
                       "treatments record use, so they're excluded here. Re-enter them in the product's unit.")
        st.caption("Used value is priced at that product's average purchase cost. On-hand is an estimate "
                   "(purchased minus used on completed treatments).")

    # --- Unit costs ---
    st.subheader("Cost per activity")
    cpa = calc.cost_per_activity(season, te, data["surv_events"], data["complaints"],
                                 data["treatments"], data["larvae_dips"], di, lv)
    if cpa.empty:
        st.caption("Nothing to show yet.")
    else:
        st.dataframe(cpa, hide_index=True, use_container_width=True)


def _log_time(data, season):
    officers = data["users"]["Name"].tolist()
    sites = data["sites"].sort_values("Site_Name")
    site_lookup = {"(none)": ""} | dict(zip(sites["Site_Name"] + " (" + sites["Site_ID"] + ")", sites["Site_ID"]))
    with st.form("log_time", clear_on_submit=True):
        officer = st.selectbox("Officer", officers)
        d = st.date_input("Date", value=dt.date.today())
        activity = st.selectbox("Activity", TIME_ACTIVITIES)
        hours = st.number_input("Hours", min_value=0.0, max_value=24.0, value=1.0, step=0.25)
        site = st.selectbox("Site (optional)", list(site_lookup.keys()))
        notes = st.text_input("Notes (optional)")
        if st.form_submit_button("Save time entry"):
            if hours <= 0:
                st.error("Hours must be greater than 0.")
            else:
                new_id = ui.add_time_entry({
                    "Season": ui.infer_season(d), "Date": d.isoformat(), "Officer": officer,
                    "Activity": activity, "Hours": hours, "Site_ID": site_lookup[site],
                    "Notes": notes, "Created_By": officer, "Created_Date": dt.date.today().isoformat(),
                })
                st.success(f"Saved {new_id}.")


def _log_spend(data):
    officers = data["users"]["Name"].tolist()
    products = {p: f"{n} ({p})" for p, n in zip(data["products"]["Product_ID"], data["products"]["Product_Name"])
                if p in QUANTITY_USED_UNITS}
    with st.form("log_cost", clear_on_submit=True):
        officer = st.selectbox("Entered by", officers)
        d = st.date_input("Invoice / purchase date", value=dt.date.today())
        category = st.selectbox("Category", COST_CATEGORIES)
        product = st.selectbox("Larvicide product (larvicide only)", [""] + list(products),
                               format_func=lambda p: products.get(p, "(n/a)"))
        st.caption("Dry ice: quantity in **kg**. Larvicide: quantity in the product's use unit "
                   + ", ".join(f"{p} = {u}" for p, u in QUANTITY_USED_UNITS.items()) + ".")
        qty = st.number_input("Quantity", min_value=0.0, step=1.0)
        unit = st.text_input("Unit (kg / g / briquet(s) / ...)")
        total = st.number_input("Total cost, ex-GST ($)", min_value=0.0, step=1.0)
        desc = st.text_input("Description")
        supplier = st.text_input("Supplier (optional)")
        invoice = st.text_input("Invoice ref (optional)")
        if st.form_submit_button("Save spend"):
            if total <= 0:
                st.error("Total cost must be greater than 0.")
            elif category == COST_CATEGORY_LARVICIDE and not product:
                st.error("Choose the larvicide product so usage can be compared with purchases.")
            elif category == COST_CATEGORY_LARVICIDE and unit != QUANTITY_USED_UNITS.get(product):
                st.error(f"Unit for that product must be '{QUANTITY_USED_UNITS.get(product)}'.")
            elif category == COST_CATEGORY_DRY_ICE and unit.lower() != "kg":
                st.error("Dry ice must be recorded in kg.")
            else:
                new_id = ui.add_cost_entry({
                    "Season": ui.infer_season(d), "Date": d.isoformat(), "Category": category,
                    "Description": desc, "Product_ID": product if category == COST_CATEGORY_LARVICIDE else "",
                    "Quantity": qty if qty else "", "Quantity_Unit": unit, "Total_Cost": total,
                    "Supplier": supplier, "Invoice_Ref": invoice,
                    "Created_By": officer, "Created_Date": dt.date.today().isoformat(),
                })
                st.success(f"Saved {new_id}.")


def _settings(data, season, settings):
    st.caption(f"Settings for **{season}**. Each save is kept as a new row (latest wins), so there's an audit trail.")
    officers = data["users"]["Name"].tolist()
    fields = [(BUDGET_KEY_BUDGET_HOURS, "Officer hours budget for the season (hours, optional)"),
              (BUDGET_KEY_DRY_ICE_PRICE, "Dry ice price ($/kg, ex-GST)"),
              (BUDGET_KEY_DRY_ICE_KG_PER_NIGHT, "Dry ice used per trap-night (kg)")]
    fields += [(BUDGET_KEY_BUDGET_PREFIX + c, f"Budget: {c} ($)") for c in BUDGET_CATEGORIES]
    with st.form("settings"):
        who = st.selectbox("Changed by", officers)
        vals = {k: st.number_input(label, min_value=0.0, value=float(settings.get(k, 0.0)), step=1.0,
                                   key=f"set_{k}") for k, label in fields}
        if st.form_submit_button("Save settings"):
            n = 0
            for k, v in vals.items():
                if v > 0 and abs(v - settings.get(k, -1)) > 1e-9:
                    ui.add_budget_setting({"Season": season, "Key": k, "Value": v, "Notes": "",
                                           "Created_By": who, "Created_Date": dt.date.today().isoformat()})
                    n += 1
            st.success(f"Saved {n} changed setting(s)." if n else "No changes to save.")
    st.caption("A value of 0 means 'not set' and isn't saved.")


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Budget")
    ui.sample_data_banner()
    season = filters["season"]
    st.caption(f"Season **{season}** - costs ex-GST")

    settings = calc.latest_budget_settings(data["budget_settings"], season)
    start, end = ui.SEASON_BOUNDS[season]
    as_of = min(max(pd.Timestamp(filters["date_range"][1]), start), pd.Timestamp.now().normalize())
    as_of = max(as_of, start)

    forms.show_flash()
    t1, t2, t3, t4, t5 = st.tabs(["Overview", "Log time", "Log spend", "Settings", "Fix an entry"])
    with t1:
        _overview(data, season, settings, as_of)
    with t2:
        _log_time(data, season)
    with t3:
        _log_spend(data)
    with t4:
        _settings(data, season, settings)
    with t5:
        edit_forms.edit_form(data, filters, edit_forms.BUDGET_TYPES)


render()
