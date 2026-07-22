---
name: deploy-check
description: Verify that the latest push to main deployed successfully on both Vercel (frontend) and Render (backend). Use after pushing to main, or when the user asks whether the deploy worked or why the live site is broken.
---

Pushing to `main` auto-deploys frontend to Vercel and backend to Render. Verify both:

1. Note the latest local commit: `git log -1 --oneline` and confirm it's pushed (`git status` shows up to date with origin/main).

2. **Vercel (frontend):** use the Vercel MCP tools — `list_deployments` for the breathesafe project, find the newest deployment, check its state matches the pushed commit SHA. If it errored, fetch `get_deployment_build_logs` and summarize the actual error lines (not the whole log).

3. **Render (backend):** if the Render MCP server is connected, check the latest deploy status and logs there. Otherwise fall back to probing the live API: `curl <backend-url>/health` (URL is in `HOSTING_GUIDE.md` locally or `frontend/.env` as `VITE_API_URL`). Remember Render free tier cold-starts: a first request can take ~30 s, so retry once after a timeout before declaring it down.

4. Report a simple verdict per service: deployed commit, status (✅/❌), and if failed, the root-cause error and the file/line to fix. Explain in simple terms what went wrong.

Common failure causes in this repo:
- Backend: a missing/renamed env var in Render settings, an Alembic migration error at startup (startup CMD runs `alembic upgrade head`), or missing `.joblib` model files not committed to git.
- Frontend: `VITE_API_URL` not set in Vercel env settings, or a build-time import error from Vite.
