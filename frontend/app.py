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
import threading
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
# sidebar, and it also closes the sidebar after any card "Select" tap.
# "View Details" uses the dedicated collapse component below instead.
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

    // Wishlist / catalogue Select buttons are Streamlit widgets that
    // trigger a full rerun; a delegated parent-document listener is the
    // reliable place to collapse the mobile sidebar right after the tap.
    // View Details uses the dedicated details-view collapse component instead.
    if (!host.__mmGuideSelectBound) {
        host.__mmGuideSelectBound = true;
        host.__mmGuideSelectHandler = function (event) {
            if (host.innerWidth > MOBILE_MAX_WIDTH) { return; }
            var target = event.target && event.target.closest
                ? event.target.closest('button') : null;
            if (!target) { return; }
            var label = (target.textContent || '').trim();
            if (label !== 'Select') { return; }
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

# Fired once on the rerun that opens a Product Details page. The guide tap
# listener above is intentionally limited to "Select" so it cannot double-fire.
_MOBILE_DETAILS_COLLAPSE_JS = """
<script>
if (window.parent.innerWidth <= 768) {
    const btn = window.parent.document.querySelector(
        '[data-testid="stSidebarCollapseButton"] button, ' +
        '[data-testid="stSidebar"] button[kind="header"]'
    );
    if (btn) btn.click();
}
</script>
"""

# Touch-first defaults shared by the logged-out and signed-in screens.
# ``touch-action: manipulation`` removes the mobile 300 ms double-tap zoom wait,
# and the mobile media query drops GPU-heavy blur/transitions on low-end phones.
_TOUCH_FIRST_CSS = """
button,
[data-baseweb="tab"],
div[data-testid="stCheckbox"] label {
    touch-action: manipulation !important;
    -webkit-tap-highlight-color: transparent !important;
    user-select: none !important;
    -webkit-user-select: none !important;
}
@media (max-width: 768px) {
    html body *,
    html body *::before,
    html body *::after {
        backdrop-filter: none !important;
        -webkit-backdrop-filter: none !important;
        transition: none !important;
    }
}
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
            "touchAction": "manipulation",
            "WebkitTapHighlightColor": "transparent",
            "userSelect": "none",
            # Keep the searchbox hover desktop-only; phones fire the click on
            # the first tap instead of burning it on a sticky hover state.
            "@media (hover: hover)": {"&:hover": {"border": "1px solid #2EA043"}},
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

# Injected once for every screen (auth + dashboard); ``!important`` keeps these
# interaction defaults ahead of the theme CSS that follows.
st.markdown(f"<style>{_TOUCH_FIRST_CSS}</style>", unsafe_allow_html=True)

# Publish the viewport width into the URL so Python callbacks can pick the
# right catalogue page size (4 cards on phones, 6 on desktop) from the tap.
_VIEWPORT_DETECT_JS = """
<script>
(function () {
    function publish() {
        try {
            var win = window.parent || window;
            var mobile = win.innerWidth <= 768 ? "1" : "0";
            var url = new URL(win.location.href);
            if (url.searchParams.get("mm_mobile") !== mobile) {
                url.searchParams.set("mm_mobile", mobile);
                win.history.replaceState(win.history.state, "", url.toString());
                // Streamlit syncs st.query_params from the parent URL on popstate.
                win.dispatchEvent(
                    new PopStateEvent("popstate", { state: win.history.state })
                );
            }
        } catch (e) { /* non-browser preview: keep the desktop default */ }
    }
    var win = window.parent || window;
    publish();
    if (!win.__mmViewportListener) {
        win.addEventListener("resize", publish);
        win.__mmViewportListener = true;
    }
})();
</script>
"""
# The viewport component is rendered by _render_deferred_components() at the
# bottom so it never introduces blank space above a dedicated page's controls.

# ── Brand logo ──────────────────────────────────────────────────────────────
# The source PNG has a baked-in white background. Convert it to true alpha so
# it blends into dark surfaces (auth card and dashboard header) cleanly.
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "macromatch_logo.png"


@st.cache_resource(show_spinner=False)
def _transparent_logo_data_url(path: Path) -> str:
    """Cached base64 PNG data URI for the logo (used by PWA + app chrome)."""
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
# PWA / Android APK packaging bootstrap
# ─────────────────────────────────────────────
# components.html renders in an iframe, so the tags are written into the parent
# Streamlit document from JavaScript. This keeps the manifest installable while
# still being injected from a single zero-height component.
_PWA_HEAD_INJECTION_JS = ""
_PWA_INSTALL_BUTTON_JS = ""

if LOGO_SRC:
    _PWA_MANIFEST = {
        "name": "MacroMatch — Your macros, anywhere.",
        "short_name": "MacroMatch",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0D1117",
        "theme_color": "#0D1117",
        "icons": [
            {
                "src": LOGO_SRC,
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": LOGO_SRC,
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    _PWA_MANIFEST_HREF = "data:application/manifest+json;base64," + base64.b64encode(
        json.dumps(_PWA_MANIFEST, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    _PWA_HEAD_INJECTION_JS = """
    <script>
    (function () {
        var MANIFEST_HREF = __MM_MANIFEST_HREF__;
        var ICON_HREF = __MM_ICON_HREF__;
        var INSTALL_KEY = '__mmDeferredInstallPrompt';

        function parentWindow() {
            try {
                return (window.parent && window.parent.document) ? window.parent : window;
            } catch (e) {
                return window;
            }
        }

        function setMeta(name, content) {
            var doc = parentWindow().document;
            if (!doc || !doc.head) { return; }
            var meta = doc.querySelector('meta[name="' + name + '"]');
            if (!meta) {
                meta = doc.createElement('meta');
                meta.setAttribute('name', name);
                doc.head.appendChild(meta);
            }
            if (meta.getAttribute('content') !== content) {
                meta.setAttribute('content', content);
            }
        }

        function setLink(rel, href) {
            var doc = parentWindow().document;
            if (!doc || !doc.head) { return; }
            var link = doc.querySelector('link[rel="' + rel + '"]');
            if (!link) {
                link = doc.createElement('link');
                link.setAttribute('rel', rel);
                doc.head.appendChild(link);
            }
            if (link.getAttribute('href') !== href) {
                link.setAttribute('href', href);
            }
            link.setAttribute('data-mm-pwa', '1');
        }

        setLink('manifest', MANIFEST_HREF);
        setLink('apple-touch-icon', ICON_HREF);
        setMeta('theme-color', '#0D1117');
        setMeta('apple-mobile-web-app-capable', 'yes');

        // Capture the Android install prompt once and stash it on the parent
        // window; both the sidebar tap and the install page can trigger it.
        var parent = parentWindow();
        if (!parent.__mmPwaInstallListener) {
            parent.addEventListener('beforeinstallprompt', function (event) {
                event.preventDefault();
                parent[INSTALL_KEY] = event;
                if (window !== parent) { window[INSTALL_KEY] = event; }
            });
            parent.__mmPwaInstallListener = true;
        }
        if (!parent.__mmPwaInstalledListener) {
            parent.addEventListener('appinstalled', function () {
                parent[INSTALL_KEY] = null;
                parent.__mmInstallPromptActive = false;
                if (window !== parent) { window[INSTALL_KEY] = null; }
            });
            parent.__mmPwaInstalledListener = true;
        }

        if (!parent.__mmTriggerInstallPrompt) {
            parent.__mmTriggerInstallPrompt = function () {
                if (parent.__mmInstallPromptActive) { return false; }
                var promptEvent = parent[INSTALL_KEY];
                if (!promptEvent || typeof promptEvent.prompt !== 'function') {
                    return false;
                }
                parent.__mmInstallPromptActive = true;
                var finish = function () {
                    parent[INSTALL_KEY] = null;
                    parent.__mmInstallPromptActive = false;
                    if (window !== parent) { window[INSTALL_KEY] = null; }
                };
                try {
                    var choicePromise = promptEvent.prompt();
                    if (choicePromise && typeof choicePromise.then === 'function') {
                        choicePromise.then(finish).catch(finish);
                    } else if (promptEvent.userChoice && typeof promptEvent.userChoice.then === 'function') {
                        promptEvent.userChoice.then(finish).catch(finish);
                    } else {
                        finish();
                    }
                    return true;
                } catch (e) {
                    parent.__mmInstallPromptActive = false;
                    return false;
                }
            };
        }

        // The sidebar button is a Streamlit widget, so a capture-phase listener
        // on the parent document keeps the native prompt inside the user tap.
        if (!parent.__mmSidebarInstallBound) {
            parent.__mmSidebarInstallBound = true;
            parent.document.addEventListener('click', function (event) {
                var target = event.target && event.target.closest
                    ? event.target.closest('button')
                    : null;
                if (!target || !target.textContent) { return; }
                if (target.textContent.indexOf('Install Mobile App') < 0) { return; }
                if (typeof parent.__mmTriggerInstallPrompt === 'function') {
                    parent.__mmTriggerInstallPrompt();
                }
            }, true);
        }
    })();
    </script>
    """.replace(
        "__MM_MANIFEST_HREF__", json.dumps(_PWA_MANIFEST_HREF)
    ).replace("__MM_ICON_HREF__", json.dumps(LOGO_SRC))

    _PWA_INSTALL_BUTTON_JS = """
    <script>
    (function () {
        var KEY = '__mmDeferredInstallPrompt';
        var SLOT_ID = 'mm-pwa-install-slot';
        var BUTTON_ID = 'mm-native-install-button';

        function parentWindow() {
            try {
                return (window.parent && window.parent.document) ? window.parent : window;
            } catch (e) {
                return window;
            }
        }

        function ensureButton() {
            var parent = parentWindow();
            var doc = parent.document;
            if (!doc) { return false; }
            var slot = doc.getElementById(SLOT_ID);
            if (!slot) { return false; }

            var button = doc.getElementById(BUTTON_ID);
            if (!button) {
                button = doc.createElement('button');
                button.id = BUTTON_ID;
                button.type = 'button';
                button.textContent = '📲 Install app';
                button.style.cssText = [
                    'width:100%',
                    'min-height:42px',
                    'margin-top:10px',
                    'padding:8px 12px',
                    'border-radius:10px',
                    'border:1px solid #2EA043',
                    'background:rgba(46,160,67,0.16)',
                    'color:#A7F3D0',
                    'font-weight:700',
                    'cursor:pointer',
                    'display:none'
                ].join(';');
                button.addEventListener('click', function () {
                    if (typeof parent.__mmTriggerInstallPrompt === 'function') {
                        if (parent.__mmTriggerInstallPrompt()) {
                            button.textContent = 'Installing…';
                            return;
                        }
                    }
                    button.textContent = 'Use your browser menu to install';
                });
                slot.appendChild(button);
            }

            var canPrompt = !!(parent[KEY] && typeof parent[KEY].prompt === 'function');
            button.style.display = canPrompt ? 'inline-flex' : 'none';
            return true;
        }

        var parent = parentWindow();
        ensureButton();

        // Opening the dedicated install page attempts the native prompt too;
        // if the browser requires another user gesture, the button above is
        // the visible fallback.
        if (!parent.__mmInstallAutoTried) {
            parent.__mmInstallAutoTried = true;
            if (typeof parent.__mmTriggerInstallPrompt === 'function') {
                parent.__mmTriggerInstallPrompt();
            }
        }

        var tries = 0;
        var timer = parent.setInterval(function () {
            if (ensureButton() || ++tries > 100) { parent.clearInterval(timer); }
        }, 100);
    })();
    </script>
    """

# All zero-height JS components are rendered in one deferred block at the very
# end of the script (or immediately before an early stop). Keeping them out of
# the page body prevents blank vertical gaps above the top-right back button.
_DEFERRED_COLLAPSE_FLAGS = (
    "_collapse_sidebar_for_details",
    "_collapse_sidebar_for_wishlist",
    "_collapse_sidebar_for_catalogue",
    "_collapse_sidebar_for_install",
)


def _render_deferred_components() -> None:
    """Render every parent-document JS helper after the visible page content."""
    components.html(_VIEWPORT_DETECT_JS, height=0, scrolling=False)

    if _PWA_HEAD_INJECTION_JS:
        components.html(_PWA_HEAD_INJECTION_JS, height=0, scrolling=False)

    components.html(_MOBILE_SIDEBAR_TOGGLE_JS, height=0, scrolling=False)

    collapse_requested = [
        st.session_state.pop(flag, False) for flag in _DEFERRED_COLLAPSE_FLAGS
    ]
    if any(collapse_requested):
        components.html(_MOBILE_DETAILS_COLLAPSE_JS, height=0, scrolling=False)

    if st.session_state.get("show_install_page", False) and _PWA_INSTALL_BUTTON_JS:
        components.html(_PWA_INSTALL_BUTTON_JS, height=0, scrolling=False)


def _stop_after_deferred_components() -> None:
    """Flush deferred JS helpers, then halt this Streamlit run."""
    _render_deferred_components()
    st.stop()


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
        _stop_after_deferred_components()
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


def _normalize_wishlist(value) -> list[str]:
    """Accept a stored wishlist list (or single name) and drop empty values."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if item]


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
    st.session_state["wishlist"] = _normalize_wishlist(metadata.get("wishlist", []))

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


def _set_auth_view(view: str) -> None:
    """Auth navigation callback; st.button supplies the single rerun."""
    st.session_state.auth_view = view


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
        _stop_after_deferred_components()
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

    /* Keep the Streamlit top header transparent and compact without pushing content down */
header[data-testid="stHeader"] {
    background: transparent !important;
    height: 2.6rem !important;
    min-height: 2.6rem !important;
}

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

    # Last word on touch behaviour for the auth screen as well.
    st.markdown(f"<style>{_TOUCH_FIRST_CSS}</style>", unsafe_allow_html=True)

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
                    st.button(
                        "Forgot Password",
                        key="forgot_link",
                        on_click=_set_auth_view,
                        args=("forgot",),
                    )
                with col2:
                    st.button(
                        "Reset Password",
                        key="reset_link",
                        on_click=_set_auth_view,
                        args=("reset",),
                    )

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

                st.button(
                    "← Back to Sign in",
                    key="back_from_forgot",
                    on_click=_set_auth_view,
                    args=("signin",),
                )

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

                st.button(
                    "← Back to Sign in",
                    key="back_from_reset",
                    on_click=_set_auth_view,
                    args=("signin",),
                )

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
    _stop_after_deferred_components()

# Mobile swipe/guide-select sidebar helpers are installed by the deferred block.


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
        # Refresh only on save: normal widget clicks read from session state.
        get_saved_matches(auth_user_id, force_refresh=True)
        return True
    except Exception as e:
        st.error(f"Save failed: {e}")
        return False


def _saved_matches_cache_key(user_id) -> str:
    return f"saved_matches::{user_id}"


def _fetch_saved_matches_from_supabase(user_id) -> list[dict]:
    """Single Supabase read for this user's saved matches."""
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


def get_saved_matches(user_id, force_refresh: bool = False) -> list[dict]:
    """Session-cached saved matches; Supabase is read only on login/save/delete."""
    key = _saved_matches_cache_key(user_id)
    if force_refresh or key not in st.session_state:
        st.session_state[key] = _fetch_saved_matches_from_supabase(user_id)
    return list(st.session_state[key] or [])


def _prime_saved_matches_for_user(user_id) -> None:
    """Hydrate the session cache once, when the signed-in user changes."""
    user_key = "_saved_matches_cache_user"
    if st.session_state.get(user_key) == user_id:
        return
    st.session_state[user_key] = user_id
    st.session_state.pop(_saved_matches_cache_key(user_id), None)
    get_saved_matches(user_id, force_refresh=True)


_prime_saved_matches_for_user(CURRENT_USER_ID)


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
        get_saved_matches(str(current_user.id), force_refresh=True)
        return True
    except Exception as e:
        st.error(f"Delete failed: {e}")
        return False


def _delete_saved_match_callback(match_id):
    """Widget callback: delete a row; the fragment redraws on the same click."""
    delete_saved_match(match_id)


def _save_match_callback(
    product, city, diet_rules, allergens, priority, alternatives
) -> None:
    """Save in the widget's single callback pass; no second st.rerun()."""
    if save_match(
        CURRENT_USER_ID,
        product,
        city,
        diet_rules,
        allergens,
        priority,
        alternatives,
    ):
        st.session_state["saved_match_flash"] = True


def _load_saved_match_callback(match) -> None:
    """Restore a saved match in one pass; the button supplies the rerun."""
    load_saved_match(match)


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
    st.session_state["inspect_product"] = None
    st.session_state["show_ai_help"] = False
    st.session_state["show_wishlist_page"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_details"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = False


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
            st.button(
                label,
                key=f"load_match_{match['id']}",
                use_container_width=True,
                on_click=_load_saved_match_callback,
                args=(match,),
            )
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
BACKEND_URL      = API_BASE  # alias used by the silent background wake-up ping
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


def _ping_backend_health() -> None:
    """One-shot health request whose only job is to wake a sleeping backend."""
    try:
        requests.get(f"{BACKEND_URL}/health", timeout=1)
    except requests.exceptions.RequestException:
        # A cold backend normally times out here; the request still reaches it
        # and starts the wake-up. No UI element depends on this response.
        pass


def _start_backend_wakeup() -> None:
    """Fire the wake-up ping once per session, without blocking page render."""
    if st.session_state.get("_backend_wakeup_started"):
        return
    st.session_state["_backend_wakeup_started"] = True
    threading.Thread(
        target=_ping_backend_health,
        name="macromatch-backend-wakeup",
        daemon=True,
    ).start()


_start_backend_wakeup()

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
# Top-bar AI assistant panel and its in-session conversation history.
st.session_state.setdefault("show_ai_help", False)
st.session_state.setdefault("ai_chat_history", [])
# The wishlist owns the whole main screen when opened from the sidebar button.
st.session_state.setdefault("show_wishlist_page", False)
st.session_state.setdefault("_collapse_sidebar_for_wishlist", False)
# Dedicated catalogue page: six cards at a time on desktop, four on phones.
CATALOGUE_PAGE_SIZE = 6
st.session_state.setdefault("show_all_products_page", False)
st.session_state.setdefault("_collapse_sidebar_for_catalogue", False)
st.session_state.setdefault("catalogue_visible_count", CATALOGUE_PAGE_SIZE)
st.session_state.setdefault("catalogue_initial_count", CATALOGUE_PAGE_SIZE)
# Dedicated PWA install page opened from the sidebar button.
st.session_state.setdefault("show_install_page", False)
st.session_state.setdefault("_collapse_sidebar_for_install", False)
# Sidebar profile pill expands the elevated glass card in place.
st.session_state.setdefault("show_user_profile", False)
# Home is clean by default; Find Alternatives switches to the ranked swaps
# view, while View Details opens a full product card on the main screen.
if "show_swaps_results" not in st.session_state:
    st.session_state["show_swaps_results"] = False
st.session_state.setdefault("inspect_product", None)
# Set by View Details / wishlist-name taps and consumed on the details rerun.
st.session_state.setdefault("_collapse_sidebar_for_details", False)
if "daily_protein_goal" not in st.session_state:
    st.session_state["daily_protein_goal"] = 120
if "daily_calorie_goal" not in st.session_state:
    st.session_state["daily_calorie_goal"] = 2000
if "default_diet_select" not in st.session_state:
    st.session_state["default_diet_select"] = "None"
if "default_allergens_select" not in st.session_state:
    st.session_state["default_allergens_select"] = []
st.session_state.setdefault("wishlist", [])

# Auth has already been enforced above, so it is safe to hydrate the signed-in
# user's saved targets/preferences before any dashboard widgets are created.
if st.session_state.get("supabase_user") is not None:
    _load_user_preferences(st.session_state["supabase_user"])

# Dedicated views own the whole main area: no hero, no how-it-works bar, no
# Help toggle, and no search form until the user taps "⌂ Back to home".
show_product_details = st.session_state.get("inspect_product") is not None
show_ai_help = st.session_state.get("show_ai_help", False)
show_wishlist_page = st.session_state.get("show_wishlist_page", False)
show_all_products_page = st.session_state.get("show_all_products_page", False)
show_install_page = st.session_state.get("show_install_page", False)


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


def _toggle_wishlist_callback(product_name: str) -> None:
    """Widget callback: persist a wishlist change in the button's own pass."""
    toggle_wishlist(product_name)


def _remove_wishlist_item(product_name: str) -> None:
    """Remove one saved food, persist it immediately; the tap supplies the rerun."""
    if not product_name:
        return
    if product_name in _normalize_wishlist(st.session_state.get("wishlist", [])):
        toggle_wishlist(product_name)


def toggle_wishlist(product_name: str) -> None:
    """Add/remove a food and persist the list to Supabase Auth user_metadata."""
    if not product_name:
        return
    wishlist = _normalize_wishlist(st.session_state.get("wishlist", []))
    if product_name in wishlist:
        wishlist.remove(product_name)
        message = "Removed from Wishlist"
    else:
        wishlist.append(product_name)
        message = "Added to Wishlist"

    st.session_state["wishlist"] = wishlist
    try:
        response = supabase.auth.update_user(
            {"data": {"wishlist": st.session_state["wishlist"]}}
        )
        user = getattr(response, "user", None)
        if user is not None:
            st.session_state["supabase_user"] = user
    except Exception as exc:
        st.error(f"Could not save your wishlist: {exc}")
    st.toast(message)


def _wishlist_button_label(product_name: str) -> str:
    """Label that always reflects the current wishlist state."""
    return (
        "❤️ Wishlisted"
        if product_name in st.session_state.get("wishlist", [])
        else "🤍 Wishlist"
    )


def render_wishlist_button(
    product_name: str, key: str, use_container_width: bool = False
) -> None:
    """Reusable wishlist toggle for guide, spotlight and swap cards."""
    st.button(
        _wishlist_button_label(product_name),
        key=key,
        use_container_width=use_container_width,
        type="secondary",
        on_click=_toggle_wishlist_callback,
        args=(product_name,),
    )


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
    """Return to the clean home view and drop inspect/AI/ranked-result state."""
    st.session_state["show_swaps_results"] = False
    st.session_state["inspect_product"] = None
    st.session_state["show_ai_help"] = False
    st.session_state["show_wishlist_page"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_details"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = False
    st.session_state.pop("match_result_data", None)


def _open_swaps_results() -> None:
    """Find Alternatives callback: one state pass, one automatic widget rerun."""
    st.session_state["show_swaps_results"] = True
    st.session_state["inspect_product"] = None
    st.session_state["show_ai_help"] = False
    st.session_state["show_wishlist_page"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_details"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = False
    st.session_state.pop("match_result_data", None)


def _close_ai_help() -> None:
    """AI Help back-button callback (the button supplies the single rerun)."""
    st.session_state["show_ai_help"] = False
    st.session_state["show_wishlist_page"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = False


def _open_wishlist_page() -> None:
    """Sidebar button callback: hand the main screen to the wishlist view."""
    st.session_state["show_wishlist_page"] = True
    st.session_state["inspect_product"] = None
    st.session_state["show_swaps_results"] = False
    st.session_state["show_ai_help"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_details"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = True
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = False
    st.session_state.pop("match_result_data", None)


def _close_wishlist_page() -> None:
    """Wishlist back-button callback (the button supplies the single rerun)."""
    st.session_state["show_wishlist_page"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_install"] = False


def _open_catalogue_page() -> None:
    """Sidebar button callback: hand the main screen to the product catalogue."""
    mobile = str(st.query_params.get("mm_mobile", "0")) in ("1", "true", "True")
    page_size = 4 if mobile else CATALOGUE_PAGE_SIZE
    st.session_state["show_all_products_page"] = True
    st.session_state["show_wishlist_page"] = False
    st.session_state["inspect_product"] = None
    st.session_state["show_swaps_results"] = False
    st.session_state["show_ai_help"] = False
    st.session_state["show_install_page"] = False
    st.session_state["catalogue_initial_count"] = page_size
    st.session_state["catalogue_visible_count"] = page_size
    st.session_state["_collapse_sidebar_for_details"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = True
    st.session_state["_collapse_sidebar_for_install"] = False
    st.session_state.pop("match_result_data", None)


def _close_catalogue_page() -> None:
    """Catalogue back-button callback (the button supplies the single rerun)."""
    st.session_state["show_all_products_page"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_install"] = False


def _show_more_catalogue_products() -> None:
    """Catalogue View More callback; reveal six more product cards."""
    st.session_state["catalogue_visible_count"] += CATALOGUE_PAGE_SIZE


def _show_less_catalogue_products() -> None:
    """Catalogue Show Less callback; restore the device's starting page size."""
    st.session_state["catalogue_visible_count"] = st.session_state[
        "catalogue_initial_count"
    ]


def _open_install_page() -> None:
    """Sidebar button callback: hand the main screen to the PWA install guide."""
    st.session_state["show_install_page"] = True
    st.session_state["show_wishlist_page"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["inspect_product"] = None
    st.session_state["show_swaps_results"] = False
    st.session_state["show_ai_help"] = False
    st.session_state["_collapse_sidebar_for_details"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = True
    st.session_state.pop("match_result_data", None)


def _close_install_page() -> None:
    """Install-page back-button callback (the button supplies the single rerun)."""
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_install"] = False


def _toggle_user_profile() -> None:
    """Sidebar pill callback: expand or collapse the elevated profile card."""
    st.session_state["show_user_profile"] = not st.session_state.get(
        "show_user_profile", False
    )


def _profile_sign_out() -> None:
    """Sign out from the profile card and clear the whole app session."""
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    st.session_state.clear()


def _render_top_right_back_button(key: str, on_click) -> None:
    """Render the shared top-right back pill on every dedicated page."""
    # The invisible marker reserves header height in the normal flow while CSS
    # pins the actual button to the top-right, opposite the sidebar control.
    st.markdown(
        '<div class="back-home-top-right" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    st.button(
        "⌂ Back to home",
        key=key,
        help="Return to the start page",
        on_click=on_click,
    )


def _render_back_to_home(key: str) -> None:
    """Top-right back button shared by the details and swaps views."""
    _render_top_right_back_button(key, _reset_swaps_view)


def _render_wishlist_back_to_home(key: str) -> None:
    """Top-right dark-emerald back pill for the dedicated wishlist page."""
    _render_top_right_back_button(key, _close_wishlist_page)


def _render_catalogue_back_to_home(key: str) -> None:
    """Top-right dark-emerald back pill for the dedicated catalogue page."""
    _render_top_right_back_button(key, _close_catalogue_page)


def _render_install_back_to_home(key: str) -> None:
    """Top-right dark-emerald back pill for the dedicated install page."""
    _render_top_right_back_button(key, _close_install_page)


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
    """Sidebar guide `Select`: load the product into Step 1 of the clean home."""
    if not product:
        return
    _sync_food_selection(product, product)
    st.session_state["inspect_product"] = None
    _reset_swaps_view()
    st.session_state["show_wishlist_page"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = False
    st.session_state["food_box_ver"] = st.session_state.get("food_box_ver", 0) + 1


def inspect_food_value_callback(product: str) -> None:
    """View Details / wishlist name: open the dedicated full-page overview."""
    if not product:
        return
    st.session_state["inspect_product"] = product
    st.session_state["show_swaps_results"] = False
    st.session_state["show_ai_help"] = False
    st.session_state["show_wishlist_page"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_details"] = True
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = False
    st.session_state.pop("match_result_data", None)


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

# ─────────────────────────────────────────────────────────────
# Rich product overview copy (used by the dedicated details page)
# ─────────────────────────────────────────────────────────────
PRODUCT_ABOUT: dict[str, str] = {
    "Whey Protein Powder": "A fast-digesting dairy protein made from milk during cheese-making. It is rich in complete protein and useful after training or when you need an easy protein top-up; best for active people who tolerate dairy.",
    "Pea Protein Powder": "A plant protein made from yellow peas, with a solid amino-acid profile and no dairy or soy. It blends easily into shakes and cooking; best for vegan/vegetarian users or anyone avoiding dairy.",
    "Soya Chunks (TVP)": "Defatted soy flour textured into a chewy, shelf-stable meat substitute. It delivers high protein with very little fat and absorbs flavours well; best for budget-friendly vegetarian high-protein meals.",
    "Tofu (Firm)": "A firm soy-bean curd that is mild, versatile and high in complete plant protein. It also supplies calcium when set with calcium salts; best for vegan/vegetarian bowls, curries and grills.",
    "Tempeh": "Fermented soybeans pressed into a firm cake; fermentation makes it easier to digest and gives a nutty flavour. It offers protein plus fibre; best for people wanting a hearty plant protein.",
    "Edamame": "Young soybeans eaten fresh, with protein, fibre and a mild, fresh taste. They make a simple snack or side; best for plant-based eaters and lunchboxes.",
    "Paneer": "Fresh Indian cheese with a mild flavour and a firm texture that holds up in curries. It provides protein and calcium; best for vegetarians who tolerate dairy and want filling meals.",
    "Greek Yogurt": "Strained yogurt with a thicker texture and more protein than regular curd. It supports breakfast and snack protein goals; best for people who enjoy dairy and want a quick, creamy option.",
    "Cottage Cheese (Low Fat)": "Fresh low-fat curds with slow-digesting casein protein. It is light yet filling and works sweet or savoury; best for breakfast, snacks or a pre-sleep protein option.",
    "Masoor Dal (Red Lentils)": "Split red lentils that cook quickly and turn soft and creamy. They supply plant protein and fibre at a low cost; best for everyday dal, soups and khichdi.",
    "Chana Dal": "Split chickpeas with a nutty flavour and firm bite. They offer plant protein and fibre; best for people who enjoy traditional dals and want a slower-digesting pulse.",
    "Moong Dal": "Small, mild lentils that cook fast and are easy to digest when soaked. They provide plant protein and fibre; best for light meals, khichdi and sprouted salads.",
    "Chickpeas (Kabuli Chana)": "Round legumes with a nutty taste and firm texture. They combine plant protein with fibre for steady energy; best for curries, salads and hummus-style dishes.",
    "Rajma (Kidney Beans)": "Kidney-shaped beans with a hearty texture and earthy flavour. They are rich in plant protein and fibre; best for filling rice bowls and wraps when cooked thoroughly.",
    "Rolled Oats": "Whole oat flakes that cook into a creamy, fibre-rich cereal. They provide slow-release carbohydrate and useful protein for breakfast; best for morning meals and pre-workout fuel.",
    "Quinoa": "A gluten-free grain-like seed with a light, fluffy texture. It offers complete plant protein and fibre; best for grain bowls, salads and rice swaps.",
    "Brown Rice": "Wholegrain rice with the bran intact, giving a nuttier taste and more fibre than white rice. It gives steady energy; best as a base for dal, sabzi and protein bowls.",
    "Peanut Butter": "A creamy or crunchy paste of roasted groundnuts, dense in energy, healthy fats and some protein. Best in small portions for snacks, toast and smoothies.",
    "Almond Butter": "A nut butter made from almonds, with healthy fats, vitamin E and a mild sweetness. It is energy-dense; best for toast, fruit dips and smoothies in measured servings.",
    "Almonds": "Whole tree nuts with healthy fats, fibre, vitamin E and a satisfying crunch. They are portable and energy-dense; best as a measured snack or topping.",
    "Cashews": "Creamy tree nuts that blend into rich sauces and dairy-free creams. They provide healthy fats and minerals; best for curries, trail mixes and creamy smoothies in small portions.",
    "Walnuts": "Tree nuts known for their omega-3 alpha-linolenic acid and rich flavour. They pair well with sweet and savoury dishes; best as a small snack or a salad/breakfast topping.",
    "Chia Seeds": "Tiny seeds that form a gel when soaked, adding fibre and healthy fats. They are very energy-dense; best for puddings, soaked drinks and smoothies, never eaten dry.",
    "Flaxseeds": "Small seeds rich in fibre and plant omega-3, best used ground. They add a mild nutty note; best for people adding fibre to oats, roti dough or smoothies.",
    "Pumpkin Seeds": "Flat green seeds with a crisp texture and decent protein and minerals. They are easy to sprinkle; best for snacks, salads and trail mixes.",
    "Sunflower Seeds": "Small hulled seeds with a mild nutty flavour and healthy fats. They are a nut-free crunchy option; best for toppings, snacks and seed butters.",
    "Soy Milk": "A plant milk made from soybeans, usually fortified with calcium and vitamin D. It has a neutral taste and useful protein; best for vegan/vegetarian drinks, cereal and cooking.",
    "Almond Milk": "A light plant milk made from almonds, usually lower in calories than dairy milk. It works well in drinks and cereal; best for people wanting a nutty, dairy-free option.",
    "Oat Milk": "A creamy plant milk made from oats, naturally slightly sweet. It froths well for coffee and cooks well; best for dairy-free drinks, cereal and baking.",
    "Coconut Milk (Canned)": "Rich canned coconut milk with a pronounced coconut flavour and high saturated fat. It adds creaminess to curries and desserts; best for occasional cooking use in small amounts.",
}

PRODUCT_STORAGE: dict[str, str] = {
    "Whey Protein Powder": "Keep sealed in a cool, dry place; scoop with a dry spoon and close the lid after each use.",
    "Pea Protein Powder": "Keep sealed in a cool, dry place; use a dry scoop and avoid moisture entering the pouch.",
    "Soya Chunks (TVP)": "Store dry in an airtight jar; once soaked, refrigerate and cook within a day.",
    "Tofu (Firm)": "Keep refrigerated in its liquid; after opening, store submerged in fresh water and use within 2–3 days.",
    "Tempeh": "Refrigerate and use within a few days; it also freezes well when tightly wrapped.",
    "Edamame": "Freeze if not using fresh; refrigerate cooked pods for up to 2 days.",
    "Paneer": "Refrigerate in an airtight box, use within 3–4 days, or freeze in cubes.",
    "Greek Yogurt": "Keep chilled, use a clean spoon every time, and avoid long spells at room temperature.",
    "Cottage Cheese (Low Fat)": "Keep chilled and consume soon after opening; drain excess liquid before cooking.",
    "Masoor Dal (Red Lentils)": "Store dry in an airtight jar away from moisture; rinse before cooking.",
    "Chana Dal": "Store dry in an airtight jar; soak before cooking for a creamier texture.",
    "Moong Dal": "Store dry and airtight; rinse well and soak when the recipe calls for it.",
    "Chickpeas (Kabuli Chana)": "Keep dried chickpeas airtight; cooked chickpeas refrigerate 3–4 days or freeze in portions.",
    "Rajma (Kidney Beans)": "Keep dried beans airtight; cooked beans refrigerate 3–4 days or freeze in portions.",
    "Rolled Oats": "Keep in a sealed container away from moisture; discard if it smells rancid.",
    "Quinoa": "Store dry in an airtight jar; cooked quinoa keeps 3–4 days refrigerated.",
    "Brown Rice": "Store dry in an airtight jar; cooked rice should be refrigerated promptly and eaten within 3–4 days.",
    "Peanut Butter": "Store sealed; natural oil separation is normal—stir well. Refrigeration after opening extends freshness.",
    "Almond Butter": "Store sealed; stir if oils separate. Refrigerate after opening for longer freshness.",
    "Almonds": "Keep in an airtight container in a cool, dark place or fridge to prevent rancidity.",
    "Cashews": "Keep airtight and away from heat; refrigeration helps prevent rancidity.",
    "Walnuts": "Store airtight in the fridge or freezer because their oils go rancid quickly.",
    "Chia Seeds": "Keep dry and sealed; soaked chia should be refrigerated and used within a day or two.",
    "Flaxseeds": "Store whole seeds airtight; grind just before use and refrigerate ground flax.",
    "Pumpkin Seeds": "Keep airtight in a cool, dark place or fridge to protect the oils.",
    "Sunflower Seeds": "Store airtight and cool; roasted seeds are best used soon after opening.",
    "Soy Milk": "Refrigerate after opening, shake the carton, and use within 4–5 days.",
    "Almond Milk": "Refrigerate after opening, shake before pouring, and finish within 4–5 days.",
    "Oat Milk": "Refrigerate after opening and use within 4–5 days; shake well before pouring.",
    "Coconut Milk (Canned)": "Store unopened in a cool cupboard; once opened, refrigerate in a non-metal container and use within 3–4 days.",
}

PRODUCT_PAIRINGS: dict[str, str] = {
    "Whey Protein Powder": "Pair with banana, oats or Greek yogurt for a fuller recovery snack.",
    "Pea Protein Powder": "Pair with banana, oat milk or a small handful of nuts.",
    "Soya Chunks (TVP)": "Pair with brown rice, wholegrain roti and plenty of vegetables.",
    "Tofu (Firm)": "Pair with brown rice, quinoa, sesame and crunchy vegetables.",
    "Tempeh": "Pair with brown rice, leafy greens and a light soy-ginger glaze.",
    "Edamame": "Pair with brown rice, citrus, sea salt or a light soy dip.",
    "Paneer": "Pair with wholegrain roti, brown rice or a large vegetable side.",
    "Greek Yogurt": "Pair with berries, oats, chia seeds or a drizzle of honey.",
    "Cottage Cheese (Low Fat)": "Pair with fruit, wholegrain toast, herbs or cracked pepper.",
    "Masoor Dal (Red Lentils)": "Pair with brown rice, quinoa, roti or a vegetable side.",
    "Chana Dal": "Pair with brown rice, roti or a cucumber and lemon side.",
    "Moong Dal": "Pair with brown rice, quinoa or sprouted vegetables.",
    "Chickpeas (Kabuli Chana)": "Pair with quinoa, rice, cucumber and lemon-tahini style dressing.",
    "Rajma (Kidney Beans)": "Pair with brown rice, quinoa or a wholegrain wrap.",
    "Rolled Oats": "Pair with Greek yogurt, berries, seeds or a spoon of nut butter.",
    "Quinoa": "Pair with roasted vegetables, chickpeas, tofu or fresh herbs.",
    "Brown Rice": "Pair with dal, paneer, tofu, beans or stir-fried vegetables.",
    "Peanut Butter": "Pair with fruit slices, wholegrain toast or oatmeal.",
    "Almond Butter": "Pair with apple, banana, toast or overnight oats.",
    "Almonds": "Pair with fruit, yogurt or a small handful of seeds.",
    "Cashews": "Pair with fruit, yogurt, oats or a light trail mix.",
    "Walnuts": "Pair with yogurt, oats, berries or a leafy salad.",
    "Chia Seeds": "Pair with milk, yogurt, oats or a soaked smoothie.",
    "Flaxseeds": "Pair with oatmeal, roti dough, yogurt or smoothies.",
    "Pumpkin Seeds": "Pair with yogurt, oats, salads or trail mix.",
    "Sunflower Seeds": "Pair with salads, oatmeal, yogurt or seed butter.",
    "Soy Milk": "Pair with coffee, cereal, oats or a fruit smoothie.",
    "Almond Milk": "Pair with coffee, tea, cereal or a smoothie.",
    "Oat Milk": "Pair with coffee, muesli, overnight oats or baking.",
    "Coconut Milk (Canned)": "Pair with vegetables, tofu, beans and rice; keep portions modest.",
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

/* Keep the Streamlit top header transparent and compact without pushing content down */
header[data-testid="stHeader"] {
    background: transparent !important;
    height: 2.6rem !important;
    min-height: 2.6rem !important;
}
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

/* Highlight BOTH the collapse (<<) and expand (>>) sidebar buttons identically */
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarHeader"] button,
section[data-testid="stSidebar"] button[kind="header"],
[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button,
header[data-testid="stHeader"] button[kind="header"] {
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
section[data-testid="stSidebar"] button[kind="header"] svg,
[data-testid="stExpandSidebarButton"] svg,
[data-testid="stSidebarCollapsedControl"] button svg,
[data-testid="collapsedControl"] button svg,
header[data-testid="stHeader"] button[kind="header"] svg {
    fill: #6EE798 !important;
    color: #6EE798 !important;
    width: 18px !important;
    height: 18px !important;
}

@media (hover: hover) {
    [data-testid="stSidebarCollapseButton"] button:hover,
    [data-testid="stSidebarHeader"] button:hover,
    section[data-testid="stSidebar"] button[kind="header"]:hover,
    [data-testid="stExpandSidebarButton"]:hover,
    [data-testid="stSidebarCollapsedControl"] button:hover,
    [data-testid="collapsedControl"] button:hover,
    header[data-testid="stHeader"] button[kind="header"]:hover {
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
/* Remove excessive blank top space on both mobile and desktop */
.block-container,
[data-testid="stAppViewBlockContainer"],
.main .block-container,
section.main > div[data-testid="stMainBlockContainer"] {
    padding-top: 1.2rem !important;
    margin-top: 0 !important;
}

@media (max-width: 768px) {
    .block-container,
    [data-testid="stAppViewBlockContainer"],
    .main .block-container,
    section.main > div[data-testid="stMainBlockContainer"] {
        padding-top: 0.75rem !important;
    }
}

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

/* Wishlist cards now reuse the product-guide card markup and styles. */
.wishlist-marker, .wishlist-name-marker { display: none !important; }

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

/* ── Dedicated Product Details — rich nutrition guide ── */
.detail-guide-marker { display: none !important; }
div[data-testid="stVerticalBlockBorderWrapper"]:has(.detail-guide-marker) {
    background: linear-gradient(180deg, rgba(22, 27, 34, 0.96), rgba(13, 17, 23, 0.96)) !important;
    border: 1px solid rgba(46, 160, 67, 0.35) !important;
    border-radius: 14px !important;
    padding: 1.1rem !important;
    margin-top: 0.9rem !important;
}
.detail-section-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 1.05rem !important;
    font-weight: 800 !important;
    color: #7EE2A8 !important;
    margin: 0 0 0.55rem !important;
    letter-spacing: 0.01em !important;
}
.detail-section-title + .detail-copy,
.detail-section-title + .detail-macro-table {
    margin-top: 0 !important;
}
.detail-copy {
    font-size: 0.92rem !important;
    line-height: 1.65 !important;
    color: #C9D1D9 !important;
    margin: 0 0 0.85rem !important;
}
.detail-macro-table {
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 0.86rem !important;
    font-variant-numeric: tabular-nums !important;
}
.detail-macro-table th, .detail-macro-table td {
    padding: 0.45rem 0.55rem !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07) !important;
    text-align: right !important;
}
.detail-macro-table th:first-child, .detail-macro-table td:first-child {
    text-align: left !important;
    color: #94A3B8 !important;
}
.detail-macro-table thead th {
    color: #7EE2A8 !important;
    font-weight: 700 !important;
    border-bottom-color: rgba(46, 160, 67, 0.45) !important;
}
.detail-macro-table tbody tr:last-child td { border-bottom: none !important; }
.detail-mini-card {
    background: rgba(11, 15, 25, 0.55) !important;
    border: 1px solid rgba(255, 255, 255, 0.07) !important;
    border-radius: 10px !important;
    padding: 0.75rem 0.85rem !important;
    margin-bottom: 0.7rem !important;
}
.detail-mini-card p { margin: 0 !important; }
.detail-mini-label {
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.09em !important;
    color: #8B949E !important;
    margin-bottom: 0.3rem !important;
}
.detail-mini-value {
    font-size: 0.95rem !important;
    font-weight: 650 !important;
    color: #E6EDF3 !important;
}
.detail-tip-list {
    margin: 0 !important;
    padding-left: 1.1rem !important;
    color: #C9D1D9 !important;
    font-size: 0.9rem !important;
    line-height: 1.6 !important;
}

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

/* ── Top-bar Help toggle + dedicated dark glass AI page ── */
.ai-help-toggle-marker, .ai-help-marker {
    display: none !important;
}
div[data-testid="stVerticalBlockElement"]:has(.ai-help-toggle-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button {
    min-height: 46px !important;
    padding: 0.5rem 0.9rem !important;
    font-size: 0.95rem !important;
    font-weight: 700 !important;
    color: #7EE2A8 !important;
    background: rgba(46, 160, 67, 0.10) !important;
    border: 1px solid #2EA043 !important;
    border-radius: 10px !important;
    transition: all 0.15s ease !important;
}
@media (hover: hover) {
    div[data-testid="stVerticalBlockElement"]:has(.ai-help-toggle-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button:hover {
        background: rgba(46, 160, 67, 0.20) !important;
        border-color: #3FB950 !important;
        color: #A7F3D0 !important;
    }
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ai-help-marker) {
    background: linear-gradient(145deg, #161B22, #0D1117) !important;
    border: 1px solid rgba(46, 160, 67, 0.45) !important;
    border-radius: 16px !important;
    padding: 20px !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4) !important;
    margin-bottom: 16px !important;
}
.ai-help-heading {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 1.2rem !important;
    font-weight: 800 !important;
    color: #E6EDF3 !important;
    line-height: 1.3 !important;
}
.ai-help-subtitle {
    font-size: 0.92rem !important;
    line-height: 1.55 !important;
    color: #9BA7B4 !important;
    margin: 0.35rem 0 1.1rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ai-help-marker) .stButton > button {
    min-height: 42px !important;
    padding: 0.35rem 0.7rem !important;
    font-size: 0.82rem !important;
    font-weight: 650 !important;
    color: #A7F3D0 !important;
    background: rgba(46, 160, 67, 0.12) !important;
    border: 1px solid rgba(46, 160, 67, 0.35) !important;
    border-radius: 999px !important;
    transition: all 0.15s ease !important;
}
@media (hover: hover) {
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.ai-help-marker) .stButton > button:hover {
        background: rgba(46, 160, 67, 0.22) !important;
        border-color: rgba(46, 160, 67, 0.65) !important;
        color: #FFFFFF !important;
    }
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ai-help-marker) [data-testid="stChatMessage"] {
    width: 100% !important;
    max-width: 100% !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ai-help-marker) [data-testid="stChatInput"] {
    width: 100% !important;
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
    font-size: 16px !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
    line-height: 1.4 !important;
    color: #4ADE80 !important;
    margin: 0 0 8px !important;
}
.search-card-title--spaced {
    margin-top: 1.1rem !important;
}
.search-step-badge {
    flex-shrink: 0 !important;
}

/* ── Filter questions — bold, crisp labels; choices stay regular weight ── */
.filters-expander-marker {
    display: none !important;
}
div[data-testid="stExpander"]:has(.filters-expander-marker) label[data-testid="stWidgetLabel"] p {
    font-weight: 700 !important;
    color: #E6EDF3 !important;
    font-size: 16px !important;
}
div[data-testid="stExpander"]:has(.filters-expander-marker) .stRadio div[role="radiogroup"] label,
div[data-testid="stExpander"]:has(.filters-expander-marker) .stRadio div[role="radiogroup"] span {
    font-weight: 400 !important;
}

/* ── Sidebar product guide — compact single-column cards ── */
[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.guide-card) {
    background-color: #161B22 !important;
    border: 1px solid #30363D !important;
    border-radius: 12px !important;
    padding: 12px !important;
    margin-bottom: 12px !important;
}
.guide-thumb {
    display: block;
    width: 100%;
    height: 100px;
    object-fit: cover;
    object-position: center;
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
div[data-testid="stVerticalBlockBorderWrapper"]:has(.guide-card) .stButton > button {
    min-height: 32px !important;
    padding: 0.3rem 0.6rem !important;
    font-size: 0.78rem !important;
    border-radius: 8px !important;
    margin-top: 0.55rem !important;
}

.selected-value {
    font-size: 16px !important;
    font-weight: 700 !important;
    color: #E6EDF3 !important;
    margin: 6px 0 10px 0 !important;
}
.selected-value strong,
.selected-value span {
    font-weight: 700 !important;
    color: #4ADE80 !important;
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

/* ── Back-to-home pill — pinned top-right on every dedicated page ── */
div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) {
    height: 2.6rem !important;
    min-height: 2.6rem !important;
    margin: 0 !important;
    padding: 0 !important;
}
.back-home-top-right {
    display: block !important;
    visibility: hidden !important;
    height: 2.6rem !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* The button element is removed from normal flow and pinned opposite the
   fixed ☰ Menu / >> control at the top-left. */
div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] {
    position: fixed !important;
    top: 16px !important;
    right: 16px !important;
    left: auto !important;
    z-index: 999999 !important;
    display: block !important;
    width: auto !important;
    margin: 0 !important;
    padding: 0 !important;
    text-align: right !important;
}
div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] div[data-testid="stButton"] {
    display: block !important;
    width: auto !important;
    margin-left: auto !important;
    margin-right: 0 !important;
}
div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] .stButton > button,
div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] button[data-testid="stBaseButton-secondary"] {
    background-color: rgba(46, 160, 67, 0.14) !important;
    border: 1px solid rgba(46, 160, 67, 0.65) !important;
    border-radius: 10px !important;
    color: #6EE798 !important;
    font-weight: 600 !important;
    padding: 6px 16px !important;
    width: auto !important;
    display: block !important;
    margin-left: auto !important;
    margin-right: 0 !important;
    height: auto !important;
    min-height: 0 !important;
    font-size: 15px !important;
    line-height: 1.2 !important;
    box-shadow: none !important;
    transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
}
div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] .stButton > button p,
div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] button[data-testid="stBaseButton-secondary"] p {
    color: #6EE798 !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    margin: 0 !important;
}
@media (hover: hover) {
    div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] .stButton > button:hover,
    div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] button[data-testid="stBaseButton-secondary"]:hover {
        background-color: rgba(46, 160, 67, 0.22) !important;
        border-color: #3FB950 !important;
        color: #FFFFFF !important;
    }
    div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] .stButton > button:hover p,
    div[data-testid="stVerticalBlockElement"]:has(.back-home-top-right) + div[data-testid="stVerticalBlockElement"] button[data-testid="stBaseButton-secondary"]:hover p {
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
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) div[data-testid="stToggle"] label,
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) div[data-testid="stToggle"] label p,
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) div[data-testid="stCheckbox"] label,
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) div[data-testid="stCheckbox"] label p {
    font-weight: 700 !important;
    font-size: 16px !important;
    color: #E6EDF3 !important;
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
    font-size: 16px !important;
    font-weight: 700 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.results-tabs-marker) .stTabs button[data-baseweb="tab"] p {
    font-weight: 700 !important;
    font-size: 16px !important;
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
        margin-left: auto !important;
        margin-right: auto !important;
    }

    .search-card-title {
        font-size: 18px !important;
        font-weight: 700 !important;
        letter-spacing: 0.04em !important;
        line-height: 1.4 !important;
        color: #4ADE80 !important;
        margin-bottom: 8px !important;
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
    /* Top padding is set globally above; keep the compact header clear here. */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.search-card-title) {
        padding: 0.85rem !important;
        border-radius: 14px !important;
    }
    .search-card-title {
        font-size: 16px !important;
        font-weight: 700 !important;
        letter-spacing: 0.04em !important;
        line-height: 1.4 !important;
        color: #4ADE80 !important;
        margin-bottom: 8px !important;
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

/* ── Sidebar headings, saved expander, toggle, and summary highlight ── */
.saved-matches-marker {
    display: none !important;
}
[data-testid="stSidebar"] div[data-testid="stExpander"]:has(.saved-matches-marker) [data-testid="stExpanderHeader"] p,
[data-testid="stSidebar"] div[data-testid="stExpander"]:has(.saved-matches-marker) summary p,
[data-testid="stSidebar"] div[data-testid="stExpander"]:has(.saved-matches-marker) .streamlit-expanderHeader p {
    font-weight: 700 !important;
    font-size: 16px !important;
    color: #FFFFFF !important;
}

.sidebar-section-title {
    font-size: 18px !important;
    font-weight: 800 !important;
    color: #4ADE80 !important;
    background-color: rgba(46, 160, 67, 0.14);
    border-left: 3px solid #2EA043;
    padding: 4px 10px;
    border-radius: 6px;
    display: inline-block;
    margin: 0.4rem 0 0.3rem !important;
}

section[data-testid="stSidebar"] div[data-testid="stToggle"],
section[data-testid="stSidebar"] div[data-testid="stCheckbox"] {
    background-color: rgba(46, 160, 67, 0.12) !important;
    border: 1px solid rgba(46, 160, 67, 0.45) !important;
    border-radius: 10px !important;
    padding: 8px 12px !important;
}
section[data-testid="stSidebar"] div[data-testid="stToggle"] label,
section[data-testid="stSidebar"] div[data-testid="stToggle"] label p,
section[data-testid="stSidebar"] div[data-testid="stCheckbox"] label,
section[data-testid="stSidebar"] div[data-testid="stCheckbox"] label p {
    font-weight: 700 !important;
    font-size: 16px !important;
    color: #6EE798 !important;
}

.sidebar-stats {
    background: linear-gradient(135deg, rgba(46, 160, 67, 0.16), rgba(22, 27, 34, 0.95)) !important;
    border: 1px solid rgba(46, 160, 67, 0.55) !important;
    border-radius: 12px !important;
    padding: 12px 14px !important;
    box-shadow: 0 4px 14px rgba(46, 160, 67, 0.12) !important;
}
.sidebar-stats .stats-row {
    align-items: center !important;
}
.sidebar-stats .stats-label {
    font-weight: 800 !important;
    color: #FFFFFF !important;
    font-size: 16px !important;
}
.sidebar-stats .stats-value {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    min-width: 28px !important;
    padding: 2px 9px !important;
    border-radius: 999px !important;
    background-color: rgba(46, 160, 67, 0.22) !important;
    border: 1px solid rgba(46, 160, 67, 0.6) !important;
    color: #6EE798 !important;
    font-size: 16px !important;
    font-weight: 800 !important;
    font-variant-numeric: tabular-nums !important;
}
.sidebar-stats .stats-tip {
    color: #C9D1D9 !important;
    font-weight: 400 !important;
    font-size: 14.5px !important;
}
.sidebar-stats .stats-tip strong {
    color: #FBBF24 !important;
    font-weight: 700 !important;
}

/* ── Sidebar profile pill + elevated glass card ── */
[data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.profile-toggle-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, rgba(46, 160, 67, 0.18), rgba(22, 27, 34, 0.96)) !important;
    border: 1.5px solid #3FB950 !important;
    border-radius: 999px !important;
    padding: 11px 18px !important;
    font-size: 16px !important;
    font-weight: 700 !important;
    color: #FFFFFF !important;
    box-shadow: 0 0 16px rgba(63, 185, 80, 0.28) !important;
    min-height: 46px !important;
}
.profile-card {
    background-color: #161B22 !important;
    border: 1px solid #30363D !important;
    border-radius: 16px !important;
    padding: 16px !important;
    margin-top: 10px !important;
    margin-bottom: 12px !important;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.45) !important;
}
.profile-user-row {
    display: flex !important;
    align-items: center !important;
    gap: 12px !important;
}
.profile-avatar {
    width: 42px !important;
    height: 42px !important;
    border-radius: 50% !important;
    background: linear-gradient(135deg, #2EA043, #2563EB) !important;
    color: #FFFFFF !important;
    font-weight: 800 !important;
    font-size: 18px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex-shrink: 0 !important;
}
.profile-name {
    font-size: 16px !important;
    font-weight: 700 !important;
    color: #FFFFFF !important;
    line-height: 1.25 !important;
}
.profile-email {
    font-size: 13px !important;
    color: #8B949E !important;
    line-height: 1.35 !important;
    margin-top: 2px !important;
}
.profile-stat-pill {
    background-color: #1C2128 !important;
    border: 1px solid #30363D !important;
    border-radius: 999px !important;
    padding: 7px 14px !important;
    font-size: 14px !important;
    color: #E6EDF3 !important;
    margin-top: 8px !important;
    text-align: center !important;
}
[data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.profile-signout-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button {
    background-color: rgba(248, 81, 73, 0.12) !important;
    border: 1px solid rgba(248, 81, 73, 0.65) !important;
    color: #FFA198 !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    margin-top: 12px !important;
}

/* ── Wishlist + catalogue + install launchers and dedicated full pages ── */
.wishlist-open-marker,
.catalogue-open-marker,
.install-open-marker,
.wishlist-page-marker,
.catalogue-page-marker,
.install-page-marker,
.install-steps-marker,
.profile-toggle-marker,
.profile-signout-marker,
.wishlist-grid-marker,
.catalogue-grid-marker {
    display: none !important;
}
[data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.wishlist-open-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button,
[data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.catalogue-open-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button,
[data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.install-open-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, rgba(46, 160, 67, 0.14), rgba(22, 27, 34, 0.95)) !important;
    border: 1px solid rgba(46, 160, 67, 0.65) !important;
    border-radius: 12px !important;
    padding: 10px 14px !important;
    font-weight: 700 !important;
    font-size: 16px !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25) !important;
    min-height: 46px !important;
}
[data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.install-open-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button {
    background: linear-gradient(135deg, rgba(46, 160, 67, 0.16), rgba(22, 27, 34, 0.95)) !important;
}
@media (hover: hover) {
    [data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.wishlist-open-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button:hover,
    [data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.catalogue-open-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button:hover,
    [data-testid="stSidebar"] div[data-testid="stVerticalBlockElement"]:has(.install-open-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button:hover {
        background: linear-gradient(135deg, rgba(46, 160, 67, 0.24), rgba(76, 20, 45, 0.82)) !important;
        border-color: rgba(251, 113, 133, 0.75) !important;
        color: #FFFFFF !important;
    }
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.wishlist-page-marker),
div[data-testid="stVerticalBlockBorderWrapper"]:has(.catalogue-page-marker),
div[data-testid="stVerticalBlockBorderWrapper"]:has(.install-page-marker) {
    background: linear-gradient(145deg, rgba(22, 27, 34, 0.98), rgba(13, 17, 23, 0.98)) !important;
    border: 1px solid rgba(46, 160, 67, 0.35) !important;
    border-radius: 16px !important;
    padding: 16px !important;
}
.wishlist-page-heading {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-size: 1.7rem !important;
    font-weight: 800 !important;
    color: #FFFFFF !important;
    margin: 0 0 14px !important;
    letter-spacing: -0.02em !important;
}
.wishlist-page-heading span {
    color: #FB7185 !important;
}
.catalogue-page-heading {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-size: 1.7rem !important;
    font-weight: 800 !important;
    color: #FFFFFF !important;
    margin: 0 0 14px !important;
    letter-spacing: -0.02em !important;
}
.catalogue-page-heading span {
    color: #6EE798 !important;
}
.install-page-heading {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-size: 1.7rem !important;
    font-weight: 800 !important;
    color: #FFFFFF !important;
    margin: 0 0 8px !important;
    letter-spacing: -0.02em !important;
}
.install-page-subtitle {
    color: #C9D1D9 !important;
    font-size: 15px !important;
    line-height: 1.5 !important;
    margin: 0 0 18px !important;
}
@media (max-width: 768px) {
    .wishlist-page-heading,
    .catalogue-page-heading,
    .install-page-heading {
        font-size: 1.35rem !important;
    }
}
.wishlist-empty-card {
    border: 1px dashed rgba(46, 160, 67, 0.5) !important;
    border-radius: 14px !important;
    background: rgba(46, 160, 67, 0.08) !important;
    padding: 28px 20px !important;
    text-align: center !important;
    color: #C9D1D9 !important;
}
.wishlist-empty-card .empty-icon {
    display: block !important;
    font-size: 2.4rem !important;
    margin-bottom: 10px !important;
}
.wishlist-empty-card .empty-title {
    display: block !important;
    font-size: 1.15rem !important;
    font-weight: 700 !important;
    color: #F8FAFC !important;
    margin-bottom: 6px !important;
}

/* ── Dedicated install page — clean two-step platform cards ── */
div[data-testid="stVerticalBlockElement"]:has(.install-steps-marker) + div[data-testid="stHorizontalBlock"] {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 14px !important;
    align-items: stretch !important;
}
div[data-testid="stVerticalBlockElement"]:has(.install-steps-marker) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    width: auto !important;
    min-width: 0 !important;
}
@media (max-width: 768px) {
    div[data-testid="stVerticalBlockElement"]:has(.install-steps-marker) + div[data-testid="stHorizontalBlock"] {
        grid-template-columns: 1fr !important;
    }
}
.install-step-card {
    height: 100% !important;
    background: linear-gradient(145deg, rgba(46, 160, 67, 0.14), rgba(22, 27, 34, 0.95)) !important;
    border: 1px solid rgba(46, 160, 67, 0.5) !important;
    border-radius: 14px !important;
    padding: 18px !important;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.22) !important;
}
.install-step-num {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 30px !important;
    height: 30px !important;
    border-radius: 999px !important;
    background: rgba(46, 160, 67, 0.25) !important;
    border: 1px solid rgba(46, 160, 67, 0.7) !important;
    color: #6EE798 !important;
    font-weight: 800 !important;
    margin-bottom: 10px !important;
}
.install-step-title {
    font-size: 1.1rem !important;
    font-weight: 800 !important;
    color: #FFFFFF !important;
    margin-bottom: 8px !important;
}
.install-step-body {
    color: #C9D1D9 !important;
    font-size: 14.5px !important;
    line-height: 1.6 !important;
}
.install-step-body strong {
    color: #6EE798 !important;
    font-weight: 700 !important;
}
.install-native-note {
    color: #8B949E !important;
    font-size: 13px !important;
    margin-top: 14px !important;
}
div[data-testid="stVerticalBlockElement"]:has(.install-page-marker) #mm-pwa-install-slot {
    margin-top: 12px !important;
}

div[data-testid="stVerticalBlockElement"]:has(.wishlist-grid-marker) + div[data-testid="stHorizontalBlock"],
div[data-testid="stVerticalBlockElement"]:has(.catalogue-grid-marker) + div[data-testid="stHorizontalBlock"] {
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
    gap: 16px !important;
    align-items: start !important;
}
div[data-testid="stVerticalBlockElement"]:has(.wishlist-grid-marker) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
div[data-testid="stVerticalBlockElement"]:has(.catalogue-grid-marker) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    width: auto !important;
    min-width: 0 !important;
}
@media (max-width: 768px) {
    div[data-testid="stVerticalBlockElement"]:has(.wishlist-grid-marker) + div[data-testid="stHorizontalBlock"],
    div[data-testid="stVerticalBlockElement"]:has(.catalogue-grid-marker) + div[data-testid="stHorizontalBlock"] {
        grid-template-columns: 1fr !important;
    }
}

/* ── Catalogue pagination — emerald-outlined buttons on the main screen ── */
.catalogue-view-more-marker,
.catalogue-show-less-marker {
    display: none !important;
}
div[data-testid="stVerticalBlockElement"]:has(.catalogue-view-more-marker) + div[data-testid="stVerticalBlockElement"],
div[data-testid="stVerticalBlockElement"]:has(.catalogue-show-less-marker) + div[data-testid="stVerticalBlockElement"] {
    display: flex !important;
    justify-content: center !important;
}
div[data-testid="stVerticalBlockElement"]:has(.catalogue-view-more-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button,
div[data-testid="stVerticalBlockElement"]:has(.catalogue-show-less-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button {
    background: linear-gradient(135deg, rgba(46, 160, 67, 0.2), rgba(22, 27, 34, 0.95)) !important;
    border: 1px solid rgba(46, 160, 67, 0.65) !important;
    color: #6EE798 !important;
    font-weight: 700 !important;
    font-size: 15px !important;
    letter-spacing: 0.03em !important;
    border-radius: 10px !important;
    padding: 10px 20px !important;
    min-width: 150px !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3) !important;
    margin-top: 0.5rem !important;
}
@media (hover: hover) {
    div[data-testid="stVerticalBlockElement"]:has(.catalogue-view-more-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button:hover,
    div[data-testid="stVerticalBlockElement"]:has(.catalogue-show-less-marker) + div[data-testid="stVerticalBlockElement"] .stButton > button:hover {
        background: rgba(46, 160, 67, 0.32) !important;
        border-color: #3FB950 !important;
        color: #FFFFFF !important;
    }
}
</style>
""", unsafe_allow_html=True)

# Re-apply the touch-first defaults after the dashboard theme so mobile blur
# and transition rules cannot win the cascade on first tap.
st.markdown(f"<style>{_TOUCH_FIRST_CSS}</style>", unsafe_allow_html=True)

# NOTE: Authentication CSS now lives INSIDE the logged-out block near the top
# of this file. It must be injected BEFORE st.stop(), otherwise the login screen
# never receives it (the old copy here was dead code after st.stop()).


# ─────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_product_list() -> list[str]:
    """
    Fetch all product names from GET /products with a 2.5 s probe timeout.

    Raises BackendUnavailable on failure so the failure is never cached; the
    caller (`cached_all_foods`) switches to the bundled dataset immediately.
    """
    try:
        resp = requests.get(f"{API_BASE}/products", timeout=2.5)
        resp.raise_for_status()
        return resp.json().get("products", [])
    except requests.exceptions.RequestException as exc:
        # Connection error, timeout, or non-2xx status.
        raise BackendUnavailable(API_BASE) from exc


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_city_list() -> list[str]:
    """Fetch destination cities from GET /cities with the same fast timeout."""
    try:
        resp = requests.get(f"{API_BASE}/cities", timeout=2.5)
        resp.raise_for_status()
        return resp.json().get("cities", [])
    except requests.exceptions.RequestException as exc:
        raise BackendUnavailable(API_BASE) from exc


@st.cache_data(ttl=3600, show_spinner=False)
def load_product_csv() -> pd.DataFrame:
    """Load products.csv to retrieve original product macros for comparison."""
    csv_path = Path(__file__).parent.parent / "data" / "products.csv"
    df = pd.read_csv(csv_path)
    df["name"] = df["name"].str.strip()
    return df


@st.cache_data(ttl=3600, show_spinner=False)
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


@st.cache_data(ttl=3600, show_spinner=False)
def _local_food_list() -> list[str]:
    """Bundled product names — the instant fallback when /products is slow."""
    try:
        df = load_product_csv()
        names = [str(value).strip() for value in df["name"].dropna()]
        names = [name for name in names if name]
        if names:
            return names
    except Exception:
        pass
    # Last resort if data/products.csv is missing: canonical names from code.
    return list(PRODUCT_SERVING_G) or list(PRODUCT_CAUTIONS)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_all_foods() -> list[str]:
    """Plain sorted list for O(n) autocomplete; never blocks on a cold API."""
    try:
        foods = fetch_product_list()
    except Exception:
        # Timeout, connection error, or a malformed response — all fall back.
        foods = []
    if not foods:
        foods = _local_food_list()
    return sorted(set(foods))


@st.cache_data(ttl=3600, show_spinner=False)
def cached_all_cities() -> list[str]:
    """Plain sorted list for O(n) city autocomplete; local fallback included."""
    try:
        cities = fetch_city_list()
    except Exception:
        # Same rule as foods: any API failure uses the bundled city list.
        cities = []
    if not cities:
        cities = load_city_list() or CITIES_FALLBACK
    return sorted(set(cities))


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


@st.cache_data(ttl=3600, show_spinner=False)
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


@st.cache_resource(show_spinner=False)
def product_image(name: str) -> Path | None:
    """Return the locally stored photo path for a product, if one exists."""
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = PRODUCT_IMAGE_DIR / f"{_slug(name)}{ext}"
        if candidate.exists():
            return candidate
    return None


@st.cache_resource(show_spinner=False)
def product_image_src(name: str) -> str | None:
    """Return a cached data-URI for embedding a product photo in custom HTML."""
    image = product_image(name)
    if not image:
        return None
    mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@st.cache_data(ttl=3600, show_spinner=False)
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


# ─────────────────────────────────────────────
# Context-aware AI diet & product assistant
# ─────────────────────────────────────────────

def _ai_current_context() -> dict:
    """Snapshot the user's live MacroMatch choices for the AI assistant."""
    selected_product = _canonical_value(
        str(st.session_state.get("selected_product", "")), PRODUCT_DISPLAY_ALIASES
    )
    selected_city = _canonical_value(
        str(st.session_state.get("selected_city", "")), CITY_DISPLAY_ALIASES
    )

    # Before the main filter widgets are first created, apply the saved
    # sidebar defaults. Once they exist, respect exactly what the user tapped.
    if "diet_pills" in st.session_state:
        diet_values = list(st.session_state.get("diet_pills") or [])
    else:
        saved = st.session_state.get("default_diet_select")
        diet_values = [saved] if saved and saved != "None" else []

    if "allergen_select" in st.session_state:
        allergen_values = list(st.session_state.get("allergen_select") or [])
    else:
        allergen_values = list(
            st.session_state.get("default_allergens_select") or []
        )

    label_to_key = {label: key for key, label in DIET_LABELS.items()}
    diets: list[str] = []
    for value in diet_values:
        key = label_to_key.get(value, value)
        if key in DIET_LABELS and key not in diets:
            diets.append(key)

    allergens = [
        value for value in allergen_values if value in ALLERGEN_OPTIONS
    ]

    try:
        protein_goal = float(st.session_state.get("daily_protein_goal", 120))
    except (TypeError, ValueError):
        protein_goal = 120.0
    try:
        calorie_goal = float(st.session_state.get("daily_calorie_goal", 2000))
    except (TypeError, ValueError):
        calorie_goal = 2000.0

    return {
        "selected_product": selected_product,
        "selected_city": selected_city,
        "diets": diets,
        "allergens": allergens,
        "protein_goal": protein_goal,
        "calorie_goal": calorie_goal,
    }


def _ai_catalog_text(details: dict[str, dict]) -> str:
    """Compact per-100 g facts for every product in data/products.csv."""
    lines = []
    for name in sorted(details):
        detail = details[name]
        diet_flags = [
            label
            for key, label in (
                ("vegan", "vegan"),
                ("vegetarian", "vegetarian"),
                ("dairy_free", "dairy-free"),
                ("gluten_free", "gluten-free"),
                ("low_sugar", "low-sugar"),
            )
            if detail.get(key)
        ]
        allergens = [
            label
            for key, label in (
                ("contains_soy", "soy"),
                ("contains_nuts", "nuts"),
                ("contains_dairy", "dairy"),
            )
            if detail.get(key)
        ]
        lines.append(
            f"{name} | category={detail.get('category', '')} | "
            f"per 100 g: protein={detail['protein']:g}g, carbs={detail['carbs']:g}g, "
            f"fat={detail['fat']:g}g, fibre={detail['fiber']:g}g, "
            f"calories={detail['calories']:g}kcal | "
            f"diet={'/'.join(diet_flags) or 'none'} | "
            f"contains={'/'.join(allergens) or 'none'} | "
            f"available_in={', '.join(detail.get('cities', [])) or 'none'}"
        )
    return "\n".join(lines)


def _ai_practical_guide_text(details: dict[str, dict]) -> str:
    """Serving / best-time / tips companion to the raw products.csv macros."""
    lines = []
    for name in sorted(details):
        how_to = PRODUCT_HOW_TO_USE.get(name, {})
        serving = how_to.get("serving") or f"{PRODUCT_SERVING_G.get(name, 100)} g"
        best_time = how_to.get("best_time") or "Any time of day"
        tips = " | ".join(how_to.get("tips") or []) or "No stored tips"
        lines.append(
            f"{name} | serving={serving} | best_time={best_time} | tips={tips}"
        )
    return "\n".join(lines)


def _ai_system_prompt(context: dict, details: dict[str, dict]) -> str:
    context_text = (
        f"Selected product: {context['selected_product'] or 'none'}\n"
        f"Destination city: {context['selected_city'] or 'none'}\n"
        f"Active diet rules: {', '.join(context['diets']) or 'none'}\n"
        f"Allergens to avoid: {', '.join(context['allergens']) or 'none'}\n"
        f"Daily protein goal: {context['protein_goal']:g} g\n"
        f"Daily calorie goal: {context['calorie_goal']:g} kcal"
    )
    return f"""You are the MacroMatch Nutrition & Product Assistant inside the
MacroMatch food-swap app. Answer the user's question concisely and accurately,
using ONLY the product facts and user context below. Macro values are per 100 g;
simple arithmetic (for example, goal percentages) is allowed. Serving advice
comes from the practical guide, not from guessing.

Rules:
- Detect the user's intent first: how-to/serving, benefits, comparison, travel,
  or general macro lookup. Answer that intent directly; never dump every macro.
- Match the user's language. If they write Hinglish/Hindi (for example,
  "kaise khaye", "fayde", "kitna"), reply in simple, friendly Hinglish with
  clear bullets. Otherwise reply in natural English.
- For how-to questions, use the food's Serving Size, Best Time and Tips &
  Ways to Eat from the practical guide. Give simple numbered/bulleted steps and
  end with one short macro line.
- For benefits questions, highlight nutritional strengths and how much of the
  user's daily protein goal one serving covers.
- For comparisons, put the two named foods side by side on protein, carbs, fat,
  fibre and calories, then give a one-line practical takeaway.
- For travel questions, respect destination availability and suggest portable,
  measured ways to eat the food.
- Be brief: usually 2-5 short bullets or one short paragraph.
- Only recommend foods from the catalogue below, and respect the active diet
  rules and allergens whenever making suggestions.
- Never invent foods, brands, prices, macros, availability, or health claims.
- If the answer is not covered by the data, say so plainly and point to the
  closest catalogue facts you do have.
- Do not give medical advice. A short caution is fine only when clearly relevant.

USER CONTEXT
{context_text}

MACROMATCH PRODUCT CATALOGUE (data/products.csv)
{_ai_catalog_text(details)}

PRACTICAL FOOD GUIDE (serving size, best time, tips & ways to eat)
{_ai_practical_guide_text(details)}
"""


def _configured_anthropic_key() -> str | None:
    """Read an Anthropic-compatible key from Streamlit secrets or the env."""
    for key_name in ("ANTHROPIC_API_KEY", "LLM_API_KEY"):
        try:
            value = st.secrets.get(key_name)
        except Exception:
            value = None
        if value:
            return str(value)
        value = os.getenv(key_name)
        if value:
            return value
    return None


def _call_anthropic(system_prompt: str, question: str) -> str | None:
    """Return an LLM answer, or None when unavailable/misconfigured/failed."""
    api_key = _configured_anthropic_key()
    if not api_key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=700,
            system=system_prompt,
            messages=[{"role": "user", "content": question}],
        )
        text = "".join(
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        ).strip()
        return text or None
    except Exception:
        # Missing quota, network trouble, or an older SDK all fall through to
        # the deterministic catalogue answer below.
        return None


def _ai_macro_summary(detail: dict) -> str:
    return (
        f"P {detail['protein']:g}g · C {detail['carbs']:g}g · "
        f"F {detail['fat']:g}g · fibre {detail['fiber']:g}g · "
        f"{detail['calories']:g} kcal per 100 g"
    )


# ── Intent vocabulary shared by the deterministic fallback and the LLM prompt ──
_AI_HOW_PHRASES = (
    "kaise khaye", "kaise khaaye", "kaise khana", "khaye", "khaaye", "khana",
    "how to eat", "how to use", "ways to eat", "way to eat", "use",
    "recipe", "serving", "kitna", "kitni", "kab khaye", "best time", "kab",
)
_AI_BENEFIT_PHRASES = (
    "fayde", "faayde", "fayda", "faayda", "benefits", "benefit", "why eat",
    "healthy", "weight loss", "fat loss", "muscle", "high protein",
    "protein rich", "good for",
    "accha", "achha", "labh",
)
_AI_COMPARE_PHRASES = ("vs", "versus", "compare", "comparison", "better", "ya")
_AI_TRAVEL_PHRASES = (
    "travel", "trip", "journey", "safar", "snack", "portable", "pack",
)
_AI_HINGLISH_PHRASES = (
    "kaise", "khaye", "khaaye", "khana", "kitna", "kitni", "fayde",
    "faayde", "fayda", "kya", "kab", "ya", "accha", "achha", "ke liye",
)


def _ai_text(question: str) -> str:
    return re.sub(r"\s+", " ", str(question or "").strip().lower())


def _ai_has_phrase(q: str, phrases: tuple[str, ...]) -> bool:
    """Word-boundary matching for single words, substring for Hinglish phrases."""
    for phrase in phrases:
        if " " in phrase:
            if phrase in q:
                return True
        elif re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", q):
            return True
    return False


def _ai_food_mentions(question: str, details: dict[str, dict]) -> list[str]:
    """Resolve canonical, short, alias and local-name food mentions in a query."""
    q = _ai_text(question)
    found: list[str] = []
    for name in sorted(details):
        phrases = {name.lower()}
        short_name = re.sub(r"\s*\([^)]*\)", "", name).strip().lower()
        if short_name:
            phrases.add(short_name)
        for part in re.split(r"[/()]", PRODUCT_LOCAL_NAMES.get(name, "")):
            part = part.strip().lower()
            if part:
                phrases.add(part)
        for alias, canonical in PRODUCT_DISPLAY_ALIASES.items():
            if canonical == name:
                phrases.add(alias.lower())
        if any(
            re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", q)
            for phrase in phrases
            if phrase
        ):
            found.append(name)
    return found


def _ai_resolve_food(
    question: str, details: dict[str, dict], context: dict
) -> str | None:
    """Use an explicitly named food, else fall back to the Step 1 selection."""
    mentions = _ai_food_mentions(question, details)
    if mentions:
        return mentions[0]
    selected = context.get("selected_product")
    return selected if selected in details else None


def _ai_allowed(detail: dict, context: dict) -> bool:
    diets = set(context.get("diets") or [])
    allergens = set(context.get("allergens") or [])
    if "vegan" in diets and not detail.get("vegan"):
        return False
    if "vegetarian" in diets and not detail.get("vegetarian"):
        return False
    if "dairy_free" in diets and not detail.get("dairy_free"):
        return False
    if "gluten_free" in diets and not detail.get("gluten_free"):
        return False
    if "low_sugar" in diets and not detail.get("low_sugar"):
        return False
    if "soy" in allergens and detail.get("contains_soy"):
        return False
    if "nuts" in allergens and detail.get("contains_nuts"):
        return False
    if "dairy" in allergens and detail.get("contains_dairy"):
        return False
    return True


def _ai_goal(context: dict, key: str, default: float) -> float:
    try:
        value = float(context.get(key) or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _ai_serving_grams(name: str) -> int:
    try:
        return int(PRODUCT_SERVING_G.get(name, 100))
    except (TypeError, ValueError):
        return 100


def _ai_serving_summary(name: str, detail: dict) -> str:
    grams = _ai_serving_grams(name)
    factor = grams / 100.0
    return (
        f"per {grams:g} g serving: P {float(detail['protein']) * factor:g}g · "
        f"C {float(detail['carbs']) * factor:g}g · "
        f"F {float(detail['fat']) * factor:g}g · "
        f"{float(detail['calories']) * factor:.0f} kcal"
    )


def _ai_protein_coverage(
    name: str, detail: dict, context: dict
) -> tuple[float, int, float]:
    goal = _ai_goal(context, "protein_goal", 120)
    protein = float(detail["protein"]) * _ai_serving_grams(name) / 100.0
    percent = round(protein / goal * 100) if goal else 0
    return protein, percent, goal


def _ai_strengths(detail: dict) -> list[str]:
    protein = float(detail["protein"])
    carbs = float(detail["carbs"])
    fat = float(detail["fat"])
    fiber = float(detail["fiber"])
    strengths: list[str] = []
    if protein >= 20:
        strengths.append("Very high in protein for a 100 g portion.")
    elif protein >= 12:
        strengths.append("A solid protein option for a 100 g portion.")
    if fiber >= 5:
        strengths.append("High in fibre, which helps keep meals satisfying.")
    elif fiber >= 2.5:
        strengths.append("Adds useful fibre to your day.")
    if fat >= 10:
        strengths.append(
            "Rich in healthy fats — tasty, but measure the serving because "
            "calories add up quickly."
        )
    if max(0.0, carbs - fiber) <= 10 and protein >= 10:
        strengths.append("Lower in net carbs, so it can fit a keto-style day.")
    if detail.get("vegan"):
        strengths.append("Vegan-friendly.")
    if detail.get("gluten_free"):
        strengths.append("Gluten-free.")
    if detail.get("low_sugar"):
        strengths.append("Low in sugar.")
    return strengths[:4]


def _ai_how_to_answer(
    name: str, detail: dict, context: dict, hinglish: bool
) -> str:
    """Step-by-step serving/best-time/tips answer for how-to style questions."""
    how_to = PRODUCT_HOW_TO_USE.get(name, {})
    serving = how_to.get("serving") or f"{_ai_serving_grams(name)} g"
    best_time = how_to.get("best_time") or "Any time of day"
    tips = list(how_to.get("tips") or [])
    if not tips:
        tips = ["Use a measured portion and pair it with your usual meal."]

    heading = (
        f"**{name} kaise khaye — easy guide:**"
        if hinglish
        else f"**How to eat {name} — simple guide:**"
    )
    lines = [
        heading,
        f"1. **Serving size ({'kitna lein' if hinglish else 'how much'})**: {serving}",
        f"2. **Best time ({'kab khaye' if hinglish else 'when'})**: {best_time}",
        f"3. **{'Kaise use karein' if hinglish else 'Ways to eat'}**:",
    ]
    lines.extend(f"   - {tip}" for tip in tips[:3])
    caution = PRODUCT_CAUTIONS.get(name)
    if caution:
        lines.append(f"4. **Caution / {'savdhan' if hinglish else 'who should avoid'}**: {caution}")
    lines.append(
        f"\nQuick macro line: {_ai_macro_summary(detail)}; "
        f"{_ai_serving_summary(name, detail)}."
    )
    return "\n".join(lines)


def _ai_benefits_answer(
    question: str, name: str, detail: dict, context: dict, hinglish: bool
) -> str:
    """Benefits-first answer that still ties back to the user's protein goal."""
    q = _ai_text(question)
    heading = (
        f"**{name} ke fayde — kyun accha hai:**"
        if hinglish
        else f"**Why {name} is a good pick:**"
    )
    lines = [heading]
    strengths = _ai_strengths(detail)
    lines.extend(f"- {strength}" for strength in strengths or [
        "It is a useful catalogue food that can fit a balanced day."
    ])

    protein, percent, goal = _ai_protein_coverage(name, detail, context)
    lines.append(
        f"- Protein goal: one {_ai_serving_grams(name)} g serving gives "
        f"{protein:g} g protein — about {percent}% of your {goal:g} g daily goal."
    )
    about = PRODUCT_ABOUT.get(name)
    if about:
        first_sentence = about.split(".")[0].strip()
        lines.append(f"- In short: {first_sentence}.")
    pairing = PRODUCT_PAIRINGS.get(name)
    if pairing:
        lines.append(f"- Easy way to use it: {pairing}")

    if _ai_has_phrase(q, ("weight loss", "fat loss", "weight")):
        lines.append(
            "- For weight loss: keep the serving measured; protein and fibre "
            "help you feel satisfied without overshooting calories."
        )
    if _ai_has_phrase(q, ("muscle", "workout", "gym")):
        lines.append(
            "- For muscle goals: use it as a protein top-up alongside your "
            "main meals and training routine."
        )
    caution = PRODUCT_CAUTIONS.get(name)
    if caution:
        lines.append(f"- Caution: {caution}")
    return "\n".join(lines)


def _ai_compare_answer(
    question: str, details: dict[str, dict], context: dict, hinglish: bool
) -> str:
    """Side-by-side comparison of two named foods (or selected + nearest)."""
    mentions = _ai_food_mentions(question, details)
    selected = context.get("selected_product")
    selected = selected if selected in details else None

    if len(mentions) >= 2:
        first_name, second_name = mentions[0], mentions[1]
    elif mentions and selected and selected != mentions[0]:
        first_name, second_name = selected, mentions[0]
    elif selected:
        swaps = _smart_swaps(selected, details[selected], details, limit=1)
        if not swaps:
            return "Tell me two catalogue foods to compare and I'll line up their macros."
        first_name, second_name = selected, swaps[0]
    else:
        return "Tell me two catalogue foods to compare and I'll line up their macros."

    left, right = details[first_name], details[second_name]
    heading = (
        f"**{first_name} vs {second_name} — comparison:**"
        if hinglish
        else f"**{first_name} vs {second_name} (per 100 g):**"
    )
    lines = [
        heading,
        "",
        f"| Nutrient | {first_name} | {second_name} |",
        "|---|---:|---:|",
    ]
    for label, key, unit in (
        ("Protein", "protein", " g"),
        ("Carbs", "carbs", " g"),
        ("Fat", "fat", " g"),
        ("Fibre", "fiber", " g"),
        ("Energy", "calories", " kcal"),
    ):
        lines.append(f"| {label} | {float(left[key]):g}{unit} | {float(right[key]):g}{unit} |")

    if float(left["protein"]) > float(right["protein"]):
        lines.append(f"- **{first_name}** has more protein per 100 g.")
    elif float(right["protein"]) > float(left["protein"]):
        lines.append(f"- **{second_name}** has more protein per 100 g.")
    if float(right["calories"]) < float(left["calories"]):
        lines.append(f"- **{second_name}** is lower in calories per 100 g.")
    elif float(left["calories"]) < float(right["calories"]):
        lines.append(f"- **{first_name}** is lower in calories per 100 g.")
    lines.append(
        f"- Quick macro line: {first_name} — {_ai_macro_summary(left)}; "
        f"{second_name} — {_ai_macro_summary(right)}."
    )
    return "\n".join(lines)


def _ai_travel_answer(
    question: str, details: dict[str, dict], context: dict, hinglish: bool
) -> str:
    """Travel intent: portable format, serving, city availability and one tip."""
    city = context.get("selected_city") or ""
    mentions = _ai_food_mentions(question, details)
    if mentions:
        name = mentions[0]
        detail = details[name]
        how_to = PRODUCT_HOW_TO_USE.get(name, {})
        tip = (
            list(how_to.get("tips") or [])
            or ["Keep a measured portion in a small airtight container."]
        )[0]
        available = (
            "Yes"
            if city and city in detail.get("cities", [])
            else f"Not listed for {city or 'your city'}"
        )
        lines = [
            f"**{name} for travel — quick guide:**"
            if not hinglish
            else f"**{name} travel ke liye — quick guide:**",
            f"- Serving: {how_to.get('serving') or f'{_ai_serving_grams(name)} g'}",
            f"- Best time: {how_to.get('best_time') or 'Any time of day'}",
            f"- Pack it: {tip}",
            f"- Available in {city or 'your city'}: {available}",
            f"- {_ai_serving_summary(name, detail)}",
        ]
        return "\n".join(lines)

    pool = [(name, detail) for name, detail in details.items() if _ai_allowed(detail, context)]
    in_city = [
        (name, detail) for name, detail in pool
        if city and city in detail.get("cities", [])
    ]
    pool = in_city or pool
    pool.sort(
        key=lambda item: (
            float(item[1]["protein"]) * 2.5
            + float(item[1]["fiber"]) * 1.5
            + (12 if item[1].get("low_sugar") else 0)
            - float(item[1]["carbs"]) * 0.25
            - float(item[1]["calories"]) * 0.04
        ),
        reverse=True,
    )
    if not pool:
        return (
            "No catalogue food matches every filter you have set. "
            "Remove one diet or allergen rule and I can suggest options."
        )
    heading = (
        f"**Travel-friendly picks available in {city}:**"
        if in_city and city and not hinglish
        else "**Travel-friendly picks from the catalogue:**"
        if not hinglish
        else f"**Travel ke liye best picks — {city or 'catalogue'}:**"
    )
    lines = [heading]
    for name, detail in pool[:3]:
        how_to = PRODUCT_HOW_TO_USE.get(name, {})
        tip = (
            list(how_to.get("tips") or [])
            or ["Carry a measured portion in a small container."]
        )[0]
        lines.append(
            f"- **{name}**: "
            f"{how_to.get('serving') or f'{_ai_serving_grams(name)} g'} serving; "
            f"{tip} {_ai_serving_summary(name, detail)}"
        )
    lines.append("- Tip: portion nut butters and nuts before leaving home.")
    return "\n".join(lines)


def _ai_general_answer(
    question: str, details: dict[str, dict], context: dict, hinglish: bool
) -> str:
    """Macro lookup with practical tips; useful even with no explicit intent."""
    name = _ai_resolve_food(question, details, context)
    if name:
        detail = details[name]
        how_to = PRODUCT_HOW_TO_USE.get(name, {})
        tips = list(how_to.get("tips") or [])[:2]
        if not tips:
            tips = ["Use a measured portion.", "Pair it with a balanced meal."]
        heading = (
            f"**{name} — quick details:**"
            if hinglish
            else f"**{name} at a glance:**"
        )
        lines = [
            heading,
            f"- Per 100 g: {_ai_macro_summary(detail)}",
            f"- Per serving: {_ai_serving_summary(name, detail)}",
            f"- Serving size: {how_to.get('serving') or f'{_ai_serving_grams(name)} g'}",
            f"- Best time: {how_to.get('best_time') or 'Any time of day'}",
            "- 2 quick tips:",
        ]
        lines.extend(f"  - {tip}" for tip in tips)
        return "\n".join(lines)

    pool = [(n, d) for n, d in details.items() if _ai_allowed(d, context)]
    pool.sort(key=lambda item: float(item[1]["protein"]), reverse=True)
    if not pool:
        return (
            "No catalogue food matches every filter you have set. "
            "Try removing one diet or allergen rule."
        )
    lines = [
        "**Strongest protein options that fit your rules:**"
        if not hinglish
        else "**Aapke rules ke hisaab se best protein options:**"
    ]
    lines.extend(
        f"- **{n}** — {_ai_macro_summary(d)}" for n, d in pool[:3]
    )
    lines.append("Ask me how to eat one, its benefits, or a comparison.")
    return "\n".join(lines)


def _deterministic_ai_answer(
    question: str, details: dict[str, dict], context: dict
) -> str:
    """Intent-aware, data-backed answer that works with no API key/network."""
    q = _ai_text(question)
    hinglish = _ai_has_phrase(q, _AI_HINGLISH_PHRASES)

    # Compare first so "almond butter vs peanut butter benefits" is not stolen
    # by the benefits or macro-lookup branches.
    if _ai_has_phrase(q, _AI_COMPARE_PHRASES):
        return _ai_compare_answer(q, details, context, hinglish)

    if _ai_has_phrase(q, _AI_HOW_PHRASES):
        name = _ai_resolve_food(q, details, context)
        if name:
            return _ai_how_to_answer(name, details[name], context, hinglish)

    if _ai_has_phrase(q, _AI_BENEFIT_PHRASES):
        name = _ai_resolve_food(q, details, context)
        if name:
            return _ai_benefits_answer(q, name, details[name], context, hinglish)

    if _ai_has_phrase(q, _AI_TRAVEL_PHRASES):
        return _ai_travel_answer(q, details, context, hinglish)

    goal = _ai_goal(context, "protein_goal", 120)
    calories = _ai_goal(context, "calorie_goal", 2000)
    city = context.get("selected_city") or ""

    def goal_note(detail: dict) -> str:
        pct = round(float(detail["protein"]) / goal * 100) if goal else 0
        kcal_pct = round(float(detail["calories"]) / calories * 100) if calories else 0
        return (
            f"{pct}% of your {goal:g} g protein goal · "
            f"{kcal_pct}% of your {calories:g} kcal goal per 100 g"
        )

    def lines_for(items: list[tuple[str, dict]]) -> list[str]:
        return [
            f"- **{name}** — {_ai_macro_summary(detail)}; {goal_note(detail)}."
            for name, detail in items
        ]

    high_protein = _ai_has_phrase(
        q, ("high", "best", "top", "more", "boost")
    ) and _ai_has_phrase(q, ("protein",))
    if high_protein or _ai_has_phrase(q, ("vegetarian", "vegan", "diet")):
        pool = [
            (name, detail)
            for name, detail in details.items()
            if _ai_allowed(detail, context)
        ]
        if _ai_has_phrase(q, ("vegetarian", "vegan")):
            require_vegan = "vegan" in q
            pool = [
                (name, detail)
                for name, detail in pool
                if (detail.get("vegan") if require_vegan else detail.get("vegetarian"))
            ]
        pool.sort(key=lambda item: float(item[1]["protein"]), reverse=True)
        if not pool:
            return (
                "No catalogue food matches every filter you have set. "
                "Try removing one diet or allergen rule."
            )
        heading = (
            "Highest-protein vegan options"
            if "vegan" in q
            else "Highest-protein vegetarian options"
            if "vegetarian" in q
            else "Highest-protein options that fit your rules"
        )
        return "\n".join([heading + " (per 100 g):", *lines_for(pool[:5])])

    if city and city.lower() in q:
        pool = [
            (name, detail)
            for name, detail in details.items()
            if _ai_allowed(detail, context) and city in detail.get("cities", [])
        ]
        if pool:
            pool.sort(key=lambda item: float(item[1]["protein"]), reverse=True)
            return "\n".join(
                [f"Catalogue foods available in **{city}** (per 100 g):",
                 *lines_for(pool[:5])]
            )

    # Any product lookup now gets macros plus practical tips, never a bare dump.
    return _ai_general_answer(q, details, context, hinglish)


def _generate_ai_answer(question: str) -> str:
    """LLM answer when configured, with a deterministic data-backed fallback."""
    details = load_product_details()
    context = _ai_current_context()
    llm_answer = _call_anthropic(_ai_system_prompt(context, details), question)
    if llm_answer:
        return llm_answer
    return _deterministic_ai_answer(question, details, context)


def _submit_ai_question(question: str) -> None:
    """Append one exchange to the in-session AI chat history."""
    question = question.strip()
    if not question:
        return
    history = list(st.session_state.get("ai_chat_history") or [])
    history.append({"role": "user", "content": question})
    try:
        answer = _generate_ai_answer(question)
    except Exception:
        answer = _deterministic_ai_answer(
            question, load_product_details(), _ai_current_context()
        )
    history.append({"role": "assistant", "content": answer})
    # Keep the panel light on long sessions while preserving recent context.
    st.session_state["ai_chat_history"] = history[-20:]


def _submit_ai_prompt(prompt: str) -> None:
    """Quick-chip callback: append the answer in the button's single rerun."""
    _submit_ai_question(prompt)


def _open_ai_help() -> None:
    """Top-bar Help button: open the dedicated AI view from a clean home."""
    st.session_state["show_ai_help"] = True
    st.session_state["inspect_product"] = None
    st.session_state["show_swaps_results"] = False
    st.session_state["show_wishlist_page"] = False
    st.session_state["show_all_products_page"] = False
    st.session_state["show_install_page"] = False
    st.session_state["_collapse_sidebar_for_details"] = False
    st.session_state["_collapse_sidebar_for_wishlist"] = False
    st.session_state["_collapse_sidebar_for_catalogue"] = False
    st.session_state["_collapse_sidebar_for_install"] = False
    st.session_state.pop("match_result_data", None)


def _render_ai_back_to_home(key: str) -> None:
    """Top-right dark-emerald back button for the dedicated AI help page."""
    _render_top_right_back_button(key, _close_ai_help)


def _render_ai_help() -> None:
    """Dedicated full-page AI assistant with a top-right back button."""
    if not st.session_state.get("show_ai_help"):
        return

    # Same dark-emerald pill as the details/swaps views, but left-aligned.
    _render_ai_back_to_home("ai_help_back_to_home")

    with st.container(border=True):
        st.markdown(
            '<div class="ai-help-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="ai-help-heading">🤖 MacroMatch Nutrition &amp; Product Assistant</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="ai-help-subtitle">Ask anything about our 30 foods, '
            "macros, travel swaps, or your personal diet goals.</div>",
            unsafe_allow_html=True,
        )

        suggestions = [
            "💪 High-protein vegetarian options",
            "🥗 Compare my selected food macros",
            "✈️ Best travel snacks for my diet",
        ]
        quick_col1, quick_col2, quick_col3 = st.columns(3)
        for col, label in zip(
            (quick_col1, quick_col2, quick_col3), suggestions
        ):
            with col:
                st.button(
                    label,
                    key=f"ai_quick_{label[:12]}",
                    use_container_width=True,
                    type="secondary",
                    on_click=_submit_ai_prompt,
                    args=(label,),
                )

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        for message in st.session_state.get("ai_chat_history", []):
            with st.chat_message(message.get("role", "assistant")):
                st.markdown(message.get("content", ""))

        chat_prompt = st.chat_input(
            "Ask anything about foods, macros, or your diet..."
        )
        if chat_prompt:
            _submit_ai_question(chat_prompt)
            # chat_input already returns through a rerun; this second pass only
            # renders the freshly appended user/assistant pair in order.
            st.rerun()


def _render_wishlist_page() -> None:
    """Dedicated full-page wishlist with a responsive 3-column card grid."""
    if not st.session_state.get("show_wishlist_page"):
        return

    # The one-shot mobile collapse flag is consumed by the deferred JS block.
    _render_wishlist_back_to_home("wishlist_back_to_home")
    wishlist_items = _normalize_wishlist(st.session_state.get("wishlist", []))

    with st.container(border=True):
        st.markdown(
            '<div class="wishlist-page-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="wishlist-page-heading">❤️ Your Saved Wishlist '
            f'<span>({len(wishlist_items)})</span></div>',
            unsafe_allow_html=True,
        )

        if not wishlist_items:
            st.markdown(
                '<div class="wishlist-empty-card">'
                '<span class="empty-icon">💚</span>'
                '<span class="empty-title">Nothing saved yet</span>'
                "Tap <strong>🤍 Wishlist</strong> on any food card to keep it "
                "here for quick access."
                "</div>",
                unsafe_allow_html=True,
            )
            return

        details = load_product_details()
        st.markdown(
            '<div class="wishlist-grid-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        grid_cols = st.columns(3, gap="medium")
        for index, food_name in enumerate(wishlist_items):
            with grid_cols[index % 3]:
                detail = details.get(food_name)
                if detail is None:
                    st.caption(f"⚠️ {food_name} is no longer in the catalogue.")
                    continue
                _render_sidebar_product_card(
                    food_name,
                    detail,
                    key_prefix="wish_page",
                    wishlist_label="🗑️ Remove",
                    on_wishlist_click=_remove_wishlist_item,
                )


def _render_catalogue_page() -> None:
    """Dedicated full-page catalogue with a responsive 3-column card grid."""
    if not st.session_state.get("show_all_products_page"):
        return

    # The one-shot mobile collapse flag is consumed by the deferred JS block.
    _render_catalogue_back_to_home("catalogue_back_to_home")
    details = load_product_details()
    all_products = sorted(details)
    initial_count = int(
        st.session_state.get("catalogue_initial_count", CATALOGUE_PAGE_SIZE)
    )
    visible_count = min(
        int(st.session_state.get("catalogue_visible_count", CATALOGUE_PAGE_SIZE)),
        len(all_products),
    )
    st.session_state["catalogue_visible_count"] = visible_count

    with st.container(border=True):
        st.markdown(
            '<div class="catalogue-page-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="catalogue-page-heading">📖 All Available Products '
            f'<span>({len(all_products)})</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="catalogue-grid-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        grid_cols = st.columns(3, gap="medium")
        for index, item_name in enumerate(all_products[:visible_count]):
            with grid_cols[index % 3]:
                _render_sidebar_product_card(
                    item_name,
                    details[item_name],
                    key_prefix="catalogue",
                )

        st.caption(f"Showing {visible_count} of {len(all_products)} products")

        if visible_count < len(all_products):
            st.markdown(
                '<div class="catalogue-view-more-marker" aria-hidden="true"></div>',
                unsafe_allow_html=True,
            )
            st.button(
                "View More",
                key="catalogue_view_more",
                use_container_width=False,
                on_click=_show_more_catalogue_products,
            )

        if visible_count > initial_count:
            st.markdown(
                '<div class="catalogue-show-less-marker" aria-hidden="true"></div>',
                unsafe_allow_html=True,
            )
            st.button(
                "Show Less",
                key="catalogue_show_less",
                use_container_width=False,
                on_click=_show_less_catalogue_products,
            )


def _render_install_page() -> None:
    """Dedicated full-page install guide with native-prompt fallback."""
    if not st.session_state.get("show_install_page"):
        return

    # The one-shot mobile collapse flag is consumed by the deferred JS block.
    _render_install_back_to_home("install_back_to_home")

    with st.container(border=True):
        st.markdown(
            '<div class="install-page-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="install-page-heading">📲 Install MacroMatch Mobile App</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="install-page-subtitle">Keep MacroMatch on your home '
            "screen for one-tap access to swaps, macros and your wishlist."
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="install-steps-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        android_col, iphone_col = st.columns(2, gap="medium")
        with android_col:
            st.markdown(
                '<div class="install-step-card">'
                '<div class="install-step-num">1</div>'
                '<div class="install-step-title">🤖 Android — Chrome</div>'
                '<div class="install-step-body">Tap the <strong>⋮ menu</strong>, '
                "then choose <strong>Install app</strong> or "
                "<strong>Add to Home screen</strong>.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
        with iphone_col:
            st.markdown(
                '<div class="install-step-card">'
                '<div class="install-step-num">2</div>'
                '<div class="install-step-title">🍎 iPhone — Safari</div>'
                '<div class="install-step-body">Tap <strong>Share (⬆️)</strong>, '
                "then choose <strong>Add to Home Screen</strong>.</div>"
                "</div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            '<div id="mm-pwa-install-slot"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="install-native-note">If your browser supports a one-tap '
            "install, the button appears above automatically. Otherwise follow "
            "the steps for your device.</div>",
            unsafe_allow_html=True,
        )
        # The native-install button helper runs in the deferred JS block so it
        # cannot add blank space above the top-right back button.


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


def _goal_number(key: str, default: float) -> float:
    try:
        value = float(st.session_state.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _goal_percent(value: float, goal: float) -> float:
    return value / goal * 100 if goal else 0.0


def _nutrition_table_html(
    detail: dict, serving_g: int, protein_goal: float, calorie_goal: float
) -> str:
    """Exact per-100 g and per-serving macros with daily-goal context."""
    factor = serving_g / 100.0
    rows = []
    for label, key in (
        ("Protein", "protein"),
        ("Carbs", "carbs"),
        ("Fat", "fat"),
        ("Fibre", "fiber"),
        ("Energy", "calories"),
    ):
        per_100 = float(detail[key])
        per_serving = per_100 * factor

        def cell(value: float) -> str:
            text = f"{value:.0f} kcal" if key == "calories" else f"{value:g} g"
            if key == "protein":
                text += f" <span style='color:#7EE2A8;'>({_goal_percent(value, protein_goal):.0f}% goal)</span>"
            elif key == "calories":
                text += f" <span style='color:#FBBF24;'>({_goal_percent(value, calorie_goal):.0f}% goal)</span>"
            return text

        rows.append(
            f"<tr><td>{label}</td><td>{cell(per_100)}</td>"
            f"<td>{cell(per_serving)}</td></tr>"
        )
    return (
        '<table class="detail-macro-table">'
        "<thead><tr><th>Nutrient</th><th>Per 100 g</th>"
        f"<th>Per {serving_g:g} g</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _smart_swaps(
    name: str, detail: dict, details: dict[str, dict], limit: int = 2
) -> list[str]:
    """Nearby catalogue foods by macro distance, preferring the same category."""
    scored: list[tuple[float, str]] = []
    for other_name, other_detail in details.items():
        if other_name == name:
            continue
        distance = 0.0
        for key in MACRO_COLS:
            base = float(detail[key]) or 1.0
            distance += ((float(other_detail[key]) - float(detail[key])) / base) ** 2
        if other_detail.get("category") == detail.get("category"):
            distance *= 0.55
        scored.append((distance, other_name))
    scored.sort(key=lambda item: item[0])
    return [other_name for _, other_name in scored[:limit]]


def _render_complete_food_guide(
    name: str, detail: dict, keto: bool, details: dict[str, dict]
) -> None:
    """Full-page education card shown only in the dedicated details view."""
    how_to = PRODUCT_HOW_TO_USE.get(name, {})
    serving_g = int(PRODUCT_SERVING_G.get(name, 100))
    protein_goal = _goal_number("daily_protein_goal", 120)
    calorie_goal = _goal_number("daily_calorie_goal", 2000)
    about = PRODUCT_ABOUT.get(
        name,
        f"{name} is one of MacroMatch's 30 catalogue foods. Use the macro table "
        "below to compare it with your daily goals.",
    )
    tips = list(how_to.get("tips") or [])
    swaps = _smart_swaps(name, detail, details)
    caution = PRODUCT_CAUTIONS.get(name)
    flags_html = (
        _badges_html(detail)
        or '<span class="detail-mini-value">No flags listed.</span>'
    )

    with st.container(border=True):
        st.markdown(
            '<div class="detail-guide-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        st.markdown("#### 🍽️ Complete Food & Nutrition Guide")

        st.markdown(
            '<div class="detail-section-title">💚 About This Food &amp; Health Benefits</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="detail-copy">{html.escape(about)}</div>',
            unsafe_allow_html=True,
        )

        macro_col, tips_col = st.columns([1.05, 1], gap="medium")
        with macro_col:
            st.markdown(
                '<div class="detail-section-title">🍴 Serving Size &amp; Daily Goal Impact</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <div class="detail-mini-card">
                    <p class="detail-mini-label">Serving Size</p>
                    <p class="detail-mini-value">{html.escape(str(how_to.get('serving', f'{serving_g} g')))}</p>
                </div>
                <div class="detail-mini-card">
                    <p class="detail-mini-label">⏰ Best Time to Have</p>
                    <p class="detail-mini-value">{html.escape(str(how_to.get('best_time', 'Any time')))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                _nutrition_table_html(detail, serving_g, protein_goal, calorie_goal),
                unsafe_allow_html=True,
            )
            if keto:
                net_carbs = max(0.0, detail["carbs"] - detail["fiber"])
                st.caption(
                    f"Keto view: {net_carbs:g} g net carbs per 100 g "
                    f"({net_carbs * serving_g / 100:g} g per serving)."
                )

        with tips_col:
            st.markdown(
                '<div class="detail-section-title">💡 Tips &amp; Ways to Eat</div>',
                unsafe_allow_html=True,
            )
            if tips:
                tips_html = "".join(
                    f"<li>{html.escape(tip)}</li>" for tip in tips
                )
                st.markdown(
                    f'<ul class="detail-tip-list">{tips_html}</ul>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="detail-copy">No preparation notes are stored for this food yet.</div>',
                    unsafe_allow_html=True,
                )
            pairing = PRODUCT_PAIRINGS.get(name)
            if pairing:
                st.markdown(
                    f"""
                    <div class="detail-mini-card">
                        <p class="detail-mini-label">🥗 Pairing Ideas</p>
                        <p class="detail-mini-value">{html.escape(pairing)}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown(
            '<div class="detail-section-title">🔁 Smart Swaps &amp; Storage / Caution Notes</div>',
            unsafe_allow_html=True,
        )
        swap_col, caution_col = st.columns([1, 1], gap="medium")
        with swap_col:
            if swaps:
                swap_html = "".join(
                    f"<li>{html.escape(swap)} — {_ai_macro_summary(details[swap])}</li>"
                    for swap in swaps
                    if swap in details
                )
                st.markdown(
                    '<div class="detail-copy" style="margin-bottom:0.35rem !important;">'
                    "Closest catalogue alternatives by macro profile "
                    "(same category preferred):</div>"
                    f'<ul class="detail-tip-list">{swap_html}</ul>',
                    unsafe_allow_html=True,
                )
            storage = PRODUCT_STORAGE.get(name)
            if storage:
                st.markdown(
                    f"""
                    <div class="detail-mini-card">
                        <p class="detail-mini-label">📦 Storage</p>
                        <p class="detail-mini-value">{html.escape(storage)}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        with caution_col:
            st.markdown(
                '<div class="detail-mini-card">'
                '<p class="detail-mini-label">🏷️ Diet &amp; Allergen Flags</p>'
                f"{flags_html}"
                "</div>",
                unsafe_allow_html=True,
            )
            if caution:
                st.markdown(
                    f'<div class="caution-box"><strong>⚠️ Caution / Who Should Avoid:</strong> {html.escape(caution)}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.caption(
                    "No special caution is listed for this food. Check local "
                    "packaging for allergen and cross-contamination details."
                )


def render_product_spotlight(
    name: str, detail: dict, keto: bool = False, all_details: dict[str, dict] | None = None
) -> None:
    """Main nutrition summary followed by the complete food & nutrition guide."""
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
            render_wishlist_button(name, key=f"wishlist_spotlight_{name}")
            with st.expander(f"📍 Available in {len(detail['cities'])} cities"):
                st.write(", ".join(detail["cities"]))

    # Full education card: about, serving math, tips, swaps, storage, caution.
    _render_complete_food_guide(
        name,
        detail,
        keto,
        all_details if all_details is not None else load_product_details(),
    )


def _render_sidebar_product_card(
    item_name: str,
    detail: dict,
    *,
    key_prefix: str,
    wishlist_label: str | None = None,
    on_wishlist_click=None,
) -> None:
    """Shared dark card for the full-page wishlist and product catalogue."""
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
        # Identical 3-button row on both full-page surfaces. "Select" is
        # auto-collapsed on mobile; "View Details" opens the dedicated guide.
        col_sel, col_det, col_wish = st.columns([1, 1.15, 1])
        with col_sel:
            st.button(
                "Select",
                key=f"{key_prefix}_select_{item_name}",
                use_container_width=True,
                type="secondary",
                on_click=select_food_value_callback,
                args=(item_name,),
            )
        with col_det:
            st.button(
                "👁️ View Details",
                key=f"{key_prefix}_details_{item_name}",
                use_container_width=True,
                type="secondary",
                on_click=inspect_food_value_callback,
                args=(item_name,),
            )
        with col_wish:
            if wishlist_label is None:
                render_wishlist_button(
                    item_name,
                    key=f"{key_prefix}_wish_{item_name}",
                    use_container_width=True,
                )
            else:
                st.button(
                    wishlist_label,
                    key=f"{key_prefix}_heart_{item_name}",
                    use_container_width=True,
                    type="secondary",
                    on_click=on_wishlist_click or toggle_wishlist,
                    args=(item_name,),
                    help=f"Remove {item_name} from wishlist",
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
            <div>Photos: Wikimedia Commons.</div>
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


if (
    not show_product_details
    and not show_ai_help
    and not show_wishlist_page
    and not show_all_products_page
    and not show_install_page
):
    # ─────────────────────────────────────────────
    # Hero header (home + results only)
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

    # Pinned directly under the header, before the search card. The AI help
    # toggle sits beside the how-it-works bar with its emerald-accented style.
    col_how, col_ai = st.columns([1.3, 1], vertical_alignment="center")
    with col_how:
        render_how_it_works()
    with col_ai:
        st.markdown(
            '<div class="ai-help-toggle-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "❓ Help",
            key="ai_help_toggle",
            use_container_width=True,
            on_click=_open_ai_help,
        ):
            pass

    # The dedicated AI Help page renders after the sidebar, below.


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

    # ─── Profile pill + elevated glass card (Supabase Auth) ─────────────
    _auth_user = st.session_state.get("supabase_user")
    _metadata = getattr(_auth_user, "user_metadata", None) or {}
    _email_local = CURRENT_USER_EMAIL.split("@")[0] if CURRENT_USER_EMAIL else "there"
    user_name = str(_metadata.get("full_name") or _email_local).strip() or _email_local
    _safe_user_name = html.escape(user_name)
    _safe_email = html.escape(CURRENT_USER_EMAIL)
    _profile_initial = html.escape(user_name[0].upper())
    try:
        _protein_goal = int(st.session_state.get("daily_protein_goal", 120))
    except (TypeError, ValueError):
        _protein_goal = 120
    try:
        _calorie_goal = int(st.session_state.get("daily_calorie_goal", 2000))
    except (TypeError, ValueError):
        _calorie_goal = 2000
    _wishlist_count = len(_normalize_wishlist(st.session_state.get("wishlist", [])))
    _saved_count = len(get_saved_matches(CURRENT_USER_ID) or [])

    st.markdown(
        '<div class="profile-toggle-marker" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    _profile_caret = "▴" if st.session_state.get("show_user_profile") else "▾"
    st.button(
        f"🟢  {user_name}   {_profile_caret}",
        key="sidebar_profile_toggle",
        use_container_width=True,
        type="secondary",
        on_click=_toggle_user_profile,
    )

    if st.session_state.get("show_user_profile"):
        st.markdown(
            f"""
            <div class="profile-card">
                <div class="profile-user-row">
                    <div class="profile-avatar">{_profile_initial}</div>
                    <div>
                        <div class="profile-name">{_safe_user_name}</div>
                        <div class="profile-email">{_safe_email}</div>
                    </div>
                </div>
                <div class="profile-stat-pill">🎯 {_protein_goal}g Protein · {_calorie_goal} kcal</div>
                <div class="profile-stat-pill">❤️ {_wishlist_count} Wishlist  ·  🕒 {_saved_count} Swaps</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="profile-signout-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        st.button(
            "🚪 Sign out",
            key="profile_card_signout",
            use_container_width=True,
            type="secondary",
            on_click=_profile_sign_out,
        )

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ─── Per-user saved matches history (Supabase, user_id-keyed) ────────
    # Open the expander automatically on the rerun right after a save so the
    # newly inserted row is immediately visible.
    with st.expander(
        "🕘 My saved matches",
        expanded=bool(st.session_state.get("saved_match_flash")),
    ):
        st.markdown(
            '<div class="saved-matches-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        saved_matches_slot = st.empty()
        render_saved_matches(saved_matches_slot)

    # ─── Wishlist launcher (full page lives on the main screen) ──────────
    product_details = load_product_details()
    st.markdown(
        '<div class="wishlist-open-marker" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    st.button(
        f"❤️ View Your Wishlist ({len(st.session_state['wishlist'])})",
        key="open_wishlist_page",
        use_container_width=True,
        type="secondary",
        on_click=_open_wishlist_page,
    )

    # ─── Product guide (opens the dedicated full-page catalogue) ─────────
    st.markdown(
        '<div class="sidebar-section-title">📖 Product guide</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Browse every food with its photo, macros per 100 g, diet rules and "
        "allergens on a full page."
    )
    st.markdown(
        '<div class="catalogue-open-marker" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    st.button(
        f"📖 View All Products ({len(product_details)})",
        key="open_catalogue_page",
        use_container_width=True,
        type="secondary",
        on_click=_open_catalogue_page,
    )

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

    # ─── Mobile install launcher (full page lives on the main screen) ───
    st.markdown(
        '<div class="install-open-marker" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    st.button(
        "📲 Install Mobile App",
        key="sidebar_install_app_btn",
        use_container_width=True,
        type="secondary",
        on_click=_open_install_page,
    )

    # ─── Bottom activity footer ────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="sidebar-stats">
            <div class="stats-row">
                <span class="stats-label">Saved matches</span>
                <span class="stats-value">{_saved_count}</span>
            </div>
            <div class="stats-tip">
                <div style="font-size: 14.5px; color: #C9D1D9; line-height: 1.45;"><strong style="color: #FBBF24;">💡 Tip:</strong> Open the product guide to load any food instantly.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
# Dedicated PWA Install page — replaces the entire main screen
# ─────────────────────────────────────────────
if show_install_page:
    _render_install_page()
    _stop_after_deferred_components()


# ─────────────────────────────────────────────
# Dedicated Product Catalogue page — replaces the entire main screen
# ─────────────────────────────────────────────
if show_all_products_page:
    _render_catalogue_page()
    _stop_after_deferred_components()


# ─────────────────────────────────────────────
# Dedicated Wishlist page — replaces the entire main screen
# ─────────────────────────────────────────────
if show_wishlist_page:
    _render_wishlist_page()
    _stop_after_deferred_components()


# ─────────────────────────────────────────────
# Dedicated AI Help page — replaces the entire main screen
# ─────────────────────────────────────────────
if show_ai_help:
    _render_ai_help()
    _stop_after_deferred_components()


# ─────────────────────────────────────────────
# Dedicated Product Details page — replaces the entire main screen
# ─────────────────────────────────────────────
if show_product_details:
    details_map = load_product_details()
    inspected_name = st.session_state.get("inspect_product")
    inspected_detail = details_map.get(inspected_name)

    if not inspected_detail:
        # Stale state (e.g. a product removed from the CSV) → clean home.
        st.session_state["inspect_product"] = None
        st.session_state["_collapse_sidebar_for_details"] = False
        st.rerun()

    # The one-shot mobile collapse flag is consumed by the deferred JS block.
    _render_back_to_home("back_to_home_details")
    st.markdown("### 🥗 Product Overview")
    details_context = _ai_current_context()
    render_product_spotlight(
        inspected_name,
        inspected_detail,
        keto="keto" in details_context["diets"],
        all_details=details_map,
    )
    _stop_after_deferred_components()


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
        # The active choice lives in the placeholder, not in `default`, so the
        # input stays empty at rest and typing/backspacing is never snapped back.
        placeholder=f"🔍 {selected_product} (or type to search...)",
        default=None,
        default_searchterm="",
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
        f'<div class="selected-value" style="font-size: 16px; font-weight: 700; color: #E6EDF3; margin: 6px 0 10px 0;">Selected food: <span style="color: #4ADE80;">{html.escape(selected_product)}</span></div>',
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
        '<div class="search-card-title" style="display: flex; align-items: center; gap: 10px; margin: 14px 0 8px 0;">'
        '<span class="step-badge search-step-badge" style="background-color: #2EA043; color: #FFFFFF; font-weight: 800; font-size: 14px; width: 26px; height: 26px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;">2</span>'
        '<span class="search-step-label" style="color: #4ADE80; font-weight: 700; font-size: 17px; letter-spacing: 0.04em;">DESTINATION</span>'
        '</div>',
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
        # Same placeholder-driven pattern as the food box: show the current
        # city at rest, but leave the field itself free for instant typing.
        placeholder=f"🔍 {selected_city} (or type to search...)",
        default=None,
        default_searchterm="",
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
        f'<div class="selected-value" style="font-size: 16px; font-weight: 700; color: #E6EDF3; margin: 6px 0 10px 0;">Selected city: <span style="color: #4ADE80;">{html.escape(selected_city)}</span></div>',
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
        '<div class="search-card-title" style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">'
        '<span class="step-badge search-step-badge" style="background-color: #2EA043; color: #FFFFFF; font-weight: 800; font-size: 14px; width: 26px; height: 26px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;">1</span>'
        '<span class="search-step-label" style="color: #4ADE80; font-weight: 700; font-size: 17px; letter-spacing: 0.04em;">YOUR PRODUCT — What do you normally eat?</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    # Fast 2.5 s API probe with an instant local fallback and no spinner, so a
    # sleeping free-tier backend never holds up the UI. The wake-up ping was
    # already fired in a background thread when this page loaded.
    all_foods = cached_all_foods()
    all_cities = cached_all_cities()

    if not all_foods:
        st.error("No food data is available. Check `data/products.csv`.")
        _stop_after_deferred_components()

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

    st.markdown(
        '<div style="display: flex; align-items: center; gap: 10px; margin: 16px 0 8px 0;"><span style="background-color: #2EA043; color: #FFFFFF; font-weight: 800; font-size: 14px; width: 26px; height: 26px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;">3</span><span style="color: #4ADE80; font-weight: 700; font-size: 17px; letter-spacing: 0.04em;">PREFERENCES — Customize your diet & macro priority</span></div>',
        unsafe_allow_html=True,
    )
    with st.expander("🥦 Filters — diet, allergens & priority", expanded=True):
        st.markdown(
            '<div class="filters-expander-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
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
            "**Allergens to avoid**",
            options=ALLERGEN_OPTIONS,
            format_func=lambda x: {
                "soy": "🫘 Soy", "nuts": "🥜 Nuts", "dairy": "🥛 Dairy"
            }[x],
            key="allergen_select",
        )

        priority_label = st.radio(
            "**What matters most in the match?**",
            options=PRIORITY_KEYS,
            format_func=lambda k: PRIORITY_LABELS[k].replace(" ", "\u00a0", 1),
            index=2,   # default: balanced
            key="priority_radio",
        )

    st.button(
        "🔍 Find Alternatives",
        use_container_width=True,
        type="primary",
        key="find_alternatives",
        on_click=_open_swaps_results,
    )

    show_swaps_results = st.session_state["show_swaps_results"]


# ─────────────────────────────────────────────
# Main area — results
# ─────────────────────────────────────────────

# Default home: only the clean Step 1 / 2 / 3 search card is shown here.
# Details mode already returned above, so the search form is fully hidden.
if not show_swaps_results:
    render_footer()
    _stop_after_deferred_components()


# ── Back to home ──────────────────────────────
# In the swaps view this stays at the very top, immediately before the results
# container. The product card now lives on its own details page, not here.
_render_back_to_home("back_to_home")


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
        _stop_after_deferred_components()

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
        _stop_after_deferred_components()

    if response.status_code == 422:
        # FastAPI validation errors arrive as a list of {loc, msg, type} objects.
        st.error("❌ **Invalid input.** Check your selections and try again.")
        with st.expander("Details"):
            st.json(response.json().get("detail", response.text))
        _stop_after_deferred_components()

    if response.status_code != 200:
        st.error(f"❌ Unexpected error ({response.status_code}): {response.text}")
        _stop_after_deferred_components()

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
        '<div style="background: linear-gradient(135deg, rgba(46, 160, 67, 0.16), rgba(22, 27, 34, 0.95)); '
        'border: 1px solid rgba(46, 160, 67, 0.55); border-radius: 12px; '
        'padding: 14px 18px; margin-bottom: 1.25rem; display: flex; '
        'align-items: center; gap: 1rem;">'
        '<span style="font-size: 1.5rem">✅</span>'
        '<div>'
        '<span style="font-size: 20px; font-weight: 800; color: #FFFFFF;">'
        f"Top {len(alternatives)} Swap{'s' if len(alternatives) != 1 else ''} for "
        f'<span style="color: #4ADE80; font-style: normal; font-weight: 800;">{html.escape(selected_product)}</span>'
        ' in '
        f'<span style="color: #4ADE80; font-style: normal; font-weight: 800;">{html.escape(selected_city)}</span>'
        '</span><br>'
        '<span style="color: #E6EDF3; font-weight: 700; font-size: 15px;">'
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
            "**Per Serving**",
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
                    col_wish, col_save = st.columns([1, 1])
                    with col_wish:
                        render_wishlist_button(
                            alt["name"],
                            key=f"wishlist_swap_{rank_i + 1}",
                            use_container_width=True,
                        )
                    with col_save:
                        st.button(
                            "💾 Save Match",
                            key=f"save_swap_{rank_i + 1}",
                            use_container_width=True,
                            type="primary",
                            on_click=_save_match_callback,
                            args=(
                                selected_product,
                                selected_city,
                                selected_diets,
                                selected_allergens,
                                priority_label,
                                [alt],
                            ),
                        )

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

# Defer every zero-height JS component until all visible content is rendered.
_render_deferred_components()
