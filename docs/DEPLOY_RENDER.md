# Deploy the dashboard on Render

The Dash app (`run_dashboard.py`) runs as a Docker web service on Render.
GitHub Actions tells Render when to build. **GitHub Pages is not used** and
must stay disabled — Pages cannot run this process.

Google Cloud Run, the bucket `montesfund-etf-dashboard-data`, and Cloud
Scheduler are legacy. Leave them until this URL works, then delete them
yourself. Nothing in this repo deletes GCP resources.

## URL

Blueprint service name: `fontesfund-dashboard`.

Usual public URL:

`https://fontesfund-dashboard.onrender.com`

If that hostname is already taken, Render assigns a different
`*.onrender.com` name. Use the URL on the service page. Health check:

`GET /healthz` → `{"ok": true, "service": "fontesfund-dashboard"}`

## One-time checklist

Do these after this change is on `main`. The Blueprint field `branch: main`
builds that branch.

1. Create a Render account at https://render.com (Hobby workspace). A card is
   not required for a free web service.
2. In the Render Dashboard choose **New → Blueprint**.
3. Connect GitHub and select `fintechshan/FontesFund`. Apply `render.yaml`.
4. When Render prompts for environment variables, set them with these exact
   names:
   - `FRED_API_KEY` — https://fred.stlouisfed.org/docs/api/api_key.html
   - `FINNHUB_API_KEY` — https://finnhub.io/register (the site still serves
     baked results if this is a placeholder)
   - `REFRESH_TOKEN` — a long random string you generate. You will paste the
     same value into GitHub in step 7.
5. Apply the Blueprint. Render builds the `Dockerfile` and deploys once.
   The first build downloads CPU PyTorch and FinBERT and often takes 15
   minutes or longer. Open the service **Events** page and wait until the
   deploy is live.
6. Copy the deploy hook: service **Settings → Deploy Hook**.
7. In GitHub, open `fintechshan/FontesFund` → **Settings → Secrets and
   variables → Actions → New repository secret**. Create these exact names:

   | Secret | Value |
   |---|---|
   | `RENDER_DEPLOY_HOOK_URL` | The deploy hook URL from step 6 |
   | `DASHBOARD_URL` | `https://fontesfund-dashboard.onrender.com` (no trailing slash; use the hostname Render actually assigned) |
   | `REFRESH_TOKEN` | The same string you set on the Render service |

8. GitHub → **Actions → Deploy to Render → Run workflow**. That is the ongoing
   deploy path. `render.yaml` sets `autoDeployTrigger: off`, so a later push
   to `main` deploys only through this workflow.
9. Confirm `https://<your-host>.onrender.com/healthz` returns JSON, then open
   `/` and check the Regime, Portfolio, and Backtest tabs.
10. Do **not** enable GitHub Pages.

The merge that adds these workflow files will run **Deploy to Render** once
before the hook secret exists. That run fails on purpose. Re-run it after
step 7.

## What Render sets for you

From `render.yaml`, not typed by hand:

| Variable | Value | Why |
|---|---|---|
| `DISABLE_STARTUP_REFRESH` | `1` | Boot must not spawn `run_backtest.py` on 512 MB |
| `FINBERT_ENABLED` | `0` | Lexicon sentiment; the FinBERT weights stay in the image and are not loaded |
| `ENABLE_IBKR` | `0` | Execution tab stays suspended |
| `PYTHONUNBUFFERED` | `1` | Logs flush to the Render dashboard |
| `PORT` | `10000` (Render default) | `run_dashboard.py` binds `0.0.0.0:$PORT` |

Leave `GCS_BUCKET` unset.

## Refresh

`.github/workflows/refresh-dashboard.yml` runs weekdays at 11:00 UTC (the old
Cloud Scheduler time) and `POST`s `/tasks/refresh` with header
`X-Refresh-Token`. You can also run that workflow by hand from the Actions tab.

Free-instance tradeoff, stated plainly:

- The free service sleeps after 15 minutes without requests. Sleep, restart,
  and the next deploy all drop files written inside the container.
- A successful `/tasks/refresh` updates the **running** process only.
- After the next cold start the site shows `data/backtest_results/*.csv` from
  the image again. Those CSVs are in git. `data/cache/` (prices and macro) is
  gitignored, so a cold start has the committed backtest tables and no fresh
  price cache.
- To publish new results that survive sleep: run `python run_backtest.py` on a
  machine with enough RAM, commit the updated files under
  `data/backtest_results/`, and push to `main`. The deploy workflow rebuilds
  the image with those files inside it.

Free and Starter are both **512 MB** RAM and **0.1 / 0.5 CPU**. Starter does
not fix an out-of-memory kill. If Events or the logs show the process was
killed, change `plan: free` to `plan: standard` (2 GB / 1 CPU) in `render.yaml`
and redeploy. On that plan you can set `FINBERT_ENABLED=1`.

`/tasks/refresh` itself runs the full backtest inside the web process. On
512 MB that call can be killed. The weekday workflow will then fail, and the
site keeps serving the baked CSVs.

## Legacy Google Cloud (do not require for this path)

| Old piece | Role it had | Now |
|---|---|---|
| Cloud Run service | Hosted `run_dashboard.py` | Replaced by the Render web service |
| GCS bucket `montesfund-etf-dashboard-data` | Survived scale-to-zero | Unused unless you set `GCS_BUCKET` |
| Cloud Scheduler `etf-daily-refresh` | `POST /tasks/refresh` at 11:00 UTC | Replaced by `refresh-dashboard.yml` |
| `.gcloudignore` | Cloud Build upload filter | Unused by Render |

`src/dashboard/gcs_sync.py` remains so an existing Cloud Run revision keeps
working until you remove it. Rotate the FRED key and `REFRESH_TOKEN` that were
exposed in a gcloud log before you rely on them anywhere else.
