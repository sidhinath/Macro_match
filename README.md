<p align="center">
  <img src="assets/macromatch_logo.png" alt="MacroMatch logo" width="460">
</p>

# MacroMatch

**Your macros, anywhere.**

MacroMatch finds the nutritionally closest substitute for a food you already eat,
in a city you are travelling to — while respecting your diet and allergies.

You tell it *"I usually eat Paneer, I'm going to Bangalore, I'm vegan and avoid
dairy, protein matters most."* It replies with the three best local swaps,
ranked by macro similarity, with a side-by-side nutrition comparison and a
plain-English explanation for each match.

> The numbers are computed deterministically with pandas/NumPy. The LLM only
> writes the explanation text — it never does arithmetic and never picks the
> winner. If no API key is configured, the app still works using built-in
> fallback explanations.

---

## The problem

Dietary habits do not travel well. A product you rely on at home may be
unavailable, labelled differently, or replaced by something with a very
different macro profile in your destination city. Reading every label in an
unfamiliar shop is slow, and "high protein" or "keto friendly" claims are hard
to compare across brands.

MacroMatch treats the problem as what it is: **a nearest-neighbour search over
nutrition data, constrained by availability, diet rules, and allergens.**

## Features

- **Macro-similarity matching** — weighted Euclidean distance over protein,
  carbs, fat, fiber and calories, with per-nutrient min-max normalization so
  calories do not drown out fiber.
- **City availability filter** — only suggests products sold in your destination.
- **Diet rules** — `vegan`, `gluten_free`, and `keto` (carbs ≤ 10 g / 100 g).
- **Allergen exclusion** — hard-excludes `soy`, `nuts`, and `dairy`.
- **Priority modes** — `protein`, `low_carb`, or `balanced`, each mapping to a
  different weight vector.
- **LLM explanations with a safety net** — Claude describes *why* each match
  fits; authentication, rate-limit, network, and parsing failures fall back to
  deterministic, data-driven text.
- **Rich Streamlit UI** — ranked cards, macro comparison tables, bar charts,
  and a dark, card-based layout.
- **Auto-generated API docs** at `/docs` (Swagger UI) and `/redoc`.
- **Test suite** covering city filtering, invalid products, vegan and allergen
  invariants, and weight sensitivity.

## Architecture

```
┌──────────────────────────────┐
│  Streamlit UI                │
│  frontend/app.py             │
│  • inputs, cards, charts     │
└──────────────┬───────────────┘
               │  HTTP/JSON (requests)
               ▼
┌──────────────────────────────┐
│  FastAPI service             │
│  backend/main.py             │
│  • routing, validation,      │
│    priority → weights        │
└───┬───────────────┬──────────┘
    │               │
    ▼               ▼
┌─────────────┐  ┌──────────────────────────┐
│ matcher.py  │  │ explainer.py             │
│ pandas +    │  │ Anthropic Claude         │
│ NumPy       │  │ (optional, with fallback)│
└──────┬──────┘  └──────────────────────────┘
       │
       ▼
 data/products.csv
```

### Request flow

1. The UI sends `POST /suggest-alternative` with the product, city, diet rules,
   allergens, and priority.
2. Pydantic validates the body and rejects unknown diet/allergen/priority values
   with `422`.
3. `matcher.find_alternatives()` loads the CSV, finds the original product
   (case-insensitive), removes it from the candidate pool, then applies hard
   filters: city availability → diet rules → allergens.
4. Surviving candidates are scored with a weighted Euclidean distance over
   min-max normalized macros. The lowest score wins.
5. `explainer.generate_explanations()` receives the top 3 **already-computed**
   results and asks Claude for two sentences per alternative.
6. FastAPI returns a typed response; the UI renders cards, tables, and charts.

### Why the LLM cannot bend the numbers

`explainer.py` receives only pre-computed values and is instructed not to
calculate, compare, or invent numbers. It outputs prose only. Explanation
failures degrade gracefully to template text, so matching quality is fully
independent of the LLM.

## Project structure

```
Macro_match/
├── backend/
│   ├── main.py          # FastAPI app, routes, error mapping, weights
│   ├── matcher.py       # CSV loading, hard filters, similarity scoring
│   ├── explainer.py     # Claude prompt + deterministic fallback
│   └── schemas.py       # Pydantic request/response models
├── frontend/
│   └── app.py           # Streamlit UI
├── data/
│   └── products.csv     # 30 products, 14 cities, macro + diet/allergen flags
├── tests/
│   ├── test_matcher.py  # pytest suite (5 tests, no network)
│   └── smoke_test.py    # manual live API check (run as a script)
├── requirements.txt
├── .env.example
└── render.yaml          # optional Render blueprint for the API
```

## Running the Project

### Option 1: Use the Deployed Application (Recommended)

Frontend (Streamlit):
<https://macromatchgit-8qnnjnxumw4sjopvkcpttz.streamlit.app/>

Backend API (Render):
<https://macro-match.onrender.com>

Users can open the Streamlit URL in any browser and use the application
directly without installing anything.

**Note:**

- The backend is hosted on Render's **free tier**.
- The first request may take **30–60 seconds** if the backend is waking up from
  inactivity.
- After the backend wakes up, the application works normally.

### Option 2: Run Locally

**Prerequisites:** Python **3.10+** (developed and tested on 3.13). An Anthropic
API key is **optional** — without it the app uses fallback explanations.

