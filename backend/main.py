"""
main.py — MacroMatch FastAPI Application
-----------------------------------------
Exposes a REST API for finding nutritional substitutes.

Endpoints:
    GET  /           → Health check / welcome message
    GET  /products   → List all available product names
    POST /suggest-alternative → Core matching endpoint

Run with:
    uvicorn backend.main:app --reload

Then open: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import traceback

from backend.schemas import (
    AlternativeRequest,
    AlternativeResponse,
    AlternativeProduct,
    NutritionInfo,
    PriorityEnum,
)
from backend.matcher import find_alternatives, load_data
from backend.explainer import generate_explanations, ExplainerInput, ProductInfo

# ─────────────────────────────────────────────
# Priority → Weight presets
# ─────────────────────────────────────────────
# These translate the user-friendly "priority" dropdown into
# the numeric weight dict that compute_similarity_scores() needs.

PRIORITY_WEIGHTS: dict[str, dict[str, float]] = {
    PriorityEnum.protein: {
        "protein":  0.50,  # Match protein content most closely
        "calories": 0.20,
        "carbs":    0.15,
        "fat":      0.10,
        "fiber":    0.05,
    },
    PriorityEnum.low_carb: {
        "carbs":    0.50,  # Match (low) carb content most closely
        "protein":  0.20,
        "fat":      0.15,
        "fiber":    0.10,
        "calories": 0.05,
    },
    PriorityEnum.balanced: {
        "protein":  0.25,  # All macros matter equally
        "carbs":    0.25,
        "fat":      0.20,
        "fiber":    0.15,
        "calories": 0.15,
    },
}


# ─────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────

app = FastAPI(
    title="MacroMatch API",
    description=(
        "Find the closest nutritional substitute for your usual product "
        "when you travel to a new city. Supports vegetarian, vegan, dairy-free, "
        "gluten-free, keto, and low-sugar diets with allergen filtering."
    ),
    version="1.0.0",
    contact={
        "name": "MacroMatch",
    },
    license_info={
        "name": "MIT",
    },
)


# ─────────────────────────────────────────────
# GET / — Health check
# ─────────────────────────────────────────────

@app.get("/", tags=["Health"], summary="Welcome / health check")
def root():
    """
    Returns a simple status message confirming the API is running.
    """
    return {
        "status": "ok",
        "message": "MacroMatch API is running. Visit /docs to explore endpoints.",
    }


# ─────────────────────────────────────────────
# GET /products — List all product names
# ─────────────────────────────────────────────

@app.get("/products", tags=["Data"], summary="List all available products")
def list_products():
    """
    Returns all product names currently in the database.
    Use these exact names in the `product` field of POST /suggest-alternative.
    """
    try:
        df = load_data()
        products = sorted(df["name"].tolist())
        return {"total": len(products), "products": products}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load product data: {str(e)}")


# ─────────────────────────────────────────────
# POST /suggest-alternative — Core endpoint
# ─────────────────────────────────────────────

@app.post(
    "/suggest-alternative",
    response_model=AlternativeResponse,
    tags=["Matching"],
    summary="Find nutritional alternatives in a destination city",
)
def suggest_alternative(request: AlternativeRequest):
    """
    Given your usual product and destination city, returns the top 3
    nutritionally closest substitutes that match your diet and allergen rules.

    **How scoring works:**
    - Nutrient values are min-max normalized so no single macro dominates by scale.
    - A weighted Euclidean distance is computed for each candidate.
    - Lower `match_score` = nutritionally closer to your original product.

    **Priority effects:**
    - `protein`  → heavily weights protein content match
    - `low_carb` → heavily weights carbohydrate content match
    - `balanced` → equal weighting across all macros

    **Error responses:**
    - `404` if the product name is not found in the database.
    - `404` if no alternatives survive the city / diet / allergen filters.
    - `422` if the request body is malformed (FastAPI built-in validation).
    """

    # Resolve priority → weight dict
    weights = PRIORITY_WEIGHTS[request.priority]

    try:
        results_df = find_alternatives(
            product_name=request.product,
            city=request.city,
            diet_rules=[rule.value for rule in request.diet_rules],
            allergens=[allergen.value for allergen in request.allergens],
            weights=weights,
            top_n=3,
        )

    except ValueError as e:
        error_msg = str(e)

        # Distinguish between "product not found" and "no city matches"
        if "not found in database" in error_msg:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "product_not_found",
                    "message": (
                        f"'{request.product}' was not found in our database. "
                        f"Use GET /products to see all valid product names."
                    ),
                },
            )
        elif "No alternatives found" in error_msg:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "no_alternatives_found",
                    "message": (
                        f"No alternatives for '{request.product}' found in {request.city} "
                        f"matching your filters. Try a different city, or relax your "
                        f"diet rules / allergen list."
                    ),
                },
            )
        else:
            raise HTTPException(status_code=400, detail={"error": "bad_request", "message": error_msg})

    except Exception as e:
        # Catch-all for unexpected errors — log full traceback server-side
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "An unexpected error occurred."},
        )

    # ── Step 2: Build ExplainerInput from matcher results ──────────
    # Convert each DataFrame row into a ProductInfo dataclass so the
    # explainer can inject exact macro numbers into the Claude prompt.
    product_infos = [
        ProductInfo(
            name=row["name"],
            protein=row["protein"],
            carbs=row["carbs"],
            fat=row["fat"],
            fiber=row["fiber"],
            calories=row["calories"],
            match_score=round(row["match_score"], 4),
            cities=row["cities"],
        )
        for _, row in results_df.iterrows()
    ]

    explainer_input = ExplainerInput(
        original_product=request.product,
        city=request.city,
        diet_rules=[r.value for r in request.diet_rules],
        allergens=[a.value for a in request.allergens],
        priority=request.priority.value,
        alternatives=product_infos,
    )

    # ── Step 3: Generate plain-English explanations via Claude ──────
    # generate_explanations() never fails hard — it falls back to
    # deterministic text if the API is unavailable or the key is missing.
    explanations: list[str] = generate_explanations(explainer_input)

    # ── Step 4: Build structured response ───────────────────────────
    # Zip matcher results with Claude explanations (1-to-1 correspondence).
    alternatives = []
    for rank, ((_, row), explanation) in enumerate(
        zip(results_df.iterrows(), explanations), start=1
    ):
        alternatives.append(
            AlternativeProduct(
                rank=rank,
                name=row["name"],
                category=row["category"],
                nutrition=NutritionInfo(
                    protein=row["protein"],
                    carbs=row["carbs"],
                    fat=row["fat"],
                    fiber=row["fiber"],
                    calories=row["calories"],
                ),
                match_score=round(row["match_score"], 4),
                cities=row["cities"],
                explanation=explanation,
            )
        )

    return AlternativeResponse(
        original_product=request.product,
        city=request.city,
        priority_used=request.priority.value,
        diet_rules=[r.value for r in request.diet_rules],
        allergens=[a.value for a in request.allergens],
        alternatives=alternatives,
    )
