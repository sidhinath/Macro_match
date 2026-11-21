"""
explainer.py — MacroMatch Human-Readable Explanation Generator
---------------------------------------------------------------
This is the ONLY file in MacroMatch that calls an LLM (Claude via Anthropic API).

Role of Claude here:
  - Write 2-line plain-English explanations of WHY each alternative was suggested.
  - Claude ONLY receives numbers from the matcher — it never calculates anything.
  - All macro math is done upstream in matcher.py (Python/NumPy).

The API key is loaded from a .env file. Never hardcode it.
"""

import os
import anthropic
from dotenv import load_dotenv
from dataclasses import dataclass

# Load environment variables from the .env file at project root
# This must be called before accessing os.environ for ANTHROPIC_API_KEY.
load_dotenv()

# ─────────────────────────────────────────────
# Data structures passed into this module
# ─────────────────────────────────────────────

@dataclass
class ProductInfo:
    """
    Holds the macro data for a single product.
    Passed in from matcher.py results — never computed here.
    """
    name:         str
    protein:      float
    carbs:        float
    fat:          float
    fiber:        float
    calories:     float
    match_score:  float   # Lower = closer nutritional match
    cities:       str     # Comma-separated list of available cities


@dataclass
class ExplainerInput:
    """
    Everything Claude needs to write explanations.
    Constructed in main.py from the matcher output.
    """
    original_product: str         # e.g. "Paneer"
    city:             str         # e.g. "Bangalore"
    diet_rules:       list[str]   # e.g. ["vegan", "gluten_free"]
    allergens:        list[str]   # e.g. ["dairy"]
    priority:         str         # e.g. "protein"
    alternatives:     list[ProductInfo]   # Top 3 from matcher


# ─────────────────────────────────────────────
# Prompt Builder
# ─────────────────────────────────────────────

def _build_prompt(data: ExplainerInput) -> str:
    """
    Build a tightly controlled prompt for Claude.

    Key design principles:
    1. All numbers are injected directly — Claude cannot invent values.
    2. Claude is explicitly told NOT to do any arithmetic or add new numbers.
    3. Output format is strict — 2 lines per product, no headers or markdown.
    """

    # Format the original product section
    original_section = f'Original product: "{data.original_product}"'

    # Format user context
    diet_str     = ", ".join(data.diet_rules) if data.diet_rules else "none"
    allergen_str = ", ".join(data.allergens)  if data.allergens  else "none"
    context_section = (
        f"User's destination city : {data.city}\n"
        f"Diet rules applied      : {diet_str}\n"
        f"Allergens to avoid      : {allergen_str}\n"
        f"Priority (what mattered most in matching): {data.priority}"
    )

    # Format each alternative with its exact macro numbers
    alternatives_section = ""
    for i, alt in enumerate(data.alternatives, start=1):
        match_pct = round((1 - alt.match_score) * 100)
        alternatives_section += (
            f"\nAlternative {i}: {alt.name}  ({match_pct}% match)\n"
            f"  - Protein  : {alt.protein}g per 100g\n"
            f"  - Carbs    : {alt.carbs}g per 100g\n"
            f"  - Fat      : {alt.fat}g per 100g\n"
            f"  - Fiber    : {alt.fiber}g per 100g\n"
            f"  - Calories : {alt.calories} kcal per 100g\n"
            f"  - Available in: {alt.cities}\n"
        )

    prompt = f"""You are a nutrition assistant writing brief, friendly explanations for a travel nutrition app called MacroMatch.

A user travels to {data.city} and needs a substitute for "{data.original_product}".
The app has already found the top 3 alternatives using a nutritional matching algorithm.
Your job is to explain each match in 2 plain-English sentences.

=== DATA PROVIDED (use ONLY these numbers — do not invent or calculate any new values) ===

{original_section}

{context_section}

{alternatives_section}

=== YOUR INSTRUCTIONS ===

Write exactly 2 sentences for each alternative. Each explanation must:
1. Mention why it is a good match (refer to the specific macro that matched best based on the priority: "{data.priority}").
2. Mention that it is available in {data.city} and is compatible with the user's diet ({diet_str}) and allergen needs ({allergen_str}).

Rules you MUST follow:
- Use ONLY the numbers given above. Do NOT perform any calculations. Do NOT add, subtract, compare, or derive any new numbers.
- Do NOT include the match percentage or any score number in your sentences — the app displays it separately in the UI.
- Do NOT use markdown, bullet points, headers, or bold text.
- Do NOT number the alternatives in your response.
- Write in a friendly, simple, non-technical tone — as if speaking to someone tracking macros for the first time.
- Each explanation must be exactly 2 sentences (no more, no less).
- Separate each explanation with a single blank line.

Write the 3 explanations now:"""

    return prompt


# ─────────────────────────────────────────────
# Fallback Explanation (used when API fails)
# ─────────────────────────────────────────────

