"""
frontend/app.py — MacroMatch Streamlit UI
------------------------------------------
Run from the project root with:
    venv\\Scripts\\python.exe -m streamlit run frontend/app.py

Requires the FastAPI backend to be running at http://127.0.0.1:8000
    venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload
"""

import os

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
GET_TIMEOUT      = 20   # seconds; free-tier hosts can need ~1 min to wake from sleep
POST_TIMEOUT     = 90   # seconds; includes the optional Claude call
CITIES_FALLBACK   = ["Delhi", "Mumbai", "Bangalore", "Dehradun", "Pune"]
DIET_OPTIONS    = ["vegan", "gluten_free", "keto"]
ALLERGEN_OPTIONS= ["soy", "nuts", "dairy"]
MACRO_COLS      = ["protein", "carbs", "fat", "fiber", "calories"]

PRIORITY_LABELS = {
    "protein":  "🥩 Protein-first — match protein content most closely",
    "low_carb": "🌿 Low Carb — match carbohydrate content most closely",
    "balanced": "⚖️ Balanced — equal weight across all macros",
}
PRIORITY_KEYS = list(PRIORITY_LABELS.keys())

RANK_COLORS = ["#4ade80", "#60a5fa", "#f472b6"]   # green, blue, pink
RANK_LABELS = ["🥇 Best Match", "🥈 Second Match", "🥉 Third Match"]

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
    color: #94a3b8;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 0.25rem;
}

/* ── Hero header ── */
.hero-block {
    text-align: center;
    padding: 1.2rem 1rem 0.8rem;
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
    color: #64748b;
    margin-bottom: 0.4rem;
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
    color: #94a3b8;
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
    color: #94a3b8 !important;
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
    color: #94a3b8;
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
    color: #94a3b8;
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
    """Fetch all product names from GET /products. Returns [] if unreachable."""
    try:
        resp = requests.get(f"{API_BASE}/products", timeout=GET_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("products", [])
    except requests.exceptions.RequestException:
        # Connection error, timeout, or non-2xx status — the sidebar shows a
        # single "cannot reach backend" message, so no detail is needed here.
        return []


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
st.markdown("""
<div class="hero-block">
    <div class="hero-title">MacroMatch</div>
    <div class="hero-tagline">Your macros, anywhere.</div>
</div>
""", unsafe_allow_html=True)
st.markdown('<hr class="section-divider">', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Sidebar — inputs
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛒 Your Product")
    products = fetch_product_list()

    if not products:
        st.error(
            f"⚠️ Cannot reach the backend at `{API_BASE}`.\n\n"
            "If it is a free-tier deployment, it may still be waking up — "
            "wait about a minute and reload. Locally, start it with:\n\n"
            "`uvicorn backend.main:app --reload`"
        )
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

# ── Summary strip ─────────────────────────────
st.markdown(f"""
<div style="
    background:#1e293b;
    border:1px solid #334155;
    border-radius:12px;
    padding:0.75rem 1.25rem;
    margin-bottom:1.25rem;
    display:flex;
    align-items:center;
    gap:1rem;
">
    <span style="font-size:1.5rem">✅</span>
    <div>
        <span style="color:#f1f5f9;font-weight:600;">
            Found {len(alternatives)} alternative{'s' if len(alternatives) != 1 else ''}
            for <em>{selected_product}</em> in {selected_city}
        </span><br>
        <span style="color:#64748b;font-size:0.85rem;">
            Priority: {PRIORITY_LABELS[priority_label].split('—')[0].strip()}
            {"&nbsp;·&nbsp; Diet: " + ", ".join(selected_diets) if selected_diets else ""}
            {"&nbsp;·&nbsp; Avoiding: " + ", ".join(selected_allergens) if selected_allergens else ""}
        </span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Result cards ──────────────────────────────
for alt in alternatives:
    rank     = alt["rank"] - 1          # 0-indexed for color/label arrays
    color    = RANK_COLORS[rank]
    label    = RANK_LABELS[rank]
    nutr     = alt["nutrition"]

    with st.container():
        # ── Card header ──
        st.markdown(f"""
        <div class="result-card">
            <span class="rank-badge" style="background:{color}22;color:{color};">{label}</span>
            <p class="card-product-name">{alt['name']}
                <span class="score-pill">score {alt['match_score']}</span>
            </p>
            <p class="card-category">{alt['category']} &nbsp;·&nbsp; Available in: {alt['cities']}</p>
        </div>
        """, unsafe_allow_html=True)

        # ── Two columns: table | chart ──
        col_table, col_chart = st.columns([1, 1], gap="medium")

        with col_table:
            st.markdown(f"**Macro Comparison** *(per 100g)*")
            if orig_macros:
                comparison_df = pd.DataFrame({
                    "Nutrient":     ["Protein (g)", "Carbs (g)", "Fat (g)", "Fiber (g)", "Calories (kcal)"],
                    f"🏠 {selected_product}": [
                        orig_macros["protein"],
                        orig_macros["carbs"],
                        orig_macros["fat"],
                        orig_macros["fiber"],
                        orig_macros["calories"],
                    ],
                    f"📍 {alt['name']}": [
                        nutr["protein"],
                        nutr["carbs"],
                        nutr["fat"],
                        nutr["fiber"],
                        nutr["calories"],
                    ],
                })
                st.dataframe(
                    comparison_df.set_index("Nutrient"),
                    use_container_width=True,
                )
            else:
                st.info("Original product macros not available for comparison.")

        with col_chart:
            st.markdown("**Visual Comparison** *(excl. calories)*")
            if orig_macros:
                chart_df = pd.DataFrame({
                    f"🏠 {selected_product}": [
                        orig_macros["protein"],
                        orig_macros["carbs"],
                        orig_macros["fat"],
                        orig_macros["fiber"],
                    ],
                    f"📍 {alt['name']}": [
                        nutr["protein"],
                        nutr["carbs"],
                        nutr["fat"],
                        nutr["fiber"],
                    ],
                }, index=["Protein", "Carbs", "Fat", "Fiber"])

                st.bar_chart(chart_df, use_container_width=True, height=220)

        # ── Explanation ──
        explanation = alt.get("explanation", "").strip()
        if explanation:
            st.markdown(f"""
            <div class="explanation-box">
                💬 {explanation}
            </div>
            """, unsafe_allow_html=True)

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
