"""
frontend/app.py — MacroMatch Streamlit UI
------------------------------------------
Run from the project root with:
    venv\\Scripts\\python.exe -m streamlit run frontend/app.py

Requires the FastAPI backend to be running at http://127.0.0.1:8000
    venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload
"""

import os
import re
import io
import html
import base64
import json
from datetime import datetime, timezone

import numpy as np
from PIL import Image
import streamlit as st
import streamlit.components.v1 as components
from streamlit_searchbox import st_searchbox
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

from supabase import create_client, Client  # >>> NEW: Supabase client for Auth + database

# Load .env (local dev). On Streamlit Community Cloud, use the app's Secrets instead.
load_dotenv()

# Zero-height component that installs mobile sidebar gestures once per session.
# It listens on window.parent.document so a swipe from anywhere closes the
# sidebar, and it also closes the sidebar after a Product guide "Select" tap.
_MOBILE_SIDEBAR_TOGGLE_JS = """
<script>
(function () {
    var MOBILE_MAX_WIDTH = 768;

    function parentWindow() {
        try {
            return (window.parent && window.parent.document) ? window.parent : window;
        } catch (e) {
            return window;
        }
    }

    function first(doc, selectors) {
        for (var i = 0; i < selectors.length; i++) {
            var el = doc.querySelector(selectors[i]);
            if (el) { return el; }
        }
        return null;
    }

    var COLLAPSE_SELECTORS = [
        '[data-testid="stSidebarCollapseButton"] button',
        'button[data-testid="stSidebarCollapseButton"]',
        '[data-testid="stSidebar"] button[kind="header"]',
        '[data-testid="stSidebarHeader"] button[kind="header"]'
    ];
    var EXPAND_SELECTORS = [
        '[data-testid="stSidebarCollapsedControl"] button',
        'button[data-testid="stSidebarCollapsedControl"]',
        '[data-testid="collapsedControl"] button',
        'button[data-testid="collapsedControl"]'
    ];

    function sidebarIsOpen(doc) {
        var sidebar = doc.querySelector('[data-testid="stSidebar"]');
        if (!sidebar) { return false; }
        var view = doc.defaultView || window;
        var style = view.getComputedStyle(sidebar);
        var rect = sidebar.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0;
    }

    function collapseSidebar() {
        var win = parentWindow();
        if (!win || win.innerWidth > MOBILE_MAX_WIDTH) { return false; }
        var doc = win.document;
        if (!doc) { return false; }
        var collapseButton = first(doc, COLLAPSE_SELECTORS);
        if (collapseButton) {
            collapseButton.click();
            win.__mmLastCollapseAt = Date.now();
            return true;
        }
        if (!sidebarIsOpen(doc)) { return false; }
        var control = first(doc, EXPAND_SELECTORS);
        if (control) {
            control.click();
            win.__mmLastCollapseAt = Date.now();
            return true;
        }
        return false;
    }

    var host = parentWindow();
    // The iframe is recreated on each app rerun, so refresh the shared helper
    // while keeping the parent-document listeners bound only once.
    host.__macroMatchCollapseSidebar = collapseSidebar;
    var doc = host.document;

    if (!host.__mmSwipeBound) {
        host.__mmSwipeBound = true;
        var startX = null;
        var startY = null;
        host.__mmTouchStart = function (event) {
            if (host.innerWidth > MOBILE_MAX_WIDTH ||
                    !event.touches || event.touches.length !== 1) {
                startX = null;
                startY = null;
                return;
            }
            startX = event.touches[0].clientX;
            startY = event.touches[0].clientY;
        };
        host.__mmTouchEnd = function (event) {
            if (startX === null || host.innerWidth > MOBILE_MAX_WIDTH) {
                startX = null;
                startY = null;
                return;
            }
            var touch = event.changedTouches && event.changedTouches[0];
            if (touch) {
                var deltaX = startX - touch.clientX;
                var deltaY = Math.abs(startY - touch.clientY);
                if (deltaX > 60 && deltaX > deltaY) {
                    collapseSidebar();
                }
            }
            startX = null;
            startY = null;
        };
        doc.addEventListener('touchstart', host.__mmTouchStart,
                             { passive: true, capture: true });
        doc.addEventListener('touchend', host.__mmTouchEnd,
                             { passive: true, capture: true });
    }

    // Product-guide Select buttons are Streamlit widgets that trigger a full
    // rerun; a delegated parent-document listener is the reliable place to
    // collapse the mobile sidebar right after the selection is registered.
    if (!host.__mmGuideSelectBound) {
        host.__mmGuideSelectBound = true;
        host.__mmGuideSelectHandler = function (event) {
            if (host.innerWidth > MOBILE_MAX_WIDTH) { return; }
            var target = event.target && event.target.closest
                ? event.target.closest('button') : null;
            if (!target || (target.textContent || '').trim() !== 'Select') { return; }
            var sidebar = doc.querySelector('[data-testid="stSidebar"]');
            if (!sidebar || !sidebar.contains(target)) { return; }
            // Retry once only if Streamlit has not swapped in the collapse
            // control yet; a successful click must never be repeated.
            if (!collapseSidebar()) {
                host.setTimeout(collapseSidebar, 80);
            }
        };
        doc.addEventListener('click', host.__mmGuideSelectHandler, false);
    }
})();
</script>
"""

# Dark theme for the streamlit-searchbox component. These values are passed
# straight into its React/Select styles because the widget lives in an iframe.
_SEARCHBOX_STYLE_OVERRIDES = {
    "wrapper": {"width": "100%"},
    "clear": {
        "icon": "cross",
        "clearable": "always",
        "stroke": "#8B949E",
        "width": 18,
        "height": 18,
    },
    "dropdown": {"fill": "#8B949E", "width": 18, "height": 18},
    "searchbox": {
        "control": {
            "backgroundColor": "#161B22",
            "color": "#E6EDF3",
            "border": "1px solid #30363D",
            "borderRadius": "10px",
            "minHeight": "46px",
            "boxShadow": "none",
            "&:hover": {"border": "1px solid #2EA043"},
            "&:focus-within": {
                "border": "1px solid #2EA043",
                "boxShadow": "0 0 0 1px #2EA043, 0 0 14px rgba(46, 160, 67, 0.35)",
            },
        },
        "menuList": {
            "backgroundColor": "#0D1117",
            "border": "1px solid #30363D",
            "borderRadius": "10px",
            "padding": "4px",
            "boxShadow": "0 12px 28px rgba(0, 0, 0, 0.45)",
        },
        "option": {
            "color": "#E6EDF3",
            "backgroundColor": "#0D1117",
            "fontSize": "16px",
            "fontWeight": 500,
            "padding": "10px 12px",
            "borderRadius": "8px",
            "highlightColor": "rgba(46, 160, 67, 0.45)",
        },
        "input": {"color": "#E6EDF3", "fontSize": "16px"},
        "singleValue": {"color": "#E6EDF3", "fontSize": "16px"},
        "placeholder": {"color": "#8B949E", "fontSize": "16px"},
    },
}

# ─────────────────────────────────────────────
# Page config — must be the FIRST st call
# ─────────────────────────────────────────────
_ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "macromatch_icon.png"

