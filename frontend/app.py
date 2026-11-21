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

import streamlit as st
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

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
DIET_OPTIONS    = ["vegan", "gluten_free", "keto"]
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
# Custom CSS — clean, modern, card-based design
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── App background ── */
.stApp {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #e2e8f0;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #1e293b;
    border-right: 1px solid #334155;
}
[data-testid="stSidebar"] .stMarkdown h2 {
    color: #f1f5f9;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    margin-bottom: 0.25rem;
    font-weight: 700;
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    background: rgba(96, 165, 250, 0.15);
    border: 1px solid rgba(96, 165, 250, 0.35);
}

/* ── Hero header ── */
.hero-block {
    text-align: center;
    padding: 1.2rem 1rem 0.8rem;
}
/* Logo + heading grouped together */
.hero-brand {
    display: inline-flex;
    align-items: center;
    gap: 0.75rem;
}
.hero-logo {
    height: 2.9rem;
    width: auto;
    display: block;
}
/* Streamlit's own paragraph rules outrank a bare class, hence !important. */
.hero-title {
    display: inline-block;          /* keep the gradient inside the word */
    font-size: 2.6rem !important;
    font-weight: 700;
    background: linear-gradient(90deg, #4ade80, #60a5fa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.15;
    margin: 0 !important;
}
.hero-tagline {
    font-size: 1.05rem !important;
    color: #94a3b8 !important;
    margin: 0.45rem 0 0 !important;
    font-weight: 300;
    letter-spacing: 0.03em;
}

/* ── Primary action ── */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background: #2E74B5;
    border: 1px solid #3b82f6;
    color: #f8fafc;
    font-weight: 600;
    border-radius: 10px;
    transition: background 0.2s, transform 0.15s;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: #3b82f6;
    border-color: #60a5fa;
    color: #f8fafc;
    transform: translateY(-1px);
}

/* ── Section divider ── */
.section-divider {
    border: none;
    border-top: 1px solid #334155;
    margin: 0.8rem 0;
}

/* ── Result card ── */
.result-card {
    background: #1e293b;
    border-radius: 16px;
    border: 1px solid #334155;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.result-card:hover {
    border-color: #4ade80;
}

/* ── Product guide / spotlight ── */
.product-emoji {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 170px;
    font-size: 5rem;
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 12px;
}
.tag {
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 999px;
    margin: 0.15rem 0.25rem 0.15rem 0;
}
.result-card-head {
    display: flex;
    align-items: center;
    gap: 0.9rem;
}
.result-card-body {
    flex: 1;
    min-width: 0;
}
.result-thumb {
    width: 78px;
    height: 78px;
    object-fit: cover;
    border-radius: 12px;
    border: 1px solid #334155;
    flex-shrink: 0;
}
.result-thumb-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 2rem;
    background: #0f172a;
}

/* ── Rank badge ── */
.rank-badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 3px 10px;
    border-radius: 999px;
    margin-bottom: 0.35rem;
}

/* ── Product name in card ── */
.card-product-name {
    font-size: 1.4rem;
    font-weight: 600;
    color: #f1f5f9;
    margin: 0 0 0.15rem;
}
.card-category {
    font-size: 0.85rem;
    color: #b0b8c4;
    margin-bottom: 0.4rem;
    overflow-wrap: anywhere;
}

/* ── Explanation box ── */
.explanation-box {
    background: #0f172a;
    border-left: 3px solid #4ade80;
    border-radius: 0 8px 8px 0;
    padding: 0.7rem 1rem;
    font-size: 0.9rem;
    color: #cbd5e1;
    line-height: 1.6;
    margin-top: 0.6rem;
    font-style: italic;
}

/* ── Match score pill ── */
.score-pill {
    display: inline-block;
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 0.8rem;
    color: #cbd5e1;
    margin-left: 0.5rem;
    font-family: monospace;
}

