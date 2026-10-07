"""
auth.py

A single shared-password gate for the whole app (every page calls
ui.apply_page_style(), which calls require_login() before anything else
runs, so no page - and no data load - happens until the visitor is signed in).

HOW IT'S CONFIGURED (no code change, no password in the repo)
    APP_PASSWORD   the shared team password. Set it as a Streamlit Cloud app
                   secret (Manage app -> Settings -> Secrets:
                   APP_PASSWORD = "...") or as an environment variable
                   locally. core/ui.py copies the secret into the environment
                   at startup, the same way it does for DATABASE_URL.
    APP_MODE       "live" turns on live-data behaviour: hides the sample-data
                   banner and makes the gate mandatory.

THREE MODES
    off            No APP_PASSWORD and not live (no DATABASE_URL, APP_MODE
                   not "live"): the open demo/prototype - no login. Nothing
                   real is stored in this mode, so nothing needs protecting.
    password       APP_PASSWORD is set: login screen until the right
                   password is entered.
    misconfigured  The app is holding (or about to hold) real data -
                   DATABASE_URL is set, or APP_MODE=live - but no
                   APP_PASSWORD exists. FAILS CLOSED: shows an error and
                   stops. A live deployment should never silently open up
                   because someone forgot a secret.

WHAT THIS IS, HONESTLY
    A shared password stops casual/unauthorised access and keeps the app from
    being a public page. It is NOT per-person authentication: anyone with the
    password is "the team", nothing records who actually did what (officer
    names are still picked from a dropdown), and removing one person's access
    means changing the password for everyone. Per-officer sign-in (e.g.
    Microsoft/Entra SSO) is the natural next step before wider rollout - see
    README Section 8. Choose a long passphrase, don't reuse a password from
    anywhere else, and rotate it when someone leaves the team.

Failed attempts are slowed down process-wide (not per browser session, so
opening new tabs doesn't reset it): each recent failure adds a delay to the
next attempt, up to a few seconds. This blunts password-guessing without
locking real staff out.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import deque

import streamlit as st

from core.config import APP_TITLE

SESSION_KEY = "_auth_ok_at"
SESSION_MAX_AGE_S = 12 * 60 * 60     # sign in again after 12 hours
FAILURE_WINDOW_S = 5 * 60            # failures older than this stop counting
DELAY_PER_RECENT_FAILURE_S = 0.5
MAX_DELAY_S = 5.0

MODE_OFF = "off"
MODE_PASSWORD = "password"
MODE_MISCONFIGURED = "misconfigured"


@st.cache_resource
def _failure_log() -> deque:
    """Process-wide list of recent failed-attempt timestamps (shared by every
    browser session on this server)."""
    return deque(maxlen=200)


def auth_mode() -> str:
    password = os.environ.get("APP_PASSWORD", "")
    live = os.environ.get("APP_MODE", "").strip().lower() == "live" or bool(os.environ.get("DATABASE_URL"))
    if password:
        return MODE_PASSWORD
    return MODE_MISCONFIGURED if live else MODE_OFF


def is_live_mode() -> bool:
    """True when the app is holding real data (hide sample banners, etc.)."""
    return os.environ.get("APP_MODE", "").strip().lower() == "live" or bool(os.environ.get("DATABASE_URL"))


def passwords_match(entered: str, expected: str) -> bool:
    """Constant-time comparison. Both sides are hashed first so the check
    doesn't leak the expected password's length and never raises on
    non-ASCII input."""
    a = hashlib.sha256((entered or "").encode("utf-8")).digest()
    b = hashlib.sha256((expected or "").encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def _recent_failures(now: float) -> int:
    log = _failure_log()
    while log and now - log[0] > FAILURE_WINDOW_S:
        log.popleft()
    return len(log)


def attempt_delay(now: float | None = None) -> float:
    now = time.time() if now is None else now
    return min(_recent_failures(now) * DELAY_PER_RECENT_FAILURE_S, MAX_DELAY_S)


def _hide_sidebar_nav():
    st.markdown(
        "<style>[data-testid='stSidebarNav'], [data-testid='stSidebar'] {display: none;}</style>",
        unsafe_allow_html=True,
    )


def _signed_in() -> bool:
    ok_at = st.session_state.get(SESSION_KEY)
    return ok_at is not None and (time.time() - ok_at) < SESSION_MAX_AGE_S


def sign_out():
    st.session_state.pop(SESSION_KEY, None)


def require_login():
    """Call at the top of every page (ui.apply_page_style does). Returns only
    when the visitor may see the page; otherwise renders the login screen /
    error and halts the script with st.stop()."""
    mode = auth_mode()
    if mode == MODE_OFF:
        return

    if mode == MODE_MISCONFIGURED:
        _hide_sidebar_nav()
        st.title(APP_TITLE)
        st.error(
            "This app is set up for real data (DATABASE_URL / APP_MODE=live) but no **APP_PASSWORD** has been "
            "configured, so it is locked. Add `APP_PASSWORD = \"...\"` under Manage app -> Settings -> Secrets "
            "(or set the APP_PASSWORD environment variable) and reload."
        )
        st.stop()

    expected = os.environ.get("APP_PASSWORD", "")
    if _signed_in():
        if st.sidebar.button("Log out", key="auth_logout"):
            sign_out()
            st.rerun()
        return

    sign_out()  # clear any expired marker
    _hide_sidebar_nav()
    st.title(APP_TITLE)
    st.caption("Environmental Health - team sign-in")
    with st.form("auth_login_form"):
        entered = st.text_input("Team password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        delay = attempt_delay()
        if delay:
            time.sleep(delay)
        if passwords_match(entered, expected):
            st.session_state[SESSION_KEY] = time.time()
            st.rerun()
        else:
            _failure_log().append(time.time())
            st.error("Incorrect password.")
    st.stop()