#### 1. Clone the repository

```bash
git clone https://github.com/sidhinath/Macro_match.git
cd Macro_match
```

#### 2. Create and activate a virtual environment

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Windows (cmd.exe)
venv\Scripts\activate.bat
```

#### 3. Install dependencies

```bash
pip install -r requirements.txt
```

#### 4. Configure the environment (optional)

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Then edit `.env`:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
```

Leave it unset or empty to use fallback explanations. `.env` is git-ignored.

> ⚠️ **Never commit a real key.** If a key has ever been pasted into a tracked
> file such as `.env.example`, revoke it in the
> [Anthropic console](https://console.anthropic.com/settings/keys) and issue a new one.

#### 5. Start the backend (terminal 1)

From the project root:

```bash
python -m uvicorn backend.main:app --reload
```

- API: <http://127.0.0.1:8000>
- Interactive docs: <http://127.0.0.1:8000/docs>

#### 6. Start the frontend (terminal 2)

With the same virtual environment active:

```bash
python -m streamlit run frontend/app.py
```

Streamlit opens <http://localhost:8501>. The UI reads the API URL from the
`MACROMATCH_API_URL` environment variable (or its Streamlit secret), defaulting
to `http://127.0.0.1:8000`.

#### 7. Run the tests (optional)

```bash
pytest tests -q
```

For a live end-to-end check against a running API:

```bash
python tests/smoke_test.py
```

## API reference

| Method | Path                   | Purpose                                    |
| ------ | ---------------------- | ------------------------------------------ |
| `GET`  | `/`                    | Health check                               |
| `GET`  | `/products`            | List all product names                     |
| `POST` | `/suggest-alternative` | Ranked substitutes for a product in a city |

### `POST /suggest-alternative`

```json
{
  "product": "Paneer",
  "city": "Bangalore",
  "diet_rules": ["vegan"],
  "allergens": ["dairy"],
  "priority": "protein"
}
```

```bash
curl -X POST http://127.0.0.1:8000/suggest-alternative \
  -H "Content-Type: application/json" \
  -d '{"product":"Paneer","city":"Bangalore","diet_rules":["vegan"],"allergens":["dairy"],"priority":"protein"}'
```

Abridged response:

```json
{
  "original_product": "Paneer",
  "city": "Bangalore",
  "priority_used": "protein",
  "diet_rules": ["vegan"],
  "allergens": ["dairy"],
  "alternatives": [
    {
      "rank": 1,
      "name": "Tempeh",
      "category": "Soy Product",
      "nutrition": {
        "protein": 19.0, "carbs": 9.0, "fat": 11.0,
        "fiber": 5.0, "calories": 193.0
      },
      "match_score": 0.0886,
      "cities": "Mumbai,Bangalore",
      "explanation": "Tempeh is a close nutritional match for Paneer, ..."
    }
  ]
}
```

**Understanding `match_score`:** lower is closer. It is a weighted Euclidean
distance in normalized macro space, computed relative to the current
original + candidate set — treat it as a ranking signal, **not** a percentage
or a stable cross-query metric.

**Errors:**

| Status | When                                                     |
| ------ | -------------------------------------------------------- |
| `422`  | Invalid body, unknown enum value, or empty product/city  |
| `404`  | `product_not_found` or `no_alternatives_found`           |
| `500`  | Unexpected server error (details logged server-side only)|

## Data

`data/products.csv` — one row per product, macros per 100 g:

| Column | Type | Meaning |
| ------ | ---- | ------- |
| `name` | string | Unique product name |
| `category` | string | Display category |
| `protein`, `carbs`, `fat`, `fiber` | float | Grams per 100 g |
| `calories` | float | kcal per 100 g |
| `vegan`, `gluten_free` | bool | Diet compliance flags |
| `contains_soy`, `contains_nuts`, `contains_dairy` | bool | Allergen flags |
| `cities` | string | Comma-separated cities where it is sold |

To add products, append rows with unique names and keep the boolean columns as
`TRUE`/`FALSE`. Unknown cities simply yield `no_alternatives_found`.

## Tests

```bash
pytest tests -q
```

Covers: unknown city, invalid product, vegan filter excluding dairy, nut allergy
excluding nut products, and weight sensitivity. The suite is offline and fast
(~1 s).

For a live end-to-end check against a running API:

```bash
python tests/smoke_test.py
# or against a deployed API:
MACROMATCH_API_URL=https://your-api.onrender.com python tests/smoke_test.py
```

## Deployment

Free deployment instructions (Streamlit Community Cloud for the UI, Render for
the API), including secrets, cold starts, and troubleshooting, are in
[`DEPLOYMENT.md`](DEPLOYMENT.md).

## Design notes & limitations

- **Small curated dataset.** 30 products across 14 cities. It is a demonstration,
  not a nutrition database. City availability is hand-maintained.
- **Scores are relative.** Min-max normalization uses the original product plus
  the filtered candidates for that query, so adding a product can shift scores.
- **No persistence or user accounts.** Every request is stateless; nothing is
  stored.
- **Keto is a carb ceiling** (≤ 10 g / 100 g), not a full macro-ratio model.
- **Public API has no auth or rate limiting.** If you expose it with a real
  Anthropic key, add a key cap or gateway to avoid burning credits.
- **Allergen data is only as good as the CSV.** Cross-contamination and
  "may contain" warnings are out of scope. This is not medical advice.

## License

MIT
