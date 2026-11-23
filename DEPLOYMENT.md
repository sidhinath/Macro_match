# Deploying MacroMatch for free

Target setup:

```
Browser ──► Streamlit Community Cloud  (frontend/app.py)
                    │ HTTPS
                    ▼
            Render Web Service           (FastAPI backend)
                    │ optional
                    ▼
            Anthropic API                (explanations only)
```

- **UI:** Streamlit Community Cloud — free, no credit card.
- **API:** Render free web service — free, no credit card.
- **LLM:** optional. Without `ANTHROPIC_API_KEY`, the API returns deterministic
  fallback explanations and the demo still works. You only pay Anthropic for
  actual explanation calls.

Everything below costs **$0/month** on the free tiers. The only trade-off is
cold starts: the Render service sleeps after 15 minutes of inactivity.

---

## 0. Prepare the repository

The API and UI must be in the same GitHub repo.

```bash
cd Macro_match
git init
git add .
git status          # confirm .env is NOT staged
git commit -m "MacroMatch"
git branch -M main
git remote add origin https://github.com/<you>/macromatch.git
git push -u origin main
```

Before pushing, confirm:

- `.env` is **not** committed (it is already in `.gitignore`).
- `.env.example` contains only a placeholder, not a real key.
- `data/products.csv` **is** committed — the matcher needs it at runtime.
- `requirements.txt` is at the repo root.

