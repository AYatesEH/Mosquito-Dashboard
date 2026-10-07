"""Enter Data - every data-entry form in one place.

Reading/analysis pages (Surveillance, Treatments, Complaints...) are view-only.
Budget time and spend are logged on the Budget page. Two quick shortcuts stay
where the context is: the To Do List's dip/inspection log and the Map's
"Add a new site".
"""

import streamlit as st

from core import ui, forms

FORMS = {
    "Trap check": ("Log a trap check", forms.trap_form),
    "Larvae dip": ("Log a larvae dip count", forms.dip_form),
    "Treatment": ("Record a treatment", forms.treatment_form),
    "Complaint": ("Log a complaint", forms.complaint_form),
    "Site observation": ("Record a site observation", forms.observation_form),
}


def render():
    ui.apply_page_style()
    data = ui.get_data()
    ui.render_global_filters(data)

    st.title("Enter Data")
    ui.sample_data_banner()
    st.caption("Pick what you're recording. Time and spend go on the Budget page; new sites are added from the Map.")
    forms.show_flash()

    choice = st.radio("What are you recording?", list(FORMS), horizontal=True, key="enter_data_choice")
    title, form_fn = FORMS[choice]
    st.subheader(title)
    form_fn(data)


render()
