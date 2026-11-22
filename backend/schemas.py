"""
schemas.py — Pydantic models for MacroMatch API request and response validation.
FastAPI uses these to auto-validate inputs and generate the /docs UI.
"""

import re

from pydantic import BaseModel, Field, field_validator
from typing import Literal
from enum import Enum


# ─────────────────────────────────────────────
# Allowed values (Enums for /docs dropdowns)
# ─────────────────────────────────────────────

class PriorityEnum(str, Enum):
    protein    = "protein"    # Prioritise matching protein content
    low_carb   = "low_carb"   # Prioritise matching low carbohydrate content
    balanced   = "balanced"   # Equal weight across all macros


class DietRuleEnum(str, Enum):
    vegetarian  = "vegetarian"
    vegan       = "vegan"
    dairy_free  = "dairy_free"
    gluten_free = "gluten_free"
    keto        = "keto"
    low_sugar   = "low_sugar"


# The frontend shows human-readable, emoji-prefixed pills (e.g. "🥛 Dairy-Free").
# Accept those display labels as well as the canonical snake_case keys so a
# mismatch between frontend and deployed backend can never cause a 422 error.
DIET_RULE_ALIASES: dict[str, str] = {
    "vegetarian":  "vegetarian",
    "veg":         "vegetarian",
    "vegan":       "vegan",
    "dairy_free":  "dairy_free",
    "dairyfree":   "dairy_free",
    "gluten_free": "gluten_free",
    "glutenfree":  "gluten_free",
    "keto":        "keto",
    "low_sugar":   "low_sugar",
    "lowsugar":    "low_sugar",
}


def normalize_diet_rule(value) -> str:
    """
    Normalize a diet rule into the canonical snake_case key.

    Accepts canonical keys ("dairy_free"), display names ("Dairy-Free"), and
    emoji-prefixed pill labels ("🥛 Dairy-Free") interchangeably.
    """
    if isinstance(value, DietRuleEnum):
        return value.value

    text = str(value).strip().lower()
    # Strip leading emoji / symbols: "🥛 Dairy-Free" -> "dairy-free"
    text = re.sub(r"^[^\w]+", "", text)
    # Collapse whitespace, then convert spaces & hyphens to underscores.
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" ", "_").replace("-", "_")
    return DIET_RULE_ALIASES.get(text, text)


class AllergenEnum(str, Enum):
    soy   = "soy"
    nuts  = "nuts"
    dairy = "dairy"


# ─────────────────────────────────────────────
# Request model
# ─────────────────────────────────────────────

class AlternativeRequest(BaseModel):
    """
    Body sent by the user to POST /suggest-alternative
    """
    product: str = Field(
        ...,
        description="Name of the user's usual product (must match the database exactly).",
        examples=["Paneer"],
    )
    city: str = Field(
        ...,
        description="Destination city where the user needs a substitute.",
        examples=["Bangalore"],
    )
    diet_rules: list[DietRuleEnum] = Field(
        default=[],
        description="Diet constraints. Allowed: 'vegetarian', 'vegan', 'dairy_free', 'gluten_free', 'keto', 'low_sugar'.",
        examples=[["vegan"]],
    )
    allergens: list[AllergenEnum] = Field(
        default=[],
        description="Allergens to avoid. Allowed: 'soy', 'nuts', 'dairy'.",
        examples=[["dairy"]],
    )
    priority: PriorityEnum = Field(
        default=PriorityEnum.balanced,
        description=(
            "Determines which macros are weighted more heavily when scoring matches.\n"
            "• protein   — prioritises protein content match\n"
            "• low_carb  — prioritises low carbohydrate match\n"
            "• balanced  — equal weight across all macros"
        ),
    )

    @field_validator("diet_rules", mode="before")
    @classmethod
    def normalize_diet_rules(cls, v):
        """Accept keys, display names, or emoji pill labels for every rule."""
        if v is None:
            return []
        if not isinstance(v, (list, tuple)):
            return v  # let Pydantic emit its normal type-validation error
        return [normalize_diet_rule(rule) for rule in v]

    @field_validator("product")
    @classmethod
    def product_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Product name must not be empty.")
        return v.strip()

    @field_validator("city")
    @classmethod
    def city_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("City must not be empty.")
        return v.strip()


# ─────────────────────────────────────────────
# Sub-models for the response
# ─────────────────────────────────────────────

class NutritionInfo(BaseModel):
    """Macro breakdown of a product (per 100g)."""
    protein:  float
    carbs:    float
    fat:      float
    fiber:    float
    calories: float


class AlternativeProduct(BaseModel):
    """A single matched alternative product."""
    rank:         int   = Field(..., description="1 = closest match.")
    name:         str
    category:     str
    nutrition:    NutritionInfo
    match_score:  float = Field(..., description="Lower = closer nutritional match.")
    cities:       str
    explanation:  str   = Field(
        default="",
        description="Plain-English explanation of why this product was suggested (generated by Claude).",
    )


# ─────────────────────────────────────────────
# Full response model
# ─────────────────────────────────────────────

class AlternativeResponse(BaseModel):
    """Full response returned by POST /suggest-alternative"""
    original_product: str
    city:             str
    priority_used:    str
    diet_rules:       list[str]
    allergens:        list[str]
    alternatives:     list[AlternativeProduct]