> If a real Anthropic key was ever committed or shared, revoke it now in the
> [Anthropic console](https://console.anthropic.com/settings/keys) and create a
> new one. Removing it from the latest commit does not remove it from git history.

---

## 1. Deploy the API on Render

### Option A — Blueprint (uses `render.yaml`)

1. Go to <https://dashboard.render.com> → **New** → **Blueprint**.
2. Connect your GitHub repo. Render reads `render.yaml`.
3. Click **Apply**. When prompted for `ANTHROPIC_API_KEY`, either paste a key or
   leave it blank to use fallback explanations.
4. Wait for the first build (2–4 minutes for pandas/NumPy wheels).

### Option B — Manual web service

1. **New** → **Web Service** → connect the repo.
2. Settings:

   | Field | Value |
   | ----- | ----- |
   | Name | `macromatch-api` (or anything) |
   | Region | closest to you |
   | Branch | `main` |
   | Root Directory | *(leave empty — repo root)* |
   | Runtime | Python 3 |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
   | Instance Type | **Free** |
   | Health Check Path | `/` |
   | Auto-Deploy | Yes |

3. Under **Environment**, add:

   | Key | Value |
   | --- | ----- |
   | `ANTHROPIC_API_KEY` | your key, or leave it out entirely |

   Do **not** add `PORT` manually — Render provides it, and `$PORT` in the start
   command expands to it. Binding to `127.0.0.1` instead of `0.0.0.0` will fail
   Render's port scan.

4. Deploy and wait for **Live**.

### Verify

```bash
curl https://<your-service>.onrender.com/
# {"status":"ok","message":"MacroMatch API is running. ..."}

curl https://<your-service>.onrender.com/products
```

Swagger docs are at `https://<your-service>.onrender.com/docs`.

> The first request after a sleep period can take 30–60 s while the container
> starts and imports pandas. That is normal on the free tier.

---

## 2. Deploy the UI on Streamlit Community Cloud

1. Go to <https://share.streamlit.io> and sign in with GitHub.
2. **Create app** → **Deploy a public app from GitHub**.
3. Fill in:

   | Field | Value |
   | ----- | ----- |
   | Repository | `<you>/macromatch` |
   | Branch | `main` |
   | Main file path | `frontend/app.py` |
   | App URL | choose a subdomain, e.g. `macromatch` |

4. Open **Advanced settings** → **Secrets** and paste:

   ```toml
   MACROMATCH_API_URL = "https://<your-service>.onrender.com"

   [auth]
   # Cookie signing secret for streamlit-authenticator's remember-me cookie.
   # Generate one with:  python -c "import secrets; print(secrets.token_hex(32))"
   cookie_key = "<long-random-secret>"
   ```

   The frontend reads both values via `st.secrets`. The cookie key must be set
   here — it is intentionally never stored in the repository (see
   `.streamlit/secrets.toml.example`). `MACROMATCH_API_URL` also accepts the
   same name as an environment variable for local/container use and falls back
   to `http://127.0.0.1:8000` when neither is set.

5. **Deploy**. The first build installs `requirements.txt` (1–3 minutes).

6. Open the app URL and run a query, e.g. *Paneer → Bangalore → vegan → dairy →
   protein*.

> The Anthropic key belongs on **Render only**. The Streamlit app never needs it
> and should never hold it — all LLM calls happen in the API.

---

## 3. What the free tiers actually give you

| | Render Free Web Service | Streamlit Community Cloud |
| --- | --- | --- |
| Cost | $0 | $0 |
| RAM | 512 MB | ~1 GB |
| Sleeps | after 15 min idle | after a longer idle period |
| Wake time | ~30–60 s (cold start) | a few seconds |
| Custom domain | no (free subdomain) | no (free `*.streamlit.app`) |
| Persistent disk | not included | not included |
| Card required | no | no |

Neither service needs a database or persistent disk: the product catalogue is a
CSV committed to the repo and all state is per-request.

### Cold-start behavior

Render spins a free service down after 15 minutes without traffic. The next
request triggers a cold start. MacroMatch handles this gracefully:

- The UI waits up to **20 s** for `GET /products` and **90 s** for
  `POST /suggest-alternative`.
- If the API is still asleep, the UI shows a clear "cannot reach the backend —
  it may be starting up" message with a retry hint instead of crashing.

Options if cold starts bother you:

- Reload the page after ~1 minute (the container is then warm).
- Keep the service awake with a scheduled ping (note that this consumes your
  free instance hours and may violate Render's fair-use expectations — check
  their current terms).
- Move to a paid instance ($7/month) for always-on behavior.

---

## 4. Deploying updates

Both platforms auto-deploy on push:

```bash
git add .
git commit -m "Update products"
git push
```

- Render rebuilds the API.
- Streamlit Cloud rebuilds the UI.

If you change a secret, use the dashboard (Render → Environment; Streamlit →
App settings → Secrets). Streamlit restarts the app when secrets change.

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| UI: "Cannot reach the backend" | Wrong `MACROMATCH_API_URL`, or API cold-starting | Check the Render URL; wait ~1 min and reload |
| UI shows the localhost hint after deploy | Secret not set or app not restarted | Add `MACROMATCH_API_URL` in Streamlit Secrets, then reboot the app |
| Render: "No open ports detected" | Start command binds to `127.0.0.1` or ignores `$PORT` | Use `--host 0.0.0.0 --port $PORT` |
| Render: `ModuleNotFoundError: backend` | Root directory set to a subfolder, or repo layout changed | Keep Root Directory empty and the `backend/` package at repo root |
| Render build fails on pandas/NumPy | Unsupported Python version | Pin `PYTHON_VERSION` (e.g. `3.12.7`) in Render env vars |
| API returns 500 with fallback text missing | CSV path or schema changed | Check Render logs; `data/products.csv` must be committed |
| Explanations look templated | No/invalid `ANTHROPIC_API_KEY`, rate limit, or network error | Expected fallback; set a valid key on Render and redeploy |
| 404 `no_alternatives_found` | City not in the CSV / filters too strict | Try another city or relax diet/allergen filters — this is correct behavior |
| CORS error in the browser | You are calling the API directly from JS | Add `CORSMiddleware` to `backend/main.py` (not needed for the Streamlit UI, which calls the API server-side) |

---

## 6. Security notes for a public deployment

- **Never put `ANTHROPIC_API_KEY` in the frontend or in the repo.** It belongs
  only in Render's environment settings.
- Rotate any key that has been pasted into a tracked file or shared chat.
- The API has **no authentication or rate limiting**. Anyone with the URL can
  call it and consume Anthropic credits. For a public demo, consider:
  - leaving `ANTHROPIC_API_KEY` unset (fallback explanations, zero LLM cost), or
  - adding a cap/gateway (e.g. Cloudflare, a simple API key check, or
    `slowapi` rate limiting).
- Treat `/docs` as public. It exposes your schema, not your secrets, but you may
  want to disable it in production with `FastAPI(docs_url=None, redoc_url=None)`.
- Keep dependencies patched; `requirements.txt` currently uses lower bounds only.

---

## 7. Alternatives (also free, if you prefer)

| Need | Option | Notes |
| --- | --- | --- |
| API | Koyeb / Fly.io free allowances | Fly.io now requires a card for most accounts |
| API | Hugging Face Spaces (Docker) | Good if you want UI + API in one Space |
| UI | Hugging Face Spaces (Streamlit SDK) | Simple, but sleeps too |
| Full stack | Single Streamlit app calling `backend.matcher` directly | No API host at all, but loses the REST layer |

The current split (Streamlit Cloud + Render) keeps the API independently
testable and documented, which is why it is the recommended setup.

---

## 8. Limitation: ephemeral filesystem (accounts & saved matches can reset)

Streamlit Community Cloud does **not** give you a persistent disk. Every time
the app redeploys or reboots, the local filesystem is reset, so:

- `config.yaml` (user accounts with hashed passwords) is lost — users must
  sign up again.
- `data/user_data.db` (SQLite saved matches) is lost — saved history is gone.

This is by design in this mini project: everything stays file-based and simple
so the code is easy to explain in a viva. If you need real persistence, the
simple upgrade path is to replace the file-based storage with a hosted store
still keyed by username, e.g.:

- **Supabase** (free PostgreSQL tier) — `users` and `saved_matches` tables,
  Row Level Security so each user sees only their own rows.
- **Google Sheets** — one sheet for users, one for saved matches, appended via
  the Sheets API.

The login / logout / session-check flow in `frontend/app.py` stays exactly the
same; only the `load_config` / `save_config` / `save_match` / `get_saved_matches`
functions would swap files for API calls.
