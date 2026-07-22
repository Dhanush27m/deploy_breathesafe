# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

BreatheSafe — AI air-quality platform for 29 Indian cities: live AQI, XGBoost forecasts (1/3/7-day), personalized health risk (PAERI), pollution-aware route planning, and email alerts. Monorepo: `frontend/` (React 18 + Vite + Tailwind SPA) and `backend/` (FastAPI + SQLAlchemy/Alembic, Python 3.11) with Supabase Postgres.

## Git — the user commits, never you

Dhanush handles all git commits and pushes himself. **Never run `git commit`,
`git push`, or stage files, and never ask whether he wants you to.** Leave
finished work in the working tree and say what changed; he takes it from there.
Read-only git (`status`, `diff`, `log`, `show`) is fine and useful.

## Deployment (push to main auto-deploys)

- Pushing to `main` triggers **both** deploys automatically: Vercel rebuilds the frontend, Render rebuilds the backend Docker image. Never push half-finished work to main.
- Render free tier spins down after 15 min idle; first request takes ~30 s (frontend's `BackendKeepAlive` pings `/health` every 9 min).
- All secrets live in Render/Vercel dashboard env settings, never in committed files. `.env` files and `HOSTING_GUIDE.md` (live URLs/project IDs) are deliberately gitignored.

## ML models — committed to git on purpose

- `backend/ml/models/*.joblib` (29 cities + `metadata.json`) **must stay in git** — Render's Docker build COPYs them into the image; no training happens at deploy time.
- Retraining (local, every 3–6 months): `python sync_csv.py` (pulls new rows from Supabase into `data/aqi_india_enriched.csv`; needs `SUPABASE_DATABASE_URL` in root `.env`), then `python train_for_deploy.py`, then commit + push `backend/ml/models/`.
- `backend/train_models.py` is the *in-container* variant (hardcoded `/app/...` paths) — use `train_for_deploy.py` from the repo root on Windows.
- The training CSV (`data/*.csv`, ~220 MB) is gitignored.

## Local development

- `docker-compose up --build` — non-standard local ports: frontend **5174**, backend **8001**, Postgres **5434**.
- Backend container startup runs `alembic upgrade head` + `seed_cities.py` automatically.
- Frontend-only dev: `npm run dev` in `frontend/` (Vite, port 5173, `/api` proxied via `vite.config.js`).
- API docs: `http://localhost:8001/docs`.

## Lint

- Backend: `python -m ruff check backend` (config in `backend/ruff.toml`; E701/E402/E711/E712 are deliberately ignored to match codebase style — one-liner ifs, dotenv-before-import scripts, SQLAlchemy `== None` filters).
- Frontend: `npm run lint --prefix frontend` (config in `frontend/.eslintrc.cjs`).
- A PostToolUse hook (`.claude/hooks/lint-on-edit.py`) auto-lints every edited file and reports leftovers — fix them when it does.

## Gotchas

- `DATABASE_URL` must be the Supabase **Session pooler** URI (host ends in `pooler.supabase.com`), not the direct connection string.
- `ALLOWED_ORIGINS` env var is a JSON array string, not comma-separated.
- SMTP uses a Gmail **App Password** (16 chars), not the account password.
- No tests exist yet (`backend/tests/` is empty; pytest is in requirements.txt).
- On startup the backend self-heals stale data: if newest AQI row is >2 h old it backfills from archive APIs (`app/main.py` lifespan hook); APScheduler then runs the hourly pipeline, 30-min alert checks, and nightly 90-day cleanup (`app/scheduler.py`).

## Project isolation — stay inside this folder

Work only within `deploy_breathesafe`. Do not read, write, list, or reason about the user's other projects, other project memory folders, or unrelated folders on this machine — the user has other work on this drive that is deliberately out of scope, and this project must never touch it.

- Never `cd` above the repo root; never resolve paths outside it.
- If a task genuinely cannot be completed without going outside this folder, **stop and ask first**, explaining exactly which path is needed and why. Do not proceed on your own judgement.
- `.env` and `HOSTING_GUIDE.md` hold live secrets and URLs. Don't open them unless asked; say so first if a value is genuinely needed.
- Enforcement lives in `.claude/settings.local.json` (deny rules). Those rules are a safety net, not the reason to behave — treat the boundary as real even where a rule doesn't happen to cover it.

## Session continuity — the work log

`.claude/WORKLOG.md` is this project's memory across terminals. A `SessionStart` hook loads it automatically, so each new session continues the previous one rather than starting cold.

- **Read it as continuing conversation**, not as a briefing document. The user should never have to re-explain context already captured there.
- **Update it as you go** — after any meaningful decision, change, or discovery, add to the newest entry at the top. Don't wait to be asked, and don't wait until the end of a session.
- Record decisions + state + open threads, and the *why* behind them. Skip routine edits.
- Convert relative dates to absolute ones. Flag stale claims rather than trusting them — verify against current code before asserting anything from the log as fact.
- It's gitignored and local-only, so it never rides along on a deploy.
