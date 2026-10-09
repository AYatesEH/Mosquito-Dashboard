"""Edit or delete existing records (the "Fix a record" option on Enter Data and
the Budget page's "Edit entries" tab).

Pick a record from the selected season, change what was wrong, save - or
delete it. The record ID, season and who first created it never change.
Changing a treatment's PRODUCT or rate isn't offered (the rate is locked to the
product label): delete the treatment and re-enter it instead.

Everything is generic over a small spec per record type, so adding a type is a
few lines. Writes go through ui.update_record / ui.delete_record.
"""

import pandas as pd
import streamlit as st

from core import ui
from core.forms import (
    TRAP_OUTCOMES, COMPLAINT_CATEGORIES, INVESTIGATION_STATUSES, OUTCOMES, _saved,
)
from core.config import (
    TRAP_TYPES, TREATMENT_STATUSES, OBSERVATION_CATEGORIES, TIME_ACTIVITIES, COST_CATEGORIES,
)

TREATMENT_REASONS = ["Surveillance threshold exceeded", "Complaint-triggered inspection",
                     "Routine scheduled treatment", "Follow-up after prior treatment"]
CANCELLED_REASONS = ["Site access restricted", "Weather unsuitable", "Insufficient surveillance trigger",
                     "Resourcing/staff availability", "Product unavailable"]
VALIDITY = ["Valid", "Invalid", "N/A"]


def _blank(v) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v)) or (isinstance(v, str) and v.strip() == "")


# field: (column, label, kind, options)  -  kinds: text, textarea, select, select_opt,
# date, datetime (date shown, original time-of-day kept), int, float, site, site_opt, officer
SPECS = {
    "Trap result": {
        "table": "surveillance_events", "id": "Event_ID", "date": "Deployment_DateTime", "df": "surv_events",
        "fields": [("Site_ID", "Trap location", "site", None),
                   ("Trap_Type", "Trap type", "select", TRAP_TYPES),
                   ("Deployment_DateTime", "Deployment date", "datetime", None),
                   ("Retrieval_DateTime", "Retrieval date", "datetime", None),
                   ("Trap_Status", "Trap outcome", "select", TRAP_OUTCOMES),
                   ("Sample_Validity", "Sample validity", "select", VALIDITY),
                   ("Officer", "Officer", "officer", None),
                   ("Notes", "Notes", "textarea", None)],
    },
    "Larvae dip": {
        "table": "larvae_dips", "id": "Dip_ID", "date": "DateTime", "df": "larvae_dips",
        "fields": [("Site_ID", "Site", "site", None), ("DateTime", "Dip date", "datetime", None),
                   ("Larvae_Count", "Larvae count", "int", None), ("Officer", "Officer", "officer", None),
                   ("Notes", "Notes", "textarea", None)],
    },
    "Treatment": {
        "table": "treatments", "id": "Treatment_ID", "date": "Planned_Date", "df": "treatments",
        "fields": [("Site_ID", "Site", "site", None),
                   ("Treatment_Status", "Treatment status", "select", TREATMENT_STATUSES),
                   ("Planned_Date", "Treatment date", "date", None),
                   ("Area_Treated_M2", "Area / water surface treated (m²)", "float", None),
                   ("Quantity_Used", "Quantity used (in the product's unit)", "float", None),
                   ("Operator", "Assigned officer", "officer", None),
                   ("Reason", "Reason", "select", TREATMENT_REASONS),
                   ("Cancelled_Reason", "Cancelled reason (if cancelled)", "select_opt", CANCELLED_REASONS),
                   ("Notes", "Notes", "textarea", None)],
    },
    "Complaint": {
        "table": "complaints", "id": "Complaint_ID", "date": "Date_Received", "df": "complaints",
        "fields": [("Date_Received", "Date received", "date", None),
                   ("Site_ID", "Site (if known)", "site_opt", None),
                   ("Category", "Category", "select", COMPLAINT_CATEGORIES),
                   ("Investigation_Status", "Investigation status", "select", INVESTIGATION_STATUSES),
                   ("Outcome", "Outcome (if closed)", "select_opt", OUTCOMES),
                   ("Officer", "Officer", "officer", None),
                   ("Description", "Description", "textarea", None)],
    },
    "Site observation": {
        "table": "site_observations", "id": "Observation_ID", "date": "DateTime", "df": "observations",
        "fields": [("Site_ID", "Site", "site_opt", None), ("DateTime", "Date", "datetime", None),
                   ("Observation_Category", "Category", "select", OBSERVATION_CATEGORIES),
                   ("Officer", "Officer", "officer", None), ("Notes", "Notes", "textarea", None)],
    },
    "Time entry": {
        "table": "time_entries", "id": "Entry_ID", "date": "Date", "df": "time_entries",
        "fields": [("Date", "Date", "date", None), ("Officer", "Officer", "officer", None),
                   ("Activity", "Activity", "select", TIME_ACTIVITIES), ("Hours", "Hours", "float", None),
                   ("Site_ID", "Site (optional)", "site_opt", None), ("Notes", "Notes", "text", None)],
    },
    "Spend entry": {
        "table": "cost_entries", "id": "Cost_ID", "date": "Date", "df": "cost_entries",
        "fields": [("Date", "Date", "date", None), ("Category", "Category", "select", COST_CATEGORIES),
                   ("Description", "Description", "text", None), ("Quantity", "Quantity", "float", None),
                   ("Quantity_Unit", "Unit", "text", None), ("Total_Cost", "Total cost, ex-GST ($)", "float", None),
                   ("Supplier", "Supplier", "text", None), ("Invoice_Ref", "Invoice ref", "text", None)],
    },
}

