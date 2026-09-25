"""
weather_api.py

Live weather lookups via Open-Meteo (https://open-meteo.com) - a free
weather API that needs NO API key/account for non-commercial use (confirmed
against Open-Meteo's own docs as of when this was written; if that ever
changes, these calls will start failing with a 401/403 and should be
revisited).

Kept deliberately free of Streamlit code (same reasoning as calculations.py)
so it can be tested/reused independently - callers (core/ui.py or a page)
are responsible for wrapping these with st.cache_data, since caching policy
is a UI concern, not a data-fetching one.

IMPORTANT - this could not be tested against the live API from the
environment this was built in (outbound network access there is restricted
to package registries/GitHub only). The request/response shapes below are
built directly from Open-Meteo's published API docs, but this genuinely
needs a first real run to confirm - if weather lookups don't work first
time, check the error message surfaced in the UI (network/timeout vs. a
changed API response shape) before assuming something deeper is wrong.

Two endpoints are used:
  - Forecast API (api.open-meteo.com/v1/forecast): current conditions, plus
    daily data for a date range roughly -92 to +16 days from today. Used for
    "today", recent past treatments, and near-future planning.
  - Historical/archive API (archive-api.open-meteo.com/v1/archive): final
    reanalysis data back to 1940, used as a fallback for older dates the
    forecast endpoint won't cover.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
REQUEST_TIMEOUT_SECONDS = 10
TIDE_VAR = "sea_level_height_msl"

DAILY_VARS = ["precipitation_sum", "rain_sum", "temperature_2m_max", "temperature_2m_min"]
CURRENT_VARS = ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m", "weather_code"]

# Roughly how far back/forward the forecast endpoint's date-range query
# reliably covers (per Open-Meteo docs) - used only to pick which endpoint to
# call, not enforced strictly.
FORECAST_PAST_DAYS_LIMIT = 90
FORECAST_FUTURE_DAYS_LIMIT = 16


def _get(url: str, params: dict) -> dict:
    """Single place all HTTP calls go through, so error handling is
    consistent. Returns {'error': '<message>'} on any failure rather than
    raising - callers should check for that key before reading data."""
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        return {"error": f"Weather lookup timed out after {REQUEST_TIMEOUT_SECONDS}s."}
    except requests.exceptions.RequestException as e:
        return {"error": f"Weather lookup failed: {e}"}
    except ValueError:
        return {"error": "Weather API returned a response that wasn't valid JSON."}


def fetch_current_conditions(lat: float, lon: float) -> dict:
    """
    Live conditions right now at (lat, lon), plus today's running daily
    totals. Returns a flat dict on success:
        {temperature_c, humidity_pct, precipitation_now_mm, wind_speed_kmh,
         observed_at, today_rainfall_mm, today_temp_max_c, today_temp_min_c}
    or {'error': '<message>'} on failure - always check for 'error' first.
    """
    params = {
        "latitude": lat, "longitude": lon,
        "current": ",".join(CURRENT_VARS),
        "daily": ",".join(DAILY_VARS),
        "timezone": "auto",
        "forecast_days": 1,
    }
    data = _get(FORECAST_URL, params)
    if "error" in data:
        return data
    try:
        current = data["current"]
        daily = data["daily"]
        return {
            "temperature_c": current.get("temperature_2m"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "precipitation_now_mm": current.get("precipitation"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "observed_at": current.get("time"),
            "today_rainfall_mm": daily.get("precipitation_sum", [None])[0],
            "today_temp_max_c": daily.get("temperature_2m_max", [None])[0],
            "today_temp_min_c": daily.get("temperature_2m_min", [None])[0],
        }
    except (KeyError, IndexError, TypeError):
        return {"error": "Weather API response was missing an expected field - the API may have changed shape."}


TIDE_CAVEAT = (
    "Rough OPEN-OCEAN approximation only (Open-Meteo Marine Weather API, ~8km-resolution model) - NOT an "
    "accurate Swan River reading. Open-Meteo's own docs say this model's coastal accuracy is limited and it "
    "'does not replace your nautical almanac'; a narrow, upstream estuary like the Swan River (whose tide is "
    "measurably dampened and time-lagged behind the ocean entrance at Fremantle) is exactly the case it doesn't "
    "resolve well. There is no free, no-API-key source of accurate real Swan River tide predictions - WA "
    "Department of Transport publishes only an interactive real-time chart and static annual PDF tables (not a "
    "queryable API), and BOM has no official public API either. Use this ONLY as a rough rising/falling "
    "indicator - never as the actual water level - and confirm against WA DoT's real Perth (Barrack St) tide "
    "station before timing any river-bank work: https://www.transport.wa.gov.au/marine/charts-warnings-current-"
    "conditions/coastal-data-charts/tide-data/perth"
)


def fetch_tide_indicator(lat: float, lon: float) -> dict:
    """
    A ROUGH rising/falling tide/sea-level indicator via Open-Meteo's free,
    no-API-key Marine Weather API - added specifically to help roughly time
    larvicide/dipping visits to the Swan River foreshore site, per the
    person's request. See TIDE_CAVEAT above (also returned in the result,
    under 'caveat') for why this is NOT an accurate Swan River reading and
    must not be used as the sole basis for timing river-bank work.

    Returns on success:
        {sea_level_m, observed_at, trend ('Rising'/'Falling'/'Steady'/None),
         next_turn_time, next_turn_type ('High'/'Low'/None), caveat}
    or {'error': '<message>'} on failure - always check for 'error' first.
    Like the other functions here, this was written against Open-Meteo's
    published docs and could not be exercised live from this sandbox
    (network restricted) - first real run on the deployed app will confirm.
    """
    params = {
        "latitude": lat, "longitude": lon,
        "current": TIDE_VAR, "hourly": TIDE_VAR,
        "timezone": "auto", "forecast_days": 2,
    }
    data = _get(MARINE_URL, params)
    if "error" in data:
        return data
    try:
        current_level = data["current"][TIDE_VAR]
        current_time = data["current"]["time"]
        hourly_times = data["hourly"]["time"]
        hourly_levels = data["hourly"][TIDE_VAR]

        idx = hourly_times.index(current_time) if current_time in hourly_times else None

        trend = None
        if idx is not None and idx + 1 < len(hourly_levels) and current_level is not None \
                and hourly_levels[idx + 1] is not None:
            next_level = hourly_levels[idx + 1]
            trend = "Rising" if next_level > current_level else ("Falling" if next_level < current_level else "Steady")

        # Rough "next high/low": first local turning point in the remaining
        # hourly series from now onward.
        next_turn_time, next_turn_type = None, None
        if idx is not None:
            remaining_levels = hourly_levels[idx:]
            remaining_times = hourly_times[idx:]
            for i in range(1, len(remaining_levels) - 1):
                prev_v, this_v, next_v = remaining_levels[i - 1], remaining_levels[i], remaining_levels[i + 1]
                if prev_v is None or this_v is None or next_v is None:
                    continue
                if this_v >= prev_v and this_v >= next_v:
                    next_turn_time, next_turn_type = remaining_times[i], "High"
                    break
                if this_v <= prev_v and this_v <= next_v:
                    next_turn_time, next_turn_type = remaining_times[i], "Low"
                    break

        return {
            "sea_level_m": current_level,
            "observed_at": current_time,
            "trend": trend,
            "next_turn_time": next_turn_time,
            "next_turn_type": next_turn_type,
            "caveat": TIDE_CAVEAT,
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return {"error": "Marine/tide API response was missing an expected field - the API may have changed shape."}


def fetch_weather_for_date(lat: float, lon: float, target_date: date) -> dict:
    """
    Daily rainfall/temperature for ONE specific date at (lat, lon) - past,
    today, or up to ~16 days ahead (a forecast, not an observation, for
    future dates). Returns:
        {date, rainfall_mm, temp_max_c, temp_min_c, source}
    or {'error': '<message>'} on failure.

    Routes to the forecast endpoint (covers roughly the last 90 days through
    the next 16, using `start_date`/`end_date`) or the historical archive
    endpoint for anything older, since the archive's final reanalysis data
    typically lags several days behind real-time and won't have very recent
    dates yet.
    """
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    today = date.today()
    days_ago = (today - target_date).days

    date_str = target_date.strftime("%Y-%m-%d")
    if -FORECAST_FUTURE_DAYS_LIMIT <= days_ago <= FORECAST_PAST_DAYS_LIMIT:
        url, source = FORECAST_URL, "forecast/recent-observation model"
    else:
        url, source = ARCHIVE_URL, "historical archive (reanalysis)"

    params = {
        "latitude": lat, "longitude": lon,
        "start_date": date_str, "end_date": date_str,
        "daily": ",".join(DAILY_VARS),
        "timezone": "auto",
    }
    data = _get(url, params)
    if "error" in data:
        return data
    try:
        daily = data["daily"]
        return {
            "date": date_str,
            "rainfall_mm": daily.get("precipitation_sum", [None])[0],
            "temp_max_c": daily.get("temperature_2m_max", [None])[0],
            "temp_min_c": daily.get("temperature_2m_min", [None])[0],
            "source": source,
        }
    except (KeyError, IndexError, TypeError):
        return {"error": "Weather API response was missing an expected field - the API may have changed shape."}
