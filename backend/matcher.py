"""
matcher.py — MacroMatch Core Matching Engine
---------------------------------------------
All macro calculations are done here in pure Python/Pandas/NumPy.
No LLM is involved in any numeric computation.

Main function:
    find_alternatives(product_name, city, diet_rules, allergens, weights)
        → Returns a DataFrame of the top 3 closest nutritional substitutes.
"""

import pandas as pd
import numpy as np
from pathlib import Path

from backend.schemas import normalize_diet_rule

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

# Path to the product database (relative to this file's location)
DATA_PATH = Path(__file__).parent.parent / "data" / "products.csv"

# Nutrients used for distance calculation
NUTRIENT_COLS = ["protein", "carbs", "fat", "fiber", "calories"]

# Columns that flag allergen presence (True = contains it)
ALLERGEN_MAP = {
    "soy":   "contains_soy",
    "nuts":  "contains_nuts",
    "dairy": "contains_dairy",
}

# Columns that flag diet compliance (True = safe for that diet)
DIET_MAP = {
    "vegetarian":  "vegetarian",
    "vegan":       "vegan",
    "dairy_free":  "dairy_free",
    "gluten_free": "gluten_free",
}

# For keto, we apply a carb ceiling instead of a boolean column
KETO_CARB_LIMIT = 10.0   # grams per 100g

# For low_sugar, we apply a carb ceiling (total carbs used as proxy for sugar)
LOW_SUGAR_CARB_LIMIT = 15.0  # grams per 100g