OPERATIONAL_TYPES = ["Trap result", "Larvae dip", "Treatment", "Complaint", "Site observation"]
BUDGET_TYPES = ["Time entry", "Spend entry"]


def _site_label_map(sites: pd.DataFrame) -> dict:
    s = sites.sort_values("Site_Name")
    return dict(zip(s["Site_ID"], s["Site_Name"] + " (" + s["Site_ID"] + ")"))


def _record_label(kind: str, row, site_names: dict) -> str:
    spec = SPECS[kind]
    d = row[spec["date"]]
    d = "?" if pd.isna(d) else pd.Timestamp(d).strftime("%Y-%m-%d")
    site = site_names.get(row.get("Site_ID"), "") if "Site_ID" in row.index else ""
    extra = {"Trap result": row.get("Trap_Status", ""), "Larvae dip": f"{row.get('Larvae_Count', '')} larvae",
             "Treatment": row.get("Treatment_Status", ""), "Complaint": row.get("Category", ""),
             "Site observation": row.get("Observation_Category", ""),
             "Time entry": f"{row.get('Hours', '')} h {row.get('Activity', '')}",
             "Spend entry": f"{row.get('Category', '')} ${row.get('Total_Cost', '')}"}[kind]
    return " | ".join(str(x) for x in (row[spec["id"]], d, site, extra) if str(x) not in ("", "nan"))


def _widget(kind_f, col, label, current, options, key, sites_map, officers):
    """Renders one field prefilled with `current`; returns the new value."""
    if kind_f in ("select", "select_opt"):
        opts = ([""] if kind_f == "select_opt" else []) + list(options)
        cur = "" if _blank(current) else str(current)
        if cur and cur not in opts:
            opts.append(cur)
        return st.selectbox(label, opts, index=opts.index(cur) if cur in opts else 0, key=key)
    if kind_f == "officer":
        opts = list(officers)
        cur = "" if _blank(current) else str(current)
        if cur and cur not in opts:
            opts.append(cur)
        return st.selectbox(label, opts, index=opts.index(cur) if cur in opts else 0, key=key)
    if kind_f in ("site", "site_opt"):
        ids = ([""] if kind_f == "site_opt" else []) + list(sites_map)
        cur = "" if _blank(current) else str(current)
        if cur and cur not in ids:
            ids.append(cur)
        return st.selectbox(label, ids, index=ids.index(cur) if cur in ids else 0, key=key,
                            format_func=lambda i: sites_map.get(i, "(none)" if i == "" else i))
    if kind_f in ("date", "datetime"):
        base = pd.Timestamp.now().date() if _blank(current) else pd.Timestamp(current).date()
        return st.date_input(label, value=base, key=key)
    if kind_f == "int":
        return st.number_input(label, min_value=0, step=1, value=0 if _blank(current) else int(float(current)), key=key)
    if kind_f == "float":
        return st.number_input(label, min_value=0.0, step=0.5, value=0.0 if _blank(current) else float(current), key=key)
    if kind_f == "textarea":
        return st.text_area(label, value="" if _blank(current) else str(current), key=key)
    return st.text_input(label, value="" if _blank(current) else str(current), key=key)


