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

## 1.5. Set up Supabase Authentication (free tier)

1. Go to <https://supabase.com> and create a free project.
2. In **Project Settings → API**, copy the **Project URL** and **anon public key**.
   These become `SUPABASE_URL` and `SUPABASE_ANON_KEY` in Streamlit secrets.
3. In **Authentication → Providers**, enable **Email** (email/password sign-in).
4. In the **SQL Editor**, run this to create the tables the app needs:

   ```sql
   -- Profiles: public name linked to each Supabase Auth user
   create table profiles (
     id uuid references auth.users not null primary key,
     email text not null,
     name text not null,
     created_at timestamptz default now()
   );

   -- Saved matches: one row per saved food swap, owned by a user
   create table saved_matches (
     id bigserial primary key,
     user_id uuid references auth.users not null,
     product text not null,
     city text not null,
     diet_rules jsonb not null default '[]',
     allergens jsonb not null default '[]',
     priority text not null,
     alternatives jsonb not null default '[]',
     created_at timestamptz default now()
   );

   -- Enable Row Level Security so users only see their own rows
   alter table profiles enable row level security;
   alter table saved_matches enable row level security;

   create policy "users can view own profile" on profiles
     for select using (auth.uid() = id);
   create policy "users can insert own profile" on profiles
     for insert with check (auth.uid() = id);
   create policy "users can view own saved matches" on saved_matches
     for select using (auth.uid() = user_id);
   create policy "users can insert own saved matches" on saved_matches
     for insert with check (auth.uid() = user_id);
   create policy "users can delete own saved matches" on saved_matches
     for delete using (auth.uid() = user_id);
   ```

5. In **Authentication → URL Configuration**, add your Streamlit app URL
   (e.g. `https://macromatch.streamlit.app`) to **Redirect URLs** if you later
   add email confirmation or OAuth providers.

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

   # Supabase — get these from Project Settings → API in your Supabase dashboard
   SUPABASE_URL = "https://<your-project-ref>.supabase.co"
   SUPABASE_ANON_KEY = "<your-anon-key>"
   ```

   The frontend reads all three values via `st.secrets`. Supabase credentials are
   intentionally never stored in the repository (see
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

## 8. Persistence note

User accounts (Supabase Auth) and saved matches (Supabase `saved_matches`
table) live in the cloud, so they **persist across Streamlit deployments and
reboots**. Nothing is stored on the local filesystem anymore — `config.yaml`
and `data/user_data.db` are no longer used.

The only client-side caveat: Streamlit's `st.session_state` resets when the
browser tab is closed or refreshed. The app attempts to restore the Supabase
session from stored tokens on each run, but after a hard refresh the user may
need to sign in again. This is normal behavior for a client-side session.

If you need true "remember me" across browser sessions, enable email
confirmation in Supabase Auth or implement OAuth (Google/GitHub) login in
Authentication → Providers.