# ─────────────────────────────────────────────
# Step 1: Data Loader
# ─────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    """
    Load products.csv into a Pandas DataFrame.
    Strips whitespace from city lists and validates required columns.
    """
    df = pd.read_csv(DATA_PATH)

    # Normalize boolean columns (CSV stores TRUE/FALSE as strings sometimes)
    bool_cols = [
        "vegan", "gluten_free", "vegetarian", "dairy_free", "low_sugar",
        "contains_soy", "contains_nuts", "contains_dairy",
    ]
    for col in bool_cols:
        df[col] = df[col].astype(str).str.strip().str.upper() == "TRUE"

    # Strip whitespace from product names for safe matching
    df["name"] = df["name"].str.strip()

    # Strip whitespace from city strings
    df["cities"] = df["cities"].str.strip()

    return df


# ─────────────────────────────────────────────
# Step 2: Hard Filters
# ─────────────────────────────────────────────

def apply_city_filter(df: pd.DataFrame, city: str) -> pd.DataFrame:
    """
    Keep only products available in the destination city.
    The 'cities' column is a comma-separated string, e.g. "Delhi,Mumbai,Bangalore"
    """
    city_clean = city.strip()
    # Split each row's city list and check if the target city is in it
    mask = df["cities"].apply(
        lambda cell: city_clean in [c.strip() for c in cell.split(",")]
    )
    return df[mask].copy()


def apply_diet_filter(df: pd.DataFrame, diet_rules: list[str]) -> pd.DataFrame:
    """
    Keep only products that satisfy ALL specified diet rules.

    Supported rules:
        "vegetarian"  → product must have vegetarian == True
        "vegan"       → product must have vegan == True
        "dairy_free"  → product must have dairy_free == True
        "gluten_free" → product must have gluten_free == True
        "keto"        → product must have carbs <= KETO_CARB_LIMIT per 100g
        "low_sugar"   → product must have carbs <= LOW_SUGAR_CARB_LIMIT per 100g

    Example: diet_rules=["vegan", "gluten_free"]
    """
    for rule in diet_rules:
        # Normalize keys, display names ("Dairy-Free"), and emoji pill
        # labels ("🥛 Dairy-Free") to the canonical snake_case key.
        rule_lower = normalize_diet_rule(rule)

        if rule_lower == "keto":
            # Keto = very low carb (not a boolean flag in our data)
            df = df[df["carbs"] <= KETO_CARB_LIMIT].copy()

        elif rule_lower == "low_sugar":
            # Low-sugar = total carbs used as a sugar proxy
            df = df[df["carbs"] <= LOW_SUGAR_CARB_LIMIT].copy()

        elif rule_lower in DIET_MAP:
            col = DIET_MAP[rule_lower]
            df = df[df[col] == True].copy()

        else:
            print(f"[WARNING] Unknown diet rule '{rule}' — skipped.")

    return df


def apply_allergen_filter(df: pd.DataFrame, allergens: list[str]) -> pd.DataFrame:
    """
    Remove products that contain any of the user's allergens.

    Supported allergens: "soy", "nuts", "dairy"

    Example: allergens=["dairy", "nuts"]
    → removes any product where contains_dairy=True OR contains_nuts=True
    """
    for allergen in allergens:
        allergen_lower = allergen.lower().strip()

        if allergen_lower in ALLERGEN_MAP:
            col = ALLERGEN_MAP[allergen_lower]
            # Keep only rows where the allergen is NOT present
            df = df[df[col] == False].copy()

        else:
            print(f"[WARNING] Unknown allergen '{allergen}' — skipped.")

    return df


# ─────────────────────────────────────────────
# Step 3: Similarity Scoring
# ─────────────────────────────────────────────

def compute_similarity_scores(
    original: pd.Series,
    candidates: pd.DataFrame,
    weights: dict[str, float],
) -> pd.DataFrame:
    """
    Compute a weighted Euclidean distance between the original product
    and each candidate, using min-max normalized nutrient values.

    Normalization ensures that calories (0–600 range) doesn't dominate
    over fiber (0–35 range) just because of its larger numeric scale.

    Parameters:
        original   : A single-row Series with NUTRIENT_COLS values.
        candidates : DataFrame of filtered products.
        weights    : Dict mapping nutrient name → importance weight.
                     Weights do not need to sum to 1 (they are normalized internally).

    Returns:
        candidates DataFrame with a new 'match_score' column (lower = closer match).
    """
    # --- Extract only the nutrient columns we need ---
    original_nutrients = original[NUTRIENT_COLS].values.astype(float)  # shape: (5,)
    candidate_nutrients = candidates[NUTRIENT_COLS].values.astype(float)  # shape: (N, 5)

    # --- Min-Max Normalization ---
    # We normalize across the FULL dataset range (original + candidates combined)
    # so that the original product's position is also correctly scaled.
    all_values = np.vstack([original_nutrients, candidate_nutrients])  # shape: (N+1, 5)

    col_min = all_values.min(axis=0)   # shape: (5,) — minimum per nutrient
    col_max = all_values.max(axis=0)   # shape: (5,) — maximum per nutrient
    col_range = col_max - col_min

    # Avoid division by zero if all values in a column are identical
    col_range[col_range == 0] = 1.0

    # Apply normalization: scale each value to [0, 1]
    original_norm = (original_nutrients - col_min) / col_range       # shape: (5,)
    candidates_norm = (candidate_nutrients - col_min) / col_range     # shape: (N, 5)

    # --- Build Weight Vector ---
    # Pull weights in the same order as NUTRIENT_COLS; default to 1.0 if not specified
    weight_vector = np.array(
        [weights.get(col, 1.0) for col in NUTRIENT_COLS], dtype=float
    )
    # Normalize weights so they sum to 1
    weight_vector = weight_vector / weight_vector.sum()

    # --- Weighted Euclidean Distance ---
    # For each candidate: sqrt( sum( weight_i * (candidate_i - original_i)^2 ) )
    diff = candidates_norm - original_norm                            # shape: (N, 5)
    squared_diff = diff ** 2                                          # shape: (N, 5)
    weighted_squared = squared_diff * weight_vector                   # shape: (N, 5)
    distances = np.sqrt(weighted_squared.sum(axis=1))                 # shape: (N,)

    # Attach scores back to the DataFrame
    result = candidates.copy()
    result["match_score"] = np.round(distances, 4)

    return result


# ─────────────────────────────────────────────
# Main Public Function
# ─────────────────────────────────────────────

def find_alternatives(
    product_name: str,
    city: str,
    diet_rules: list[str] = None,
    allergens: list[str] = None,
    weights: dict[str, float] = None,
    top_n: int = 3,
) -> pd.DataFrame:
    """
    Find the closest nutritional substitutes for a product in a destination city.

    Parameters:
        product_name : Name of the user's usual product (must match CSV exactly).
        city         : Destination city (e.g., "Delhi", "Bangalore").
        diet_rules   : List of diet constraints, e.g. ["vegetarian", "vegan",
                       "dairy_free", "gluten_free", "keto", "low_sugar"].
        allergens    : List of allergens to avoid, e.g. ["dairy", "nuts"].
        weights      : Dict of nutrient importance weights.
                       Default gives more importance to protein and calories.
        top_n        : Number of alternatives to return (default: 3).

    Returns:
        A DataFrame with the top N alternatives, sorted by match_score (ascending).
        Lower match_score = nutritionally closer to the original product.

    Raises:
        ValueError: If the product_name is not found in the database.
        ValueError: If no alternatives remain after applying filters.
    """

    # --- Set Defaults ---
    if diet_rules is None:
        diet_rules = []
    if allergens is None:
        allergens = []
    if weights is None:
        # Default weights: prioritize protein and calories
        weights = {
            "protein":  0.35,
            "calories": 0.25,
            "carbs":    0.20,
            "fat":      0.15,
            "fiber":    0.05,
        }

    # ── Step 1: Load data ──
    df = load_data()

    # ── Step 2: Find the original product ──
    original_rows = df[df["name"].str.lower() == product_name.strip().lower()]
    if original_rows.empty:
        available = df["name"].tolist()
        raise ValueError(
            f"Product '{product_name}' not found in database.\n"
            f"Available products:\n  " + "\n  ".join(available)
        )
    original = original_rows.iloc[0]  # Take first match

    # ── Step 3: Apply hard filters ──

    # 3a. Remove the original product itself from candidates
    candidates = df[df["name"].str.lower() != product_name.strip().lower()].copy()

    # 3b. City filter — only products available in destination
    candidates = apply_city_filter(candidates, city)

    # 3c. Diet filter — apply each diet rule
    candidates = apply_diet_filter(candidates, diet_rules)

    # 3d. Allergen filter — exclude products with user's allergens
    candidates = apply_allergen_filter(candidates, allergens)

    # Check if any candidates survived the filters
    if candidates.empty:
        raise ValueError(
            f"No alternatives found in {city} matching the given filters.\n"
            f"Try relaxing your diet rules or allergen list."
        )

    # ── Step 4: Compute similarity scores ──
    scored = compute_similarity_scores(original, candidates, weights)

    # ── Step 5: Sort and return top N ──
    top_matches = (
        scored
        .sort_values("match_score", ascending=True)
        .head(top_n)
        .reset_index(drop=True)
    )

    # Select the most useful columns to display
    display_cols = ["name", "category", "protein", "carbs", "fat",
                    "fiber", "calories", "match_score", "cities"]

    return top_matches[display_cols]


# ─────────────────────────────────────────────
# CLI — Run directly for quick testing
# ─────────────────────────────────────────────

if __name__ == "__main__":

    print("=" * 60)
    print("MacroMatch — Nutritional Substitute Finder")
    print("=" * 60)

    # ── Example 1 ──────────────────────────────────────────────
    # A vegan traveller going to Bangalore, usually uses Whey Protein.
    # They want a vegan, soy-free alternative.
    print("\n📌 Example 1: Vegan + soy-free alternative to Whey Protein in Bangalore")
    result1 = find_alternatives(
        product_name="Whey Protein Powder",
        city="Bangalore",
        diet_rules=["vegan"],
        allergens=["soy"],
        weights={"protein": 0.5, "calories": 0.2, "carbs": 0.15, "fat": 0.1, "fiber": 0.05},
    )
    print(result1.to_string(index=False))

    # ── Example 2 ──────────────────────────────────────────────
    # A keto traveller going to Delhi, usually eats Oats.
    # They want a keto-friendly, gluten-free, nut-free swap.
    print("\n📌 Example 2: Keto + gluten-free + nut-free alternative to Oats in Delhi")
    result2 = find_alternatives(
        product_name="Rolled Oats",
        city="Delhi",
        diet_rules=["keto", "gluten_free"],
        allergens=["nuts"],
        weights={"carbs": 0.4, "protein": 0.3, "fat": 0.2, "fiber": 0.05, "calories": 0.05},
    )
    print(result2.to_string(index=False))

    # ── Example 3 ──────────────────────────────────────────────
    # A dairy-allergic traveller going to Pune, usually eats Paneer.
    # They want a high-protein, dairy-free swap — no specific diet.
    print("\n📌 Example 3: Dairy-free alternative to Paneer in Pune (no diet restriction)")
    result3 = find_alternatives(
        product_name="Paneer",
        city="Pune",
        diet_rules=[],
        allergens=["dairy"],
        weights={"protein": 0.4, "fat": 0.3, "calories": 0.2, "carbs": 0.05, "fiber": 0.05},
    )
    print(result3.to_string(index=False))