st.set_page_config(
    page_title="MacroMatch",
    page_icon=str(_ICON_PATH) if _ICON_PATH.exists() else "🥗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Brand logo ──────────────────────────────────────────────────────────────
# The source PNG has a baked-in white background. Convert it to true alpha so
# it blends into dark surfaces (auth card and dashboard header) cleanly.
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "macromatch_logo.png"


def _transparent_logo_data_url(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
        alpha = np.clip((255.0 - rgb.min(axis=2)) / 255.0, 0.0, 1.0)
        foreground = np.zeros_like(rgb)
        solid = alpha > 0.01
        foreground[solid] = (
            rgb[solid] - (1.0 - alpha[solid, None]) * 255.0
        ) / alpha[solid, None]
        rgba = np.dstack(
            [np.clip(foreground, 0, 255), alpha * 255.0]
        ).astype(np.uint8)
        buffer = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(
            buffer.getvalue()
        ).decode("ascii")
    except Exception:
        # Fall back to the original image if Pillow/NumPy are unavailable.
        return "data:image/png;base64," + base64.b64encode(
            path.read_bytes()
        ).decode("ascii")


LOGO_SRC = _transparent_logo_data_url(_LOGO_PATH)


# ─────────────────────────────────────────────
# NEW: Supabase Authentication
# Users live in Supabase Auth (cloud). No config.yaml, no local SQLite.
# Session tokens are stored in st.session_state; user data persists across
# deployments because it lives in Supabase.
# ─────────────────────────────────────────────


def get_supabase_client() -> Client:
    """Create a Supabase client from st.secrets (Cloud) or env vars (local dev)."""
    url = st.secrets.get("SUPABASE_URL", "") if hasattr(st, "secrets") else ""
    key = (
        st.secrets.get("SUPABASE_ANON_KEY", "") if hasattr(st, "secrets") else ""
    )
    if not url:
        url = os.environ.get("SUPABASE_URL", "")
    if not key:
        key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        st.error(
            "⚠️ Supabase is not configured. Add SUPABASE_URL and SUPABASE_ANON_KEY "
            "to .streamlit/secrets.toml (or set them as environment variables)."
        )
        st.stop()
    return create_client(url, key)


supabase: Client = get_supabase_client()


@st.cache_data(ttl=3600)
def fetch_profile_name(user_id: str, fallback: str) -> str:
    """Look up a profile name, tolerating a missing `profiles` table (PGRST205)."""
    try:
        profile = (
            get_authenticated_supabase()
            .table("profiles")
            .select("name")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if profile.data and profile.data.get("name"):
            return profile.data["name"]
    except Exception:
        pass
    return fallback


# Session-state keys for Supabase Auth persistence
if "supabase_user" not in st.session_state:
    st.session_state["supabase_user"] = None
if "supabase_access_token" not in st.session_state:
    st.session_state["supabase_access_token"] = None
if "supabase_refresh_token" not in st.session_state:
    st.session_state["supabase_refresh_token"] = None
if "supabase_user_name" not in st.session_state:
    st.session_state["supabase_user_name"] = None
if "supabase_recovery_mode" not in st.session_state:
    st.session_state["supabase_recovery_mode"] = False


def _metadata_int(metadata: dict, key: str, default: int, low: int, high: int) -> int:
    """Read a bounded integer goal from Supabase metadata without failing on junk."""
    try:
        value = int(metadata.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _normalize_diet_label(value) -> str:
    """Accept either a diet key or its pill label from saved metadata."""
    if not isinstance(value, str):
        return "None"
    if value in DIET_LABELS.values():
        return value
    if value in DIET_LABELS:
        return DIET_LABELS[value]
    return "None"


def _normalize_allergens(value) -> list[str]:
    """Drop unknown allergen keys so the multiselect never receives junk."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [item for item in value if item in ALLERGEN_OPTIONS]


def _load_user_preferences(user) -> None:
    """Initialize per-user goals/preferences once from Supabase Auth metadata."""
    user_id = getattr(user, "id", None)
    if user_id is not None and st.session_state.get("_preferences_user_id") == user_id:
        return

    metadata = getattr(user, "user_metadata", None) or {}
    st.session_state["daily_protein_goal"] = _metadata_int(
        metadata, "daily_protein_goal", 120, 1, 500
    )
    st.session_state["daily_calorie_goal"] = _metadata_int(
        metadata, "daily_calorie_goal", 2000, 500, 10000
    )
    st.session_state["default_diet_select"] = _normalize_diet_label(
        metadata.get("default_diet")
    )
    st.session_state["default_allergens_select"] = _normalize_allergens(
        metadata.get("default_allergens")
    )

    st.session_state["_preferences_user_id"] = user_id
    st.session_state["_preferences_filters_pending"] = True


def _ensure_supabase_session() -> None:
    """Attach stored tokens to the client on EVERY rerun.

    get_supabase_client() creates a fresh client each script run. Without
    calling set_session() again, PostgREST requests are anonymous and RLS
    policies (`auth.uid() = user_id`) reject the saved-matches queries.
    """
    access = st.session_state["supabase_access_token"]
    refresh = st.session_state["supabase_refresh_token"]
    if not access or not refresh:
        return

    try:
        supabase.auth.set_session(access, refresh)
    except Exception:
        try:
            refreshed = supabase.auth.refresh_session(refresh)
            session = getattr(refreshed, "session", None)
            if not (session and session.access_token and session.refresh_token):
                raise RuntimeError("refresh_session returned no tokens")
            access, refresh = session.access_token, session.refresh_token
            st.session_state["supabase_access_token"] = access
            st.session_state["supabase_refresh_token"] = refresh
            supabase.auth.set_session(access, refresh)
        except Exception as exc:
            st.session_state["supabase_access_token"] = None
            st.session_state["supabase_refresh_token"] = None
            st.session_state["supabase_user"] = None
            st.session_state["supabase_user_name"] = None
            st.session_state["supabase_recovery_mode"] = False
            st.error(f"Supabase session expired — please sign in again: {exc}")
            return

    # The user object is already in session state after the first load; skip
    # the extra network round-trip on every subsequent widget click.
    if st.session_state["supabase_user"] is not None:
        return

    try:
        user_response = supabase.auth.get_user()
        if user_response and user_response.user:
            st.session_state["supabase_user"] = user_response.user
            st.session_state["supabase_user_name"] = fetch_profile_name(
                user_response.user.id, user_response.user.email or ""
            )
    except Exception as exc:
        st.error(f"Could not verify Supabase session: {exc}")


def get_authenticated_supabase() -> Client:
    """Return a fresh Supabase client with this user's JWT attached.

    RLS policies on `saved_matches` compare `auth.uid()` with `user_id`. A
    client created without a session talks to PostgREST as `anon`, which is
    why inserts from other signed-in users fail with 42501. Building the
    client per call and explicitly attaching the stored access token keeps
    every query authenticated, even after reruns or on another device.
    """
    client = get_supabase_client()
    access = st.session_state.get("supabase_access_token")
    refresh = st.session_state.get("supabase_refresh_token")

    # Recover a usable access token when only the refresh token survived.
    if not access and refresh:
        try:
            refreshed = client.auth.refresh_session(refresh)
            session = getattr(refreshed, "session", None)
            if session and session.access_token:
                access = session.access_token
                refresh = session.refresh_token or refresh
                st.session_state["supabase_access_token"] = access
                st.session_state["supabase_refresh_token"] = refresh
        except Exception:
            access = None

    if access:
        try:
            client.auth.set_session(access, refresh or "")
        except Exception:
            # Older/newer supabase-py versions vary in set_session semantics;
            # setting the PostgREST header directly is the reliable fallback.
            pass
        try:
            client.postgrest.auth(access)
        except Exception:
            pass

    return client


def _authenticated_user(client: Client):
    """Resolve the user tied to the attached JWT, preferring cached state."""
    user = st.session_state.get("supabase_user")
    if user is not None and getattr(user, "id", None):
        return user
    try:
        response = client.auth.get_user()
        user = getattr(response, "user", None) if response is not None else None
        if user is not None and getattr(user, "id", None):
            st.session_state["supabase_user"] = user
            return user
    except Exception:
        pass
    return None


# Supabase OAuth and password-recovery links return auth data in the query
# string. Capture it before session restoration so Google sign-in and the
# `type=recovery` password reset flow can both complete.
_auth_params = st.query_params
_is_recovery_link = str(_auth_params.get("type", "")) == "recovery"

if st.session_state["supabase_user"] is None or _is_recovery_link:
    _tokens_captured = False

    # Implicit flow: access_token + refresh_token + type=recovery.
    if "access_token" in _auth_params and "refresh_token" in _auth_params:
        st.session_state["supabase_access_token"] = _auth_params["access_token"]
        st.session_state["supabase_refresh_token"] = _auth_params["refresh_token"]
        _tokens_captured = True

    # PKCE flow: Supabase may send a one-time `code` instead of raw tokens.
    elif "code" in _auth_params:
        try:
            _code_response = supabase.auth.exchange_code_for_session(
                {"auth_code": _auth_params["code"]}
            )
            _code_session = getattr(_code_response, "session", None)
            if _code_session and _code_session.access_token and _code_session.refresh_token:
                st.session_state["supabase_access_token"] = _code_session.access_token
                st.session_state["supabase_refresh_token"] = _code_session.refresh_token
                _tokens_captured = True
        except Exception as exc:
            st.error(f"Error: could not start the recovery session: {exc}")

    if _is_recovery_link:
        st.session_state["supabase_recovery_mode"] = True
        st.session_state.auth_view = "reset"
        if (
            not _tokens_captured
            and not st.session_state["supabase_access_token"]
            and not st.session_state["supabase_refresh_token"]
        ):
            st.warning(
                "Recovery link opened without a session. Enter your email, "
                "current password, and new password below."
            )

    # Remove one-time auth params so a refresh cannot replay them.
    for _param in ("access_token", "refresh_token", "code", "type"):
        try:
            if _param in st.query_params:
                del st.query_params[_param]
        except Exception:
            pass

_ensure_supabase_session()


# ─────────────────────────────────────────────
# AUTHENTICATION UI — ONE unified centered card
# Rendered while logged out, and while a password-recovery session is active.
# ─────────────────────────────────────────────

# Normalise stale values from earlier deployments so forms never disappear.
if st.session_state.get("auth_view") not in ("signin", "forgot", "reset"):
    st.session_state.auth_view = "signin"


def _oauth_redirect_url() -> str:
    """Return the configured Supabase OAuth redirect URL, if any."""
    configured = os.environ.get("SUPABASE_REDIRECT_URL", "").strip()
    if not configured:
        try:
            configured = str(st.secrets.get("SUPABASE_REDIRECT_URL", "")).strip()
        except Exception:
            configured = ""
    return configured


def _app_url() -> str:
    """Return this app's public URL for Supabase email redirects."""
    for key in ("APP_URL", "STREAMLIT_APP_URL"):
        configured = os.environ.get(key, "").strip()
        if not configured:
            try:
                configured = str(st.secrets.get(key, "")).strip()
            except Exception:
                configured = ""
        if configured:
            return configured
    # Reuse the redirect URL already configured for Google/OAuth if present.
    return _oauth_redirect_url()


def _begin_google_sign_in() -> None:
    """Start Supabase Google OAuth, or explain what needs configuring."""
    redirect_to = _oauth_redirect_url()
    if not redirect_to:
        st.warning(
            "Google sign-in needs the Google provider enabled in Supabase and "
            "`SUPABASE_REDIRECT_URL` set to this app's URL. Use email sign-in "
            "for now."
        )
        return
    try:
        oauth_response = supabase.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {"redirect_to": redirect_to},
            }
        )
        oauth_url = getattr(oauth_response, "url", None)
        if not oauth_url:
            raise RuntimeError("Supabase did not return an OAuth URL")
        st.markdown(
            f'<meta http-equiv="refresh" content="0;url={html.escape(oauth_url, quote=True)}">',
            unsafe_allow_html=True,
        )
        st.success("Redirecting to Google…")
        st.stop()
    except Exception as exc:
        st.error(f"Google sign-in could not start: {exc}")


# A recovery session is authenticated, but must stay on the reset form until
# the user has actually changed their password.
show_auth_ui = (
    st.session_state["supabase_user"] is None
    or st.session_state.get("supabase_recovery_mode", False)
)

if show_auth_ui:

    # ── Auth CSS — MUST be injected before st.stop() below ──────────────
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');

    :root {
        --auth-green: #2EA043;
        --auth-green-bright: #3FB950;
        --auth-text: #F8FAFC;
        --auth-muted: #94A3B8;
        --auth-glass: rgba(255, 255, 255, 0.14);
        --auth-radius: 24px;
    }

    /* Hide Streamlit chrome and flatten the header — never touch the sidebar toggle. */
    [data-testid="stToolbarActions"], #MainMenu, footer,
    .stDeployButton, [data-testid="stAppDeployButton"], [data-testid="manage-app-button"] {
        display: none !important;
    }

    /* Hide the bottom-right Streamlit viewer badge and creator profile avatar for all visitors */
    [data-testid="stStatusWidget"],
    [data-testid="manage-app-button"],
    .stDeployButton,
    [class*="viewerBadge"],
    [class*="StatusWidget"],
    div[class*="_container_"][class*="_viewerBadge_"],
    a[href*="streamlit.io/cloud"] {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }

    header[data-testid="stHeader"] { background: transparent !important; }

    /* Keep the control interactive, then apply the custom "☰ Menu" styling. */
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        pointer-events: auto !important;
        width: auto !important;
        min-width: 0 !important;
        height: auto !important;
    }
    button[data-testid="stSidebarCollapsedControl"],
    button[data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"] button,
    [data-testid="collapsedControl"] button {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: auto !important;
        height: auto !important;
        min-width: 0 !important;
    }
    [data-testid="stSidebarCollapsedControl"] button,
    [data-testid="collapsedControl"] button {
        padding: 2px 4px !important;
        background: transparent !important;
        border: none !important;
    }
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {
        position: fixed !important;
        top: 16px !important;
        left: 16px !important;
        z-index: 999999 !important;
        background-color: #161B22 !important;
        border: 1px solid #30363D !important;
        border-radius: 10px !important;
        padding: 4px 12px !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4) !important;
        transition: background-color 0.12s ease, border-color 0.12s ease, transform 0.12s ease !important;
    }
    @media (hover: hover) {
        [data-testid="stSidebarCollapsedControl"]:hover,
        [data-testid="collapsedControl"]:hover {
            background-color: #21262D !important;
            border-color: #2EA043 !important;
        }
    }
    [data-testid="stSidebarCollapsedControl"] svg,
    [data-testid="collapsedControl"] svg {
        display: none !important;
    }
    button[data-testid="stSidebarCollapsedControl"]::after,
    button[data-testid="collapsedControl"]::after,
    div[data-testid="stSidebarCollapsedControl"] button::after,
    div[data-testid="collapsedControl"] button::after,
    span[data-testid="stSidebarCollapsedControl"] button::after,
    span[data-testid="collapsedControl"] button::after {
        content: "☰  Menu";
        color: #E6EDF3 !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        white-space: nowrap !important;
        padding: 2px 4px !important;
    }

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', sans-serif !important;
    }

    /* Dark navy + black canvas with restrained green ambience. */
    .stApp {
        background:
            radial-gradient(900px 520px at 10% 4%, rgba(46, 160, 67, 0.14), transparent 62%),
            radial-gradient(760px 520px at 90% 16%, rgba(16, 185, 129, 0.09), transparent 60%),
            linear-gradient(180deg, #04060B 0%, #0A1020 50%, #03050A 100%) !important;
    }
    .stApp::before {
        content: "";
        position: fixed;
        inset: 0;
        z-index: 0;
        pointer-events: none;
        background-image:
            linear-gradient(rgba(148, 163, 184, 0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(148, 163, 184, 0.035) 1px, transparent 1px);
        background-size: 44px 44px;
        -webkit-mask-image: radial-gradient(circle at 50% 26%, black, transparent 76%);
        mask-image: radial-gradient(circle at 50% 26%, black, transparent 76%);
    }
    .stApp::after {
        content: "";
        position: fixed;
        top: 46%;
        left: 50%;
        width: min(860px, 96vw);
        height: min(860px, 96vw);
        transform: translate(-50%, -50%);
        z-index: 0;
        pointer-events: none;
        background: radial-gradient(circle, rgba(46, 160, 67, 0.26) 0%, rgba(16, 185, 129, 0.10) 40%, transparent 72%);
    }

    /* Single centered card: the side spacer/hero columns are never rendered. */
    div[data-testid="stHorizontalBlock"]:has(.auth-brand) > div[data-testid="column"]:nth-of-type(1),
    div[data-testid="stHorizontalBlock"]:has(.auth-brand) > div[data-testid="column"]:nth-of-type(3) {
        display: none !important;
    }

    /* The middle column from st.columns([1.4, 1.3, 1.4]) is the auth card. */
    div[data-testid="column"]:has(.auth-brand) {
        position: relative;
        z-index: 1;
        overflow: hidden;
        flex: 0 0 min(560px, calc(100% - 1rem)) !important;
        width: min(560px, calc(100% - 1rem)) !important;
        max-width: 560px !important;
        margin: clamp(1.5rem, 4vh, 3.25rem) auto 2rem !important;
        padding: 2.25rem 2.25rem 1.75rem !important;
        background: linear-gradient(160deg, rgba(21, 31, 49, 0.66), rgba(7, 12, 22, 0.80)) !important;
        border: 1px solid var(--auth-glass) !important;
        border-radius: var(--auth-radius) !important;
        box-shadow:
            0 30px 80px rgba(0, 0, 0, 0.58),
            0 0 85px rgba(46, 160, 67, 0.28),
            inset 0 1px 0 rgba(255, 255, 255, 0.10) !important;
        -webkit-backdrop-filter: blur(26px) saturate(150%) !important;
        backdrop-filter: blur(26px) saturate(150%) !important;
        animation: authRise 0.45s ease both;
    }
    div[data-testid="column"]:has(.auth-brand)::before {
        content: "";
        position: absolute;
        inset: 0 0 auto 0;
        height: 3px;
        background: linear-gradient(90deg, transparent, #2EA043, #60A5FA, transparent);
        opacity: 0.9;
    }

    /* Branded logo area + hierarchy. */
    .auth-brand {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.65rem;
        margin-bottom: 1.1rem;
    }
    .auth-brand-mark {
        width: 84px;
        height: 84px;
        border-radius: 24px;
        display: grid;
        place-items: center;
        background: linear-gradient(145deg, #EAFBF0 0%, #BFF0CE 100%);
        border: 1px solid rgba(126, 226, 168, 0.55);
        box-shadow: 0 16px 44px rgba(46, 160, 67, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.9);
    }
    .auth-brand-mark img {
        width: 64px;
        height: 64px;
        object-fit: contain;
        display: block;
    }
    .auth-brand-kicker {
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: #7EE2A8;
    }
    .auth-title {
        text-align: center !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 2.15rem !important;
        line-height: 1.12 !important;
        font-weight: 800 !important;
        letter-spacing: -0.035em !important;
        color: var(--auth-text) !important;
        margin: 0 0 0.5rem !important;
    }
    .auth-subtitle {
        text-align: center !important;
        font-size: 0.95rem !important;
        line-height: 1.55 !important;
        color: var(--auth-muted) !important;
        margin: 0 0 1.4rem !important;
    }
    .auth-view-title {
        text-align: center !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 1.15rem !important;
        font-weight: 700 !important;
        color: var(--auth-text) !important;
        margin: 0 0 1rem !important;
    }

    /* Invisible markers let the CSS target the Google button and recovery row. */
    .auth-google-slot, .auth-recovery-slot {
        display: none !important;
    }
    div[data-testid="stVerticalBlockElement"]:has(.auth-google-slot) + div[data-testid="stVerticalBlockElement"] button {
        width: 100% !important;
        min-height: 52px !important;
        color: #F8FAFC !important;
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.02)) !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        border-radius: 14px !important;
        font-size: 0.95rem !important;
        font-weight: 700 !important;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
        transition: background-color 0.18s ease, border-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease !important;
    }
    @media (hover: hover) {
        div[data-testid="stVerticalBlockElement"]:has(.auth-google-slot) + div[data-testid="stVerticalBlockElement"] button:hover {
            transform: translateY(-1px) !important;
            color: #FFFFFF !important;
            background: rgba(46, 160, 67, 0.12) !important;
            border-color: rgba(126, 226, 168, 0.5) !important;
            box-shadow: 0 12px 28px rgba(0, 0, 0, 0.3), 0 0 20px rgba(46, 160, 67, 0.16) !important;
        }
    }

    .auth-divider {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin: 1.1rem 0;
        color: #64748B;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.22em;
        text-transform: uppercase;
    }
    .auth-divider span {
        padding: 0 0.25rem;
    }
    .auth-divider::before,
    .auth-divider::after {
        content: "";
        height: 1px;
        flex: 1;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.18), transparent);
    }

    /* Pill tabs. */
    .stTabs [data-baseweb="tab-list"] {
        width: 100% !important;
        display: flex !important;
        gap: 0.3rem !important;
        padding: 0.3rem !important;
        background: rgba(8, 13, 23, 0.72) !important;
        border: 1px solid var(--auth-glass) !important;
        border-radius: 999px !important;
    }
    .stTabs button[data-baseweb="tab"] {
        flex: 1 1 50% !important;
        border-radius: 999px !important;
        padding: 0.65rem 1rem !important;
        font-size: 0.9rem !important;
        font-weight: 700 !important;
        color: var(--auth-muted) !important;
        background: rgba(148, 163, 184, 0.06) !important;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
        transition: background-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease !important;
    }
    @media (hover: hover) {
        .stTabs button[data-baseweb="tab"]:hover {
            color: #E2E8F0 !important;
            background: rgba(148, 163, 184, 0.12) !important;
        }
    }
    .stTabs button[data-baseweb="tab"][aria-selected="true"] {
        color: #FFFFFF !important;
        background: linear-gradient(135deg, #2EA043 0%, #10B981 100%) !important;
        box-shadow: 0 8px 22px rgba(46, 160, 67, 0.3) !important;
    }
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] {
        display: none !important;
    }

    /* Forms and inputs. */
    div[data-testid="stForm"] {
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    div[data-testid="column"]:has(.auth-brand) .stTextInput {
        margin-bottom: 0.15rem !important;
    }
    div[data-testid="column"]:has(.auth-brand) .stTextInput label p {
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        color: #CBD5E1 !important;
        letter-spacing: 0.01em !important;
    }
    div[data-testid="column"]:has(.auth-brand) .stTextInput input {
        font-size: 0.95rem !important;
        min-height: 50px !important;
        padding: 0.85rem 1rem 0.85rem 2.8rem !important;
        border-radius: 14px !important;
        background-color: rgba(4, 9, 18, 0.68) !important;
        border: 1px solid rgba(255, 255, 255, 0.10) !important;
        color: #F1F5F9 !important;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
        background-repeat: no-repeat !important;
        background-position: 14px center !important;
        background-size: 18px 18px !important;
        transition: border-color 0.16s ease, box-shadow 0.16s ease, background-color 0.16s ease !important;
    }
    div[data-testid="column"]:has(.auth-brand) .stTextInput input::placeholder {
        color: #64748B !important;
    }
    div[data-testid="column"]:has(.auth-brand) .stTextInput input[placeholder="you@example.com"] {
        background-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="%2394A3B8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 6l10 7 10-7"/></svg>') !important;
    }
    div[data-testid="column"]:has(.auth-brand) .stTextInput input[placeholder="Jane Doe"] {
        background-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="%2394A3B8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/></svg>') !important;
    }
    div[data-testid="column"]:has(.auth-brand) .stTextInput input[placeholder="••••••••"] {
        background-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="%2394A3B8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>') !important;
    }
    div[data-testid="column"]:has(.auth-brand) .stTextInput input:focus {
        outline: none !important;
        border-color: var(--auth-green) !important;
        background-color: rgba(4, 9, 18, 0.9) !important;
        box-shadow: 0 0 0 4px rgba(46, 160, 67, 0.20), 0 0 26px rgba(46, 160, 67, 0.16) !important;
    }

    /* Primary action. */
    div.stButton > button[kind="primary"],
    html body button[kind="primary"],
    html body .stFormSubmitButton button {
        background: linear-gradient(135deg, #2EA043 0%, #10B981 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 14px !important;
        font-size: 0.95rem !important;
        font-weight: 700 !important;
        padding: 0.85rem 1.1rem !important;
        width: 100% !important;
        min-height: 52px !important;
        box-shadow: 0 12px 28px rgba(46, 160, 67, 0.28), 0 0 20px rgba(46, 160, 67, 0.16) !important;
        transition: transform 0.18s ease, box-shadow 0.18s ease !important;
    }
    @media (hover: hover) {
        div.stButton > button[kind="primary"]:hover,
        html body button[kind="primary"]:hover,
        html body .stFormSubmitButton button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 16px 34px rgba(46, 160, 67, 0.36), 0 0 26px rgba(46, 160, 67, 0.22) !important;
        }
    }
    div.stButton > button[kind="primary"]:active,
    html body button[kind="primary"]:active,
    html body .stFormSubmitButton button:active {
        transform: translateY(0) !important;
    }

    /* Secondary actions (Google fallback + recovery links). */
    div[data-testid="column"]:has(.auth-brand) button[kind="secondary"],
    div[data-testid="column"]:has(.auth-brand) button:not([kind="primary"]) {
        color: #A5B4C8 !important;
        background: rgba(255, 255, 255, 0.04) !important;
        border: 1px solid rgba(255, 255, 255, 0.10) !important;
        border-radius: 14px !important;
        padding: 0.65rem 0.9rem !important;
        min-height: 46px !important;
        font-size: 0.86rem !important;
        font-weight: 600 !important;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
        transition: background-color 0.16s ease, border-color 0.16s ease, color 0.16s ease, transform 0.16s ease !important;
    }
    @media (hover: hover) {
        div[data-testid="column"]:has(.auth-brand) button[kind="secondary"]:hover,
        div[data-testid="column"]:has(.auth-brand) button:not([kind="primary"]):hover {
            color: #F8FAFC !important;
            background: rgba(46, 160, 67, 0.12) !important;
            border-color: rgba(126, 226, 168, 0.42) !important;
            text-decoration: none !important;
        }
    }

    /* Forgot Password / Reset Password: modern link pills, left + right. */
    div[data-testid="stVerticalBlockElement"]:has(.auth-recovery-slot) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] button {
        display: inline-flex !important;
        min-height: 0 !important;
        color: #94A3B8 !important;
        background: transparent !important;
        border: none !important;
        border-radius: 999px !important;
        padding: 0.35rem 0.25rem !important;
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        box-shadow: none !important;
    }
    @media (hover: hover) {
        div[data-testid="stVerticalBlockElement"]:has(.auth-recovery-slot) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] button:hover {
            color: #7EE2A8 !important;
            background: transparent !important;
            border: none !important;
            text-decoration: underline !important;
            text-underline-offset: 4px !important;
        }
    }
    div[data-testid="stVerticalBlockElement"]:has(.auth-recovery-slot) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-of-type(2) {
        text-align: right !important;
    }
    div[data-testid="stVerticalBlockElement"]:has(.auth-recovery-slot) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-of-type(2) button {
        margin-left: auto !important;
    }
    /* Fallback alignment if the marker adjacency changes across Streamlit versions. */
    div[data-testid="column"]:has(.auth-brand) div[data-testid="column"]:nth-of-type(2) {
        text-align: right !important;
    }
    div[data-testid="column"]:has(.auth-brand) div[data-testid="column"]:nth-of-type(2) button {
        margin-left: auto !important;
    }

    .stAlert, .stAlert p {
        font-size: 0.85rem !important;
        border-radius: 12px !important;
    }

    /* Three compact feature badges. */
    .auth-features {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 0.5rem;
        margin-top: 1.5rem;
        padding-top: 1.15rem;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
    }
    .auth-feature {
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: center;
        gap: 0.4rem;
        padding: 0.55rem 0.45rem;
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.07);
        animation: authFade 0.5s ease both;
    }
    .auth-feature:nth-child(2) { animation-delay: 0.06s; }
    .auth-feature:nth-child(3) { animation-delay: 0.12s; }
    .feature-icon {
        width: 22px;
        height: 22px;
        flex: 0 0 22px;
        border-radius: 7px;
        display: grid;
        place-items: center;
        background: rgba(46, 160, 67, 0.16);
        color: #7EE2A8;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .feature-title {
        font-size: 0.68rem;
        font-weight: 700;
        line-height: 1.2;
        color: #E2E8F0;
    }

    @keyframes authRise {
        from { opacity: 0; transform: translateY(14px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @keyframes authFade {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @media (max-width: 900px) {
        div[data-testid="column"]:has(.auth-brand) {
            flex: 0 0 min(560px, calc(100% - 1rem)) !important;
            width: min(560px, calc(100% - 1rem)) !important;
        }
    }
    /* Mobile GPUs: solid surface instead of an expensive backdrop blur. */
    @media (max-width: 768px) {
        div[data-testid="column"]:has(.auth-brand) {
            -webkit-backdrop-filter: none !important;
            backdrop-filter: none !important;
            background: rgba(9, 14, 24, 0.96) !important;
        }
    }
    @media (max-width: 600px) {
        div[data-testid="column"]:has(.auth-brand) {
            padding: 1.65rem 1.15rem 1.3rem !important;
            border-radius: 20px !important;
            margin: 1rem auto !important;
        }
        .auth-title { font-size: 1.75rem !important; }
        .auth-subtitle { font-size: 0.86rem !important; }
        .auth-brand-mark { width: 68px; height: 68px; border-radius: 20px; }
        .auth-brand-mark img { width: 52px; height: 52px; }
        .stTabs button[data-baseweb="tab"] { font-size: 0.82rem !important; padding: 0.55rem 0.6rem !important; }
        .auth-features { grid-template-columns: 1fr !important; }
        .auth-feature { justify-content: flex-start; }
    }
    @media (prefers-reduced-motion: reduce) {
        div[data-testid="column"]:has(.auth-brand),
        .auth-feature {
            animation: none !important;
        }
        div[data-testid="column"]:has(.auth-brand) * {
            transition-duration: 0.01ms !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    # One card: every element below is inside card_col.
    _, card_col, _ = st.columns([1.4, 1.3, 1.4])

    with card_col:
        st.markdown(f"""
        <div class="auth-brand">
            <span class="auth-brand-mark"><img src="{LOGO_SRC}" alt="MacroMatch logo"></span>
            <span class="auth-brand-kicker">Smart nutrition, everywhere</span>
        </div>
        <div class="auth-title">Welcome to MacroMatch</div>
        <div class="auth-subtitle">AI-powered local macro swaps &amp; nutrition tracking</div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="auth-google-slot"></div>', unsafe_allow_html=True)
        if st.button(
            "Continue with Google", key="google_signin", use_container_width=True
        ):
            _begin_google_sign_in()
        st.markdown(
            '<div class="auth-divider"><span>OR</span></div>',
            unsafe_allow_html=True,
        )

        tab_signin, tab_signup = st.tabs(["Sign In", "Sign Up"])

        # ════════════════════════════════════════════════════════════
        # SIGN IN TAB — hosts signin / forgot / reset views
        # ════════════════════════════════════════════════════════════
        with tab_signin:

            # ─────────────── VIEW: signin ───────────────
            if st.session_state.auth_view == "signin":
                with st.form("signin_form", clear_on_submit=True):
                    email = st.text_input("Email", placeholder="you@example.com")
                    password = st.text_input(
                        "Password", type="password", placeholder="••••••••"
                    )
                    signin_btn = st.form_submit_button(
                        "Sign In", type="primary", use_container_width=True
                    )

                if signin_btn:
                    if not email or not password:
                        st.error("Please enter both email and password.")
                    else:
                        with st.spinner("Signing in…"):
                            try:
                                response = supabase.auth.sign_in_with_password(
                                    {"email": email, "password": password}
                                )
                                if response.user:
                                    session = response.session
                                    st.session_state["supabase_user"] = response.user
                                    st.session_state["supabase_access_token"] = (
                                        session.access_token if session else None
                                    )
                                    st.session_state["supabase_refresh_token"] = (
                                        session.refresh_token if session else None
                                    )
                                    st.session_state["supabase_user_name"] = (
                                        fetch_profile_name(
                                            response.user.id,
                                            response.user.email or "",
                                        )
                                    )
                                    st.session_state["supabase_recovery_mode"] = False
                                    st.success("✅ Signed in successfully!")
                                    st.rerun()
                                else:
                                    st.error(
                                        "❌ Sign in failed. Please check your credentials."
                                    )
                            except Exception as exc:
                                st.error(f"❌ Sign in error: {exc}")

                # Both links live INSIDE the card, directly below the form.
                st.markdown(
                    '<div class="auth-recovery-slot"></div>',
                    unsafe_allow_html=True,
                )
                col1, col2 = st.columns(2, gap="small")
                with col1:
                    if st.button("Forgot Password", key="forgot_link"):
                        st.session_state.auth_view = "forgot"
                        st.rerun()
                with col2:
                    if st.button("Reset Password", key="reset_link"):
                        st.session_state.auth_view = "reset"
                        st.rerun()

            # ─────────────── VIEW: forgot ───────────────
            elif st.session_state.auth_view == "forgot":
                st.markdown(
                    '<div class="auth-view-title">Forgot Password</div>',
                    unsafe_allow_html=True,
                )
                with st.form("forgot_form"):
                    forgot_email = st.text_input(
                        "Email", placeholder="you@example.com", key="forgot_email"
                    )
                    send_link = st.form_submit_button(
                        "Send Reset Link", type="primary", use_container_width=True
                    )

                if send_link:
                    if not forgot_email:
                        st.error("Please enter your email address.")
                    elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", forgot_email or ""):
                        st.error("Please enter a valid email address.")
                    else:
                        app_url = _app_url()
                        if not app_url:
                            st.error(
                                "Error: APP_URL is not configured. Set APP_URL "
                                "(or SUPABASE_REDIRECT_URL) in Streamlit secrets "
                                "or environment variables."
                            )
                        else:
                            with st.spinner("Sending reset link…"):
                                try:
                                    result = supabase.auth.reset_password_for_email(
                                        forgot_email, {"redirect_to": app_url}
                                    )
                                    if getattr(result, "error", None):
                                        raise RuntimeError(str(result.error))
                                    st.success(
                                        "If an account exists for this email, a reset "
                                        "link has been sent."
                                    )
                                except Exception as e:
                                    st.error(f"Error: {e}")

                if st.button("← Back to Sign in", key="back_from_forgot"):
                    st.session_state.auth_view = "signin"
                    st.rerun()

            # ─────────────── VIEW: reset ───────────────
            elif st.session_state.auth_view == "reset":
                st.markdown(
                    '<div class="auth-view-title">Reset Password</div>',
                    unsafe_allow_html=True,
                )
                if st.session_state.get("supabase_recovery_mode", False):
                    st.info(
                        "Recovery session detected. Confirm your identity with "
                        "your current password, then choose a new one."
                    )
                with st.form("reset_form"):
                    reset_email = st.text_input(
                        "Email", placeholder="you@example.com", key="reset_email"
                    )
                    current_pw = st.text_input(
                        "Current Password",
                        type="password",
                        placeholder="••••••••",
                        key="current_pw",
                    )
                    new_pw = st.text_input(
                        "New Password",
                        type="password",
                        placeholder="••••••••",
                        key="new_pw",
                    )
                    update_btn = st.form_submit_button(
                        "Update Password", type="primary", use_container_width=True
                    )

                if update_btn:
                    if not reset_email or not current_pw or not new_pw:
                        st.error("Please fill in all fields.")
                    elif len(new_pw) < 6:
                        st.error("New password must be at least 6 characters.")
                    else:
                        with st.spinner("Updating password…"):
                            try:
                                # Verify identity first, then attach the fresh
                                # session so update_user() writes to Supabase.
                                sign_in_response = supabase.auth.sign_in_with_password(
                                    {
                                        "email": reset_email,
                                        "password": current_pw,
                                    }
                                )
                                signed_in_user = getattr(sign_in_response, "user", None)
                                if not signed_in_user:
                                    raise RuntimeError(
                                        "Sign-in verification did not return a user."
                                    )

                                session = getattr(sign_in_response, "session", None)
                                if (
                                    session
                                    and session.access_token
                                    and session.refresh_token
                                ):
                                    st.session_state["supabase_access_token"] = (
                                        session.access_token
                                    )
                                    st.session_state["supabase_refresh_token"] = (
                                        session.refresh_token
                                    )
                                    supabase.auth.set_session(
                                        session.access_token, session.refresh_token
                                    )

                                update_response = supabase.auth.update_user(
                                    {"password": new_pw}
                                )
                                if getattr(update_response, "error", None):
                                    raise RuntimeError(str(update_response.error))

                                st.session_state["supabase_user"] = signed_in_user
                                st.session_state["supabase_recovery_mode"] = False
                                st.session_state.auth_view = "signin"
                                st.success("Password updated successfully.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

                if st.button("← Back to Sign in", key="back_from_reset"):
                    st.session_state.auth_view = "signin"
                    st.rerun()

        # ════════════════════════════════════════════════════════════
        # SIGN UP TAB — backend logic unchanged
        # ════════════════════════════════════════════════════════════
        with tab_signup:
            with st.form("signup_form"):
                new_name = st.text_input("Full name", placeholder="Jane Doe")
                new_email = st.text_input("Email", placeholder="you@example.com")
                new_password = st.text_input(
                    "Password",
                    type="password",
                    placeholder="••••••••",
                    help="At least 6 characters",
                )
                confirm_password = st.text_input(
                    "Confirm password", type="password", placeholder="••••••••"
                )
                create_btn = st.form_submit_button(
                    "Create account", type="primary", use_container_width=True
                )

            if create_btn:
                problems = []
                if not new_name or not new_email or not new_password or not confirm_password:
                    problems.append("Please fill in every field.")
                elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email or ""):
                    problems.append("Please enter a valid email address.")
                elif len(new_password or "") < 6:
                    problems.append("Password must be at least 6 characters long.")
                elif new_password != confirm_password:
                    problems.append("Passwords do not match.")

                if problems:
                    for p in problems:
                        st.error(p)
                else:
                    with st.spinner("Creating account…"):
                        try:
                            response = supabase.auth.sign_up(
                                {"email": new_email, "password": new_password}
                            )
                            if response.user:
                                try:
                                    supabase.table("profiles").insert(
                                        {
                                            "id": response.user.id,
                                            "email": new_email,
                                            "name": new_name,
                                        }
                                    ).execute()
                                except Exception as exc:
                                    # Auth account was created successfully; a missing
                                    # profiles table must not block sign-in.
                                    st.warning(
                                        "Account created, but the profile row could not "
                                        "be saved. Have you run the Supabase setup SQL "
                                        f"from DEPLOYMENT.md? ({exc})"
                                    )
                                st.session_state["supabase_user"] = response.user
                                st.session_state["supabase_user_name"] = new_name
                                st.session_state["supabase_recovery_mode"] = False
                                if response.session:
                                    st.session_state["supabase_access_token"] = (
                                        response.session.access_token
                                    )
                                    st.session_state["supabase_refresh_token"] = (
                                        response.session.refresh_token
                                    )
                                st.success("✅ Account created! You are now signed in.")
                                st.rerun()
                            else:
                                st.error(
                                    "❌ Sign up failed. The email may already be registered."
                                )
                        except Exception as exc:
                            st.error(f"❌ Sign up error: {exc}")

        st.markdown("""
        <div class="auth-features">
            <div class="auth-feature">
                <span class="feature-icon">◎</span>
                <span class="feature-title">Track Macros</span>
            </div>
            <div class="auth-feature">
                <span class="feature-icon">✦</span>
                <span class="feature-title">Personalized Nutrition</span>
            </div>
            <div class="auth-feature">
                <span class="feature-icon">⌁</span>
                <span class="feature-title">AI-Powered Recommendations</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

# Protect the rest of the app: a recovery session must finish the reset form
# before the dashboard is allowed to render.
if show_auth_ui:
    st.stop()

# Install the mobile swipe/guide-select sidebar helpers for the dashboard only.
components.html(_MOBILE_SIDEBAR_TOGGLE_JS, height=0, scrolling=False)


# ─────────────────────────────────────────────
# NEW: Supabase-backed saved matches (replaces local SQLite)
# Each user sees only their own data; stored in Supabase so it persists
# across deployments. RLS (Row Level Security) should be enabled on this
# table so users can only read/write their own rows.
# ─────────────────────────────────────────────
CURRENT_USER_ID = st.session_state["supabase_user"].id
CURRENT_USER_EMAIL = st.session_state["supabase_user"].email or ""


def save_match(user_id, product, city, diet_rules, allergens, priority, alternatives):
    """Insert one row into public.saved_matches.

    Column names/types match the setup SQL in DEPLOYMENT.md:
        user_id       text/uuid   = auth.uid()
        product       text
        city          text
        diet_rules    jsonb       = list[str]
        allergens     jsonb       = list[str]
        priority      text
        alternatives  jsonb       = list[dict]
        created_at    timestamptz
    """
    client = get_authenticated_supabase()
    current_user = _authenticated_user(client)
    if current_user is None:
        st.error("Cannot save: your Supabase session is not active. Please sign in again.")
        return False
    # RLS checks auth.uid() = user_id, so derive the id from the JWT-backed user
    # rather than trusting a value passed in by the caller.
    auth_user_id = str(current_user.id)
    try:
        client.table("saved_matches").insert(
            {
                "user_id": auth_user_id,
                "product": str(product),
                "city": str(city),
                "diet_rules": list(diet_rules or []),
                "allergens": list(allergens or []),
                "priority": str(priority),
                "alternatives": (
                    alternatives if isinstance(alternatives, (list, dict)) else []
                ),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        get_saved_matches.clear()  # sidebar refresh on the automatic button rerun
        return True
    except Exception as e:
        st.error(f"Save failed: {e}")
        return False


@st.cache_data(ttl=60)
def get_saved_matches(user_id):
    """Return this user's rows from public.saved_matches, newest first.

    Cached for 60s; the cache is cleared only on save/delete.
    """
    client = get_authenticated_supabase()
    try:
        result = (
            client.table("saved_matches")
            .select("*")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        st.error(f"Could not load saved matches: {e}")
        return []


# Shared diet label map (defined here so the sidebar can restore saved pills
# before the main-body widgets are created).
DIET_LABELS = {
    "vegetarian": "🌿 Vegetarian",
    "vegan":      "🌱 Vegan",
    "dairy_free": "🥛 Dairy-Free",
    "gluten_free":"🌾 Gluten-Free",
    "keto":       "⚡ Keto",
    "low_sugar":  "🍬 Low-Sugar",
}


def delete_saved_match(match_id):
    """Delete one saved row for the current user; report any failure clearly."""
    client = get_authenticated_supabase()
    current_user = _authenticated_user(client)
    if current_user is None:
        st.error("Cannot delete: your Supabase session is not active. Please sign in again.")
        return False
    try:
        client.table("saved_matches").delete().eq("id", match_id).eq(
            "user_id", str(current_user.id)
        ).execute()
        get_saved_matches.clear()
        return True
    except Exception as e:
        st.error(f"Delete failed: {e}")
        return False


def _delete_saved_match_callback(match_id):
    """Widget callback: delete a row; the fragment redraws on the same click."""
    delete_saved_match(match_id)


def load_saved_match(match):
    """Restore a saved comparison into the widgets and cached results."""
    product = match.get("product", "")
    city = match.get("city", "")
    diets = list(match.get("diet_rules") or [])
    allergens = list(match.get("allergens") or [])
    priority = match.get("priority") or "balanced"

    st.session_state["selected_product"] = product
    st.session_state["selected_city"] = city
    st.session_state["food_search_input"] = product
    st.session_state["city_search_input"] = city
    # A restored match is a programmatic selection, so remount both searchbox
    # widgets with the restored text instead of reusing any half-typed state.
    st.session_state["food_box_ver"] = st.session_state.get("food_box_ver", 0) + 1
    st.session_state["city_box_ver"] = st.session_state.get("city_box_ver", 0) + 1
    # Legacy aliases kept so older saved-state keys stay in sync.
    st.session_state["product_select"] = product
    st.session_state["city_select"] = city
    st.session_state["diet_pills"] = [DIET_LABELS[d] for d in diets if d in DIET_LABELS]
    st.session_state["allergen_select"] = [
        a for a in allergens if a in ALLERGEN_OPTIONS
    ]
    if priority in PRIORITY_KEYS:
        st.session_state["priority_radio"] = priority

    # Replay the saved ranked swaps — no backend call needed.
    st.session_state["match_result_data"] = {
        "product": product,
        "city": city,
        "diet_rules": diets,
        "allergens": allergens,
        "priority": priority,
        "alternatives": match.get("alternatives") or [],
    }
    st.session_state["show_swaps_results"] = True
    st.rerun()


@st.fragment(key="saved_matches")
def render_saved_matches(container):
    """Paint clickable saved-match rows with an optional delete button."""
    matches = get_saved_matches(CURRENT_USER_ID)
    if not matches:
        container.caption("No saved matches yet — save a result below.")
        return

    for match in matches:
        created = str(match.get("created_at", ""))[:10]
        label = (
            f"{match.get('product', 'Saved match')} → {match.get('city', '—')}\n"
            f"Priority: {match.get('priority', '—')} · {created}"
        )
        col1, col2 = st.columns([4, 1])
        with col1:
            if st.button(
                label,
                key=f"load_match_{match['id']}",
                use_container_width=True,
            ):
                load_saved_match(match)
        with col2:
            st.button(
                "🗑️",
                key=f"delete_match_{match['id']}",
                on_click=_delete_saved_match_callback,
                args=(match["id"],),
                use_container_width=True,
                help="Delete this saved match",
            )


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

DEFAULT_API_BASE = "http://127.0.0.1:8000"

def _resolve_api_base() -> str:
    """
    Resolve the backend URL from, in order:
      1. the MACROMATCH_API_URL environment variable (local dev, containers),
      2. the Streamlit secret of the same name (Community Cloud),
      3. the local development default.
    """
    base = os.environ.get("MACROMATCH_API_URL", "").strip()
    if not base:
        try:
            base = str(st.secrets.get("MACROMATCH_API_URL", "")).strip()
        except Exception:
            # No secrets.toml configured — expected during local development.
            base = ""
    return (base or DEFAULT_API_BASE).rstrip("/")


API_BASE         = _resolve_api_base()
GET_TIMEOUT      = 90   # seconds; Render's free tier can need 30-60 s to wake from sleep
POST_TIMEOUT     = 90   # seconds; includes the optional Claude call
CITIES_FALLBACK   = ["Delhi", "Mumbai", "Bangalore", "Dehradun", "Pune"]

# Touch-friendly quick picks. Display labels are mapped back to the exact
# dataset/API names so the matching backend keeps receiving valid values.
POPULAR_PRODUCTS = [
    "Almond Butter", "Peanut Butter", "Paneer", "Greek Yogurt", "Oats", "Whey Protein",
]
POPULAR_CITIES = [
    "Delhi", "Mumbai", "Bengaluru", "Greater Noida", "Hyderabad", "Pune",
]
PRODUCT_DISPLAY_ALIASES = {
    "Oats": "Rolled Oats",
    "Whey Protein": "Whey Protein Powder",
}
CITY_DISPLAY_ALIASES = {
    "Bengaluru": "Bangalore",
    "Greater Noida": "Delhi",
}

DIET_OPTIONS    = ["vegetarian", "vegan", "dairy_free", "gluten_free", "keto", "low_sugar"]
ALLERGEN_OPTIONS= ["soy", "nuts", "dairy"]
MACRO_COLS      = ["protein", "carbs", "fat", "fiber", "calories"]

PRODUCT_IMAGE_DIR = Path(__file__).resolve().parent.parent / "assets" / "products"

# Single source of truth for the touch UI. These keys are never cleared by a
# filter change, so a mobile user's food/city survives quick reruns.
if "selected_product" not in st.session_state:
    st.session_state["selected_product"] = "Almond Butter"
if "selected_city" not in st.session_state:
    st.session_state["selected_city"] = "Delhi"
# Searchbox text is independent from the active selection. Keeping it empty by
# default lets the placeholder show and lets the user backspace freely; the
# "Selected food/city" badges below each box always show the active choice.
if "food_search_input" not in st.session_state:
    st.session_state["food_search_input"] = ""
if "city_search_input" not in st.session_state:
    st.session_state["city_search_input"] = ""
# Bumped only by explicit selections (pills, guide, saved match) to remount a
# searchbox. Typing never changes these, so the input cannot snap back.
if "food_box_ver" not in st.session_state:
    st.session_state["food_box_ver"] = 0
if "city_box_ver" not in st.session_state:
    st.session_state["city_box_ver"] = 0
# Changing these label suffixes remounts the browse expanders, defeating the
# browser's cached open state so every pick reliably closes the list.
st.session_state.setdefault("food_browse_ver", 0)
st.session_state.setdefault("city_browse_ver", 0)
# Home shows the regular-food spotlight; Find Alternatives switches to the
# ranked swaps view. This flag is the single source of truth for that switch.
if "show_swaps_results" not in st.session_state:
    st.session_state["show_swaps_results"] = False
if "daily_protein_goal" not in st.session_state:
    st.session_state["daily_protein_goal"] = 120
if "daily_calorie_goal" not in st.session_state:
    st.session_state["daily_calorie_goal"] = 2000
if "default_diet_select" not in st.session_state:
    st.session_state["default_diet_select"] = "None"
if "default_allergens_select" not in st.session_state:
    st.session_state["default_allergens_select"] = []

# Auth has already been enforced above, so it is safe to hydrate the signed-in
# user's saved targets/preferences before any dashboard widgets are created.
if st.session_state.get("supabase_user") is not None:
    _load_user_preferences(st.session_state["supabase_user"])


def _canonical_value(label: str, aliases: dict[str, str]) -> str:
    """Turn a friendly pill label into the exact value the backend expects."""
    return aliases.get(label, label)


def _display_label(value: str, aliases: dict[str, str], options: list[str]) -> str:
    """Pick the pill label for a stored value, preferring the real value itself."""
    if value in options:
        return value
    for label, canonical in aliases.items():
        if canonical == value:
            return label
    return value


def _query_represents_selection(raw_query, selected_value, aliases) -> bool:
    """True when the search box holds the current choice (including aliases)."""
    raw = (raw_query or "").strip()
    if not raw:
        return True
    canonical = aliases.get(raw, aliases.get(raw.title(), raw))
    return canonical.lower() == (selected_value or "").lower()


def _ordered_suggestions(query: str, options) -> list:
    """Prefix matches first, then keyword matches, with no duplicates."""
    q = (query or "").strip().lower()
    if not q:
        return []
    starts = [food for food in options if food.lower().startswith(q)]
    partial = [food for food in options if q in food.lower() and food not in starts]
    return starts + partial


def _ordered_city_suggestions(query: str, options) -> list:
    """City matches, including friendly labels such as Bengaluru."""
    q = (query or "").strip().lower()
    if not q:
        return []
    starts = [city for city in options if city.lower().startswith(q)]
    partial = [city for city in options if q in city.lower() and city not in starts]
    suggestions = starts + partial
    for label, canonical in CITY_DISPLAY_ALIASES.items():
        if canonical not in options or canonical in suggestions:
            continue
        if label.lower().startswith(q):
            suggestions.insert(0, canonical)
        elif q in label.lower():
            suggestions.append(canonical)
    return suggestions


def _suggestion_label(value: str, aliases: dict[str, str], options) -> str:
    """Use the catalogue value when it is real; otherwise a friendly alias."""
    return _display_label(value, aliases, options)


def _apply_default_diet() -> None:
    """Mirror the sidebar default into the main diet pills widget key."""
    choice = st.session_state.get("default_diet_select", "None")
    st.session_state["diet_pills"] = [] if choice == "None" else [choice]


def _apply_default_allergens() -> None:
    """Mirror the sidebar defaults into the main allergen multiselect key."""
    st.session_state["allergen_select"] = list(
        st.session_state.get("default_allergens_select") or []
    )


def _save_user_metadata(updates: dict, success_message: str) -> None:
    """Merge selected keys into the user's Supabase Auth user_metadata."""
    client = get_authenticated_supabase()
    current = getattr(st.session_state.get("supabase_user"), "user_metadata", None) or {}
    metadata = dict(current)
    metadata.update(updates)
    try:
        response = client.auth.update_user({"data": metadata})
        user = getattr(response, "user", None)
        if user is not None:
            st.session_state["supabase_user"] = user
        st.success(success_message)
    except Exception as exc:
        st.error(f"Could not save your settings: {exc}")


def _protein_goal_badge(protein_per_100g) -> str:
    """Small badge showing daily protein coverage for a 100 g portion."""
    try:
        protein = float(protein_per_100g)
        goal = float(st.session_state.get("daily_protein_goal", 120))
    except (TypeError, ValueError):
        return ""
    if goal <= 0:
        return ""
    percent = int(round(protein / goal * 100))
    return f'<span class="macro-goal-badge">Covers {percent}% of daily protein</span>'


def _reset_swaps_view() -> None:
    """Return to the home view and drop any cached ranked results."""
    st.session_state["show_swaps_results"] = False
    st.session_state.pop("match_result_data", None)


def _sync_food_selection(canonical: str, search_value: str | None = None) -> None:
    """Keep the selected food and its visible search text in lockstep."""
    st.session_state["selected_product"] = canonical
    st.session_state["product_select"] = canonical
    st.session_state["food_search_input"] = search_value or canonical


def _sync_city_selection(canonical: str, search_value: str | None = None) -> None:
    """Keep the selected city and its visible search text in lockstep."""
    st.session_state["selected_city"] = canonical
    st.session_state["city_select"] = canonical
    st.session_state["city_search_input"] = search_value or canonical


def select_food_callback(widget_key: str) -> None:
    """Pill callback: sync food state before the widget's own single rerun."""
    picked = st.session_state.get(widget_key)
    if not picked:
        return
    # A fresh expander label remounts the list, so even re-picking the same food
    # collapses it instead of reusing Streamlit's cached browser open state.
    st.session_state.food_browse_ver += 1
    display_label = str(picked)
    canonical = _canonical_value(display_label, PRODUCT_DISPLAY_ALIASES)
    selection_changed = canonical != st.session_state.get("selected_product")
    was_showing_results = st.session_state.get("show_swaps_results", False)
    # The canonical catalogue name drives the selected badge and the visible
    # search text, so they can never disagree after a pill tap.
    _sync_food_selection(canonical)
    st.session_state["food_box_ver"] = st.session_state.get("food_box_ver", 0) + 1
    if selection_changed:
        _reset_swaps_view()
        # The outer results view needs a full pass; home taps stay fragment-only.
        if was_showing_results:
            st.rerun()


def select_food_value_callback(product: str) -> None:
    """Sidebar guide `on_click` callback for an explicitly named product."""
    if not product:
        return
    was_showing_results = st.session_state.get("show_swaps_results", False)
    _sync_food_selection(product, product)
    _reset_swaps_view()
    st.session_state["food_box_ver"] = st.session_state.get("food_box_ver", 0) + 1
    if was_showing_results:
        st.rerun()


def select_city_callback(widget_key: str) -> None:
    """Pill callback: sync city state before the widget's own single rerun."""
    picked = st.session_state.get(widget_key)
    if not picked:
        return
    # A fresh expander label remounts the list, so every city pick closes it.
    st.session_state.city_browse_ver += 1
    display_label = str(picked)
    canonical = _canonical_value(display_label, CITY_DISPLAY_ALIASES)
    _sync_city_selection(canonical)
    st.session_state["city_box_ver"] = st.session_state.get("city_box_ver", 0) + 1


PRODUCT_EMOJI = {
    "Whey Protein Powder": "🥤",
    "Pea Protein Powder": "🥤",
    "Soya Chunks (TVP)": "🫘",
    "Tofu (Firm)": "🧊",
    "Tempeh": "🫘",
    "Edamame": "🫛",
    "Paneer": "🧀",
    "Greek Yogurt": "🥣",
    "Cottage Cheese (Low Fat)": "🧀",
    "Masoor Dal (Red Lentils)": "🫘",
    "Chana Dal": "🫘",
    "Moong Dal": "🫘",
    "Chickpeas (Kabuli Chana)": "🫘",
    "Rajma (Kidney Beans)": "🫘",
    "Rolled Oats": "🌾",
    "Quinoa": "🌾",
    "Brown Rice": "🍚",
    "Peanut Butter": "🥜",
    "Almond Butter": "🥜",
    "Almonds": "🌰",
    "Cashews": "🌰",
    "Walnuts": "🌰",
    "Chia Seeds": "🌱",
    "Flaxseeds": "🌾",
    "Pumpkin Seeds": "🎃",
    "Sunflower Seeds": "🌻",
    "Soy Milk": "🥛",
    "Almond Milk": "🥛",
    "Oat Milk": "🥛",
    "Coconut Milk (Canned)": "🥥",
}


# ─────────────────────────────────────────────────────────────
# How-to-use / serving tips for each product
# ─────────────────────────────────────────────────────────────
PRODUCT_HOW_TO_USE = {
    "Whey Protein Powder": {
        "serving": "1–2 scoops (25–50 g)",
        "tips": [
            "🥤 Post-workout shake: Mix 1 scoop with 200–250 ml cold water or milk.",
            "🫙 Add to Greek yogurt or oatmeal for a protein boost.",
            "🧁 Use in protein pancakes, muffins, or energy balls.",
        ],
        "best_time": "Within 30 min after workout",
    },
    "Pea Protein Powder": {
        "serving": "1–2 scoops (25–40 g)",
        "tips": [
            "🥤 Blend with plant milk, banana, and nut butter for a vegan shake.",
            "🍲 Stir into soups or curries to increase protein without changing taste much.",
            "🧁 Works well in baked goods like protein cookies or bars.",
        ],
        "best_time": "Post-workout or as a meal supplement",
    },
    "Soya Chunks (TVP)": {
        "serving": "30–50 g dry (doubles when soaked)",
        "tips": [
            "💧 Soak in hot water for 15–20 min, then squeeze out water before cooking.",
            "🍛 Use in curries, bhurji, biryani, or pulao.",
            "🥗 Marinate and grill for a high-protein snack.",
        ],
        "best_time": "Lunch or dinner as main protein source",
    },
    "Tofu (Firm)": {
        "serving": "100–150 g per serving",
        "tips": [
            "🔪 Press firmly for 15–20 min to remove extra moisture before cooking.",
            "🍳 Pan-fry or bake at 200°C for 20 min for crispy texture.",
            "🍛 Add to stir-fries, curries, or scramble like eggs with turmeric.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Tempeh": {
        "serving": "80–100 g per serving",
        "tips": [
            "🔪 Slice thin and marinate in soy sauce + garlic for 30 min.",
            "🍳 Stir-fry, bake, or grill until golden brown.",
            "🌯 Use in wraps, sandwiches, or rice bowls.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Edamame": {
        "serving": "1 cup (155 g) shelled",
        "tips": [
            "♨️ Boil in salted water for 5 min or microwave from frozen.",
            "🧂 Sprinkle with sea salt and eat straight from the pod.",
            "🥗 Toss into salads, grain bowls, or fried rice.",
        ],
        "best_time": "Snack or side dish anytime",
    },
    "Paneer": {
        "serving": "80–100 g per serving",
        "tips": [
            "🍳 Cube and sauté in oil until golden, then add to curries.",
            "🔥 Grill as paneer tikka with spices and yogurt marinade.",
            "🥗 Crumble into salads or bhurji with vegetables.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Greek Yogurt": {
        "serving": "150–200 g",
        "tips": [
            "🍓 Top with berries, honey, and granola for a quick breakfast.",
            "🥣 Use as a base for smoothie bowls or dips (like tzatziki).",
            "🍲 Use as a healthy substitute for cream in curries and marinades.",
        ],
        "best_time": "Breakfast or post-workout snack",
    },
    "Cottage Cheese (Low Fat)": {
        "serving": "100–150 g",
        "tips": [
            "🥗 Eat plain with fruit or mix with herbs and salt as a dip.",
            "🥞 Blend into pancake batter or scrambled eggs for added protein.",
            "🫙 Top on toast or crackers for a quick high-protein snack.",
        ],
        "best_time": "Breakfast, snack, or pre-sleep (slow-digesting protein)",
    },
    "Masoor Dal (Red Lentils)": {
        "serving": "50–75 g dry (makes ~1 cup cooked)",
        "tips": [
            "💧 No soaking needed — rinse and cook directly in 2–3x water.",
            "🍲 Cook as simple dal tadka with cumin, turmeric, and tomatoes.",
            "🫙 Make dal soup or add to khichdi for a balanced meal.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Chana Dal": {
        "serving": "50–75 g dry",
        "tips": [
            "💧 Soak 1–2 hours before cooking for faster, creamier results.",
            "🍲 Cook as dal or use in chana dal khichdi with rice.",
            "🥘 Use in stuffed parathas or as a base for snack like dalmoth.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Moong Dal": {
        "serving": "50–75 g dry",
        "tips": [
            "💧 Soak split moong for 30 min; whole moong for 4–6 hours.",
            "🍲 Make classic moong dal, khichdi, or moong dal soup.",
            "🫘 Sprout whole moong for a raw, nutrient-dense salad topping.",
        ],
        "best_time": "Any meal; sprouted as breakfast",
    },
    "Chickpeas (Kabuli Chana)": {
        "serving": "80–100 g cooked (~35 g dry)",
        "tips": [
            "💧 Soak overnight (8–10 hrs) and pressure cook for 2–3 whistles.",
            "🍛 Use in chole curry, chaat, or hummus.",
            "🫙 Roast with spices at 200°C for crispy high-protein snack.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Rajma (Kidney Beans)": {
        "serving": "80–100 g cooked (~40 g dry)",
        "tips": [
            "💧 Must soak 8–12 hours and boil thoroughly — never eat raw.",
            "🍛 Classic rajma chawal: cook in tomato-onion masala.",
            "🌯 Use in burritos, wraps, or bean salads.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Rolled Oats": {
        "serving": "40–50 g dry",
        "tips": [
            "🥣 Overnight oats: Mix with milk/curd and refrigerate overnight.",
            "🍳 Cook with water or milk for 3–5 min; top with fruits and nuts.",
            "🧁 Use in homemade granola bars, protein muffins, or chilla.",
        ],
        "best_time": "Breakfast or pre-workout",
    },
    "Quinoa": {
        "serving": "45–60 g dry (makes ~1 cup cooked)",
        "tips": [
            "💧 Rinse well before cooking to remove bitterness (saponins).",
            "🍚 Cook in 2x water for 15 min; fluff with fork — use like rice.",
            "🥗 Use in grain bowls, stuffed peppers, or quinoa upma.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Brown Rice": {
        "serving": "50–75 g dry (makes ~1 cup cooked)",
        "tips": [
            "💧 Soak 30 min for fluffier texture; cook in 2–2.5x water.",
            "🍚 Use as a base for dal, sabzi, or protein bowls.",
            "🥗 Make brown rice salad with veggies and lemon dressing.",
        ],
        "best_time": "Lunch or dinner",
    },
    "Peanut Butter": {
        "serving": "1–2 tbsp (15–30 g)",
        "tips": [
            "🍞 Spread on whole grain toast with banana slices.",
            "🥤 Blend into smoothies or protein shakes for healthy fats.",
            "🍎 Dip apple, celery, or rice cakes for a balanced snack.",
        ],
        "best_time": "Breakfast or pre-workout snack",
    },
    "Almond Butter": {
        "serving": "1–2 tbsp (15–30 g)",
        "tips": [
            "🍞 Spread on toast, roti, or rice cakes for a nutritious snack.",
            "🥤 Add to smoothies, overnight oats, or protein shakes.",
            "🍎 Pair with fruit slices (apple, banana) for a balanced snack.",
        ],
        "best_time": "Morning snack or pre-workout",
    },
    "Almonds": {
        "serving": "20–30 g (a small handful, ~20 nuts)",
        "tips": [
            "🌰 Eat raw or dry-roasted as a quick snack between meals.",
            "🥣 Chop and sprinkle on oatmeal, yogurt, or salads.",
            "💧 Soak overnight for easier digestion and better nutrient absorption.",
        ],
        "best_time": "Morning (soaked) or mid-day snack",
    },
    "Cashews": {
        "serving": "20–30 g",
        "tips": [
            "🌰 Eat raw as a snack or mix into trail mix.",
            "🫙 Blend soaked cashews with water to make creamy cashew milk/cream.",
            "🍛 Use in curries like paneer makhani or korma for richness.",
        ],
        "best_time": "Snack or as cooking ingredient",
    },
    "Walnuts": {
        "serving": "20–28 g (4–7 halves)",
        "tips": [
            "🌰 Eat raw — best consumed as-is to preserve omega-3 content.",
            "🥗 Chop and add to salads, oatmeal, or baked goods.",
            "💧 Soak overnight to reduce bitterness and improve digestibility.",
        ],
        "best_time": "Morning (empty stomach if soaked) or afternoon snack",
    },
    "Chia Seeds": {
        "serving": "1–2 tbsp (10–20 g)",
        "tips": [
            "💧 Soak in 3x liquid for 15–30 min to form a gel — do not eat dry.",
            "🥣 Make chia pudding with milk/yogurt overnight; top with fruits.",
            "🥤 Add soaked chia to smoothies, juices, or lemonade.",
        ],
        "best_time": "Breakfast or pre-sleep snack",
    },
    "Flaxseeds": {
        "serving": "1–2 tbsp (10–15 g)",
        "tips": [
            "⚠️ Grind before eating — whole seeds pass undigested.",
            "🍞 Add ground flax to roti dough, oatmeal, or smoothies.",
            "🥣 Mix with water (1 tbsp + 3 tbsp water) as an egg replacer.",
        ],
        "best_time": "Morning with breakfast",
    },
    "Pumpkin Seeds": {
        "serving": "20–30 g",
        "tips": [
            "🌰 Eat raw or lightly roasted with a pinch of salt.",
            "🥗 Sprinkle on salads, soups, or yogurt for crunch.",
            "🧁 Add to granola, trail mix, or homemade energy bars.",
        ],
        "best_time": "Snack anytime",
    },
    "Sunflower Seeds": {
        "serving": "20–30 g",
        "tips": [
            "🌻 Eat hulled seeds raw or roasted as a snack.",
            "🥗 Add to salads, stir-fries, or baked goods.",
            "🫙 Blend into sunflower seed butter as a nut-free alternative.",
        ],
        "best_time": "Snack or topping",
    },
    "Soy Milk": {
        "serving": "200–250 ml",
        "tips": [
            "☕ Use as a 1:1 replacement for dairy milk in tea, coffee, or cereal.",
            "🥤 Blend into smoothies or protein shakes.",
            "🍳 Use in cooking — soups, curries, pancake batter.",
        ],
        "best_time": "Anytime — with breakfast or as a snack drink",
    },
    "Almond Milk": {
        "serving": "200–250 ml",
        "tips": [
            "☕ Add to coffee, tea, or pour over cereal and oats.",
            "🥤 Use as a smoothie base instead of dairy milk.",
            "🍳 Use in baking, pancake batter, or creamy soups.",
        ],
        "best_time": "Breakfast or anytime",
    },
    "Oat Milk": {
        "serving": "200–250 ml",
        "tips": [
            "☕ Best for coffee — it froths well and complements mild bitterness.",
            "🥣 Pour over muesli or use in overnight oats.",
            "🍳 Use in cooking and baking as a dairy-milk substitute.",
        ],
        "best_time": "Morning or with meals",
    },
    "Coconut Milk (Canned)": {
        "serving": "50–100 ml (shake/stir before opening)",
        "tips": [
            "🍛 Use full-fat in curries, dals, or rice dishes for creaminess.",
            "🥥 Refrigerate overnight — the cream rises; use cream for desserts.",
            "🥤 Dilute 1:1 with water for a lighter cooking or smoothie base.",
        ],
        "best_time": "With meals; great in post-workout curry bowls",
    },
}

# ─────────────────────────────────────────────────────────────
# Local / regional Indian names for each product
# ─────────────────────────────────────────────────────────────
PRODUCT_LOCAL_NAMES: dict[str, str] = {
    "Whey Protein Powder":       "Whey Protein / व्हे प्रोटीन पाउडर",
    "Pea Protein Powder":        "Matar Protein / मटर प्रोटीन पाउडर",
    "Soya Chunks (TVP)":         "Soya Badi / सोया बड़ी",
    "Tofu (Firm)":               "Tofu / टोफू",
    "Tempeh":                    "Tempeh / टेम्पेह",
    "Edamame":                   "Edamame / हरी सोयाबीन",
    "Paneer":                    "Paneer / पनीर",
    "Greek Yogurt":              "Greek Dahi / ग्रीक दही",
    "Cottage Cheese (Low Fat)":  "Chenna / छेना",
    "Masoor Dal (Red Lentils)":  "Masoor Dal / मसूर दाल",
    "Chana Dal":                 "Chana Dal / चना दाल",
    "Moong Dal":                 "Moong Dal / मूंग दाल",
    "Chickpeas (Kabuli Chana)":  "Kabuli Chana / काबुली चना",
    "Rajma (Kidney Beans)":      "Rajma / राजमा",
    "Rolled Oats":               "Jai / जई (Oats)",
    "Quinoa":                    "Quinoa / क्विनोआ",
    "Brown Rice":                "Bhoora Chawal / भूरे चावल",
    "Peanut Butter":             "Mungfali Makhan / मूंगफली का मक्खन",
    "Almond Butter":             "Badam Makhan / बादाम का मक्खन",
    "Almonds":                   "Badam / बादाम",
    "Cashews":                   "Kaju / काजू",
    "Walnuts":                   "Akhrot / अखरोट",
    "Chia Seeds":                "Chia Beej / चिया बीज",
    "Flaxseeds":                 "Alsi / अलसी",
    "Pumpkin Seeds":             "Kaddu ke Beej / कद्दू के बीज",
    "Sunflower Seeds":           "Surajmukhi ke Beej / सूरजमुखी के बीज",
    "Soy Milk":                  "Soya Doodh / सोया दूध",
    "Almond Milk":               "Badam Doodh / बादाम दूध",
    "Oat Milk":                  "Oat Doodh / ओट दूध",
    "Coconut Milk (Canned)":     "Nariyal ka Doodh / नारियल का दूध",
}

# ─────────────────────────────────────────────────────────────
# Safety / Consumption Precautions
# ─────────────────────────────────────────────────────────────
PRODUCT_CAUTIONS: dict[str, str | None] = {
    "Whey Protein Powder":       "Contains dairy (lactose) — not suitable for lactose-intolerant individuals. Excessive intake may stress kidneys; stay within recommended dosage.",
    "Pea Protein Powder":        None,
    "Soya Chunks (TVP)":         "Contains soy — avoid with soy allergies. Those with thyroid disorders should consult a doctor before high intake.",
    "Tofu (Firm)":               "Contains soy — avoid with soy allergies. Those with thyroid disorders should consult a doctor before high intake.",
    "Tempeh":                    "Contains soy — avoid with soy allergies. Those with thyroid disorders should consult a doctor before high intake.",
    "Edamame":                   "Contains soy — avoid with soy allergies. Those with thyroid disorders should consult a doctor before high intake.",
    "Paneer":                    "Contains dairy — avoid if lactose intolerant or dairy-allergic.",
    "Greek Yogurt":              "Contains dairy — avoid if lactose intolerant or dairy-allergic.",
    "Cottage Cheese (Low Fat)":  "Contains dairy — avoid if lactose intolerant or dairy-allergic.",
    "Masoor Dal (Red Lentils)":  "High in FODMAPs — may cause bloating in those with IBS. Soak and cook thoroughly for better digestibility.",
    "Chana Dal":                 "High in FODMAPs — may cause bloating in those with IBS. Soak and cook thoroughly for better digestibility.",
    "Moong Dal":                 "High in FODMAPs — may cause bloating in those with IBS. Soak and cook thoroughly for better digestibility.",
    "Chickpeas (Kabuli Chana)":  "High in FODMAPs — may cause bloating in those with IBS. Soak and cook thoroughly for better digestibility.",
    "Rajma (Kidney Beans)":      "Raw or undercooked kidney beans contain toxic lectins. Always soak 8–12 hours and boil thoroughly — never eat raw.",
    "Rolled Oats":               "Contains oats — may not be suitable for those with severe gluten intolerance unless certified gluten-free.",
    "Quinoa":                    "Rinse thoroughly to remove saponins which can irritate digestion. Those with oxalate kidney stones should moderate intake.",
    "Brown Rice":                None,
    "Peanut Butter":             "Contains peanuts — avoid with peanut or groundnut allergy.",
    "Almond Butter":             "Contains tree nuts — avoid if you have a tree-nut allergy.",
    "Almonds":                   "Contains tree nuts — avoid if you have a tree-nut allergy.",
    "Cashews":                   "Contains tree nuts — avoid if you have a tree-nut allergy. High in oxalates — moderate intake if prone to kidney stones.",
    "Walnuts":                   "Contains tree nuts — avoid if you have a tree-nut allergy.",
    "Chia Seeds":                "Always soak before consuming — dry chia seeds can swell in the throat. Drink plenty of water throughout the day.",
    "Flaxseeds":                 "May interact with blood thinners (warfarin) and blood-pressure medication. Avoid in large amounts during pregnancy.",
    "Pumpkin Seeds":             None,
    "Sunflower Seeds":           None,
    "Soy Milk":                  "Contains soy — avoid with soy allergies. Those with thyroid disorders should consult a doctor before high intake.",
    "Almond Milk":               None,
    "Oat Milk":                  "Made from oats — not suitable for those with severe gluten intolerance or coeliac disease unless certified gluten-free.",
    "Coconut Milk (Canned)":     "High in saturated fat — consume in moderation if managing cholesterol or cardiovascular health.",
}


class BackendUnavailable(Exception):
    """Raised when GET /products cannot reach the API."""


PRIORITY_LABELS = {
    "protein":  "🥩 Protein-first — match protein content most closely",
    "low_carb": "🌿 Low Carb — match carbohydrate content most closely",
    "balanced": "⚖️ Balanced — equal weight across all macros",
}
PRIORITY_KEYS = list(PRIORITY_LABELS.keys())

RANK_COLORS = ["#2EA043", "#60A5FA", "#94A3B8"]   # emerald, blue, slate
RANK_LABELS = ["#1 Best Match", "#2 Runner Up", "#3 Option"]

# ── Canonical serving sizes in grams (used for Per-Serving toggle) ──────────
PRODUCT_SERVING_G: dict[str, int] = {
    "Whey Protein Powder":        25,
    "Pea Protein Powder":         25,
    "Soya Chunks (TVP)":          30,
    "Tofu (Firm)":               100,
    "Tempeh":                     80,
    "Edamame":                   155,
    "Paneer":                     80,
    "Greek Yogurt":              150,
    "Cottage Cheese (Low Fat)":  100,
    "Masoor Dal (Red Lentils)":   50,
    "Chana Dal":                  50,
    "Moong Dal":                  50,
    "Chickpeas (Kabuli Chana)":   80,
    "Rajma (Kidney Beans)":       80,
    "Rolled Oats":                40,
    "Quinoa":                     45,
    "Brown Rice":                 50,
    "Peanut Butter":              15,
    "Almond Butter":              15,
    "Almonds":                    20,
    "Cashews":                    20,
    "Walnuts":                    20,
    "Chia Seeds":                 10,
    "Flaxseeds":                  10,
    "Pumpkin Seeds":              20,
    "Sunflower Seeds":            20,
    "Soy Milk":                  200,
    "Almond Milk":               200,
    "Oat Milk":                  200,
    "Coconut Milk (Canned)":      50,
}

# ─────────────────────────────────────────────
# Custom CSS — sleek, modern, consumer-grade dark-mode SaaS look
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* ── Design tokens ── */
:root {
    --bg-obsidian: #0B0F19;
    --bg-sidebar: #111827;
    --bg-card: #151C2C;
    --border: rgba(255, 255, 255, 0.08);
    --border-hover: rgba(52, 211, 153, 0.35);
    --accent-mint: #34D399;
    --accent-mint-text: #0B0F19;
    --text-heading: #F8FAFC;
    --text-body: #E2E8F0;
    --text-muted: #94A3B8;
    --radius: 14px;
}

/* ── Google Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');

/* ── Hide Streamlit chrome and flatten the header ──────────────────────
   Never hide the sidebar toggle controls. */
[data-testid="stToolbarActions"], #MainMenu, footer,
.stDeployButton, [data-testid="stAppDeployButton"], [data-testid="manage-app-button"] {
    display: none !important;
}

/* Hide the bottom-right Streamlit viewer badge and creator profile avatar for all visitors */
[data-testid="stStatusWidget"],
[data-testid="manage-app-button"],
.stDeployButton,
[class*="viewerBadge"],
[class*="StatusWidget"],
div[class*="_container_"][class*="_viewerBadge_"],
a[href*="streamlit.io/cloud"] {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
}

header[data-testid="stHeader"] { background: transparent !important; }
/* Keep the control interactive, then apply the custom "☰ Menu" styling. */
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important;
    width: auto !important;
    min-width: 0 !important;
    height: auto !important;
}
/* Streamlit may render a fixed-size icon button: let it grow for the label. */
button[data-testid="stSidebarCollapsedControl"],
button[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: auto !important;
    height: auto !important;
    min-width: 0 !important;
}
/* Only a nested button loses its own box; the outer control keeps the pill. */
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button {
    padding: 2px 4px !important;
    background: transparent !important;
    border: none !important;
}
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {
    position: fixed !important;
    top: 16px !important;
    left: 16px !important;
    z-index: 999999 !important;
    background-color: #161B22 !important;
    border: 1px solid #30363D !important;
    border-radius: 10px !important;
    padding: 4px 12px !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4) !important;
    transition: background-color 0.12s ease, border-color 0.12s ease, transform 0.12s ease !important;
}

@media (hover: hover) {
    [data-testid="stSidebarCollapsedControl"]:hover,
    [data-testid="collapsedControl"]:hover {
        background-color: #21262D !important;
        border-color: #2EA043 !important;
    }
}

/* Highlight the sidebar collapse (<<) button */
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarHeader"] button,
section[data-testid="stSidebar"] button[kind="header"] {
    background-color: rgba(46, 160, 67, 0.16) !important;
    border: 1px solid rgba(46, 160, 67, 0.65) !important;
    border-radius: 8px !important;
    padding: 4px 8px !important;
    opacity: 1 !important;
    visibility: visible !important;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35) !important;
    transition: all 0.15s ease !important;
}

[data-testid="stSidebarCollapseButton"] button svg,
[data-testid="stSidebarHeader"] button svg,
section[data-testid="stSidebar"] button[kind="header"] svg {
    fill: #6EE798 !important;
    color: #6EE798 !important;
    width: 18px !important;
    height: 18px !important;
}

@media (hover: hover) {
    [data-testid="stSidebarCollapseButton"] button:hover,
    [data-testid="stSidebarHeader"] button:hover,
    section[data-testid="stSidebar"] button[kind="header"]:hover {
        background-color: rgba(46, 160, 67, 0.3) !important;
        border-color: #3FB950 !important;
    }
}

/* Hide the native chevron in BOTH DOM shapes. */
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="collapsedControl"] svg {
    display: none !important;
}

/* Label works whether the testid is on the button itself or on a
   wrapper around it. Tag-qualified selectors avoid a duplicate label. */
button[data-testid="stSidebarCollapsedControl"]::after,
button[data-testid="collapsedControl"]::after,
div[data-testid="stSidebarCollapsedControl"] button::after,
div[data-testid="collapsedControl"] button::after,
span[data-testid="stSidebarCollapsedControl"] button::after,
span[data-testid="collapsedControl"] button::after {
    content: "☰  Menu";
    color: #E6EDF3 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    white-space: nowrap !important;
    padding: 2px 4px !important;
}
/* Balanced top spacing below the transparent header */
section.main > div[data-testid="stMainBlockContainer"],
.block-container { padding-top: 2.8rem !important; }

/* ── Base typography ── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    font-size: 0.95rem;
    line-height: 1.5;
    color: var(--text-body);
}
/* Sidebar inputs, buttons, and labels */
input, select, textarea, button, label,
.stSelectbox, .stTextInput, .stNumberInput, .stMultiselect,
.stRadio, .stCheckbox, .stSlider, .stDateInput, .stTimeInput,
.stButton button, .stDownloadButton button {
    font-family: 'Inter', sans-serif;
    font-size: 0.95rem;
    color: var(--text-body);
}
iframe[title="streamlit_searchbox.searchbox"] {
    width: 100% !important;
    border: 0 !important;
    background: transparent !important;
    border-radius: 10px !important;
}

/* ── Headings ── */
h1, h2, h3, .stHeading {
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: var(--text-heading);
}

/* ── Tabular numbers for clean metric alignment ── */
[data-testid="stMetricContainer"],
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"],
[data-testid="stMetricLabel"],
.stMetric {
    font-variant-numeric: tabular-nums;
}

/* ── App background ── */
.stApp {
    background: var(--bg-obsidian);
    color: var(--text-body);
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: var(--bg-sidebar);
    border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] .stMarkdown h2 {
    color: var(--text-body);
    font-size: 0.875rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    margin-bottom: 0.25rem;
    font-weight: 600;
    display: inline-block;
    padding: 0.2rem 0.7rem;
    border-radius: 999px;
    background: rgba(52, 211, 153, 0.12);
    border: 1px solid rgba(52, 211, 153, 0.3);
}

/* Sidebar widget labels — crisp white, 14px–15px */
[data-testid="stSidebar"] label {
    color: var(--text-heading) !important;
    font-size: 0.9rem !important;
    font-weight: 600 !important;
}

/* Sidebar checkbox / radio options — crisp white, 14px–15px */
[data-testid="stSidebar"] .stCheckbox > label > div,
[data-testid="stSidebar"] .stCheckbox > label > span,
[data-testid="stSidebar"] .stRadio > label > div,
[data-testid="stSidebar"] .stRadio > label > span {
    color: var(--text-heading) !important;
    font-size: 0.9rem !important;
    font-weight: 500 !important;
}

/* Sidebar form elements — cleaner borders & rounded corners */
[data-testid="stSidebar"] .stSelectbox > div > div,
[data-testid="stSidebar"] .stTextInput > div > div,
[data-testid="stSidebar"] .stNumberInput > div > div,
[data-testid="stSidebar"] .stMultiselect > div > div {
    background: rgba(15, 23, 42, 0.4);
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
}
[data-testid="stSidebar"] .stCheckbox > label,
[data-testid="stSidebar"] .stRadio > label {
    font-family: 'Inter', sans-serif;
}

/* ── Sidebar logo pill ── */
.sidebar-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.9rem 0.9rem 1.1rem 0.9rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1.25rem;
    max-width: 100%;
}
.sidebar-header .sidebar-logo {
    height: 2.4rem;
    width: auto;
    flex-shrink: 0;
    border-radius: 10px;
    background: transparent !important;
    padding: 0;
    box-shadow: none;
}
/* Light pill behind the dark logo so it stays crisp on the dark UI */
.logo-pill {
    background-color: #F0F6FC;
    padding: 6px 10px;
    border-radius: 12px;
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
}
.logo-pill img { display: block; }
.sidebar-header .sidebar-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.sidebar-header .sidebar-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 1.2rem;
    font-weight: 800;
    color: #f1f5f9;
    margin: 0 0 0.1rem;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.sidebar-header .sidebar-tagline {
    font-size: 0.875rem;
    color: var(--text-body);
    margin: 0;
    font-weight: 400;
    line-height: 1.1;
}

/* ── Sidebar welcome card ── */
.sidebar-welcome {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.18), rgba(5, 150, 105, 0.08));
    border: 1px solid rgba(52, 211, 153, 0.32);
    border-radius: 12px;
    padding: 0.75rem 0.9rem;
    margin: 0.25rem 0 0.85rem;
}
.sidebar-welcome .welcome-name {
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text-heading);
    line-height: 1.25;
}
.sidebar-welcome .welcome-email {
    font-size: 0.75rem;
    color: #9BA1A6;
    margin-top: 0.15rem;
    line-height: 1.25;
    text-decoration: none !important;
    word-break: break-all;
}
.sidebar-welcome a {
    color: inherit !important;
    text-decoration: none !important;
}
/* ── Sidebar bottom activity stats ── */
.sidebar-stats {
    background: rgba(11, 15, 25, 0.55);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 0.7rem 0.85rem;
    margin-top: 0.75rem;
}
.sidebar-stats .stats-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
}
.sidebar-stats .stats-label {
    font-size: 0.82rem;
    color: var(--text-body);
    font-weight: 600;
}
.sidebar-stats .stats-value {
    font-size: 1.1rem;
    font-weight: 800;
    color: #7EE2A8;
    font-variant-numeric: tabular-nums;
}
.sidebar-stats .stats-tip {
    margin-top: 0.45rem;
    padding-top: 0.45rem;
    border-top: 1px dashed var(--border);
    font-size: 0.74rem;
    line-height: 1.35;
    color: #94A3B8;
}
@media (hover: hover) {
    .sidebar-welcome a:hover {
        color: inherit !important;
        text-decoration: none !important;
    }
}
/* Consistent spacing / clean borders for sidebar sections */
[data-testid="stSidebar"] .stMarkdown h2 {
    margin: 0.9rem 0 0.5rem !important;
}
[data-testid="stSidebar"] .streamlit-expanderHeader {
    background: rgba(15, 23, 42, 0.4) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    font-size: 0.9rem !important;
    color: var(--text-heading) !important;
}
[data-testid="stSidebar"] hr.section-divider {
    margin: 0.9rem 0 !important;
}
/* Clickable saved-match rows inside "My saved matches" */
[data-testid="stSidebar"] div[data-testid="stExpander"] button {
    text-align: left !important;
    font-size: 15px !important;
    line-height: 1.35 !important;
    white-space: pre-line !important;
    padding: 0.55rem 0.7rem !important;
    border: 1px solid #30363D !important;
    border-radius: 10px !important;
    background-color: rgba(22, 27, 34, 0.9) !important;
    color: var(--text-body) !important;
}
@media (hover: hover) {
    [data-testid="stSidebar"] div[data-testid="stExpander"] button:hover {
        background-color: #21262D !important;
        border-color: #2EA043 !important;
    }
}

/* ── Hero header — one centered flex column (mobile-safe) ── */
.hero-block {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    text-align: center !important;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box !important;
    padding: 0.4rem 1rem 0.6rem;
}
.hero-block .logo-pill {
    flex-shrink: 0;
    padding: 8px 14px !important;
    border-radius: 14px !important;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.28);
}
.hero-logo {
    height: 2.7rem;
    width: auto;
    display: block;
    border-radius: 10px;
    background: transparent !important;
    padding: 0;
    box-shadow: none;
}
.hero-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    display: inline-block;
    font-size: 2.5rem !important;
    font-weight: 800;
    color: var(--text-heading);
    background: linear-gradient(90deg, #34D399, #60a5fa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.1;
    margin: 0 !important;
}
.hero-tagline {
    font-size: 1rem !important;
    color: var(--text-body) !important;
    margin: 0.4rem 0 0 !important;
    font-weight: 400;
    letter-spacing: 0.02em;
}

/* ── Primary action (emerald gradient) ── */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"],
button[kind="primary"],
button[kind="primary"] p {
    background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important;
    border: none !important;
    color: #FFFFFF !important;
    font-size: 1rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.3px !important;
    border-radius: 10px !important;
    transition: background-color 0.12s ease, border-color 0.12s ease, transform 0.12s ease !important;
    box-shadow: 0 4px 14px rgba(16, 185, 129, 0.35) !important;
}
/* Touch devices must get a clean first tap: hover effects are desktop-only. */
@media (hover: hover) {
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="stBaseButton-primary"]:hover,
    button[kind="primary"]:hover,
    button[kind="primary"] p:hover {
        background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important;
        color: #FFFFFF !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 18px rgba(16, 185, 129, 0.5) !important;
    }
}

/* ── Section divider ── */
.section-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 0.7rem 0;
}

/* ── Ranked swaps — high-contrast SaaS comparison cards ── */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.swap-card) {
    background-color: #161B22 !important;
    border: 1px solid #30363D !important;
    border-radius: 16px !important;
    padding: 1.25rem !important;
    height: 100% !important;
    min-height: 360px !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.swap-card--top) {
    border-color: #2EA043 !important;
    box-shadow: 0 0 0 1px rgba(46, 160, 67, 0.25), 0 14px 34px rgba(0, 0, 0, 0.32) !important;
}
div[data-testid="stColumn"]:has(.swap-card) > div[data-testid="stVerticalBlock"] {
    height: 100% !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.swap-card) > div[data-testid="stVerticalBlock"] {
    display: flex !important;
    flex-direction: column !important;
    height: 100% !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.swap-card) div[data-testid="stButton"] {
    margin-top: auto !important;
}
.swap-card {
    min-height: 360px !important;
    display: flex;
    flex-direction: column;
}
.swap-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.85rem;
}
.swap-rank-pill {
    display: inline-flex;
    align-items: center;
    padding: 5px 11px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    white-space: nowrap;
}
.swap-score-pill {
    display: inline-flex;
    align-items: center;
    padding: 5px 11px;
    border-radius: 999px;
    background: #0B0F19 !important;
    border: 1px solid #2EA043 !important;
    color: #7EE2A8 !important;
    font-size: 0.82rem;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.swap-thumb {
    width: 100%;
    height: 150px;
    max-height: 150px;
    object-fit: cover;
    border-radius: 10px;
    display: block;
    margin-bottom: 0.85rem;
    background: #0B0F19;
}
.swap-thumb-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 3.2rem;
}
.swap-name {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 18px !important;
    font-weight: 700 !important;
    color: #FFFFFF !important;
    line-height: 1.25 !important;
    margin: 0 0 0.25rem !important;
}
.swap-meta {
    font-size: 0.8rem;
    color: #94A3B8;
    margin-bottom: 0.7rem !important;
    overflow-wrap: anywhere;
}
.swap-macros {
    margin: 0.2rem 0 0.6rem;
}
.swap-macro-pill {
    display: inline-flex;
    align-items: center;
    padding: 4px 9px;
    margin: 0.15rem 0.3rem 0.15rem 0;
    border-radius: 999px;
    border: 1px solid;
    font-size: 14px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}
.swap-macro-pill.protein  { background: rgba(52,211,153,0.12); color: #34D399; border-color: rgba(52,211,153,0.35); }
.swap-macro-pill.carbs    { background: rgba(96,165,250,0.12); color: #60A5FA; border-color: rgba(96,165,250,0.35); }
.swap-macro-pill.fat      { background: rgba(244,114,182,0.12); color: #F472B6; border-color: rgba(244,114,182,0.35); }
.swap-macro-pill.calories { background: rgba(251,191,36,0.12); color: #FBBF24; border-color: rgba(251,191,36,0.35); }
.swap-deltas {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    margin-bottom: 0.75rem;
}
.swap-delta {
    display: inline-flex;
    align-items: center;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    background: rgba(148, 163, 184, 0.10);
    border: 1px solid rgba(148, 163, 184, 0.22);
    color: #CBD5E1;
}
.swap-delta--good {
    background: rgba(46, 160, 67, 0.14);
    border-color: rgba(46, 160, 67, 0.40);
    color: #7EE2A8;
}
.swap-delta--warn {
    background: rgba(251, 191, 36, 0.12);
    border-color: rgba(251, 191, 36, 0.35);
    color: #FBBF24;
}
.swap-explanation {
    background: #0B0F19;
    border-left: 3px solid #2EA043;
    border-radius: 0 10px 10px 0;
    padding: 0.8rem 0.9rem;
    font-size: 15px;
    color: #C9D1D9;
    line-height: 1.5;
    margin: 0 0 0.9rem;
    flex: 1;
}
.swap-explanation strong {
    color: #F1F5F9;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.swap-card) .stButton > button {
    min-height: 42px !important;
    font-size: 0.9rem !important;
    border-radius: 10px !important;
}
@media (max-width: 768px) {
    div[data-testid="stColumn"]:has(.swap-card) {
        flex: 0 0 100% !important;
        width: 100% !important;
    }
}

/* ── Product images — fixed heights, no fullscreen chrome ── */
button[title="View fullscreen"], [data-testid="StyledFullScreenButton"] {
    display: none !important;
}
.spotlight-card-marker {
    display: none !important;
}
.spotlight-thumb {
    width: 100%;
    height: 210px;
    max-height: 210px;
    object-fit: cover;
    border-radius: 12px;
    display: block;
    background: #0B0F19;
}
.spotlight-thumb-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 4.2rem;
}
.product-emoji {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 150px;
    font-size: 4.2rem;
    background: #0B0F19;
    border: 1px solid var(--border);
    border-radius: 12px;
}
/* ── Tag / pill badges ── */
.tag {
    display: inline-block;
    font-size: 0.8rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 999px;
    margin: 0.15rem 0.25rem 0.15rem 0;
    color: var(--text-body);
}
.macro-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.8rem;
    font-weight: 600;
    font-family: 'Inter', sans-serif;
    font-variant-numeric: tabular-nums;
    padding: 4px 10px;
    border-radius: 999px;
    margin: 0.1rem 0.25rem 0.1rem 0;
    border: 1px solid;
}
.macro-pill.protein { background: rgba(52, 211, 153, 0.12); color: #34D399; border-color: rgba(52, 211, 153, 0.35); }
.macro-pill.carbs   { background: rgba(96, 165, 250, 0.12); color: #60A5FA; border-color: rgba(96, 165, 250, 0.35); }
.macro-pill.fat     { background: rgba(244, 114, 182, 0.12); color: #F472B6; border-color: rgba(244, 114, 182, 0.35); }
.macro-pill.fiber   { background: rgba(168, 85, 247, 0.12); color: #A855F7; border-color: rgba(168, 85, 247, 0.35); }
.macro-pill.calories{ background: rgba(251, 191, 36, 0.12); color: #FBBF24; border-color: rgba(251, 191, 36, 0.35); }

/* ── Landing (empty state) — compact ── */
.landing {
    position: relative;
    max-width: 1060px;
    margin: 0.75rem auto 0;
    padding: 1.1rem 1.4rem 0.9rem;
    background: rgba(21, 28, 44, 0.6);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 20px 50px rgba(2, 6, 23, 0.35);
    overflow: hidden;
}
.landing::before {
    content: "";
    position: absolute;
    inset: 0 0 auto 0;
    height: 2px;
    background: linear-gradient(90deg, #34D399, #60a5fa);
    opacity: 0.9;
}
.landing-eyebrow {
    text-align: center;
    color: #60a5fa;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin-bottom: 0.35rem;
}
.landing-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    text-align: center;
    color: var(--text-heading);
    font-size: 1.75rem;
    font-weight: 800;
    line-height: 1.25;
    margin: 0 0 0.5rem;
}
.landing-sub {
    max-width: 640px;
    margin: 0 auto 0.9rem !important;
    text-align: center;
    color: var(--text-body) !important;
    font-size: 0.95rem !important;
    line-height: 1.5;
}
.steps {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem;
    margin: 0.5rem 0;
}
.step {
    background: rgba(11, 15, 25, 0.5);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.75rem 0.7rem 0.8rem;
    transition: background-color 0.12s ease, border-color 0.12s ease, transform 0.12s ease;
}
@media (hover: hover) {
    .step:hover {
        border-color: rgba(255, 255, 255, 0.18);
        transform: translateY(-2px);
    }
}
.step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    margin-bottom: 0.35rem;
    font-size: 0.85rem;
    font-weight: 800;
    color: var(--bg-obsidian);
    background: var(--accent-mint);
}
.step h3 {
    font-family: 'Plus Jakarta Sans', sans-serif;
    margin: 0 0 0.15rem;
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text-heading);
}
.step p {
    margin: 0;
    font-size: 0.875rem;
    line-height: 1.5;
    color: var(--text-body);
}
.landing-cta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    margin-top: 0.8rem;
    padding-top: 0.7rem;
    border-top: 1px dashed var(--border);
    color: var(--text-muted);
    font-size: 0.9rem;
}
.landing-cta .arrow { color: #60a5fa; font-weight: 700; }
.landing-facts {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.5rem;
    margin-top: 0.6rem;
}
.landing-facts span {
    font-size: 0.8rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-body);
    background: rgba(11, 15, 25, 0.5);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.2rem 0.7rem;
    font-weight: 600;
}
@media (max-width: 820px) {
    .landing { padding: 0.9rem 1rem 0.8rem; }
    .landing-title { font-size: 1.4rem; }
    .steps { grid-template-columns: 1fr; }
}

/* ── Top how-it-works expander — high-contrast one-line guide bar ── */
.how-guide-anchor { display: none !important; }
div[data-testid="stExpander"]:has(.landing) {
    margin: 0.15rem 0 1.1rem !important;
}
div[data-testid="stExpander"]:has(.landing) summary,
div[data-testid="stExpander"]:has(.landing) button[data-testid="stExpanderHeader"],
div[data-testid="stExpander"]:has(.landing) [data-testid="stExpanderHeader"],
div[data-testid="stVerticalBlockElement"]:has(.how-guide-anchor) + div[data-testid="stVerticalBlockElement"] div[data-testid="stExpander"] summary,
div[data-testid="stVerticalBlockElement"]:has(.how-guide-anchor) + div[data-testid="stVerticalBlockElement"] div[data-testid="stExpander"] button[data-testid="stExpanderHeader"],
div[data-testid="stVerticalBlockElement"]:has(.how-guide-anchor) + div[data-testid="stVerticalBlockElement"] div[data-testid="stExpander"] [data-testid="stExpanderHeader"] {
    background-color: #161B22 !important;
    border: 1px solid #30363D !important;
    border-radius: 10px !important;
    padding: 10px 14px !important;
    color: #E6EDF3 !important;
    font-size: 16px !important;
    font-weight: 600 !important;
}
div[data-testid="stExpander"]:has(.landing) [data-testid="stExpanderHeader"] p,
div[data-testid="stExpander"]:has(.landing) summary p,
div[data-testid="stVerticalBlockElement"]:has(.how-guide-anchor) + div[data-testid="stVerticalBlockElement"] div[data-testid="stExpander"] [data-testid="stExpanderHeader"] p {
    color: #E6EDF3 !important;
    font-size: 16px !important;
    font-weight: 600 !important;
}
div[data-testid="stExpander"]:has(.landing) [data-testid="stExpanderHeader"] svg,
div[data-testid="stVerticalBlockElement"]:has(.how-guide-anchor) + div[data-testid="stVerticalBlockElement"] div[data-testid="stExpander"] [data-testid="stExpanderHeader"] svg {
    color: #7EE2A8 !important;
    fill: #7EE2A8 !important;
}

/* ── Sidebar header ── */
.sidebar-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.9rem 0.9rem 1.1rem 0.9rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1.25rem;
    max-width: 100%;
}
.sidebar-header .sidebar-logo {
    height: 2.4rem;
    width: auto;
    flex-shrink: 0;
    border-radius: 10px;
    background: transparent !important;
    padding: 0;
    box-shadow: none;
}
.sidebar-header .sidebar-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.sidebar-header .sidebar-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 1.2rem;
    font-weight: 800;
    color: #f1f5f9;
    margin: 0 0 0.1rem;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.sidebar-header .sidebar-tagline {
    font-size: 0.72rem;
    color: var(--text-muted);
    margin: 0;
    font-weight: 400;
    line-height: 1.1;
}

/* ── Error state ── */
.error-box {
    background: #1E1015;
    border: 1px solid #7F1D1D;
    border-radius: 10px;
    padding: 1rem 1.25rem;
    color: #FCA5A5;
    font-size: 0.95rem;
    line-height: 1.5;
}

/* ── Comparison table ── */
.macro-table th {
    color: var(--text-body);
    font-weight: 600;
    font-size: 0.875rem;
    text-transform: uppercase;
}

/* Center-align Streamlit dataframe (Nutrition Breakdown) headers & cells */
[data-testid="stDataFrame"] th,
[data-testid="stDataFrame"] td,
.stDataFrame th,
.stDataFrame td {
    text-align: center !important;
}

/* ── Net Carbs keto highlight badge ── */
.net-carbs-keto {
    display: inline-block;
    background: rgba(251,191,36,0.15);
    border: 1px solid rgba(251,191,36,0.4);
    color: #fbbf24;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-left: 0.4rem;
}
.net-carbs-normal {
    display: inline-block;
    background: rgba(148,163,184,0.1);
    border: 1px solid var(--border);
    color: var(--text-body);
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.8rem;
    margin-left: 0.4rem;
}
.macro-goal-badge {
    display: inline-block;
    background: rgba(46,160,67,0.12);
    border: 1px solid rgba(46,160,67,0.38);
    color: #7EE2A8;
    border-radius: 999px;
    padding: 2px 9px;
    font-size: 0.76rem;
    font-weight: 600;
    margin: 0.25rem 0.35rem 0 0;
    white-space: nowrap;
}

/* ── Local name tag ── */
.local-name-tag {
    display: inline-block;
    background: rgba(96,165,250,0.1);
    border: 1px solid rgba(96,165,250,0.3);
    color: #93c5fd;
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-top: 0.25rem;
    letter-spacing: 0.01em;
}

/* ── Caution callout ── */
.caution-box {
    background: rgba(239,68,68,0.07);
    border-left: 3px solid rgba(239,68,68,0.5);
    border-radius: 0 8px 8px 0;
    padding: 0.55rem 0.9rem;
    margin-top: 0.6rem;
    font-size: 0.9rem;
    color: #fca5a5;
    line-height: 1.5;
}
.caution-box strong {
    color: #f87171;
    font-weight: 600;
}

/* ── Touch-first search card ── */
/* Only the main search card gets this surface, not every bordered container. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.search-card-title) {
    background: linear-gradient(160deg, rgba(19, 28, 44, 0.82), rgba(8, 13, 23, 0.92)) !important;
    border: 1px solid rgba(255, 255, 255, 0.10) !important;
    border-radius: 18px !important;
    padding: 1.1rem !important;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28) !important;
}
.search-card-title {
    font-size: 0.78rem !important;
    font-weight: 800 !important;
    letter-spacing: 0.14em !important;
    color: #7EE2A8 !important;
    margin: 0 0 0.6rem !important;
}
.search-card-title--spaced {
    margin-top: 1.1rem !important;
}

/* ── Sidebar product guide — compact single-column cards ── */
[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.guide-card) {
    background-color: #161B22 !important;
    border: 1px solid #30363D !important;
    border-radius: 12px !important;
    padding: 10px !important;
    margin-bottom: 10px !important;
}
.guide-thumb {
    display: block;
    width: 100%;
    height: 100px;
    object-fit: cover;
    border-radius: 8px !important;
    margin-bottom: 0.5rem;
}
.guide-emoji {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100px;
    border-radius: 8px;
    background: rgba(148, 163, 184, 0.10);
    font-size: 2.2rem;
    margin-bottom: 0.5rem;
}
.guide-title {
    font-size: 16px !important;
    font-weight: 700 !important;
    color: #FFFFFF !important;
    line-height: 1.25 !important;
}
.guide-category {
    font-size: 0.72rem !important;
    color: var(--text-muted) !important;
    margin: 0.15rem 0 0.4rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.guide-macros .macro-pill {
    font-size: 0.7rem !important;
    padding: 2px 6px !important;
}
.guide-macros .macro-unit {
    font-size: 0.7rem !important;
    color: var(--text-muted) !important;
    margin-left: 0.25rem !important;
}
.guide-tags .tag {
    font-size: 0.68rem !important;
    padding: 2px 6px !important;
}
.guide-cities {
    font-size: 0.72rem !important;
    color: var(--text-muted) !important;
    margin-top: 0.35rem !important;
}
[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.guide-card) .stButton > button {
    min-height: 32px !important;
    padding: 0.3rem 0.6rem !important;
    font-size: 0.78rem !important;
    border-radius: 8px !important;
    margin-top: 0.55rem !important;
}

.selected-value {
    font-size: 0.8rem !important;
    color: var(--text-muted) !important;
    margin: 0.35rem 0 0.55rem !important;
}
.selected-value strong {
    color: #7EE2A8 !important;
    font-weight: 700 !important;
}

/* Quick-tap pills: active choice is emerald green. */
div[data-testid="stPills"] button,
button[data-baseweb="pill"] {
    border-radius: 999px !important;
    border: 1px solid rgba(148, 163, 184, 0.22) !important;
    background: rgba(148, 163, 184, 0.08) !important;
    color: #CBD5E1 !important;
    font-weight: 600 !important;
    padding: 0.45rem 0.85rem !important;
    transition: background-color 0.12s ease, border-color 0.12s ease !important;
}
div[data-testid="stPills"] button[aria-pressed="true"],
div[data-testid="stPills"] button[aria-checked="true"],
div[data-testid="stPills"] button[data-selected="true"],
button[data-baseweb="pill"][aria-pressed="true"],
button[data-baseweb="pill"][aria-checked="true"],
button[data-baseweb="pill"][data-selected="true"] {
    background: #2EA043 !important;
    border-color: #2EA043 !important;
    color: #FFFFFF !important;
    box-shadow: 0 6px 16px rgba(46, 160, 67, 0.32) !important;
}
@media (hover: hover) {
    div[data-testid="stPills"] button:hover,
    button[data-baseweb="pill"]:hover {
        border-color: rgba(46, 160, 67, 0.55) !important;
        color: #FFFFFF !important;
    }
}

/* ── Back-to-home pill — centered above the Top 3 Swaps container ── */
.back-home-marker {
    display: none !important;
}
/* The marker lives directly in the centered column; no border wrapper exists. */
div[data-testid="stColumn"]:has(.back-home-marker) div[data-testid="stButton"],
div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) div[data-testid="stButton"] {
    display: flex !important;
    justify-content: center !important;
}
div[data-testid="stColumn"]:has(.back-home-marker) .stButton > button,
div[data-testid="stColumn"]:has(.back-home-marker) button[data-testid="stBaseButton-secondary"],
div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) .stButton > button,
div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) button[data-testid="stBaseButton-secondary"] {
    background-color: rgba(46, 160, 67, 0.12) !important;
    border: 1px solid rgba(46, 160, 67, 0.55) !important;
    border-radius: 10px !important;
    padding: 8px 20px !important;
    color: #6EE798 !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    line-height: 1.2 !important;
    box-shadow: none !important;
    transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
}
div[data-testid="stColumn"]:has(.back-home-marker) .stButton > button p,
div[data-testid="stColumn"]:has(.back-home-marker) button[data-testid="stBaseButton-secondary"] p,
div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) .stButton > button p,
div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) button[data-testid="stBaseButton-secondary"] p {
    color: #6EE798 !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    margin: 0 !important;
}
@media (hover: hover) {
    div[data-testid="stColumn"]:has(.back-home-marker) .stButton > button:hover,
    div[data-testid="stColumn"]:has(.back-home-marker) button[data-testid="stBaseButton-secondary"]:hover,
    div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) .stButton > button:hover,
    div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) button[data-testid="stBaseButton-secondary"]:hover {
        background-color: rgba(46, 160, 67, 0.22) !important;
        border-color: #3FB950 !important;
        color: #FFFFFF !important;
    }
    div[data-testid="stColumn"]:has(.back-home-marker) .stButton > button:hover p,
    div[data-testid="stColumn"]:has(.back-home-marker) button[data-testid="stBaseButton-secondary"]:hover p,
    div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) .stButton > button:hover p,
    div[data-testid="stHorizontalBlock"]:has(.back-home-marker) > div:nth-child(2) button[data-testid="stBaseButton-secondary"]:hover p {
        color: #FFFFFF !important;
    }
}

/* ── Unified results container + dashboard tabs ── */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) {
    background-color: #161B22 !important;
    border: 1px solid #30363D !important;
    border-radius: 16px !important;
    padding: 1.1rem !important;
}
.results-tabs-marker {
    display: none !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) .stTabs [data-baseweb="tab-list"] {
    gap: 0.4rem !important;
    background: #0B0F19 !important;
    border: 1px solid #30363D !important;
    border-radius: 12px !important;
    padding: 0.25rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) .stTabs button[data-baseweb="tab"] {
    color: #94A3B8 !important;
    background: transparent !important;
    border-radius: 999px !important;
    padding: 0.45rem 0.9rem !important;
    font-size: 0.88rem !important;
    font-weight: 700 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) .stTabs button[data-baseweb="tab"][aria-selected="true"] {
    color: #FFFFFF !important;
    background: linear-gradient(135deg, #2EA043 0%, #10B981 100%) !important;
    box-shadow: 0 6px 16px rgba(46, 160, 67, 0.28) !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) .stTabs [data-baseweb="tab-highlight"],
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) .stTabs [data-baseweb="tab-border"] {
    background: transparent !important;
}

/* ── Saved-match rows: label + delete icon stay on one mobile row ── */
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"],
div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    align-items: center !important;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child,
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:first-child,
div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child,
div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:first-child {
    min-width: 0 !important;
    flex: 1 1 auto !important;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child,
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child,
div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child,
div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child {
    width: 46px !important;
    min-width: 46px !important;
    flex: 0 0 46px !important;
}

/* ── Desktop / laptop only — larger, centered reading experience ── */
/* Everything here is gated at 769px so mobile typography stays untouched. */
@media (min-width: 769px) {
    section.main > div[data-testid="stMainBlockContainer"],
    .block-container {
        max-width: 1120px !important;
        padding-top: 3.2rem !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }

    body,
    .stMarkdown p,
    .stTextInput label p,
    .stNumberInput label p,
    div[data-testid="stExpander"] summary p {
        font-size: 16.5px !important;
        line-height: 1.55 !important;
    }

    .stTextInput input,
    .stNumberInput input {
        font-size: 15.5px !important;
        padding: 0.65rem 0.85rem !important;
    }

    div[data-testid="stPills"] button,
    button[data-baseweb="pill"] {
        font-size: 15.5px !important;
        padding: 0.55rem 0.95rem !important;
    }

    .macro-pill,
    .swap-macro-pill,
    .macro-goal-badge {
        font-size: 15.5px !important;
        padding: 5px 11px !important;
    }

    /* Richer macro pills only inside the "Your Regular Food" spotlight card. */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.spotlight-card-marker) .macro-pill,
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.spotlight-card-marker) .net-carbs-keto,
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.spotlight-card-marker) .net-carbs-normal,
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.spotlight-card-marker) .macro-goal-badge {
        font-size: 16px !important;
        padding: 6px 12px !important;
    }

    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] button,
    .sidebar-welcome .welcome-name,
    .sidebar-welcome .welcome-email,
    .sidebar-stats .stats-label,
    .sidebar-stats .stats-tip {
        font-size: 15.5px !important;
    }

    section.main .stMarkdown h3,
    .swap-name {
        font-size: 23px !important;
    }
}

/* Lightweight mobile layout — no backdrop blur, tighter spacing. */
@media (max-width: 768px) {
    /* Keep the fixed ☰ Menu button from covering the centered brand header. */
    section.main > div[data-testid="stMainBlockContainer"],
    .block-container {
        padding-top: 3.6rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.search-card-title) {
        padding: 0.85rem !important;
        border-radius: 14px !important;
    }
    .hero-block {
        padding: 0.35rem 0.75rem 0.55rem !important;
    }
    .hero-block .logo-pill {
        padding: 7px 12px !important;
        border-radius: 14px !important;
    }
    .hero-logo {
        height: 2.4rem !important;
    }
    .hero-title {
        font-size: 2rem !important;
        letter-spacing: -0.02em !important;
    }
    .hero-tagline {
        font-size: 0.9rem !important;
        margin-top: 0.3rem !important;
    }
    .hero-divider {
        margin: 0.5rem 0 !important;
    }
    .steps { grid-template-columns: 1fr !important; }
}
</style>
""", unsafe_allow_html=True)

# NOTE: Authentication CSS now lives INSIDE the logged-out block near the top
# of this file. It must be injected BEFORE st.stop(), otherwise the login screen
# never receives it (the old copy here was dead code after st.stop()).


# ─────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────

@st.cache_data(ttl=60)
def fetch_product_list() -> list[str]:
    """
    Fetch all product names from GET /products.

    Raises BackendUnavailable on failure so the failure is never cached: the
    next rerun retries the API instead of replaying a stale "unreachable" result.
    """
    try:
        resp = requests.get(f"{API_BASE}/products", timeout=GET_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("products", [])
    except requests.exceptions.RequestException as exc:
        # Connection error, timeout, or non-2xx status.
        raise BackendUnavailable(API_BASE) from exc


@st.cache_data(ttl=60)
def load_product_csv() -> pd.DataFrame:
    """Load products.csv to retrieve original product macros for comparison."""
    csv_path = Path(__file__).parent.parent / "data" / "products.csv"
    df = pd.read_csv(csv_path)
    df["name"] = df["name"].str.strip()
    return df


@st.cache_data(ttl=60)
def load_city_list() -> list[str]:
    """Destination cities derived from the dataset so the UI never drifts from the data."""
    try:
        df = load_product_csv()
    except (FileNotFoundError, pd.errors.ParserError):
        return []

    cities: set[str] = set()
    for value in df["cities"].dropna():
        for part in str(value).split(","):
            part = part.strip()
            if part:
                cities.add(part)

    # Keep the original five first (Delhi stays the default), then the rest A-Z.
    preferred = {name: i for i, name in enumerate(CITIES_FALLBACK)}
    return sorted(cities, key=lambda name: (preferred.get(name, len(preferred)), name))


@st.cache_data(ttl=60)
def cached_all_foods() -> list[str]:
    """Plain sorted Python list used for O(n) prefix autocomplete."""
    return sorted(set(fetch_product_list()))


@st.cache_data(ttl=60)
def cached_all_cities() -> list[str]:
    """Plain sorted Python list used for O(n) city autocomplete."""
    return sorted(set(load_city_list() or CITIES_FALLBACK))


def _reset_food_search_input() -> None:
    """Clear-box handler: keep the input empty without changing the selection."""
    st.session_state["food_search_input"] = ""


def _reset_city_search_input() -> None:
    """Clear-box handler: keep the input empty without changing the selection."""
    st.session_state["city_search_input"] = ""


def search_foods(searchterm: str) -> list[str]:
    """Instant food matches for st_searchbox, prefix matches before keywords."""
    term = searchterm or ""
    st.session_state["food_search_input"] = term
    query = term.strip().lower()
    foods = cached_all_foods()
    if not query:
        return [
            _canonical_value(label, PRODUCT_DISPLAY_ALIASES)
            for label in POPULAR_PRODUCTS
            if _canonical_value(label, PRODUCT_DISPLAY_ALIASES) in foods
        ]
    return _ordered_suggestions(query, foods)[:8]


def search_cities(searchterm: str) -> list[str]:
    """Instant city matches for st_searchbox, including friendly aliases."""
    term = searchterm or ""
    st.session_state["city_search_input"] = term
    query = term.strip().lower()
    cities = cached_all_cities()
    if not query:
        defaults = []
        for label in POPULAR_CITIES:
            canonical = _canonical_value(label, CITY_DISPLAY_ALIASES)
            if canonical in cities and canonical not in defaults:
                defaults.append(canonical)
        return defaults
    return _ordered_city_suggestions(query, cities)[:8]


@st.cache_data(ttl=60)
def get_original_macros(product_name: str) -> dict | None:
    """Return the macro dict for the original product from local CSV."""
    df = load_product_csv()
    row = df[df["name"] == product_name]
    if row.empty:
        return None
    r = row.iloc[0]
    return {col: float(r.get(col, 0.0)) for col in MACRO_COLS}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() == "TRUE"


def product_image(name: str) -> Path | None:
    """Return the locally stored photo for a product, if one exists."""
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = PRODUCT_IMAGE_DIR / f"{_slug(name)}{ext}"
        if candidate.exists():
            return candidate
    return None


@st.cache_data(ttl=60)
def product_image_src(name: str) -> str | None:
    """Return a data-URI for embedding a product photo in custom HTML."""
    image = product_image(name)
    if not image:
        return None
    mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@st.cache_data(ttl=60)
def load_product_details() -> dict[str, dict]:
    """Every product row as a dict, with the city list parsed out.

    Uses row.get(...) with safe defaults so a missing/older CSV column can
    never raise a KeyError — the app simply falls back to False / 0.0.
    """
    df = load_product_csv()
    details: dict[str, dict] = {}
    for _, row in df.iterrows():
        details[str(row["name"])] = {
            "category": str(row.get("category", "")),
            "protein": float(row.get("protein", 0.0)),
            "carbs": float(row.get("carbs", 0.0)),
            "fat": float(row.get("fat", 0.0)),
            "fiber": float(row.get("fiber", 0.0)),
            "calories": float(row.get("calories", 0.0)),
            "vegetarian": _as_bool(row.get("vegetarian", False)),
            "vegan": _as_bool(row.get("vegan", False)),
            "dairy_free": _as_bool(row.get("dairy_free", False)),
            "gluten_free": _as_bool(row.get("gluten_free", False)),
            "low_sugar": _as_bool(row.get("low_sugar", False)),
            "contains_soy": _as_bool(row.get("contains_soy", False)),
            "contains_nuts": _as_bool(row.get("contains_nuts", False)),
            "contains_dairy": _as_bool(row.get("contains_dairy", False)),
            "cities": [c.strip() for c in str(row.get("cities", "")).split(",") if c.strip()],
        }
    return details


def _macro_line(detail: dict, serving_g: int | None = None) -> str:
    """Return a one-line macro summary. If serving_g is given, scales per-serving."""
    if serving_g:
        factor = serving_g / 100.0
        label  = f"per {serving_g} g serving"
        prot   = round(detail["protein"]  * factor, 1)
        carbs  = round(detail["carbs"]    * factor, 1)
        fat    = round(detail["fat"]      * factor, 1)
        fiber  = round(detail["fiber"]    * factor, 1)
        kcal   = round(detail["calories"] * factor)
    else:
        label = "per 100 g"
        prot  = detail["protein"]
        carbs = detail["carbs"]
        fat   = detail["fat"]
        fiber = detail["fiber"]
        kcal  = detail["calories"]
    return (
        f'<span class="macro-pill protein">P {prot:g}g</span>'
        f'<span class="macro-pill carbs">C {carbs:g}g</span>'
        f'<span class="macro-pill fat">F {fat:g}g</span>'
        f'<span class="macro-pill fiber">Fibre {fiber:g}g</span>'
        f'<span class="macro-pill calories">{kcal:g} kcal</span>'
        f' <span style="color:#64748b;font-size:0.78rem;">({label})</span>'
    )


def _badges_html(detail: dict) -> str:
    badges = []
    if detail.get("vegetarian") and not detail.get("vegan"):
        badges.append(("🌿 Vegetarian", "good"))
    if detail["vegan"]:
        badges.append(("🌱 Vegan", "good"))
    if detail.get("dairy_free") and not detail["vegan"]:
        badges.append(("🥛 Dairy-Free", "good"))
    if detail["gluten_free"]:
        badges.append(("🌾 Gluten-free", "good"))
    if detail.get("low_sugar"):
        badges.append(("🍬 Low-Sugar", "good"))
    if detail["contains_soy"]:
        badges.append(("⚠️ Soy", "warn"))
    if detail["contains_nuts"]:
        badges.append(("⚠️ Nuts", "warn"))
    if detail["contains_dairy"]:
        badges.append(("⚠️ Dairy", "warn"))

    colors = {
        "good": ("rgba(74,222,128,0.12)", "#4ade80", "rgba(74,222,128,0.35)"),
        "warn": ("rgba(251,191,36,0.12)", "#fbbf24", "rgba(251,191,36,0.35)"),
    }
    return "".join(
        f'<span class="tag" style="background:{colors[tone][0]};color:{colors[tone][1]};'
        f'border:1px solid {colors[tone][2]};">{label}</span>'
        for label, tone in badges
    )


def render_product_spotlight(name: str, detail: dict, keto: bool = False) -> None:
    """Photo + nutrition, local name, net carbs (keto-highlighted), how-to-use, and caution."""
    # ── Pre-compute net carbs ──────────────────────────────────────────
    net_carbs = max(0.0, detail["carbs"] - detail["fiber"])
    nc_cls    = "net-carbs-keto" if keto else "net-carbs-normal"
    nc_badge  = (
        f'<span class="{nc_cls}">⚡ Net Carbs {net_carbs:g} g</span>'
    )

    # ── Local name tag ─────────────────────────────────────────────────
    local_name = PRODUCT_LOCAL_NAMES.get(name, "")
    local_tag  = (
        f'<span class="local-name-tag">🗺️ {local_name}</span>'
        if local_name else ""
    )

    with st.container(border=True):
        # Hidden marker scopes desktop-only sizing to this card, like the
        # results container's .results-tabs-marker.
        st.markdown(
            '<div class="spotlight-card-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        col_img, col_info = st.columns([1.2, 2.5], vertical_alignment="center")
        with col_img:
            image_src = product_image_src(name)
            if image_src:
                # Inline <img> keeps the exact fixed height and avoids
                # Streamlit's fullscreen button entirely.
                st.markdown(
                    f'<img class="spotlight-thumb" src="{image_src}" '
                    f'alt="{html.escape(name, quote=True)}">',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="spotlight-thumb spotlight-thumb-fallback">'
                    f'{PRODUCT_EMOJI.get(name, "🥗")}</div>',
                    unsafe_allow_html=True,
                )
        with col_info:
            st.markdown(
                f"### {PRODUCT_EMOJI.get(name, '🥗')} {name}",
            )
            # Local name tag below the title
            if local_tag:
                st.markdown(local_tag, unsafe_allow_html=True)
            st.caption(detail["category"])
            st.markdown(_macro_line(detail), unsafe_allow_html=True)
            # Net carbs badge (highlighted amber when keto is active)
            st.markdown(
                nc_badge + _protein_goal_badge(detail["protein"]),
                unsafe_allow_html=True,
            )
            st.markdown(_badges_html(detail), unsafe_allow_html=True)
            with st.expander(f"📍 Available in {len(detail['cities'])} cities"):
                st.write(", ".join(detail["cities"]))

    # ── How to Use / Eat section ──────────────────────────────────────
    how_to  = PRODUCT_HOW_TO_USE.get(name)
    caution = PRODUCT_CAUTIONS.get(name)
    if how_to:
        st.markdown("#### 🍽️ How to Eat / Use")
        col_a, col_b = st.columns([1, 1], gap="medium")
        with col_a:
            st.markdown(
                f"""
                <div style="
                    background:#1e293b;
                    border:1px solid #334155;
                    border-radius:12px;
                    padding:0.8rem 1rem;
                    margin-bottom:0.5rem;
                ">
                    <p style="margin:0 0 0.2rem;color:#b0b8c4;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;">Serving Size</p>
                    <p style="margin:0;font-size:1rem;font-weight:600;color:#f1f5f9;">{how_to['serving']}</p>
                </div>
                <div style="
                    background:#1e293b;
                    border:1px solid #334155;
                    border-radius:12px;
                    padding:0.8rem 1rem;
                ">
                    <p style="margin:0 0 0.2rem;color:#b0b8c4;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;">⏰ Best Time to Have</p>
                    <p style="margin:0;font-size:0.95rem;color:#f1f5f9;">{how_to['best_time']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col_b:
            tips_html = "".join(
                f'<li style="margin-bottom:0.4rem;color:#cbd5e1;">{tip}</li>'
                for tip in how_to["tips"]
            )
            st.markdown(
                f"""
                <div style="
                    background:#1e293b;
                    border:1px solid #334155;
                    border-radius:12px;
                    padding:0.8rem 1rem;
                    height:100%;
                ">
                    <p style="margin:0 0 0.5rem;color:#b0b8c4;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;">💡 Tips & Ways to Eat</p>
                    <ul style="margin:0;padding-left:1.1rem;list-style:none;">
                        {tips_html}
                    </ul>
                </div>
                """,
                unsafe_allow_html=True,
            )
        # ── Caution callout ───────────────────────────────────────────
        if caution:
            st.markdown(
                f'<div class="caution-box"><strong>⚠️ Caution / Who Should Avoid:</strong> {caution}</div>',
                unsafe_allow_html=True,
            )


def render_product_guide(details: dict[str, dict]) -> None:
    """Compact one-column visual catalogue tailored to the sidebar width."""
    for item_name in sorted(details):
        detail = details[item_name]
        image_src = product_image_src(item_name)
        if image_src:
            image_html = (
                f'<img class="guide-thumb" src="{image_src}" '
                f'alt="{html.escape(item_name, quote=True)}">'
            )
        else:
            image_html = (
                '<div class="guide-emoji">'
                f'{PRODUCT_EMOJI.get(item_name, "🥗")}</div>'
            )

        macros_html = (
            f'<span class="macro-pill protein">Protein {detail["protein"]:g}g</span>'
            f'<span class="macro-pill carbs">Carbs {detail["carbs"]:g}g</span>'
            f'<span class="macro-pill fat">Fat {detail["fat"]:g}g</span>'
            f'<span class="macro-pill calories">{detail["calories"]:g} kcal</span>'
            '<span class="macro-unit">per 100 g</span>'
        )

        with st.container(border=True):
            st.markdown(
                '<div class="guide-card">'
                f"{image_html}"
                f'<div class="guide-title">{PRODUCT_EMOJI.get(item_name, "🥗")} '
                f"{html.escape(item_name)}</div>"
                f'<div class="guide-category">{html.escape(detail["category"])}</div>'
                f'<div class="guide-macros">{macros_html}</div>'
                f'<div class="guide-tags">{_badges_html(detail)}</div>'
                f'<div class="guide-cities">📍 {len(detail["cities"])} cities</div>'
                "</div>",
                unsafe_allow_html=True,
            )
            # Callback updates every state key before the button's single
            # rerun, so the chosen food appears immediately in the search box.
            # On mobile, the injected parent-document listener collapses the
            # sidebar as soon as this widget is clicked.
            st.button(
                "Select",
                key=f"guide_select_{item_name}",
                use_container_width=True,
                type="secondary",
                on_click=select_food_value_callback,
                args=(item_name,),
            )

    st.caption(
        "Product photos: Wikipedia / Wikimedia Commons — "
        "see `assets/products/CREDITS.md` for the source of each image."
    )


def call_api(payload: dict) -> requests.Response | None:
    """
    POST to /suggest-alternative.

    Returns the raw Response (so the caller can inspect the status code),
    or None if the backend could not be reached / did not answer in time.
    """
    try:
        return requests.post(
            f"{API_BASE}/suggest-alternative",
            json=payload,
            timeout=POST_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        # Covers ConnectionError, Timeout, and other transport-level failures.
        return None


def render_footer() -> None:
    """Centered, mobile-safe footer for the bottom of the main page."""
    st.markdown(
        """
        <div style="
            text-align: center;
            padding: 1.5rem 1rem 3rem 1rem;
            color: #8B949E;
            font-size: 14px;
            line-height: 1.6;
        ">
            <div>
                <strong style="color: #E6EDF3; font-size: 15px;">🥗 MacroMatch</strong>
                — Smart local food swaps tailored to your macros.
            </div>
            <div>
                Nutritional values are approximate per 100g. Always check local
                packaging labels for exact allergen details.
            </div>
            <div>© 2026 MacroMatch · Eat Smart, Travel Anywhere.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_how_it_works() -> None:
    """Collapsible top guide — the original 3-step card, unchanged inside."""
    # Marker lets CSS find this expander even while it is collapsed.
    st.markdown(
        '<div class="how-guide-anchor" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    with st.expander("ℹ️ How MacroMatch Works — 3 simple steps", expanded=False):
        # Built as one unindented HTML string: Markdown ends an HTML block at
        # the first blank line and would turn any indented remainder into code.
        steps = [
            ("1", "Choose your usual product",
             "Pick from 30 everyday foods — paneer, oats, whey, tofu, dals and more."),
            ("2", "Set the destination",
             "14 cities, from Delhi and Mumbai to Jaipur, Kolkata and Kochi."),
            ("3", "Filter and prioritise",
             "Add vegan, gluten-free or keto rules, exclude allergens, and pick what matters most."),
        ]
        steps_html = "".join(
            f'<div class="step"><div class="step-num">{n}</div>'
            f"<h3>{title}</h3><p>{body}</p></div>"
            for n, title, body in steps
        )
        facts_html = "".join(
            f"<span>{fact}</span>"
            for fact in ("30 products", "14 cities", "3 ranked matches",
                         "Diet &amp; allergen aware")
        )
        st.markdown(
            '<div class="landing">'
            '<div class="landing-eyebrow">Ready when you are</div>'
            '<div class="landing-title">Three local swaps, ranked by your macros.</div>'
            '<p class="landing-sub">Tell MacroMatch what you normally eat, where you '
            "are going, and what to avoid. It compares protein, carbs, fat, fibre and "
            "calories, applies your diet and allergy rules, then explains each pick "
            "in plain language.</p>"
            f'<div class="steps">{steps_html}</div>'
            '<div class="landing-cta"><span class="arrow">&larr;</span>'
            "<span>Use the search card above, then hit <strong>Find Alternatives</strong>."
            "</span></div>"
            f'<div class="landing-facts">{facts_html}</div>'
            "</div>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────
# Hero header
# ─────────────────────────────────────────────
st.markdown(f"""
<div class="hero-block">
    <span class="logo-pill">
        <img src="{LOGO_SRC}" alt="MacroMatch logo" class="hero-logo">
    </span>
    <div class="hero-title">MacroMatch</div>
    <div class="hero-tagline">Your macros, anywhere.</div>
</div>
""", unsafe_allow_html=True)
st.markdown('<hr class="section-divider hero-divider">', unsafe_allow_html=True)

# Pinned directly under the header, before the search card.
render_how_it_works()


# ─────────────────────────────────────────────
# Sidebar — profile + saved matches only
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div class="sidebar-header">
        <span class="logo-pill">
            <img src="{LOGO_SRC}" alt="MacroMatch logo" class="sidebar-logo">
        </span>
        <div class="sidebar-text">
            <div class="sidebar-title">MacroMatch</div>
            <div class="sidebar-tagline">Your macros, anywhere.</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ─── Signed-in welcome + sign out (Supabase Auth) ───────────────
    _auth_user = st.session_state.get("supabase_user")
    _metadata = getattr(_auth_user, "user_metadata", None) or {}
    _email_local = CURRENT_USER_EMAIL.split("@")[0] if CURRENT_USER_EMAIL else "there"
    _raw_name = _metadata.get("full_name") or _email_local
    _display_name = html.escape(str(_raw_name).strip() or _email_local)
    _display_email = html.escape(CURRENT_USER_EMAIL)
    st.markdown(f"""
    <div class="sidebar-welcome">
        <div class="welcome-name">Welcome, {_display_name}</div>
        <div class="welcome-email">{_display_email}</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("🚪 Sign out", key="supabase_sign_out"):
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
        st.session_state["supabase_user"] = None
        st.session_state["supabase_access_token"] = None
        st.session_state["supabase_refresh_token"] = None
        st.session_state["supabase_user_name"] = None
        st.session_state["supabase_recovery_mode"] = False
        st.session_state.pop("_preferences_user_id", None)
        st.session_state.pop("_preferences_filters_pending", None)
        st.rerun()
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ─── Per-user saved matches history (Supabase, user_id-keyed) ────────
    # Open the expander automatically on the rerun right after a save so the
    # newly inserted row is immediately visible.
    with st.expander(
        "🕘 My saved matches",
        expanded=bool(st.session_state.get("saved_match_flash")),
    ):
        saved_matches_slot = st.empty()
        render_saved_matches(saved_matches_slot)

    # ─── Product guide (moved here from the bottom of the main page) ─────
    product_details = load_product_details()
    st.markdown("### 📖 Product guide")
    st.caption(
        "New to a food? Browse the catalogue to see what it looks like, "
        "its macros per 100 g, diet rules and allergens."
    )
    if st.toggle(f"Show all {len(product_details)} products", key="show_product_guide"):
        render_product_guide(product_details)

    # ─── Daily macro goal ──────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("🎯 Daily Macro Target", expanded=False):
        st.number_input(
            "Daily Protein Goal (g)",
            min_value=1,
            max_value=500,
            value=120,
            step=5,
            key="daily_protein_goal",
        )
        st.number_input(
            "Daily Calorie Goal (kcal)",
            min_value=500,
            max_value=10000,
            value=2000,
            step=100,
            key="daily_calorie_goal",
        )
        if st.button(
            "💾 Save Target",
            type="primary",
            use_container_width=True,
            key="save_macro_target",
        ):
            _save_user_metadata(
                {
                    "daily_protein_goal": int(st.session_state["daily_protein_goal"]),
                    "daily_calorie_goal": int(st.session_state["daily_calorie_goal"]),
                },
                "Target saved!",
            )

    # ─── Reusable filter defaults ──────────────────────────────────────
    with st.expander("⚙️ Default Diet & Allergens", expanded=False):
        st.selectbox(
            "Default diet rule",
            options=["None", *DIET_LABELS.values()],
            key="default_diet_select",
            on_change=_apply_default_diet,
        )
        st.multiselect(
            "Default allergens",
            options=ALLERGEN_OPTIONS,
            format_func=lambda x: {
                "soy": "🫘 Soy", "nuts": "🥜 Nuts", "dairy": "🥛 Dairy"
            }[x],
            key="default_allergens_select",
            on_change=_apply_default_allergens,
        )
        if st.button(
            "💾 Save Preferences",
            type="primary",
            use_container_width=True,
            key="save_preferences",
        ):
            # Apply immediately as well as persisting, so the main filters show
            # the saved defaults on this same rerun.
            _apply_default_diet()
            _apply_default_allergens()
            _save_user_metadata(
                {
                    "default_diet": st.session_state["default_diet_select"],
                    "default_allergens": list(
                        st.session_state.get("default_allergens_select") or []
                    ),
                },
                "Preferences saved!",
            )

    # ─── Bottom activity footer ────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    _saved_count = len(get_saved_matches(CURRENT_USER_ID) or [])
    st.markdown(
        f"""
        <div class="sidebar-stats">
            <div class="stats-row">
                <span class="stats-label">Saved matches</span>
                <span class="stats-value">{_saved_count}</span>
            </div>
            <div class="stats-tip">
                Tip: Click any product in the guide to load it instantly.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(key="search_controls")
def render_search_controls(all_foods: list[str], all_cities: list[str]) -> None:
    """Isolated real-time food/city autocomplete.

    st_searchbox calls search_foods/search_cities on every keystroke and reruns
    only this fragment, so the sidebar, Supabase queries, saved matches, and
    results stay untouched while the dropdown updates instantly.
    """
    # ── Food ────────────────────────────────────────────────────────────
    selected_product = _canonical_value(
        st.session_state["selected_product"], PRODUCT_DISPLAY_ALIASES
    )
    st.session_state["selected_product"] = selected_product

    food_defaults = [
        _canonical_value(label, PRODUCT_DISPLAY_ALIASES)
        for label in POPULAR_PRODUCTS
        if _canonical_value(label, PRODUCT_DISPLAY_ALIASES) in all_foods
    ]
    food_pick = st_searchbox(
        search_foods,
        placeholder="🔍 Type food name (e.g., Cashews, Oats)...",
        default=None,
        default_searchterm=st.session_state["food_search_input"],
        default_options=food_defaults,
        edit_after_submit="option",
        clear_on_submit=False,
        style_overrides=_SEARCHBOX_STYLE_OVERRIDES,
        rerun_scope="fragment",
        debounce=80,
        reset_function=_reset_food_search_input,
        key=f"food_search_{st.session_state['food_box_ver']}",
    )
    if food_pick:
        selected_food = str(food_pick).strip()
        if selected_food:
            canonical_food = _canonical_value(selected_food, PRODUCT_DISPLAY_ALIASES)
            st.session_state["selected_product"] = canonical_food
            if canonical_food != selected_product:
                _sync_food_selection(canonical_food, selected_food)
                # A full pass is only needed to dismiss the outer swaps view;
                # on home the fragment rerun triggered by st_searchbox is enough.
                if st.session_state.get("show_swaps_results"):
                    _reset_swaps_view()
                    st.rerun()

    selected_product = st.session_state["selected_product"]
    st.session_state["product_select"] = selected_product
    st.markdown(
        '<div class="selected-value">Selected food: '
        f"<strong>{html.escape(selected_product)}</strong></div>",
        unsafe_allow_html=True,
    )

    # Six quick-tap favourites stay directly below the live searchbox.
    product_pairs = [
        (label, _canonical_value(label, PRODUCT_DISPLAY_ALIASES))
        for label in POPULAR_PRODUCTS
        if _canonical_value(label, PRODUCT_DISPLAY_ALIASES) in all_foods
    ]
    if product_pairs:
        product_display_options = [label for label, _ in product_pairs]
        _current_product_display = _display_label(
            selected_product,
            PRODUCT_DISPLAY_ALIASES,
            product_display_options,
        )
        if _current_product_display not in product_display_options:
            _current_product_display = None
        # Keep both pill groups on the current choice even when it came from
        # the searchbox, sidebar guide, or a restored saved match.
        st.session_state["quick_food_pills"] = _current_product_display
        st.pills(
            "Quick food picks",
            options=product_display_options,
            selection_mode="single",
            default=_current_product_display,
            label_visibility="collapsed",
            key="quick_food_pills",
            on_change=select_food_callback,
            args=("quick_food_pills",),
        )

    with st.expander(
        f"📋 Browse all available foods ({len(all_foods)} items)" + ("\u200b" * st.session_state.food_browse_ver), expanded=False
    ):
        _all_food_default = selected_product if selected_product in all_foods else None
        st.session_state["all_food_pills"] = _all_food_default
        st.pills(
            "All foods",
            options=all_foods,
            selection_mode="single",
            default=_all_food_default,
            label_visibility="collapsed",
            key="all_food_pills",
            on_change=select_food_callback,
            args=("all_food_pills",),
        )

    # ── City ────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="search-card-title search-card-title--spaced">DESTINATION</div>',
        unsafe_allow_html=True,
    )
    selected_city = _canonical_value(
        st.session_state["selected_city"], CITY_DISPLAY_ALIASES
    )
    st.session_state["selected_city"] = selected_city

    city_defaults = []
    for label in POPULAR_CITIES:
        canonical = _canonical_value(label, CITY_DISPLAY_ALIASES)
        if canonical in all_cities and canonical not in city_defaults:
            city_defaults.append(canonical)

    city_pick = st_searchbox(
        search_cities,
        placeholder="🔍 Type city name (e.g., Delhi, Mumbai)...",
        default=None,
        default_searchterm=st.session_state["city_search_input"],
        default_options=city_defaults,
        edit_after_submit="option",
        clear_on_submit=False,
        style_overrides=_SEARCHBOX_STYLE_OVERRIDES,
        rerun_scope="fragment",
        debounce=80,
        reset_function=_reset_city_search_input,
        key=f"city_search_{st.session_state['city_box_ver']}",
    )
    if city_pick:
        selected_city_value = str(city_pick).strip()
        if selected_city_value:
            canonical_city = _canonical_value(selected_city_value, CITY_DISPLAY_ALIASES)
            st.session_state["selected_city"] = canonical_city
            if canonical_city != selected_city:
                _sync_city_selection(canonical_city, selected_city_value)

    selected_city = st.session_state["selected_city"]
    st.session_state["city_select"] = selected_city
    st.markdown(
        '<div class="selected-value">Selected city: '
        f"<strong>{html.escape(selected_city)}</strong></div>",
        unsafe_allow_html=True,
    )

    city_pairs = []
    for label in POPULAR_CITIES:
        canonical = _canonical_value(label, CITY_DISPLAY_ALIASES)
        if canonical in all_cities:
            city_pairs.append((label, canonical))
    if city_pairs:
        city_display_options = [label for label, _ in city_pairs]
        _current_city_display = _display_label(
            selected_city,
            CITY_DISPLAY_ALIASES,
            city_display_options,
        )
        if _current_city_display not in city_display_options:
            _current_city_display = None
        st.session_state["quick_city_pills"] = _current_city_display
        st.pills(
            "Quick city picks",
            options=city_display_options,
            selection_mode="single",
            default=_current_city_display,
            label_visibility="collapsed",
            key="quick_city_pills",
            on_change=select_city_callback,
            args=("quick_city_pills",),
        )

    with st.expander(
        f"📍 Browse all available cities ({len(all_cities)} cities)" + ("\u200b" * st.session_state.city_browse_ver), expanded=False
    ):
        _all_city_default = selected_city if selected_city in all_cities else None
        st.session_state["all_city_pills"] = _all_city_default
        st.pills(
            "All cities",
            options=all_cities,
            selection_mode="single",
            default=_all_city_default,
            label_visibility="collapsed",
            key="all_city_pills",
            on_change=select_city_callback,
            args=("all_city_pills",),
        )


# ─────────────────────────────────────────────
# Main area — touch-first search card + results
# ─────────────────────────────────────────────

with st.container(border=True):
    st.markdown(
        '<div class="search-card-title">YOUR PRODUCT — What do you normally eat?</div>',
        unsafe_allow_html=True,
    )
    try:
        with st.spinner(
            "Connecting to the backend — free hosting can take up to a minute to wake…"
        ):
            # Cached plain lists: built once, reused by every fragment rerun.
            all_foods = cached_all_foods()
            all_cities = cached_all_cities()
    except BackendUnavailable:
        st.error(
            f"⚠️ Cannot reach the backend at `{API_BASE}`.\n\n"
            "The free-tier API may be asleep or still starting. Retry in a "
            "moment; locally, start it with:\n\n"
            "`uvicorn backend.main:app --reload`"
        )
        if st.button("🔄 Retry", use_container_width=True):
            fetch_product_list.clear()
            cached_all_foods.clear()
            st.rerun()
        st.stop()

    if not all_foods:
        st.error("The backend returned an empty product list. Please try again.")
        st.stop()

    # Only this small fragment reruns on typing or pill taps; the sidebar,
    # Supabase queries, filters, and results below stay untouched. The fragment
    # publishes its canonical choices through Session State.
    render_search_controls(all_foods, all_cities)
    selected_product = st.session_state["selected_product"]
    selected_city = st.session_state["selected_city"]

    # Saved preferences are hydrated once per sign-in; mirror them into the
    # filter widgets here, before those widgets are instantiated.
    if st.session_state.pop("_preferences_filters_pending", False):
        _apply_default_diet()
        _apply_default_allergens()

    with st.expander("🥦 Filters — diet, allergens & priority", expanded=True):
        selected_diet_labels = st.pills(
            "Diet Rules",
            options=list(DIET_LABELS.values()),
            selection_mode="multi",
            label_visibility="collapsed",
            key="diet_pills",
        )
        selected_diet_labels = list(selected_diet_labels or [])
        _label_to_key = {v: k for k, v in DIET_LABELS.items()}
        selected_diets = [_label_to_key[lbl] for lbl in selected_diet_labels]

        selected_allergens = st.multiselect(
            "Allergens to avoid",
            options=ALLERGEN_OPTIONS,
            format_func=lambda x: {
                "soy": "🫘 Soy", "nuts": "🥜 Nuts", "dairy": "🥛 Dairy"
            }[x],
            key="allergen_select",
        )

        priority_label = st.radio(
            "What matters most in the match?",
            options=PRIORITY_KEYS,
            format_func=lambda k: PRIORITY_LABELS[k].replace(" ", "\u00a0", 1),
            index=2,   # default: balanced
            key="priority_radio",
        )

    if st.button(
        "🔍 Find Alternatives",
        use_container_width=True,
        type="primary",
        key="find_alternatives",
    ):
        st.session_state["show_swaps_results"] = True
        st.session_state.pop("match_result_data", None)  # force a fresh API call
        st.rerun()

    show_swaps_results = st.session_state["show_swaps_results"]


# ─────────────────────────────────────────────
# Main area — results
# ─────────────────────────────────────────────

selected_detail = product_details.get(selected_product)

if not show_swaps_results:
    # The 3-step guide is pinned above the search card; results follow immediately.
    if selected_detail:
        st.markdown("### 🥗 Your Regular Food")
        render_product_spotlight(
            selected_product,
            selected_detail,
            keto="keto" in selected_diets,
        )
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    render_footer()
    st.stop()


# ── Back to home ──────────────────────────────
# In the swaps view this stays at the very top, immediately before the results
# container. The regular-food card (including How to Eat / Use) is home-only.
_back_left, btn_col, _back_right = st.columns([2, 1, 2])
with btn_col:
    # No bordered container: only the styled button renders in this column.
    st.markdown(
        '<div class="back-home-marker" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    if st.button(
        "⌂ Back to home", key="back_to_home", help="Return to the start page"
    ):
        _reset_swaps_view()
        st.rerun()


# ── Call the API (result cached in session state so save-reruns keep the view)
if "match_result_data" not in st.session_state:
    with st.spinner("Searching for alternatives and generating explanations…"):
        response = call_api({
            "product":    selected_product,
            "city":       selected_city,
            "diet_rules": selected_diets,
            "allergens":  selected_allergens,
            "priority":   priority_label,
        })

    # ── Handle errors ─────────────────────────
    if response is None:
        st.error(
            f"⚠️ **Cannot reach the backend at `{API_BASE}`.**\n\n"
            "It may be starting up (free hosting sleeps after inactivity) or the "
            "URL may be wrong. Wait a minute and try again."
        )
        st.caption("Local dev: `python -m uvicorn backend.main:app --reload`")
        st.stop()

    if response.status_code == 404:
        detail = response.json().get("detail", {})
        err    = detail.get("error", "")
        msg    = detail.get("message", response.text)

        if err == "product_not_found":
            st.error(f"❌ **Product not found:** {msg}")
        elif err == "no_alternatives_found":
            st.warning(f"🔍 **No alternatives found:** {msg}")
        else:
            st.error(f"❌ {msg}")
        st.stop()

    if response.status_code == 422:
        # FastAPI validation errors arrive as a list of {loc, msg, type} objects.
        st.error("❌ **Invalid input.** Check your selections and try again.")
        with st.expander("Details"):
            st.json(response.json().get("detail", response.text))
        st.stop()

    if response.status_code != 200:
        st.error(f"❌ Unexpected error ({response.status_code}): {response.text}")
        st.stop()

    st.session_state["match_result_data"] = response.json()

# ── Parse response ────────────────────────────
data         = st.session_state["match_result_data"]
alternatives = data.get("alternatives", [])
orig_macros  = get_original_macros(selected_product)

# ── One results container: ranked cards + exact numbers in tabs ────────────
with st.container(border=True):
    st.markdown(
        '<div class="results-tabs-marker" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )

    # ── Summary strip ─────────────────────────────
    # Built as one unindented string: a whitespace-only line would end the Markdown
    # HTML block and turn the closing tags into a code block.
    diet_text = (
        f"&nbsp;·&nbsp; Diet: {', '.join(DIET_LABELS[d] for d in selected_diets)}"
        if selected_diets else ""
    )
    allergen_text = (
        f"&nbsp;·&nbsp; Avoiding: {', '.join(selected_allergens)}"
        if selected_allergens
        else ""
    )
    summary_html = (
        '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;'
        'padding:0.75rem 1.25rem;margin-bottom:1.25rem;display:flex;'
        'align-items:center;gap:1rem;">'
        '<span style="font-size:1.5rem">✅</span>'
        '<div>'
        '<span style="color:#f1f5f9;font-weight:600;">'
        f"Top {len(alternatives)} Swap{'s' if len(alternatives) != 1 else ''} for <em>{selected_product}</em> in {selected_city}"
        '</span><br>'
        '<span style="color:var(--text-muted);font-size:0.85rem;">'
        f"Priority: {PRIORITY_LABELS[priority_label].split('—')[0].strip()}"
        f"{diet_text}{allergen_text}"
        '</span>'
        '</div></div>'
    )
    st.markdown(summary_html, unsafe_allow_html=True)

    # ─── Saved-match confirmation (surfaced after per-card saves) ─────────
    if st.session_state.pop("saved_match_flash", None):
        st.success("Saved to your history — only your own account can see it.")

    # ── Per-serving toggle (shared by all comparison cards) ────────────────
    _srv_col, _lbl_col = st.columns([2, 5], gap="small")
    with _srv_col:
        per_serving_on = st.toggle(
            "Per Serving",
            value=False,
            key="per_serving_toggle",
            help="Switch between Per 100 g (default) and the product's defined serving size",
        )
    _unit_label = "per serving" if per_serving_on else "per 100 g"
    keto_on     = "keto" in selected_diets   # used for net-carbs highlight


    def _scale(macros: dict, product_name: str) -> dict:
        """Return a copy of macros dict scaled to serving size (if toggle is on)."""
        if not per_serving_on:
            return macros
        srv_g = PRODUCT_SERVING_G.get(product_name, 100)
        factor = srv_g / 100.0
        return {
            "protein":  round(macros["protein"]  * factor, 1),
            "carbs":    round(macros["carbs"]    * factor, 1),
            "fat":      round(macros["fat"]      * factor, 1),
            "fiber":    round(macros["fiber"]    * factor, 1),
            "calories": round(macros["calories"] * factor),
        }


    def _delta_html(label: str, alt_val: float, orig_val: float | None,
                    unit: str = "g", higher_is_better: bool = False) -> str:
        """Compact trade-off badge comparing an alternative with the regular food."""
        if orig_val is None:
            return ""
        diff = round(float(alt_val) - float(orig_val), 1)
        if abs(diff) < 0.05:
            return f'<span class="swap-delta">±0{unit} {label}</span>'
        sign = "+" if diff > 0 else "−"
        good = diff > 0 if higher_is_better else diff < 0
        cls = "swap-delta swap-delta--good" if good else "swap-delta swap-delta--warn"
        return f'<span class="{cls}">{sign}{abs(diff):g}{unit} {label}</span>'


    orig_scaled = _scale(orig_macros, selected_product) if orig_macros else None

    tab_swaps, tab_nutrition = st.tabs(
        ["🏆 Ranked Swaps (Top 3)", "📊 Detailed Nutrition Comparison"]
    )

    with tab_swaps:
        # ── Ranked swaps — 3 equal columns on desktop, stacked on mobile ───────
        cols = st.columns(3)

        for col, alt in zip(cols, alternatives[:3]):
            with col:
                rank_i = max(0, min(int(alt.get("rank", 1)) - 1, 2))
                color  = RANK_COLORS[rank_i]
                label  = RANK_LABELS[rank_i]
                score_pct = max(0, min(100, round((1 - float(alt["match_score"])) * 100)))
                match_pct_str = f"{score_pct}% match"

                nutr        = alt["nutrition"]
                nutr_scaled = _scale(nutr, alt["name"])

                thumb = product_image_src(alt["name"])
                if thumb:
                    thumb_html = (
                        f'<img class="swap-thumb" src="{thumb}" '
                        f'alt="{html.escape(alt["name"], quote=True)}">'
                    )
                else:
                    thumb_html = (
                        '<div class="swap-thumb swap-thumb-fallback">'
                        f'{PRODUCT_EMOJI.get(alt["name"], "🥗")}</div>'
                    )

                alt_local = PRODUCT_LOCAL_NAMES.get(alt["name"], "")
                local_tag = (
                    f'<span class="local-name-tag" style="margin-left:0;">🗺️ {html.escape(alt_local)}</span>'
                    if alt_local else ""
                )
                meta_text = html.escape(
                    f"{alt['category']} · Available in: {alt['cities'].replace(',', ', ')}"
                )

                macro_html = (
                    f'<span class="swap-macro-pill protein">P {nutr_scaled["protein"]:g}g</span>'
                    f'<span class="swap-macro-pill carbs">C {nutr_scaled["carbs"]:g}g</span>'
                    f'<span class="swap-macro-pill fat">F {nutr_scaled["fat"]:g}g</span>'
                    f'<span class="swap-macro-pill calories">{nutr_scaled["calories"]:g} kcal</span>'
                )
                # Always based on 100 g, independent of the per-serving toggle.
                protein_goal_html = _protein_goal_badge(nutr["protein"])

                delta_html = ""
                if orig_scaled:
                    delta_html = (
                        '<div class="swap-deltas">'
                        + _delta_html("Protein", nutr_scaled["protein"], orig_scaled["protein"],
                                      higher_is_better=True)
                        + _delta_html("Carbs", nutr_scaled["carbs"], orig_scaled["carbs"])
                        + _delta_html("Fat", nutr_scaled["fat"], orig_scaled["fat"])
                        + _delta_html("kcal", nutr_scaled["calories"], orig_scaled["calories"],
                                      unit="")
                        + "</div>"
                    )

                explanation = str(alt.get("explanation", "")).strip()
                if explanation:
                    # Strip raw-score artifacts leaked by older backend prompts.
                    explanation = re.sub(
                        r"\(?\s*match\s+score\s*[:\-]?\s*\d+\.\d+\s*\)?",
                        f"({match_pct_str})",
                        explanation,
                        flags=re.IGNORECASE,
                    )
                    explanation = re.sub(r"\b0\.\d{3,6}\b", "", explanation).strip()
                if not explanation:
                    explanation = (
                        f"A strong local swap for {selected_product} in {selected_city}, "
                        f"chosen for your {PRIORITY_LABELS[priority_label].split('—')[0].strip().lower()} priority."
                    )

                top_cls = " swap-card--top" if rank_i == 0 else ""
                with st.container(border=True):
                    st.markdown(
                        f'<div class="swap-card{top_cls}">'
                        '<div class="swap-card-header">'
                        f'<span class="swap-rank-pill" style="background:{color}22;color:{color};">{label}</span>'
                        f'<span class="swap-score-pill">{score_pct}% Match</span>'
                        '</div>'
                        f'{thumb_html}'
                        f'<p class="swap-name">{PRODUCT_EMOJI.get(alt["name"], "🥗")} '
                        f'{html.escape(alt["name"])}</p>'
                        f'{f"<p>{local_tag}</p>" if local_tag else ""}'
                        f'<p class="swap-meta">{meta_text}</p>'
                        f'<div class="swap-macros">{macro_html}</div>'
                        f'{protein_goal_html}'
                        f'{delta_html}'
                        '<div class="swap-explanation">'
                        f'<strong>Why this swap:</strong> {html.escape(explanation)}'
                        '<div style="margin-top:0.6rem;padding-top:0.5rem;'
                        'border-top:1px solid rgba(126,226,168,0.22);'
                        'font-size:0.82rem;color:#94A3B8;">'
                        f'📊 {_unit_label} · <strong style="color:#7EE2A8;">{match_pct_str}</strong>'
                        '</div>'
                        '</div>'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "💾 Save Match",
                        key=f"save_swap_{rank_i + 1}",
                        use_container_width=True,
                        type="primary",
                    ):
                        if save_match(
                            CURRENT_USER_ID,
                            selected_product,
                            selected_city,
                            selected_diets,
                            selected_allergens,
                            priority_label,
                            [alt],
                        ):
                            st.session_state["saved_match_flash"] = True
                            st.rerun()

    with tab_nutrition:
        # ── Exact macro table + chart (second tab) ────────────────────────────
        if not orig_scaled:
            st.info("Original product macros not available for comparison.")
        else:
            for swap in alternatives[:3]:
                swap_nutr = _scale(swap["nutrition"], swap["name"])
                orig_nc = max(
                    0.0, round(orig_scaled["carbs"] - orig_scaled["fiber"], 1)
                )
                swap_nc = max(
                    0.0, round(swap_nutr["carbs"] - swap_nutr["fiber"], 1)
                )

                st.markdown(
                    f"#### {PRODUCT_EMOJI.get(swap['name'], '🥗')} "
                    f"{html.escape(swap['name'])}"
                )
                st.caption(
                    f"{html.escape(swap.get('category', ''))} · {_unit_label}"
                )

                col_table, col_chart = st.columns([1, 1], gap="medium")
                with col_table:
                    st.markdown(f"**Nutrition Breakdown** *({_unit_label})*")
                    orig_label = f"🥗 {selected_product}"
                    swap_label = f"✨ {swap['name']}"
                    comparison_df = pd.DataFrame(
                        {
                            "Nutrient": [
                                "Protein (g)",
                                "Carbs (g)",
                                "Fat (g)",
                                "Fiber (g)",
                                "⚡ Net Carbs (g)",
                                "Calories (kcal)",
                            ],
                            orig_label: [
                                orig_scaled["protein"],
                                orig_scaled["carbs"],
                                orig_scaled["fat"],
                                orig_scaled["fiber"],
                                orig_nc,
                                orig_scaled["calories"],
                            ],
                            swap_label: [
                                swap_nutr["protein"],
                                swap_nutr["carbs"],
                                swap_nutr["fat"],
                                swap_nutr["fiber"],
                                swap_nc,
                                swap_nutr["calories"],
                            ],
                        }
                    )
                    st.dataframe(
                        comparison_df.set_index("Nutrient"),
                        use_container_width=True,
                        column_config={
                            orig_label: st.column_config.NumberColumn(
                                orig_label, format="%.1f"
                            ),
                            swap_label: st.column_config.NumberColumn(
                                swap_label, format="%.1f"
                            ),
                        },
                    )

                with col_chart:
                    st.markdown(f"**Nutrient Chart** *(excl. calories · {_unit_label})*")
                    import altair as alt_chart

                    chart_df = pd.DataFrame(
                        {
                            orig_label: [
                                orig_scaled["protein"],
                                orig_scaled["carbs"],
                                orig_scaled["fat"],
                                orig_scaled["fiber"],
                            ],
                            swap_label: [
                                swap_nutr["protein"],
                                swap_nutr["carbs"],
                                swap_nutr["fat"],
                                swap_nutr["fiber"],
                            ],
                        },
                        index=["Protein", "Carbs", "Fat", "Fiber"],
                    )
                    chart_long = (
                        chart_df.reset_index()
                        .melt(id_vars="index", var_name="Product", value_name="Value (g)")
                        .rename(columns={"index": "Nutrient"})
                    )
                    bars = (
                        alt_chart.Chart(chart_long)
                        .mark_bar()
                        .encode(
                            x=alt_chart.X(
                                "Nutrient:N",
                                sort=["Protein", "Carbs", "Fat", "Fiber"],
                                axis=alt_chart.Axis(
                                    labelAngle=0,
                                    labelFontSize=12,
                                    titleFontSize=13,
                                    labelPadding=6,
                                ),
                                title=None,
                            ),
                            xOffset=alt_chart.XOffset("Product:N"),
                            y=alt_chart.Y(
                                "Value (g):Q", axis=alt_chart.Axis(labelFontSize=11)
                            ),
                            color=alt_chart.Color(
                                "Product:N",
                                legend=alt_chart.Legend(
                                    orient="bottom",
                                    labelFontSize=11,
                                    titleFontSize=11,
                                ),
                            ),
                            tooltip=["Nutrient:N", "Product:N", "Value (g):Q"],
                        )
                        .properties(height=220)
                        .configure_view(strokeWidth=0)
                        .configure_axis(grid=True, gridColor="#334155")
                        .configure_legend(labelColor="#cbd5e1", titleColor="#b0b8c4")
                    )
                    st.altair_chart(bars, use_container_width=True)

                nc_class = "net-carbs-keto" if keto_on else "net-carbs-normal"
                st.markdown(
                    f'<span class="{nc_class}">⚡ Net Carbs {swap_nc:g} g '
                    f"({_unit_label})</span>",
                    unsafe_allow_html=True,
                )
                st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
render_footer()