/* ── Landing (empty state) ── */
.landing {
    position: relative;
    max-width: 1060px;
    margin: 1rem auto 0;
    padding: 1.6rem 1.8rem 1.3rem;
    background: rgba(30, 41, 59, 0.55);
    border: 1px solid #263449;
    border-radius: 20px;
    box-shadow: 0 24px 60px rgba(2, 6, 23, 0.35);
    overflow: hidden;
}
.landing::before {
    content: "";
    position: absolute;
    inset: 0 0 auto 0;
    height: 3px;
    background: linear-gradient(90deg, #4ade80, #60a5fa);
    opacity: 0.9;
}
.landing-eyebrow {
    text-align: center;
    color: #60a5fa;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
}
.landing-title {
    text-align: center;
    color: #f1f5f9;
    font-size: 1.85rem;
    font-weight: 600;
    line-height: 1.25;
    margin: 0.55rem 0 0.5rem;
}
.landing-sub {
    max-width: 660px;
    margin: 0 auto 1.2rem !important;
    text-align: center;
    color: #cbd5e1 !important;
    font-size: 0.95rem !important;
    line-height: 1.65;
}
.steps {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.6rem;
}
.step {
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid #334155;
    border-radius: 14px;
    padding: 0.9rem 0.95rem 1rem;
    transition: border-color 0.2s, transform 0.2s;
}
.step:hover {
    border-color: #475569;
    transform: translateY(-2px);
}
.step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: 9px;
    margin-bottom: 0.4rem;
    font-size: 0.85rem;
    font-weight: 700;
    color: #052e16;
    background: linear-gradient(135deg, #4ade80, #60a5fa);
}
.step h3 {
    margin: 0 0 0.2rem;
    font-size: 0.97rem;
    font-weight: 600;
    color: #e2e8f0;
}
.step p {
    margin: 0;
    font-size: 0.84rem;
    line-height: 1.55;
    color: #cbd5e1;
}
.landing-cta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 0.45rem;
    margin-top: 0.9rem;
    padding-top: 0.8rem;
    border-top: 1px dashed #334155;
    color: #cbd5e1;
    font-size: 0.9rem;
}
.landing-cta .arrow { color: #60a5fa; font-weight: 700; }
.landing-facts {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.45rem;
    margin-top: 0.6rem;
}
.landing-facts span {
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #94a3b8;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid #334155;
    border-radius: 999px;
    padding: 0.22rem 0.65rem;
}
@media (max-width: 820px) {
    .landing { padding: 1.2rem 1rem 1rem; }
    .landing-title { font-size: 1.4rem; }
    .steps { grid-template-columns: 1fr; }
}

/* ── Sidebar header ── */
.sidebar-header {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.75rem 0.6rem 1rem 0.6rem;
    border-bottom: 1px solid #334155;
    margin-bottom: 1rem;
    max-width: 100%;
}
.sidebar-header .sidebar-logo {
    height: 2.2rem;
    width: auto;
    flex-shrink: 0;
}
.sidebar-header .sidebar-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.sidebar-header .sidebar-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #f1f5f9;
    margin: 0 0 0.1rem;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.sidebar-header .sidebar-tagline {
    font-size: 0.75rem;
    color: #cbd5e1;
    margin: 0;
    font-weight: 400;
    line-height: 1.1;
}

/* ── Error state ── */
.error-box {
    background: #1e1015;
    border: 1px solid #7f1d1d;
    border-radius: 10px;
    padding: 1rem 1.25rem;
    color: #fca5a5;
    font-size: 0.9rem;
}

/* ── Comparison table ── */
.macro-table th {
    color: #cbd5e1;
    font-weight: 500;
    font-size: 0.8rem;
    text-transform: uppercase;
}
</style>
""", unsafe_allow_html=True)


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
    return {col: float(r[col]) for col in MACRO_COLS}


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
    """Every product row as a dict, with the city list parsed out."""
    df = load_product_csv()
    details: dict[str, dict] = {}
    for _, row in df.iterrows():
        details[str(row["name"])] = {
            "category": str(row["category"]),
            "protein": float(row["protein"]),
            "carbs": float(row["carbs"]),
            "fat": float(row["fat"]),
            "fiber": float(row["fiber"]),
            "calories": float(row["calories"]),
            "vegan": _as_bool(row["vegan"]),
            "gluten_free": _as_bool(row["gluten_free"]),
            "contains_soy": _as_bool(row["contains_soy"]),
            "contains_nuts": _as_bool(row["contains_nuts"]),
            "contains_dairy": _as_bool(row["contains_dairy"]),
            "cities": [c.strip() for c in str(row["cities"]).split(",") if c.strip()],
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
        f"**Protein** {prot:g} g &nbsp;·&nbsp; "
        f"**Carbs** {carbs:g} g &nbsp;·&nbsp; "
        f"**Fat** {fat:g} g<br>"
        f"**Fibre** {fiber:g} g &nbsp;·&nbsp; "
        f"**{kcal:g} kcal** "
        f"<span style='color:#b0b8c4;'>({label})</span>"
    )


def _badges_html(detail: dict) -> str:
    badges = []
    if detail["vegan"]:
        badges.append(("🌱 Vegan", "good"))
    if detail["gluten_free"]:
        badges.append(("🌾 Gluten-free", "good"))
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


def render_product_spotlight(name: str, detail: dict) -> None:
    """Photo + full nutrition, diet/allergen details, and how-to-use for one product."""
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
            st.markdown(f"### {PRODUCT_EMOJI.get(name, '🥗')} {name}")
            st.caption(detail["category"])
            st.markdown(_macro_line(detail), unsafe_allow_html=True)
            st.markdown(_badges_html(detail), unsafe_allow_html=True)
            with st.expander(f"📍 Available in {len(detail['cities'])} cities"):
                st.write(", ".join(detail["cities"]))

    # ── How to Use / Eat section ──────────────────────────────────────
    how_to = PRODUCT_HOW_TO_USE.get(name)
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
    selected_diets = []
    if st.checkbox("Vegan",        key="vegan"):        selected_diets.append("vegan")
    if st.checkbox("Gluten-Free",  key="gluten_free"):  selected_diets.append("gluten_free")
    if st.checkbox("Keto",         key="keto"):         selected_diets.append("keto")

    st.markdown("## ⚠️ Allergens to Avoid")
    selected_allergens = st.multiselect(
        "Select allergens",
        options=ALLERGEN_OPTIONS,
        format_func=lambda x: {"soy": "🫘 Soy", "nuts": "🥜 Nuts", "dairy": "🥛 Dairy"}[x],
    )

    st.markdown("## 🎯 Priority")
    priority_label = st.radio(
        "What matters most in the match?",
        options=PRIORITY_KEYS,
        format_func=lambda k: PRIORITY_LABELS[k],
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
        st.markdown("### 🔎 About your product")
        render_product_spotlight(selected_product, selected_detail)
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
    f"&nbsp;·&nbsp; Diet: {', '.join(selected_diets)}" if selected_diets else ""
)
allergen_text = (
    f"&nbsp;·&nbsp; Avoiding: {', '.join(selected_allergens)}"
    if selected_allergens
    else ""
)
summary_html = (
    '<div style="background:#1e293b;border:1px solid #334155;border-radius:12px;'
    'padding:0.75rem 1.25rem;margin-bottom:1.25rem;display:flex;'
    'align-items:center;gap:1rem;">'
    '<span style="font-size:1.5rem">✅</span>'
    '<div>'
    '<span style="color:#f1f5f9;font-weight:600;">'
    f"Found {len(alternatives)} alternative{'s' if len(alternatives) != 1 else ''} "
    f"for <em>{selected_product}</em> in {selected_city}"
    '</span><br>'
    '<span style="color:#64748b;font-size:0.85rem;">'
    f"Priority: {PRIORITY_LABELS[priority_label].split('—')[0].strip()}"
    f"{diet_text}{allergen_text}"
    '</span>'
    '</div></div>'
)
st.markdown(summary_html, unsafe_allow_html=True)

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
                f'<img class="result-thumb" src="{thumb}" alt="{alt["name"]}">'
            )
        else:
            thumb_html = (
                f'<div class="result-thumb result-thumb-fallback">'
                f'{PRODUCT_EMOJI.get(alt["name"], "🥗")}</div>'
            )
        st.markdown(f"""
        <div class="result-card">
            <div class="result-card-head">
                {thumb_html}
                <div class="result-card-body">
                    <span class="rank-badge" style="background:{color}22;color:{color};">{label}</span>
                    <p class="card-product-name">{alt['name']}
                        <span class="score-pill">{round((1 - alt['match_score']) * 100)}% Match</span>
                    </p>
                    <p class="card-category">{alt['category']} &nbsp;·&nbsp; Available in: {alt['cities'].replace(',', ', ')}</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Two columns: table | chart ──
        col_table, col_chart = st.columns([1, 1], gap="medium")

        with col_table:
            st.markdown(f"**Macro Comparison** *({_unit_label})*")
            if orig_scaled:
                comparison_df = pd.DataFrame({
                    "Nutrient":     ["Protein (g)", "Carbs (g)", "Fat (g)", "Fiber (g)", "Calories (kcal)"],
                    f"🏠 {selected_product}": [
                        orig_scaled["protein"],
                        orig_scaled["carbs"],
                        orig_scaled["fat"],
                        orig_scaled["fiber"],
                        orig_scaled["calories"],
                    ],
                    f"📍 {alt['name']}": [
                        nutr_scaled["protein"],
                        nutr_scaled["carbs"],
                        nutr_scaled["fat"],
                        nutr_scaled["fiber"],
                        nutr_scaled["calories"],
                    ],
                })
                st.dataframe(
                    comparison_df.set_index("Nutrient"),
                    use_container_width=True,
                )
            else:
                st.info("Original product macros not available for comparison.")

        with col_chart:
            st.markdown(f"**Visual Comparison** *(excl. calories · {_unit_label})*")
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
            st.markdown(f"""
            <div class="explanation-box">
                💬 {explanation}
            </div>
            """, unsafe_allow_html=True)

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