def edit_form(data: dict, filters: dict, kinds: list):
    """The "Fix a record" UI for the given record types."""
    kind = st.radio("What do you want to fix?", kinds, horizontal=True, key="edit_kind") if len(kinds) > 1 else kinds[0]
    spec = SPECS[kind]
    season = filters["season"]
    df = data[spec["df"]]
    df = df[df["Season"] == season] if "Season" in df.columns else df
    df = df.sort_values(spec["date"], ascending=False).head(100)
    st.caption(f"Showing the 100 most recent {kind.lower()} records in **{season}**. "
               "Change the Season in the sidebar to fix a record from another season.")
    if df.empty:
        st.info(f"No {kind.lower()} records in {season} yet.")
        return

    site_names = {r.Site_ID: r.Site_Name for r in data["sites"].itertuples()}
    labels = {r[spec["id"]]: _record_label(kind, r, site_names) for _, r in df.iterrows()}
    rec_id = st.selectbox("Record", list(labels), format_func=labels.get, key=f"edit_pick_{kind}")
    row = df[df[spec["id"]] == rec_id].iloc[0]
    sites_map = _site_label_map(data["sites"])
    officers = data["users"]["Name"].tolist()
    k = f"edit_{kind}_{rec_id}"

    st.markdown(f"**Editing {rec_id}**")
    new_vals = {}
    for col, label, kind_f, options in spec["fields"]:
        new_vals[col] = _widget(kind_f, col, label, row.get(col), options, f"{k}_{col}", sites_map, officers)

    counts_df = None
    if kind == "Trap result":
        existing = data["surv_results"][data["surv_results"]["Event_ID"] == rec_id]
        have = dict(zip(existing["Species_Code"], existing["Number_Collected"]))
        sp = data["species"][["Species_Code", "Scientific_Name"]].copy()
        sp = sp[(sp["Species_Code"] != "OTHER") | sp["Species_Code"].isin(have)]
        sp["Number_Collected"] = sp["Species_Code"].map(have).fillna(0).astype(int)
        st.caption("Number collected per species (0 for species not caught):")
        counts_df = st.data_editor(
            sp, use_container_width=True, hide_index=True, key=f"{k}_counts",
            column_config={"Species_Code": st.column_config.TextColumn(disabled=True),
                           "Scientific_Name": st.column_config.TextColumn(disabled=True),
                           "Number_Collected": st.column_config.NumberColumn(min_value=0, step=1)})

    who = st.selectbox("Changed by", officers, key=f"{k}_who")

    if st.button("Save changes", type="primary", key=f"{k}_save"):
        changes = {}
        for col, label, kind_f, options in spec["fields"]:
            v = new_vals[col]
            if kind_f == "datetime":
                old = pd.Timestamp(row[col]) if not _blank(row.get(col)) else pd.Timestamp(v)
                v = pd.Timestamp.combine(v, old.time()).strftime("%Y-%m-%d %H:%M")
            elif kind_f == "date":
                v = pd.Timestamp(v).strftime("%Y-%m-%d")
            elif kind_f in ("float", "int") and col in ("Area_Treated_M2", "Quantity_Used", "Quantity") and v == 0:
                v = ""
            changes[col] = v
        err = None
        if kind == "Trap result" and pd.Timestamp(changes["Retrieval_DateTime"]) < pd.Timestamp(changes["Deployment_DateTime"]):
            err = "Retrieval date can't be before the deployment date."
        if kind in ("Time entry",) and changes["Hours"] <= 0:
            err = "Hours must be greater than 0."
        if kind == "Spend entry" and changes["Total_Cost"] <= 0:
            err = "Total cost must be greater than 0."
        if err:
            st.error(err)
        else:
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            if kind == "Treatment":
                changes["Treatment_Date"] = changes["Planned_Date"] if changes["Treatment_Status"] == "Completed" else ""
                if changes["Treatment_Status"] != "Cancelled":
                    changes["Cancelled_Reason"] = ""
                changes["Modified_By"], changes["Modified_Date"] = who, today
            if kind == "Complaint":
                srow = data["sites"][data["sites"]["Site_ID"] == changes["Site_ID"]]
                if changes["Site_ID"] != row.get("Site_ID"):
                    changes["Approx_Latitude"] = srow["Latitude"].iloc[0] if not srow.empty else ""
                    changes["Approx_Longitude"] = srow["Longitude"].iloc[0] if not srow.empty else ""
                if changes["Investigation_Status"] != "Closed":
                    changes["Outcome"] = ""
            if kind == "Trap result":
                changes["Trap_ID"] = row.get("Trap_ID")
            ui.update_record(spec["table"], rec_id, changes)
            if counts_df is not None:
                for rid in data["surv_results"].loc[data["surv_results"]["Event_ID"] == rec_id, "Result_ID"]:
                    ui.delete_record("surveillance_results", rid)
                for _, r in counts_df.iterrows():
                    if int(r["Number_Collected"]) > 0:
                        ui.add_surveillance_result({"Event_ID": rec_id, "Species_Code": r["Species_Code"],
                                                    "Number_Collected": int(r["Number_Collected"]), "Notes": ""})
            _saved(f"Saved changes to {rec_id}.")

    with st.expander("Delete this record"):
        st.caption("Permanently removes the record" + (" and its species counts" if kind == "Trap result" else "")
                   + ". If you only need to correct something, use Save changes above instead.")
        confirm = st.checkbox(f"Yes, delete {rec_id}", key=f"{k}_confirm")
        if st.button("Delete record", key=f"{k}_delete", disabled=not confirm) and confirm:
            ui.delete_record(spec["table"], rec_id)
            _saved(f"Deleted {rec_id}.")
