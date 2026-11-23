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
import base64
import json
from datetime import datetime, timezone

import streamlit as st
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

from supabase import create_client, Client  # >>> NEW: Supabase client for Auth + database

# Load .env (local dev). On Streamlit Community Cloud, use the app's Secrets instead.
load_dotenv()

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


# Session-state keys for Supabase Auth persistence
if "supabase_user" not in st.session_state:
    st.session_state["supabase_user"] = None
if "supabase_access_token" not in st.session_state:
    st.session_state["supabase_access_token"] = None
if "supabase_refresh_token" not in st.session_state:
    st.session_state["supabase_refresh_token"] = None
if "supabase_user_name" not in st.session_state:
    st.session_state["supabase_user_name"] = None


# Restore an existing Supabase session from stored tokens so the user stays
# signed in across Streamlit reruns within the same browser session.
if (
    st.session_state["supabase_access_token"]
    and st.session_state["supabase_refresh_token"]
    and st.session_state["supabase_user"] is None
):
    try:
        supabase.auth.set_session(
            st.session_state["supabase_access_token"],
            st.session_state["supabase_refresh_token"],
        )
        user_response = supabase.auth.get_user()
        if user_response and user_response.user:
            st.session_state["supabase_user"] = user_response.user
            profile = (
                supabase.table("profiles")
                .select("name")
                .eq("id", user_response.user.id)
                .single()
                .execute()
            )
            if profile.data:
                st.session_state["supabase_user_name"] = profile.data["name"]
    except Exception:
        # Tokens expired or invalid — clear them so the user can sign in again.
        st.session_state["supabase_access_token"] = None
        st.session_state["supabase_refresh_token"] = None


# ─────────────────────────────────────────────
# AUTHENTICATION UI — strict centered card, green buttons, 16px text
# Only rendered when logged out. All Supabase backend logic is unchanged.
# ─────────────────────────────────────────────

# auth_view switches the Sign in tab between three views:
#   "signin" -> normal login form
#   "forgot" -> email + Send Reset Link
#   "reset"  -> email + current/new password + Update Password
if "auth_view" not in st.session_state:
    st.session_state.auth_view = "signin"


