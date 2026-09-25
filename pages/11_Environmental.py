"""Environmental Conditions - rainfall/temperature/tidal vs abundance. Visual comparison only, no causal claims."""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core import ui, calculations as calc


def render():
    ui.apply_page_style()
    data = ui.get_data()
    filters = ui.render_global_filters(data)

    st.title("Environmental Conditions")
    ui.sample_data_banner()
    st.caption(
        "Environmental readings are SAMPLE/synthetic and region-wide (not site-specific) for this prototype. "
        "Designed so an automated weather/tidal feed could replace this data source later without changing "
        "any other page (see core/data_source.py)."
    )

    env = data["environmental"]
    env_f = env[
        (env["Date"].dt.date >= filters["date_range"][0]) & (env["Date"].dt.date <= filters["date_range"][1])
    ]

    events_f = ui.filter_by_season_date(data["surv_events"], filters, date_col="Deployment_DateTime")
    ct = calc.event_catch_totals(events_f, data["surv_results"])

    ui.kpi_row([
        ("Total rainfall (mm)", f"{env_f['Rainfall_mm'].sum():.0f}", None),
        ("Mean max temp (C)", f"{env_f['Temp_Max_C'].mean():.1f}" if not env_f.empty else "N/A", None),
        ("Mean min temp (C)", f"{env_f['Temp_Min_C'].mean():.1f}" if not env_f.empty else "N/A", None),
        ("Mean tidal level (m)", f"{env_f['Tidal_Level_m'].mean():.2f}" if not env_f.empty else "N/A", None),
    ])

    st.divider()
    tab1, tab2, tab3 = st.tabs(["Rainfall vs. abundance", "Temperature vs. abundance", "Tidal level vs. abundance"])

    def _daily_catch():
        if ct.empty:
            return None
        d = ct.groupby(ct["Deployment_DateTime"].dt.date, as_index=False)["Total_Catch"].sum()
        d.columns = ["Date", "Total_Catch"]
        return d

    daily_catch = _daily_catch()

    with tab1:
        if daily_catch is not None and not env_f.empty:
            env_plot = env_f[["Date", "Rainfall_mm"]].copy()
            env_plot["Date"] = env_plot["Date"].dt.date
            merged = daily_catch.merge(env_plot, on="Date", how="outer").fillna(0).sort_values("Date")
            fig = px.bar(merged, x="Date", y="Rainfall_mm")
            fig.add_scatter(x=merged["Date"], y=merged["Total_Catch"], mode="lines", name="Total catch")
            fig.update_layout(height=380)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient data for this comparison.")

    with tab2:
        if daily_catch is not None and not env_f.empty:
            env_plot = env_f[["Date", "Temp_Max_C"]].copy()
            env_plot["Date"] = env_plot["Date"].dt.date
            merged = daily_catch.merge(env_plot, on="Date", how="outer").sort_values("Date")
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=merged["Date"], y=merged["Temp_Max_C"], name="Max temp (C)", mode="lines"))
            fig2.add_trace(go.Bar(x=merged["Date"], y=merged["Total_Catch"], name="Total catch"))
            fig2.update_layout(height=380)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Insufficient data for this comparison.")

    with tab3:
        if daily_catch is not None and not env_f.empty:
            env_plot = env_f[["Date", "Tidal_Level_m"]].copy()
            env_plot["Date"] = env_plot["Date"].dt.date
            merged = daily_catch.merge(env_plot, on="Date", how="outer").sort_values("Date")
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=merged["Date"], y=merged["Tidal_Level_m"], name="Tidal level (m)", mode="lines"))
            fig3.add_trace(go.Bar(x=merged["Date"], y=merged["Total_Catch"], name="Total catch"))
            fig3.update_layout(height=380)
            st.plotly_chart(fig3, use_container_width=True)
            st.caption("Most relevant for saltmarsh/estuarine sites where tidal inundation drives breeding.")
        else:
            st.info("Insufficient data for this comparison.")

    st.caption(
        "These are visual comparisons for officers to investigate possible relationships - not a statistical test "
        "and not a claim that any environmental factor caused a change in abundance."
    )


render()
