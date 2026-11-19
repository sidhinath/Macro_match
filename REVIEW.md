# Code review — MacroMatch

Reviewed: `backend/`, `frontend/app.py`, `tests/`, `requirements.txt`, config.
Method: read every file, ran the test suite, started the API and exercised
`POST /suggest-alternative` end to end.

## Summary

The core design is solid: numeric matching is deterministic and isolated from
the LLM, the fallback path is real (not decorative), and the docstrings are
better than most production code. The problems are mostly at the **edges**:
one leaked secret, deployment-breaking hardcoded config, a test file that
breaks collection, and error handling that classifies failures by matching
strings inside exception messages.

| Severity | Count | Theme |
| -------- | ----- | ----- |
| Critical | 3 | Secret in tracked file, hardcoded API URL, broken pytest collection |
| High | 6 | Brittle error mapping, no LLM timeout, silent truncation, no logging, per-request CSV load |
| Medium | 14 | Case-sensitive city filter, silent filter skips, HTML injection, missing guards |
| Low | 10 | Naming, typing, test structure, requirement pinning |

I fixed the three critical items so the README and deployment guide are
accurate (details at the end). Everything else is left for you to decide.

---

## Critical

### C1. A real-looking Anthropic key was committed in `.env.example`

`.env.example` is tracked by git; `.gitignore` only excludes `.env`. The file
contained a full `sk-ant-...` key. Secret scanners and GitHub push protection
flag exactly this pattern, and anyone with repo access can spend the credits.