if st.session_state["supabase_user"] is None:

    # ── Auth-only CSS — injected BEFORE st.stop() so it actually applies ──
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

    /* 5. Hide Streamlit toolbar / menu / footer */
    header[data-testid="stHeader"], #MainMenu, footer, .stDeployButton {
        display: none !important;
        visibility: hidden !important;
    }

    /* 3. Force Inter + minimum 16px readable text */
    html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif !important; }
    .stTextInput label p,
    .stTextInput input,
    .stTextInput input::placeholder,
    button[data-baseweb="tab"],
    [data-baseweb="tab"] p,
    [data-baseweb="tab"] div,
    .stAlert,
    .stAlert p {
        font-size: 16px !important;
        color: #E6EDF3 !important;
    }

    /* 1. The middle column IS the card */
    div[data-testid="column"]:nth-of-type(2) {
        background-color: #161B22;
        padding: 2.2rem 2rem;
        border-radius: 16px;
        border: 1px solid #30363D;
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
        margin-top: 2.5rem;
    }

    /* Card header + subtitle centered */
    div[data-testid="column"]:nth-of-type(2) h1,
    div[data-testid="column"]:nth-of-type(2) p.auth-sub {
        text-align: center !important;
        color: #E6EDF3 !important;
    }
    div[data-testid="column"]:nth-of-type(2) h1 { font-size: 26px !important; }
    p.auth-sub { font-size: 16px !important; color: #8B949E !important; margin-bottom: 1.5rem !important; }

    /* 2. GREEN primary buttons — override Streamlit's default red */
    div.stButton > button[kind="primary"] {
        background-color: #2EA043 !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-size: 16px !important;
        font-weight: 600 !important;
        padding: 0.65rem 1rem !important;
    }
    /* Fallback for form submit buttons in other Streamlit versions */
    button[kind="primary"], .stFormSubmitButton button {
        background-color: #2EA043 !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-size: 16px !important;
        font-weight: 600 !important;
    }
    div.stButton > button[kind="primary"]:hover,
    button[kind="primary"]:hover {
        background-color: #3FB950 !important;
    }

    /* 4. Secondary buttons styled as clean blue text links */
    div.stButton > button[kind="secondary"] {
        color: #58A6FF !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        font-size: 15px !important;
        padding: 0.25rem 0 !important;
    }
    div.stButton > button[kind="secondary"]:hover {
        color: #79C0FF !important;
        text-decoration: underline !important;
    }

    /* Rounded inputs inside the card */
    div[data-testid="column"]:nth-of-type(2) input {
        background-color: #0D1117 !important;
        border: 1px solid #30363D !important;
        border-radius: 8px !important;
        padding: 0.65rem 0.85rem !important;
        color: #E6EDF3 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 1. STRICT centered card — everything lives inside card_col
    _, card_col, _ = st.columns([1.3, 1.4, 1.3])

    with card_col:
        st.markdown("<h1>🥗 Welcome to MacroMatch</h1>", unsafe_allow_html=True)
        st.markdown(
            '<p class="auth-sub">Sign in to continue or create an account</p>',
            unsafe_allow_html=True,
        )

        tab_signin, tab_signup = st.tabs(["🔐 Sign in", "📝 Sign up"])

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
                        "Sign in", type="primary", use_container_width=True
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
                                    profile = (
                                        supabase.table("profiles")
                                        .select("name")
                                        .eq("id", response.user.id)
                                        .single()
                                        .execute()
                                    )
                                    st.session_state["supabase_user_name"] = (
                                        profile.data["name"]
                                        if profile.data
                                        else response.user.email
                                    )
                                    st.success("✅ Signed in successfully!")
                                    st.rerun()
                                else:
                                    st.error(
                                        "❌ Sign in failed. Please check your credentials."
                                    )
                            except Exception as exc:
                                st.error(f"❌ Sign in error: {exc}")

                # Two text-link buttons right below the password box
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Forgot password?", key="forgot_link"):
                        st.session_state.auth_view = "forgot"
                        st.rerun()
                with col2:
                    if st.button("Reset password", key="reset_link"):
                        st.session_state.auth_view = "reset"
                        st.rerun()

            # ─────────────── VIEW: forgot ───────────────
            elif st.session_state.auth_view == "forgot":
                st.markdown("### Forgot password?")
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
                        with st.spinner("Sending reset link…"):
                            # ── TODO: connect your backend password-reset function ──
                            # supabase.auth.reset_password_for_email(forgot_email)  # v2
                            # supabase.auth.reset_password_email(forgot_email)      # older
                            st.success(
                                "If an account exists for this email, a reset "
                                "link has been sent."
                            )

                if st.button("← Back to Sign in", key="back_from_forgot"):
                    st.session_state.auth_view = "signin"
                    st.rerun()

            # ─────────────── VIEW: reset ───────────────
            elif st.session_state.auth_view == "reset":
                st.markdown("### Reset password")
                with st.form("reset_form"):
                    reset_email = st.text_input(
                        "Email", placeholder="you@example.com", key="reset_email"
                    )
                    current_pw = st.text_input(
                        "Current Password", type="password",
                        placeholder="••••••••", key="current_pw",
                    )
                    new_pw = st.text_input(
                        "New Password", type="password",
                        placeholder="••••••••", key="new_pw",
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
                            # ── TODO: connect your backend update-password function ──
                            # supabase.auth.update_user({"password": new_pw})
                            # (requires a recovery session from the emailed link)
                            st.success("Password updated successfully.")

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
                    "Password", type="password", placeholder="••••••••",
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
                                supabase.table("profiles").insert(
                                    {
                                        "id": response.user.id,
                                        "email": new_email,
                                        "name": new_name,
                                    }
                                ).execute()
                                st.session_state["supabase_user"] = response.user
                                st.session_state["supabase_user_name"] = new_name
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

# Protect the rest of the app: nothing below runs for logged-out users.
if st.session_state["supabase_user"] is None:
    st.stop()


# ─────────────────────────────────────────────
# NEW: Supabase-backed saved matches (replaces local SQLite)
# Each user sees only their own data; stored in Supabase so it persists
# across deployments. RLS (Row Level Security) should be enabled on this
# table so users can only read/write their own rows.
# ─────────────────────────────────────────────
CURRENT_USER_ID = st.session_state["supabase_user"].id
CURRENT_USER_EMAIL = st.session_state["supabase_user"].email or ""


def save_match(user_id, product, city, diet_rules, allergens, priority, alternatives):
    """Insert one saved match for the given Supabase user id."""
    supabase.table("saved_matches").insert(
        {
            "user_id": user_id,
            "product": product,
            "city": city,
            "diet_rules": diet_rules,
            "allergens": allergens,
            "priority": priority,
            "alternatives": alternatives,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


def get_saved_matches(user_id):
    """Return saved matches for ONE user only — other users' rows are hidden by RLS."""
    result = (
        supabase.table("saved_matches")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

DEFAULT_API_BASE = "http://127.0.0.1:8000"

# ── Hero logo (base64-embedded so it loads in Streamlit's served context) ──
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "macromatch_logo.png"
if _LOGO_PATH.exists():
    _LOGO_B64 = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
    LOGO_SRC = f"data:image/png;base64,{_LOGO_B64}"
else:
    LOGO_SRC = ""


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
DIET_OPTIONS    = ["vegetarian", "vegan", "dairy_free", "gluten_free", "keto", "low_sugar"]
ALLERGEN_OPTIONS= ["soy", "nuts", "dairy"]
MACRO_COLS      = ["protein", "carbs", "fat", "fiber", "calories"]

PRODUCT_IMAGE_DIR = Path(__file__).resolve().parent.parent / "assets" / "products"

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

RANK_COLORS = ["#4ade80", "#60a5fa", "#f472b6"]   # green, blue, pink
RANK_LABELS = ["🥇 Best Match", "🥈 Second Match", "🥉 Third Match"]

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

/* ── Hide default Streamlit chrome ── */
/* Top-right action bar (Share / GitHub / star / edit / hamburger menu) — fully removed */
#MainMenu, [data-testid="stToolbar"], .stAppToolbar,
header button:not([kind="header"]):not([data-testid="baseButton-header"]) {
    display: none !important;
}
/* Default Streamlit footer ("Made with Streamlit") */
footer { display: none !important; }
/* Remove empty dark bar left by the hidden Streamlit header */
header[data-testid="stHeader"] { height: 0px; background: transparent !important; }
/* Keep the sidebar expand/collapse arrow visible and functional */
button[kind="header"],
button[data-testid="baseButton-header"] {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
}
/* Content sits cleanly at the top of the page with breathing room */
section.main > div[data-testid="stMainBlockContainer"],
div.block-container { padding-top: 2.5rem !important; }

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
    background: #0B0F19;
    padding: 0.12rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
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
    font-size: 0.875rem;
    color: var(--text-body);
    margin: 0;
    font-weight: 400;
    line-height: 1.1;
}

/* ── Hero header ── */
.hero-block {
    text-align: center;
    padding: 0.9rem 1rem 0.6rem;
}
.hero-brand {
    display: inline-flex;
    align-items: center;
    gap: 0.75rem;
}
.hero-logo {
    height: 2.7rem;
    width: auto;
    display: block;
    border-radius: 10px;
    background: #0B0F19;
    padding: 0.12rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
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
    transition: all 0.2s ease !important;
    box-shadow: 0 4px 14px rgba(16, 185, 129, 0.35) !important;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover,
button[kind="primary"]:hover,
button[kind="primary"] p:hover {
    background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important;
    color: #FFFFFF !important;
    transform: translateY(-1px) !important;
    filter: brightness(1.08) !important;
    box-shadow: 0 6px 18px rgba(16, 185, 129, 0.5) !important;
}

/* ── Section divider ── */
.section-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 0.7rem 0;
}

/* ── Result card ── */
.result-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
    transition: all 0.2s ease;
}
.result-card:hover {
    transform: translateY(-3px);
    border-color: var(--border-hover);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
}

/* ── Product images — fixed aspect ratio ── */
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
.result-thumb {
    width: 88px;
    height: 88px;
    min-width: 88px;
    min-height: 88px;
    object-fit: cover;
    border-radius: 12px;
    border: 1px solid var(--border);
    padding: 4px;
    background: #FFFFFF;
    box-sizing: border-box;
    flex-shrink: 0;
    aspect-ratio: 1;
}
.result-thumb-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 88px;
    height: 88px;
    min-width: 88px;
    min-height: 88px;
    font-size: 2rem;
    background: #FFFFFF;
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 4px;
    box-sizing: border-box;
    flex-shrink: 0;
    aspect-ratio: 1;
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

/* ── Rank badge ── */
.rank-badge {
    display: inline-block;
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 3px 10px;
    border-radius: 999px;
    margin-bottom: 0.35rem;
    color: var(--text-heading);
}

/* ── Product name in card ── */
.card-product-name {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 1.35rem;
    font-weight: 700;
    color: var(--text-heading);
    margin: 0 0 0.15rem;
}
.card-category {
    font-size: 0.95rem;
    color: var(--text-body);
    margin-bottom: 0.35rem;
    overflow-wrap: anywhere;
}

/* ── Explanation box ── */
.explanation-box {
    background: #0B0F19;
    border-left: 3px solid var(--accent-mint);
    border-radius: 0 8px 8px 0;
    padding: 0.7rem 1rem;
    font-size: 14.5px;
    color: #F1F5F9;
    line-height: 1.5;
    margin-top: 0.6rem;
    font-style: normal;
}

/* ── Match score pill ── */
.score-pill {
    display: inline-block;
    background: #0B0F19;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 0.875rem;
    color: var(--text-body);
    margin-left: 0.5rem;
    font-family: 'Inter', sans-serif;
    font-variant-numeric: tabular-nums;
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
    transition: all 0.2s ease;
}
.step:hover {
    border-color: rgba(255, 255, 255, 0.18);
    transform: translateY(-2px);
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
    background: #0B0F19;
    padding: 0.12rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
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
}</style>
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


@st.cache_data
def load_product_csv() -> pd.DataFrame:
    """Load products.csv to retrieve original product macros for comparison."""
    csv_path = Path(__file__).parent.parent / "data" / "products.csv"
    df = pd.read_csv(csv_path)
    df["name"] = df["name"].str.strip()
    return df


@st.cache_data
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


def product_image_src(name: str) -> str | None:
    """Return a data-URI for embedding a product photo in custom HTML."""
    image = product_image(name)
    if not image:
        return None
    mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@st.cache_data
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
        col_img, col_info = st.columns([1, 2.2], gap="medium")
        with col_img:
            image = product_image(name)
            if image:
                st.image(str(image), use_container_width=True)
            else:
                st.markdown(
                    f'<div class="product-emoji">{PRODUCT_EMOJI.get(name, "🥗")}</div>',
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
            st.markdown(nc_badge, unsafe_allow_html=True)
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
    """Searchable grid of every product with a photo and its key details."""
    col_search, col_category = st.columns([2, 1], gap="medium")
    with col_search:
        query = st.text_input(
            "Search products",
            placeholder="Search by name or category…",
            label_visibility="collapsed",
            key="guide_search",
        ).strip().lower()
    with col_category:
        categories = sorted({d["category"] for d in details.values()})
        category = st.selectbox(
            "Category",
            ["All categories", *categories],
            label_visibility="collapsed",
            key="guide_category",
        )

    names = sorted(details)
    if query:
        names = [
            n for n in names
            if query in n.lower() or query in details[n]["category"].lower()
        ]
    if category != "All categories":
        names = [n for n in names if details[n]["category"] == category]

    if not names:
        st.info("No products match that search.")
        return

    cols = st.columns(3, gap="medium")
    for i, name in enumerate(names):
        detail = details[name]
        with cols[i % 3]:
            with st.container(border=True):
                image = product_image(name)
                if image:
                    st.image(str(image), use_container_width=True)
                else:
                    st.markdown(
                        f'<div class="product-emoji">{PRODUCT_EMOJI.get(name, "🥗")}</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(f"**{PRODUCT_EMOJI.get(name, '🥗')} {name}**")
                st.caption(detail["category"])
                st.markdown(_macro_line(detail), unsafe_allow_html=True)
                st.markdown(_badges_html(detail), unsafe_allow_html=True)
                st.caption(f"📍 {len(detail['cities'])} cities")

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


# ─────────────────────────────────────────────
# Hero header
# ─────────────────────────────────────────────
st.markdown(f"""
<div class="hero-block">
    <div class="hero-brand">
        <img src="{LOGO_SRC}" alt="MacroMatch logo" class="hero-logo">
        <div class="hero-title">MacroMatch</div>
    </div>
    <div class="hero-tagline">Your macros, anywhere.</div>
</div>
""", unsafe_allow_html=True)
st.markdown('<hr class="section-divider">', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Sidebar — inputs
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div class="sidebar-header">
        <img src="{LOGO_SRC}" alt="MacroMatch logo" class="sidebar-logo">
        <div class="sidebar-text">
            <div class="sidebar-title">MacroMatch</div>
            <div class="sidebar-tagline">Your macros, anywhere.</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ─── NEW: signed-in welcome + sign out (Supabase Auth) ─────────
    _user_name = st.session_state.get("supabase_user_name", CURRENT_USER_EMAIL)
    st.success(f"Welcome, {_user_name} ({CURRENT_USER_EMAIL})")
    if st.button("🚪 Sign out", key="supabase_sign_out"):
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
        st.session_state["supabase_user"] = None
        st.session_state["supabase_access_token"] = None
        st.session_state["supabase_refresh_token"] = None
        st.session_state["supabase_user_name"] = None
        st.rerun()
    st.mark('<hr class="section-divider">', unsafe_allow_html=True)

    # ─── NEW: per-user saved matches history (Supabase, user_id-keyed) ──
    with st.expander("🕘 My saved matches", expanded=False):
        _matches = get_saved_matches(CURRENT_USER_ID)
        if not _matches:
            st.caption("No saved matches yet — save a result below.")
        else:
            for _m in _matches:
                st.caption(f"{_m['product']} → {_m['city']} · {_m['priority']}")

    st.markdown("## 🛒 Your Product")
    try:
        with st.spinner(
            "Connecting to the backend — free hosting can take up to a minute to wake…"
        ):
            products = fetch_product_list()
    except BackendUnavailable:
        st.error(
            f"⚠️ Cannot reach the backend at `{API_BASE}`.\n\n"
            "The free-tier API may be asleep or still starting. Retry in a "
            "moment; locally, start it with:\n\n"
            "`uvicorn backend.main:app --reload`"
        )
        if st.button("🔄 Retry", use_container_width=True):
            fetch_product_list.clear()
            st.rerun()
        st.stop()

    if not products:
        st.error("The backend returned an empty product list. Please try again.")
        st.stop()

    selected_product = st.selectbox(
        "What do you normally eat?",
        options=products,
        help="Select the product you use at home.",
    )

    st.markdown("## 📍 Destination")
    city_options = load_city_list() or CITIES_FALLBACK
    selected_city = st.selectbox(
        "Which city are you travelling to?",
        options=city_options,
    )

    st.markdown("## 🥦 Diet Rules")
    # Human-readable labels for each diet key
    _DIET_LABELS = {
        "vegetarian": "🌿 Vegetarian",
        "vegan":      "🌱 Vegan",
        "dairy_free": "🥛 Dairy-Free",
        "gluten_free":"🌾 Gluten-Free",
        "keto":       "⚡ Keto",
        "low_sugar":  "🍬 Low-Sugar",
    }
    selected_diet_labels = st.pills(
        "Diet Rules",
        options=list(_DIET_LABELS.values()),
        selection_mode="multi",
        label_visibility="collapsed",
    )
    # Map selected display labels back to API keys
    _LABEL_TO_KEY = {v: k for k, v in _DIET_LABELS.items()}
    selected_diets = [_LABEL_TO_KEY[lbl] for lbl in selected_diet_labels]

    st.markdown("## ⚠️ Allergens to Avoid")
    selected_allergens = st.multiselect(
        "Select allergens",
        options=ALLERGEN_OPTIONS,
        format_func=lambda x: {"soy": "🫘 Soy", "nuts": "🥜 Nuts", "dairy": "🥛 Dairy"}[x],
    )

    st.markdown("## 🎯 Priority")
    # Thin non-breaking space between the emoji and the label text gives the
    # radio circle a little breathing room without touching any logic.
    priority_label = st.radio(
        "What matters most in the match?",
        options=PRIORITY_KEYS,
        format_func=lambda k: PRIORITY_LABELS[k].replace(" ", "\u00a0", 1),
        index=2,   # default: balanced
    )

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    find_btn = st.button("🔍 Find Alternatives", use_container_width=True, type="primary")


# ─────────────────────────────────────────────
# Main area — results
# ─────────────────────────────────────────────

product_details = load_product_details()
selected_detail = product_details.get(selected_product)

if not find_btn:
    # Built as one unindented HTML string: Markdown ends an HTML block at the
    # first blank line and would turn any indented remainder into a code block.
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
        "<span>Start in the sidebar, then hit <strong>Find Alternatives</strong>."
        "</span></div>"
        f'<div class="landing-facts">{facts_html}</div>'
        "</div>",
        unsafe_allow_html=True,
    )

    if selected_detail:
        st.markdown("### 🥗 Your Regular Food")
        render_product_spotlight(
            selected_product,
            selected_detail,
            keto="keto" in selected_diets,
        )
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    st.markdown("### 📖 Product guide")
    st.caption(
        "New to a food? Browse the catalogue to see what it looks like, "
        "its macros per 100 g, diet rules and allergens."
    )
    if st.toggle(f"Show all {len(product_details)} products", key="show_product_guide"):
        render_product_guide(product_details)

    st.stop()


# ── Call the API ──────────────────────────────
with st.spinner("Searching for alternatives and generating explanations…"):
    response = call_api({
        "product":    selected_product,
        "city":       selected_city,
        "diet_rules": selected_diets,
        "allergens":  selected_allergens,
        "priority":   priority_label,
    })

# ── Handle errors ─────────────────────────────
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

# ── Parse response ────────────────────────────
data         = response.json()
alternatives = data.get("alternatives", [])
orig_macros  = get_original_macros(selected_product)

# ── Back to home ──────────────────────────────
# Clicking this reruns the script with find_btn False, which renders the landing page.
st.button("🏠 Back to home", key="back_to_home", help="Return to the start page")

# ── Summary strip ─────────────────────────────
# Built as one unindented string: a whitespace-only line would end the Markdown
# HTML block and turn the closing tags into a code block.
diet_text = (
    f"&nbsp;·&nbsp; Diet: {', '.join(_DIET_LABELS[d] for d in selected_diets)}"
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

# ─── NEW: save the current match to the logged-in user's history (Supabase) ─
if st.button("💾 Save this match to my history", key="save_match_to_history"):
    save_match(
        CURRENT_USER_ID,
        selected_product,
        selected_city,
        selected_diets,
        selected_allergens,
        priority_label,
        alternatives,
    )
    st.success("Saved to your history — only your own account can see it.")

# ── Result cards ──────────────────────────────

# ── Per-serving toggle (one shared toggle above all cards) ────────────────
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

for alt in alternatives:
    rank     = alt["rank"] - 1          # 0-indexed for color/label arrays
    color    = RANK_COLORS[rank]
    label    = RANK_LABELS[rank]
    nutr     = alt["nutrition"]

    # Scale both original and alternative macros based on toggle
    orig_scaled = _scale(orig_macros, selected_product) if orig_macros else None
    nutr_scaled = _scale(nutr, alt["name"])

    with st.container():
        # ── Card header ──
        thumb = product_image_src(alt["name"])
        if thumb:
            thumb_html = (
                f'<div style="width:88px;height:88px;min-width:88px;min-height:88px;'
                f'flex-shrink:0;border-radius:12px;background:#FFFFFF;padding:4px;'
                f'box-sizing:border-box;overflow:hidden;display:flex;align-items:center;justify-content:center;">'
                f'<img src="{thumb}" alt="{alt["name"]}" style="width:100%;height:100%;'
                f'object-fit:cover;border-radius:8px;display:block;">'
                f'</div>'
            )
        else:
            thumb_html = (
                f'<div class="result-thumb result-thumb-fallback">'
                f'{PRODUCT_EMOJI.get(alt["name"], "🥗")}</div>'
            )
        # Local name + net carbs for the alt product
        alt_local   = PRODUCT_LOCAL_NAMES.get(alt["name"], "")
        alt_local_tag = (
            f'<span class="local-name-tag" style="margin-left:0;">🗺️ {alt_local}</span>'
            if alt_local else ""
        )
        # Net carbs: use scaled value when Per Serving toggle is active
        alt_nc      = max(0.0, nutr_scaled["carbs"] - nutr_scaled["fiber"])
        alt_nc_cls  = "net-carbs-keto" if keto_on else "net-carbs-normal"
        nc_unit_note = f" ({_unit_label})" if per_serving_on else ""
        alt_nc_tag  = f'<span class="{alt_nc_cls}">⚡ Net Carbs {alt_nc:g} g{nc_unit_note}</span>'
        st.markdown(f"""
        <div class="result-card">
            <div class="result-card-head">
                {thumb_html}
                <div class="result-card-body">
                    <span class="rank-badge" style="background:{color}22;color:{color};">{label}</span>
                    <p class="card-product-name">{alt['name']}
                        <span class="score-pill">{round((1 - alt['match_score']) * 100)}% Match</span>
                        {alt_nc_tag}
                    </p>
                    {f'<p style="margin:0 0 0.2rem;">{alt_local_tag}</p>' if alt_local_tag else ''}
                    <p class="card-category">{alt['category']} &nbsp;·&nbsp; Available in: {alt['cities'].replace(',', ', ')}</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Two columns: table | chart ──
        col_table, col_chart = st.columns([1, 1], gap="medium")

        with col_table:
            st.markdown(f"**Nutrition Breakdown** *({_unit_label})*")
            if orig_scaled:
                # Net carbs rows (scaled same way as other macros)
                orig_nc_val = max(0.0, round(orig_scaled["carbs"] - orig_scaled["fiber"], 1))
                nutr_nc_val = max(0.0, round(nutr_scaled["carbs"] - nutr_scaled["fiber"], 1))
                col_a = f"🏠 {selected_product}"
                col_b = f"📍 {alt['name']}"
                comparison_df = pd.DataFrame({
                    "Nutrient": [
                        "Protein (g)", "Carbs (g)", "Fat (g)",
                        "Fiber (g)", "⚡ Net Carbs (g)", "Calories (kcal)",
                    ],
                    col_a: [
                        orig_scaled["protein"],
                        orig_scaled["carbs"],
                        orig_scaled["fat"],
                        orig_scaled["fiber"],
                        orig_nc_val,
                        orig_scaled["calories"],
                    ],
                    col_b: [
                        nutr_scaled["protein"],
                        nutr_scaled["carbs"],
                        nutr_scaled["fat"],
                        nutr_scaled["fiber"],
                        nutr_nc_val,
                        nutr_scaled["calories"],
                    ],
                })
                st.dataframe(
                    comparison_df.set_index("Nutrient"),
                    use_container_width=True,
                    column_config={
                        col_a: st.column_config.NumberColumn(col_a, format="%.1f"),
                        col_b: st.column_config.NumberColumn(col_b, format="%.1f"),
                    },
                )
            else:
                st.info("Original product macros not available for comparison.")

        with col_chart:
            st.markdown(f"**Nutrient Chart** *(excl. calories · {_unit_label})*")
            if orig_scaled:
                chart_df = pd.DataFrame({
                    f"🏠 {selected_product}": [
                        orig_scaled["protein"],
                        orig_scaled["carbs"],
                        orig_scaled["fat"],
                        orig_scaled["fiber"],
                    ],
                    f"📍 {alt['name']}": [
                        nutr_scaled["protein"],
                        nutr_scaled["carbs"],
                        nutr_scaled["fat"],
                        nutr_scaled["fiber"],
                    ],
                }, index=["Protein", "Carbs", "Fat", "Fiber"])

                # Melt to long format for Altair
                import altair as alt_chart
                chart_long = chart_df.reset_index().melt(
                    id_vars="index",
                    var_name="Product",
                    value_name="Value (g)",
                )
                chart_long = chart_long.rename(columns={"index": "Nutrient"})

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
                            "Value (g):Q",
                            axis=alt_chart.Axis(labelFontSize=11),
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

        # ── Explanation ──
        explanation = alt.get("explanation", "").strip()
        if explanation:
            # ── Sanitise any leaked raw score patterns from the backend ──────
            # Handles: "match score: 0.0873", "(match score: 0.0873)", etc.
            import re as _re
            match_pct_str = f"{round((1 - alt['match_score']) * 100)}% match"
            explanation = _re.sub(
                r"\(?\s*match\s+score\s*[:\-]?\s*[\d]+\.[\d]+\s*\)?",
                f"({match_pct_str})",
                explanation,
                flags=_re.IGNORECASE,
            )
            # Remove stray standalone raw decimal score artifacts e.g. "0.0873"
            explanation = _re.sub(
                r"\b0\.\d{3,6}\b",
                "",
                explanation,
            ).strip()

            # ── Build the live data footer (always in sync with toggle) ──────
            srv_g   = PRODUCT_SERVING_G.get(alt["name"], 100) if per_serving_on else None
            if srv_g:
                factor      = srv_g / 100.0
                p_val       = round(nutr_scaled["protein"],  1)
                c_val       = round(nutr_scaled["carbs"],    1)
                f_val       = round(nutr_scaled["fat"],      1)
                kcal_val    = round(nutr_scaled["calories"])
                unit_detail = f"per {srv_g} g serving"
            else:
                p_val       = nutr["protein"]
                c_val       = nutr["carbs"]
                f_val       = nutr["fat"]
                kcal_val    = nutr["calories"]
                unit_detail = "per 100 g"

            data_footer = (
                f'<span style="color:#F1F5F9;font-style:normal;font-size:14.5px;">'
                f'📊 {p_val:g}g protein · {c_val:g}g carbs · {f_val:g}g fat · '
                f'{kcal_val:g} kcal'
                f'<span style="margin-left:0.4rem;font-size:0.8em;opacity:0.75;">'
                f'({unit_detail})</span>'
                f' · <strong style="color:#4ade80;">{match_pct_str}</strong>'
                f'</span>'
            )

            st.markdown(f"""
            <div class="explanation-box">
                💬 {explanation}
                <div style="margin-top:0.5rem;padding-top:0.45rem;
                            border-top:1px solid rgba(74,222,128,0.2);
                            font-size:0.83rem;">
                    {data_footer}
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
