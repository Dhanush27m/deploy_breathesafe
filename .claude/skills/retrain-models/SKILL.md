---
name: retrain-models
description: Retrain the per-city XGBoost AQI forecast models on fresh data and ship them. Run when forecasts degrade or every 3-6 months.
disable-model-invocation: true
---

Retrain BreatheSafe's ML models locally and deploy them. Models are pre-trained and committed to git — Render never trains.

All commands run from the repo root (`deploy_breathesafe/`).

1. **Sync fresh data from Supabase into the training CSV:**
   ```
   python sync_csv.py --dry-run   # preview how many new rows
   python sync_csv.py             # append them to data/aqi_india_enriched.csv
   ```
   Requires `SUPABASE_DATABASE_URL` in the root `.env`. If it fails with a connection error, the URL must be the Supabase Session pooler URI.

2. **Train (takes a while — 29 cities):**
   ```
   python train_for_deploy.py
   ```
   Do NOT use `backend/train_models.py` here — that variant has hardcoded `/app/...` container paths.

3. **Verify before committing:** check `backend/ml/models/metadata.json` — training date should be today, and compare per-city MAE against the previous values (warn the user if any city got significantly worse).

4. **Ship:**
   ```
   git add backend/ml/models/
   git commit -m "retrain models on data through <latest-date>"
   git push
   ```
   The push auto-deploys Render, which COPYs the new `.joblib` files into the Docker image. Afterwards run `/deploy-check` to confirm the backend redeployed cleanly.