**Action required:** revoke that key in the
[Anthropic console](https://console.anthropic.com/settings/keys) and issue a new
one. Deleting the string from the working tree is not enough — check history
with `git log -p -- .env.example` and, if it was ever pushed, consider the key
compromised regardless.

**Fixed:** replaced with `sk-ant-your-key-here` and added a warning comment.

### C2. The frontend URL was hardcoded to `localhost`

`frontend/app.py` had `API_BASE = "http://127.0.0.1:8000"`. On Streamlit
Community Cloud, `127.0.0.1` is the Streamlit container, not the Render API, so
every deployed request would fail with "cannot reach the backend".

**Fixed:** added `_resolve_api_base()`, which reads `MACROMATCH_API_URL` from
the environment or `st.secrets`, then falls back to localhost. This is what the
deployment guide configures.

### C3. `pytest tests` failed before running any test

`tests/smoke_test.py` matched pytest's `*_test.py` collection pattern and made a
live `requests.post` at import time. Collection aborted with
`ConnectionError`, so the five real tests never ran:

```
ERROR tests/smoke_test.py - requests.exceptions.ConnectionError ...
Interrupted: 1 error during collection
```

**Fixed:** moved the request into `main()` under `if __name__ == "__main__":`,
and made the base URL configurable. `pytest tests -q` now reports `5 passed`.

---

## High

### H1. Error types are inferred from message substrings

`backend/main.py:161-189`:

```python
except ValueError as e:
    error_msg = str(e)
    if "not found in database" in error_msg:     # brittle
        ... 404 product_not_found
    elif "No alternatives found" in error_msg:   # also brittle
        ... 404 no_alternatives_found
```

Rewording a message in `matcher.py` silently changes the HTTP contract. The
matcher already distinguishes these cases; it should say so with types.

**Recommended:**

```python
# backend/matcher.py
class ProductNotFoundError(ValueError):
    """Raised when the requested product is absent from the catalogue."""

class NoAlternativesError(ValueError):
    """Raised when filters leave no candidate products."""

# backend/main.py
except ProductNotFoundError as err:
    raise HTTPException(404, {"error": "product_not_found", ...}) from err
except NoAlternativesError as err:
    raise HTTPException(404, {"error": "no_alternatives_found", ...}) from err
```

This removes the `else: 400 bad_request` branch, which currently turns any
unexpected `ValueError` into a 400.

### H2. No timeout on the Anthropic client

`backend/explainer.py:195`:

```python
client = anthropic.Anthropic(api_key=api_key)
```

The SDK's default timeout is generous (minutes, plus retries). A stalled call
can hold a FastAPI worker far longer than the frontend's 90 s budget, and on a
single-worker free instance it blocks other users. Set explicit bounds:

```python
client = anthropic.Anthropic(
    api_key=api_key,
    timeout=20.0,      # seconds per attempt
    max_retries=1,     # fail fast, fall back to template text
)
```

The fallback is already good, so failing fast is better than waiting.

### H3. Silent truncation when explanations and results disagree

`backend/main.py:233-235`:

```python
for rank, ((_, row), explanation) in enumerate(
    zip(results_df.iterrows(), explanations), start=1
):
```

If `generate_explanations()` returns fewer items, `zip` silently drops
alternatives and returns a shorter list; if it returns more, the extra ones are
ignored. Nothing logs the mismatch. The explainer already pads missing blocks,
but the contract is only convention.

**Recommended:** validate before zipping.

```python
if len(explanations) != len(results_df):
    logger.warning("explanation count %d != result count %d",
                   len(explanations), len(results_df))
fallback = _build_fallback_explanations(explainer_input)
explanations = (explanations + fallback)[:len(results_df)]
```

### H4. `print()`/`traceback.print_exc()` instead of logging

`backend/main.py:193`, `backend/explainer.py:184-242`,
`backend/matcher.py:108,131`. On Render, stdout is captured, but there are no
levels, timestamps, or request correlation, and filter warnings are
indistinguishable from real errors. Use the standard library:

```python
import logging
logger = logging.getLogger(__name__)
logger.warning("unknown diet rule %r skipped", rule)
```

FastAPI/uvicorn already configures a root handler, so this works out of the box.
Also avoid returning raw exception text to clients
(`main.py:113-114` returns `str(e)`, which can expose file paths):

```python
except OSError:
    logger.exception("could not load product data")
    raise HTTPException(500, "Could not load product data.")
```

### H5. The CSV is re-read on every request

`backend/matcher.py:47-65` is called by both `/products` and
`/suggest-alternative`, so every request performs a file read plus five
string-to-bool conversions. With 30 rows this is cheap, but it is unnecessary
I/O and a scaling trap.

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def _load_data_cached() -> pd.DataFrame:
    ...

def load_data() -> pd.DataFrame:
    return _load_data_cached().copy()   # protect callers from mutation
```

If you later switch to a database, load once at startup instead.

### H6. Broad `except Exception` hides programming errors

`backend/main.py:191` catches everything and returns a generic 500 — correct
for clients, but it also swallows bugs that should fail loudly in development.
Keep the handler, but log the exception with `logger.exception(...)` and
consider re-raising when `settings.debug` is true. Same pattern in
`frontend/app.py:50` (secrets lookup), where swallowing is acceptable.

---

## Medium

### M1. City matching is case-sensitive

`backend/matcher.py:79-81` checks `city_clean in [...c.strip() ...]`, so
`"bangalore"` returns "no alternatives" while `"Bangalore"` works. The product
lookup is case-insensitive, so this is inconsistent. Compare normalized values:

```python
target = city.strip().casefold()
mask = df["cities"].apply(
    lambda cell: target in {c.strip().casefold() for c in cell.split(",")}
)
```

Also consider a distinct `CityNotFoundError` so "typo in city" is not reported
as "filters too strict", plus a `GET /cities` endpoint instead of hardcoding
the list in the UI (`frontend/app.py:58`).

### M2. Unknown diet/allergen values are silently skipped

`backend/matcher.py:108,131` print a warning and continue. Through the API the
Pydantic enums prevent this, but `find_alternatives()` is a public function and
tests call it directly. For allergens in particular, "typo means no filter" is
the wrong failure mode. Raise `ValueError` for unknown values.

### M3. Boolean parsing fails open for allergens

`backend/matcher.py:55-57`:

```python
df[col] = df[col].astype(str).str.strip().str.upper() == "TRUE"
```

A value of `1`, `yes`, or a typo becomes `False`. For `contains_nuts` and
`contains_dairy`, `False` means "safe to suggest" — a data error could thus
recommend an allergen. Validate the raw values and abort on anything that is
not `TRUE`/`FALSE`:

```python
allowed = {"TRUE", "FALSE"}
raw = df[col].astype(str).str.strip().str.upper()
bad = set(raw) - allowed
if bad:
    raise ValueError(f"{col} has invalid values: {sorted(bad)}")
df[col] = raw == "TRUE"
```

### M4. Missing CSV values crash the city filter

`matcher.py:63` leaves `NaN` for empty city cells; `cell.split(",")` at line 80
then raises `AttributeError: 'float' object has no attribute 'split'`. Validate
required columns and nulls in `load_data()` with a clear message naming the row.

### M5. `match_score` is only meaningful within one query

Min-max normalization uses the original product plus the *filtered* candidates
(`matcher.py:165-179`), so the same pair of products gets different scores in
different queries. That is defensible for ranking, but scores must not be
presented as absolute similarity. The README now says this explicitly. If you
want stable scores, normalize against the full dataset once and reuse it.

### M6. LLM and CSV text is injected into HTML

`frontend/app.py:457` and `:516` interpolate `alt['name']`, `alt['category']`,
and the Claude-generated `explanation` into `st.markdown(..., unsafe_allow_html=True)`.
A malformed or prompt-injected response could inject markup. Escape untrusted
values:

```python
import html
safe_name = html.escape(alt["name"])
safe_explanation = html.escape(explanation)
```

Do the same for `selected_product` and `selected_city` in the summary block
(`app.py:420-438`).

### M7. Rank arrays are indexed without bounds checks

`frontend/app.py:443-444` uses `RANK_COLORS[rank]` and `RANK_LABELS[rank]`.
The API caps results at 3 today, but any future `top_n` change produces an
`IndexError` and a broken page. Use `rank % len(RANK_COLORS)` or pad the arrays.

### M8. Only the first Claude content block is read

`explainer.py:206`:

```python
raw_text: str = message.content[0].text.strip()
```

This assumes a non-empty list whose first block is text. Prefer:

```python
raw_text = "".join(
    block.text for block in message.content if block.type == "text"
).strip()
if not raw_text:
    raise ValueError("Claude returned no text blocks.")
```

### M9. The prompt hardcodes "3" alternatives

`explainer.py:101,126` says "top 3" and "Write the 3 explanations", while the
service passes a variable-length list. It works while `top_n=3` is fixed in
`main.py`, but the prompt should use `len(data.alternatives)` so the two cannot
drift.

### M10. The UI re-reads the CSV instead of using the API response

`frontend/app.py:246-262` loads `data/products.csv` locally for the comparison
table. If the UI and API are deployed from different commits, the "original"
macros can disagree with the backend that produced the matches. Return the
original product's nutrition in `AlternativeResponse` and use that.

### M11. All product-list failures look like a network outage

`frontend/app.py:233-243` returns `[]` for connection errors, timeouts, **and**
HTTP 500s, and caches that empty result for 60 s. A backend bug therefore looks
like "server is down". Capture the status code / exception and show a distinct
message (or `st.cache_data` only successful responses).

### M12. No CORS configuration

Not needed for the current Streamlit UI, which calls the API server-side. It
becomes necessary the moment a browser makes the request (custom frontend, JS
widget). Scope it narrowly if you add it:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://<your-app>.streamlit.app"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

### M13. A public endpoint can spend real money

No auth, no rate limit, no per-IP cap. Anyone who finds the Render URL can call
`/suggest-alternative` and trigger Claude requests. For a public demo, either
leave `ANTHROPIC_API_KEY` unset (fallback text, zero LLM cost) or add
`slowapi`/a gateway. `max_tokens=512` is already sensibly small.

### M14. Dependencies are only lower-bounded

`requirements.txt` uses `>=` for every package. A major release can break a
deploy without warning. Either add upper bounds (`pandas>=2.0,<3`) or commit a
lock file (`pip-compile`, `uv lock`). Pin `PYTHON_VERSION` on Render too.

---

## Low / clarity

1. **`PRIORITY_WEIGHTS` typing** (`main.py:37`): declared
   `dict[str, dict[str, float]]` but keyed by `PriorityEnum`. It works because
   `PriorityEnum` subclasses `str`, but the annotation should match:
   `dict[PriorityEnum, dict[str, float]]`.
2. **Misleading variable name** (`frontend/app.py:337,371`): `priority_label`
   holds the priority *key* (`"protein"`), not the display label. Rename to
   `priority_key` to prevent a future mix-up.
3. **Case-sensitive comparison lookup** (`app.py:257-260`): `get_original_macros`
   matches `df["name"] == product_name` exactly, while the matcher is
   case-insensitive. Normalize both or drop this code path (see M10).
4. **Awkward fallback wording** (`explainer.py:142-152`): with no diet rules it
   produces "compatible with your diet (no specific diet)". Special-case empty
   lists to "no specific diet restrictions".
5. **`cities` as a CSV string** in the response (`schemas.py:106`,
   `explainer.py:40`): clients must split it themselves. `list[str]` is a
   cleaner contract; keep the display string in the UI.
6. **No API-layer tests**: 404 mapping, 422 validation, and the response schema
   are untested. `fastapi.testclient.TestClient` makes these cheap; they would
   also have caught C2-style regressions.
7. **One dataset-dependent test**: `test_weights_affect_ranking` asserts that
   protein-heavy and fat-heavy weights produce different winners. Adding a
   product that is close on both macros could make it flaky. Use a fixed
   fixture CSV or assert on scores rather than the winner.
8. **`sys.path` manipulation** (`tests/test_matcher.py:18`) instead of a
   `conftest.py` or `pyproject.toml` with `pythonpath = ["."]`.
9. **Keto policy is an unnamed constant** (`matcher.py:40`): 10 g/100 g is a
   product decision, not a fact. Document the rationale and consider exposing
   it as configuration.
10. **`st.cache_data` on static CSV data** (`app.py:246`) means edits require a
    restart; acceptable, but note it in the data docs.
11. **Unused import** (`backend/main.py:18`): `JSONResponse` is imported but
    never used; `HTTPException` covers every response path.

---

## What I changed in this pass

| File | Change |
| ---- | ------ |
| `.env.example` | Replaced the real-looking key with a placeholder; added rotation warning and `MACROMATCH_API_URL` hint |
| `frontend/app.py` | API URL resolved from env/secret; 20 s/90 s timeouts; catch all `RequestException`; clearer cold-start and 422 messages; removed dead `st.columns(1)` |
| `tests/smoke_test.py` | Network call moved behind `main()`; configurable base URL; no longer breaks pytest collection |
| `README.md`, `DEPLOYMENT.md`, `render.yaml` | New docs and Render blueprint |

Verified after the changes:

```
pytest tests -q          → 5 passed in 1.09s
py_compile (all modules) → ok
live POST (uvicorn)      → 200, 3 ranked alternatives
```

## Recommended next steps

1. **Rotate the leaked Anthropic key today.**
2. Add typed exceptions + `logging` (H1, H4) — highest value for maintainability.
3. Add the Anthropic client timeout and the explanation-length guard (H2, H3).
4. Add `TestClient` tests for the 404/422 contract (Low 6).
5. Harden allergen CSV parsing (M3) before this is used by anyone with a real allergy.
