"""
tests/test_diet_rules.py — Diet-rule validation & filtering coverage
-------------------------------------------------------------------
Guards the Vegetarian / Vegan / Dairy-Free / Gluten-Free / Keto / Low-Sugar
rules end-to-end: Pydantic acceptance, key mapping, and real DataFrame filtering.

Run from the project root with:
    pytest tests/test_diet_rules.py -v
"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.schemas import AlternativeRequest, DietRuleEnum, normalize_diet_rule
from backend.matcher import apply_diet_filter, load_data

# Exact keys the frontend sends (frontend/app.py _DIET_LABELS -> _LABEL_TO_KEY)
FRONTEND_KEYS = [
    "vegetarian", "vegan", "dairy_free", "gluten_free", "keto", "low_sugar"
]


def test_request_accepts_every_frontend_key():
    """All six keys sent by the frontend must validate without a 422."""
    for key in FRONTEND_KEYS:
        req = AlternativeRequest(product="Chana Dal", city="Bangalore", diet_rules=[key])
        assert req.diet_rules[0].value == key


def test_request_accepts_display_names_and_emoji_pills():
    """Display labels / emoji pill text normalize to the canonical keys."""
    cases = {
        "Vegetarian": "vegetarian",
        "🌿 Vegetarian": "vegetarian",
        "Vegan": "vegan",
        "Dairy-Free": "dairy_free",
        "🥛 Dairy-Free": "dairy_free",
        "Gluten-Free": "gluten_free",
        "Keto": "keto",
        "Low-Sugar": "low_sugar",
        "🍬 Low-Sugar": "low_sugar",
    }
    for label, expected in cases.items():
        req = AlternativeRequest(product="Chana Dal", city="Bangalore", diet_rules=[label])
        assert req.diet_rules[0].value == expected


def test_request_accepts_multiple_rules_at_once():
    req = AlternativeRequest(
        product="Chana Dal",
        city="Bangalore",
        diet_rules=["vegetarian", "Dairy-Free", "🍬 Low-Sugar"],
    )
    assert [r.value for r in req.diet_rules] == [
        "vegetarian", "dairy_free", "low_sugar"
    ]


def test_request_rejects_unknown_rule():
    with pytest.raises(ValidationError):
        AlternativeRequest(product="Chana Dal", city="Bangalore", diet_rules=["paleo"])


def test_normalize_diet_rule_helper():
    assert normalize_diet_rule(DietRuleEnum.dairy_free) == "dairy_free"
    assert normalize_diet_rule("🥛 Dairy-Free") == "dairy_free"
    assert normalize_diet_rule("low_sugar") == "low_sugar"
    assert normalize_diet_rule("🍬 Low-Sugar") == "low_sugar"


def test_vegetarian_filter_runs():
    df = load_data()
    out = apply_diet_filter(df, ["vegetarian"])
    assert out["vegetarian"].all()


def test_dairy_free_filter_excludes_dairy():
    df = load_data()
    out = apply_diet_filter(df, ["dairy_free"])
    assert len(out) < len(df)
    assert out["dairy_free"].all()
    assert "Paneer" not in out["name"].tolist()


def test_low_sugar_filter_applies_carb_ceiling():
    df = load_data()
    out = apply_diet_filter(df, ["low_sugar"])
    assert len(out) < len(df)
    assert (out["carbs"] <= 15.0).all()


def test_filter_accepts_display_labels():
    """Matcher filtering is identical for keys and emoji pill labels."""
    df = load_data()
    by_key = apply_diet_filter(df, ["low_sugar", "dairy_free"])
    by_label = apply_diet_filter(df, ["🍬 Low-Sugar", "🥛 Dairy-Free"])
    assert by_key["name"].tolist() == by_label["name"].tolist()