def _build_fallback_explanations(data: ExplainerInput) -> list[str]:
    """
    If the Claude API call fails (network error, missing key, rate limit, etc.),
    this generates safe, data-driven fallback text using only Python string formatting.
    No LLM is involved — this is deterministic.

    Design note: macro numbers and match score are intentionally NOT embedded in
    this string — the frontend renders them live (with per-serving scaling) in its
    own data footer. Only narrative context (city, diet, allergens) goes here.
    """
    fallbacks = []
    diet_str     = ", ".join(data.diet_rules) if data.diet_rules else "no specific diet"
    allergen_str = ", ".join(data.allergens)  if data.allergens  else "no allergens"

    for alt in data.alternatives:
        match_pct = round((1 - alt.match_score) * 100)
        text = (
            f"{alt.name} is a {match_pct}% nutritional match for {data.original_product}. "
            f"It is available in {data.city} and is compatible with your diet "
            f"({diet_str}) and allergen requirements ({allergen_str})."
        )
        fallbacks.append(text)

    return fallbacks


# ─────────────────────────────────────────────
# Main Public Function
# ─────────────────────────────────────────────

def generate_explanations(data: ExplainerInput) -> list[str]:
    """
    Call the Anthropic Claude API to generate 2-line plain-English explanations
    for each of the top 3 nutritional alternatives.

    Parameters:
        data : ExplainerInput — contains original product, user context,
               and the top 3 alternatives with their macro data.

    Returns:
        A list of 3 strings — one explanation per alternative.
        If the API fails for any reason, returns deterministic fallback text instead.

    Design rule:
        Claude only receives pre-computed numbers from the matcher.
        It is explicitly instructed not to perform arithmetic.
        All macro math lives in matcher.py, never here.
    """

    # ── 1. Load and validate the API key ─────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print(
            "[explainer] WARNING: ANTHROPIC_API_KEY not found in environment. "
            "Add it to your .env file. Using fallback explanations."
        )
        return _build_fallback_explanations(data)

    # ── 2. Build the prompt ───────────────────────────────────────
    prompt = _build_prompt(data)

    # ── 3. Call Claude API ────────────────────────────────────────
    try:
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model="claude-sonnet-4-5",        # Capable but cost-efficient
            max_tokens=512,                   # 2 sentences × 3 alternatives is well under this
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        # Extract the text from Claude's response
        raw_text: str = message.content[0].text.strip()

        # ── 4. Parse the 3 explanations ───────────────────────────
        # Claude is instructed to separate explanations with a blank line.
        # Split on double newline and take up to 3 blocks.
        blocks = [block.strip() for block in raw_text.split("\n\n") if block.strip()]

        if len(blocks) >= 3:
            explanations = blocks[:3]
        elif len(blocks) > 0:
            # Claude returned fewer than 3 blocks — pad with fallback for missing ones
            print(
                f"[explainer] WARNING: Claude returned {len(blocks)} explanation(s), "
                f"expected 3. Padding with fallback text."
            )
            fallbacks = _build_fallback_explanations(data)
            explanations = blocks + fallbacks[len(blocks):]
        else:
            raise ValueError("Claude returned an empty response.")

        return explanations

    # ── 5. Graceful fallback on any failure ───────────────────────
    except anthropic.AuthenticationError:
        print("[explainer] ERROR: Invalid Anthropic API key. Check your .env file.")
        return _build_fallback_explanations(data)

    except anthropic.RateLimitError:
        print("[explainer] ERROR: Anthropic rate limit hit. Using fallback explanations.")
        return _build_fallback_explanations(data)

    except anthropic.APIConnectionError:
        print("[explainer] ERROR: Could not reach Anthropic API (network issue). Using fallback.")
        return _build_fallback_explanations(data)

    except Exception as e:
        print(f"[explainer] ERROR: Unexpected failure — {type(e).__name__}: {e}. Using fallback.")
        return _build_fallback_explanations(data)


# ─────────────────────────────────────────────
# Quick test — run directly to verify the API
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Sample data simulating what matcher.py would return
    sample_input = ExplainerInput(
        original_product="Paneer",
        city="Bangalore",
        diet_rules=["vegan"],
        allergens=["dairy"],
        priority="protein",
        alternatives=[
            ProductInfo("Tofu (Firm)",    protein=8.0,  carbs=2.0,  fat=4.0,  fiber=0.3, calories=76,  match_score=0.1821, cities="Delhi,Mumbai,Bangalore,Pune"),
            ProductInfo("Soya Chunks (TVP)", protein=52.0, carbs=33.0, fat=0.5, fiber=13.0, calories=345, match_score=0.2340, cities="Delhi,Mumbai,Bangalore,Pune,Dehradun"),
            ProductInfo("Tempeh",         protein=19.0, carbs=9.0,  fat=11.0, fiber=5.0, calories=193, match_score=0.2601, cities="Mumbai,Bangalore"),
        ],
    )

    print("Calling Claude API...\n")
    explanations = generate_explanations(sample_input)

    print("=" * 60)
    for i, explanation in enumerate(explanations, start=1):
        print(f"Alternative {i}:")
        print(explanation)
        print()
