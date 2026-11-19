"""
tests/test_matcher.py — Pytest test suite for MacroMatch matcher.py
--------------------------------------------------------------------
Run from the project root with:
    pytest tests/test_matcher.py -v

Each test covers a specific edge case. Failure explanations are
included as comments directly above the test that might fail.
"""

import pytest
import sys
from pathlib import Path

# ── Make sure Python can find the backend module ──────────────────
# Add the project root to sys.path so "from backend.matcher import ..."
# works regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.matcher import find_alternatives


# ═══════════════════════════════════════════════════════════════════
# TEST 1 — No product available in the chosen city
# ═══════════════════════════════════════════════════════════════════
#
# WHAT WE TEST:
#   "Kolkata" is not in our dataset at all.
#   After the city filter, zero candidates remain.
#   The function must raise a ValueError with a useful message.
#
# HOW TO FIX IF THIS FAILS:
#   Open matcher.py → check apply_city_filter().
#   After filtering, the code must raise ValueError when candidates.empty is True.
#   Confirm this block exists in find_alternatives():
#       if candidates.empty:
#           raise ValueError("No alternatives found in ...")
# ───────────────────────────────────────────────────────────────────
def test_no_products_in_city():
    with pytest.raises(ValueError, match="No alternatives found"):
        find_alternatives(
            product_name="Paneer",
            city="Kolkata",          # city not in our dataset
            diet_rules=[],
            allergens=[],
        )


# ═══════════════════════════════════════════════════════════════════
# TEST 2 — Invalid product name
# ═══════════════════════════════════════════════════════════════════
#
# WHAT WE TEST:
#   The user types a product name that doesn't exist in the CSV.
#   The function must raise a ValueError and NOT silently return an
#   empty DataFrame or crash with a confusing KeyError.
#
# HOW TO FIX IF THIS FAILS:
#   Open matcher.py → check the section after load_data():
#       original_rows = df[df["name"].str.lower() == product_name.strip().lower()]
#       if original_rows.empty:
#           raise ValueError(f"Product '{product_name}' not found...")
#   Make sure this check exists and is NOT commented out.
# ───────────────────────────────────────────────────────────────────
def test_invalid_product_name():
    with pytest.raises(ValueError, match="not found"):
        find_alternatives(
            product_name="Dragon Fruit Protein Bar",   # does not exist in CSV
            city="Delhi",
            diet_rules=[],
            allergens=[],
        )


# ═══════════════════════════════════════════════════════════════════
# TEST 3 — Vegan filter must NEVER return dairy products
# ═══════════════════════════════════════════════════════════════════
#
# WHAT WE TEST:
#   When diet_rules=["vegan"] is set, NO returned product should
#   have contains_dairy=True or vegan=False in the raw CSV.
#   We verify this by reloading the CSV and cross-checking each
#   result name against it.
#
# HOW TO FIX IF THIS FAILS:
#   Open matcher.py → check apply_diet_filter().
#   The "vegan" case must filter: df = df[df["vegan"] == True]
#   Also check load_data() — ensure boolean columns are parsed
#   correctly (TRUE/FALSE strings → Python booleans).
#   Common bug: df["vegan"].astype(str) == "True" (capital T)
#   vs the CSV having "TRUE" — the fix is .str.upper() == "TRUE".
# ───────────────────────────────────────────────────────────────────
def test_vegan_filter_excludes_dairy():
    import pandas as pd
    from pathlib import Path

    result = find_alternatives(
        product_name="Whey Protein Powder",   # dairy product itself
        city="Mumbai",
        diet_rules=["vegan"],
        allergens=[],
        top_n=5,
    )

    # Load raw CSV to cross-check flags on returned products
    csv_path = Path(__file__).parent.parent / "data" / "products.csv"
    df_raw = pd.read_csv(csv_path)

    for product_name in result["name"]:
        row = df_raw[df_raw["name"] == product_name].iloc[0]

        # Check vegan flag
        assert str(row["vegan"]).upper() == "TRUE", (
            f"'{product_name}' is NOT vegan but was returned by vegan filter!"
        )

        # Check dairy flag (belt-and-suspenders)
        assert str(row["contains_dairy"]).upper() == "FALSE", (
            f"'{product_name}' contains dairy but was returned by vegan filter!"
        )


# ═══════════════════════════════════════════════════════════════════
# TEST 4 — Nut allergy must NEVER return nut-containing products
# ═══════════════════════════════════════════════════════════════════
#
# WHAT WE TEST:
#   A user declares a nut allergy (allergens=["nuts"]).
#   Products like Almonds, Cashews, Walnuts, Peanut Butter, Almond Butter,
#   and Almond Milk — all of which have contains_nuts=TRUE — must
#   NEVER appear in the results.
#
# HOW TO FIX IF THIS FAILS:
#   Open matcher.py → check apply_allergen_filter().
#   The filter must do: df = df[df["contains_nuts"] == False]
#   Double-check that the ALLERGEN_MAP dict maps "nuts" → "contains_nuts".
#   Also verify load_data() converts "TRUE"/"FALSE" strings to Python bools.
# ───────────────────────────────────────────────────────────────────
def test_nut_allergy_excludes_all_nut_products():
    import pandas as pd
    from pathlib import Path

    # Peanut Butter is high-protein; this tests that even good macro matches
    # are excluded when they contain nuts.
    result = find_alternatives(
        product_name="Peanut Butter",      # itself contains nuts
        city="Delhi",
        diet_rules=["vegan"],
        allergens=["nuts"],                # must exclude nut products
        top_n=5,
    )

    # Reload CSV to verify contains_nuts on returned products
    csv_path = Path(__file__).parent.parent / "data" / "products.csv"
    df_raw = pd.read_csv(csv_path)

    # These are known nut-containing products in our DB — none should appear
    known_nut_products = {
        "Almonds", "Cashews", "Walnuts",
        "Peanut Butter", "Almond Butter", "Almond Milk"
    }

    for product_name in result["name"]:
        assert product_name not in known_nut_products, (
            f"'{product_name}' contains nuts but was returned despite nut allergy!"
        )

        # Also cross-check the flag in the CSV directly
        row = df_raw[df_raw["name"] == product_name].iloc[0]
        assert str(row["contains_nuts"]).upper() == "FALSE", (
            f"'{product_name}' has contains_nuts=TRUE but appeared in results!"
        )


# ═══════════════════════════════════════════════════════════════════
# TEST 5 — Different weights produce different rankings
# ═══════════════════════════════════════════════════════════════════
#
# WHAT WE TEST:
#   The weighted distance formula must be sensitive to weight changes.
#   Run the SAME query twice with very different weight distributions:
#     - Run A: heavy weight on PROTEIN (find the highest-protein match)
#     - Run B: heavy weight on FAT     (find the closest fat match)
#   The top-ranked product must differ between the two runs.
#
# HOW TO FIX IF THIS FAILS:
#   This test can fail for two reasons:
#
#   (a) Weights are ignored in the code:
#       Open matcher.py → compute_similarity_scores().
#       Confirm the weight_vector is actually multiplied into squared_diff:
#           weighted_squared = squared_diff * weight_vector
#       If this line is missing or uses ones instead of weight_vector, fix it.
#
#   (b) The dataset is too homogeneous for this product/city:
#       Try a different product_name with more diverse candidates,
#       e.g., "Masoor Dal (Red Lentils)" in Mumbai with top_n=5.
# ───────────────────────────────────────────────────────────────────
def test_weights_affect_ranking():
    # Run A: maximise protein similarity (find highest-protein alternative)
    result_protein_heavy = find_alternatives(
        product_name="Paneer",
        city="Bangalore",
        diet_rules=[],
        allergens=["dairy"],
        weights={
            "protein":  0.90,   # almost everything is protein
            "carbs":    0.03,
            "fat":      0.03,
            "fiber":    0.02,
            "calories": 0.02,
        },
        top_n=3,
    )

    # Run B: maximise fat similarity (find closest fat match)
    result_fat_heavy = find_alternatives(
        product_name="Paneer",
        city="Bangalore",
        diet_rules=[],
        allergens=["dairy"],
        weights={
            "protein":  0.03,
            "carbs":    0.03,
            "fat":      0.90,   # almost everything is fat
            "fiber":    0.02,
            "calories": 0.02,
        },
        top_n=3,
    )

    top_protein = result_protein_heavy.iloc[0]["name"]
    top_fat     = result_fat_heavy.iloc[0]["name"]

    # The top-ranked product must differ between the two runs.
    # If weights have no effect, the same product would win both — which is wrong.
    assert top_protein != top_fat, (
        f"Weights had NO effect on ranking! "
        f"Both protein-heavy and fat-heavy weights returned '{top_protein}' as #1. "
        f"Check compute_similarity_scores() in matcher.py."
    )

    # Optional: print both top picks so you can inspect them manually
    print(f"\n  Protein-heavy top pick : {top_protein}")
    print(f"  Fat-heavy top pick     : {top_fat}")
