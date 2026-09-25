"""
mapping.py

Builds the interactive operational map (Folium). Kept separate from the
Streamlit page code so the map-building logic can be tested/reused
independently, and so corporate GIS layers (shapefiles/GeoJSON/treatment
polygons) can be added here later without touching page code.

Design note on future GIS layers:
    Each layer below is added as its own `folium.FeatureGroup`, toggled via
    `folium.LayerControl`. A future GeoJSON/shapefile layer (e.g. council
    boundaries, treatment polygons) can be added the same way: build it as an
    additional FeatureGroup and add it to the map before returning.
"""

from __future__ import annotations

from typing import Optional

import folium
import pandas as pd

from core.config import STATUS_COLOURS, STATUS_UNKNOWN


def _status_colour(status: str) -> str:
    return STATUS_COLOURS.get(status, STATUS_COLOURS[STATUS_UNKNOWN])


def build_operational_map(
    sites: pd.DataFrame,
    site_status_df: pd.DataFrame,
    complaints: Optional[pd.DataFrame] = None,
    treatments: Optional[pd.DataFrame] = None,
    hotspot_site_ids: Optional[set] = None,
    show_traps: bool = True,
    show_complaints: bool = True,
    show_treatments: bool = True,
    show_hotspots_only: bool = False,
) -> folium.Map:
    """
    Builds the main operational Folium map with toggleable layers:
      - Trap sites (coloured by current operational status)
      - Recent treatments (as markers, coloured by treatment type)
      - Complaint locations
      - Hotspots (highlighted ring around hotspot-flagged sites)

    `site_status_df` must have columns Site_ID, Status, Latest_MPTN,
    Latest_Sample_Date at minimum (as produced by
    core.calculations.site_current_status, assembled into a DataFrame).
    """
    mappable_sites = sites.dropna(subset=["Latitude", "Longitude"]).copy()
    if mappable_sites.empty:
        center = [-31.928, 115.853]  # City of Vincent, WA (North Perth) fallback centre
    else:
        center = [mappable_sites["Latitude"].mean(), mappable_sites["Longitude"].mean()]

    # NOTE: "cartodbpositron" (and other CartoDB basemap styles) now require a
    # Carto account/API key for their tile service, which is why the map
    # previously showed an "API key required" message instead of a basemap.
    # "OpenStreetMap" is folium's built-in default tile source and needs no
    # key/account - it's the right choice for an internal prototype like this.
    # tiles=None here because we add OSM and satellite as two selectable base
    # layers below instead (folium only lets the *first* added tile layer be
    # passed via the `tiles=` shortcut).
    fmap = folium.Map(location=center, zoom_start=13, tiles=None)
    folium.TileLayer(
        tiles="OpenStreetMap", name="Street map", control=True, overlay=False, show=True,
    ).add_to(fmap)
    # Esri World Imagery: a free, publicly available satellite/aerial basemap
    # that needs no API key or account (standard choice for this - the same
    # basis on which the OpenStreetMap layer above is used). Resolution is
    # good for most of WA but is a global mosaic, not WA's own more current
    # Landgate aerial photography - see README for how to swap in council/
    # state GIS layers once their exact service endpoint is known.
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        name="Satellite imagery", control=True, overlay=False, show=False,
    ).add_to(fmap)

    hotspot_site_ids = hotspot_site_ids or set()
    status_lookup = {}
    if site_status_df is not None and not site_status_df.empty:
        status_lookup = site_status_df.set_index("Site_ID").to_dict(orient="index")

    # --- Layer: trap / monitoring sites -----------------------------------
    if show_traps:
        sites_layer = folium.FeatureGroup(name="Trap sites (by status)", show=True)
        for _, site in mappable_sites.iterrows():
            site_id = site["Site_ID"]
            if show_hotspots_only and site_id not in hotspot_site_ids:
                continue
            info = status_lookup.get(site_id, {})
            status = info.get("Status", STATUS_UNKNOWN)
            mptn = info.get("Latest_MPTN")
            sample_date = info.get("Latest_Sample_Date")
            popup_html = (
                f"<b>{site['Site_Name']}</b> ({site_id})<br>"
                f"Status: <b>{status}</b><br>"
                f"Latest mosquitoes/trap-night: {mptn if mptn is not None else 'N/A'}<br>"
                f"Latest sample date: {sample_date.strftime('%Y-%m-%d') if pd.notna(sample_date) else 'N/A'}<br>"
                f"Site type: {site['Site_Type']}"
            )
            radius = 7 if site_id in hotspot_site_ids else 6
            folium.CircleMarker(
                location=[site["Latitude"], site["Longitude"]],
                radius=radius,
                color=_status_colour(status),
                fill=True,
                fill_color=_status_colour(status),
                fill_opacity=0.85,
                weight=3 if site_id in hotspot_site_ids else 1,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{site['Site_Name']} - {status}",
            ).add_to(sites_layer)
        sites_layer.add_to(fmap)

    # --- Layer: treatments (recent / current season) ------------------------
    if show_treatments and treatments is not None and not treatments.empty:
        treat_layer = folium.FeatureGroup(name="Recent treatments", show=False)
        merged = treatments.merge(
            mappable_sites[["Site_ID", "Latitude", "Longitude", "Site_Name"]], on="Site_ID", how="inner"
        )
        for _, t in merged.iterrows():
            popup_html = (
                f"<b>{t['Site_Name']}</b><br>Treatment: {t['Treatment_Type']}<br>"
                f"Status: {t['Treatment_Status']}<br>Date: "
                f"{t['Treatment_Date'].strftime('%Y-%m-%d') if pd.notna(t['Treatment_Date']) else 'Not yet completed'}"
            )
            folium.Marker(
                location=[t["Latitude"], t["Longitude"]],
                icon=folium.Icon(color="blue", icon="tint", prefix="fa"),
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=f"Treatment - {t['Treatment_Type']}",
            ).add_to(treat_layer)
        treat_layer.add_to(fmap)

    # --- Layer: complaints ---------------------------------------------------
    if show_complaints and complaints is not None and not complaints.empty:
        complaints_layer = folium.FeatureGroup(name="Complaints", show=False)
        c = complaints.dropna(subset=["Approx_Latitude", "Approx_Longitude"])
        for _, row in c.iterrows():
            popup_html = (
                f"<b>Complaint {row['Complaint_ID']}</b><br>Category: {row['Category']}<br>"
                f"Received: {row['Date_Received'].strftime('%Y-%m-%d') if pd.notna(row['Date_Received']) else 'N/A'}<br>"
                f"Status: {row['Investigation_Status']}"
            )
            folium.CircleMarker(
                location=[row["Approx_Latitude"], row["Approx_Longitude"]],
                radius=4,
                color="#6A1B9A",
                fill=True,
                fill_color="#6A1B9A",
                fill_opacity=0.6,
                popup=folium.Popup(popup_html, max_width=260),
                tooltip="Complaint",
            ).add_to(complaints_layer)
        complaints_layer.add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap
