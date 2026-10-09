"""Enter Data - every data-entry form in one place.

Reading/analysis pages (Surveillance, Treatments, Complaints...) are view-only.
Budget time and spend are logged on the Budget page, and new sites are added
from the Map ("Add a new site"). To clear a To Do List dipping/inspection task
without a count, record a Site observation with category "Larvae dip / inspection".
"""

import streamlit as st

from core import ui, forms, edit_forms

FORMS = {
    "Trap result": ("Record a trap result (set one day, retrieved the next morning)", forms.trap_form),
    "Larvae dip": ("Log a larvae dip count", forms.dip_form),
    "Treatment": ("Record a treatment", forms.treatment_form),
    "Complaint": ("Log a complaint", forms.complaint_form),
    "Site observation": ("Record a site observation or inspection", forms.observation_form),
    "Fix a record": ("Fix or delete a record entered by mistake", None),
}


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Enter Data")
    ui.sample_data_banner()
    st.caption("Pick what you're recording. Time and spend go on the Budget page; new sites are added from the Map.")
    forms.show_flash()

    choice = st.radio("What are you recording?", list(FORMS), horizontal=True, key="enter_data_choice")
    title, form_fn = FORMS[choice]
    st.subheader(title)
    if form_fn is None:
        edit_forms.edit_form(data, filters, edit_forms.OPERATIONAL_TYPES)
    else:
        form_fn(data)


render()
