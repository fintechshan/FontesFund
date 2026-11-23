# Cloud Run serving

The container listens with Gunicorn, not the Werkzeug development server.

```text
python -m gunicorn -c gunicorn.conf.py wsgi:server
```

`wsgi.py` only exports the application object. Routes live in `run_dashboard.register_routes`. Do not copy them into another module.

## Why this shape

`run_dashboard.py` used to call `app.run()` after the comparison clocks, the auditor, and the AI-trend fetch. Werkzeug's default is one thread, and the port opened only after that work. A client that gave up at 45 seconds saw a timeout. The next request, after the process was listening, returned in well under a second.

Gunicorn's master binds the port before the worker finishes booting. The worker answers `/healthz` while the Dash app is still loading. `/readyz` stays 503 until that app is mounted, so a startup probe does not send users at a half-built page.

Comparison clocks are the same targeted / look-ahead / unlagged / auditor / vintage stack. They run in a spawned child so the parent's health handler is not stuck on the GIL. The display-only AI fetch has its own child and a 45 second budget (`AI_TREND_TIMEOUT_SEC`). A miss leaves the AI panel empty. It does not change weights or the backtest. The portfolio tab's Yahoo quote fetch gives up after 8 seconds and leaves the price cells blank.

`preload_app` is false and `--preload` must not be added. Threads do not survive fork, and BLAS / tokenizer locks taken in the master deadlock the worker. With one worker, preload also has nothing to share.

The background thread starts once, from `post_worker_init`, after the fork. It sends the Hermes webhook if one is configured and logs when the price or macro cache is older than a day. It does not run `run_backtest.py`. That path skipped the headline gate and then recomputed the clocks inside the server process.

`/tasks/refresh` is unchanged in what it runs: `run_backtest.py` (540s), the headline gate, the US upload, CDN (300s), QQQ Vegas market and signal (180s each), risk flags (180s), and the IBKR snapshot only when `ENABLE_IBKR=1` (60s). A second call while one is in progress returns 409 `refresh_in_progress`. After a successful upload the process reloads the book from local disk (`sync_gcs=False`) and reruns the clock child. Gunicorn's worker timeout is 0 so a quiet subprocess does not kill the worker. The handler still returns 504 when a stage hits its own timeout.

## Startup download

`download_data` stops after `GCS_DOWNLOAD_BUDGET_SEC` (default 45) and each blob call uses `GCS_BLOB_TIMEOUT_SEC` (default 15). A local file newer than the bucket object is kept. That is how a newly built image keeps a corrected book when the bucket still has the previous upload. A newer bucket object is still the daily refresh and is downloaded. A new Cloud Run instance starts from the image, not from the previous container's disk.

## Settings to apply on deploy

Service `etf-regime-strategist`, region `asia-east2`. Deploy a new revision with `--no-traffic`, check the revision URL, then move traffic. The previous revision is the rollback target.

| Setting | Value | Why |
|---|---|---|
| Command | image `CMD` (gunicorn above) | Do not override with `python run_dashboard.py`. |
| CPU / memory | 1 / 2Gi | Unchanged. One worker fits this memory. |
| Startup CPU boost | on | Covers import and the clock child until `/readyz` is 200. |
| CPU throttling | leave the default (throttled when idle) | Heavy work is during startup boost or during the refresh request. `--no-cpu-throttling` is optional and not required for this process. |
| Min instances | **1** | The clock child is allowed 240s (`HONESTY_JOB_TIMEOUT_SEC`) before ready, plus layout build. That is longer than a 45s client timeout. Scale-to-zero makes the request that woke the instance wait for the startup probe. |
| Max instances | 20 is fine | Min 1 is the part that removes the cold start the timeouts matched. |
| Concurrency | **8** | Same as Gunicorn threads. 80 queues work this one CPU cannot answer. |
| Request timeout | **1800** | Stage caps sum to about 1665s without IBKR (540+300+180+180+180+240+45) and about 1725s with it. 900s can kill a stalled refresh before the handler returns 504. 1800 leaves a short margin. Cloud Run allows up to 3600. |
| Container port | 8080 | `$PORT` |

Startup probe (HTTP, not TCP):

- path `/readyz`
- port 8080
- periodSeconds 20
- timeoutSeconds 15 (must be less than the period)
- failureThreshold 30

That allows about 10 minutes for a slow clock child. `/readyz` returns 503 until the app is mounted and 200 after that, including during a later refresh.

Liveness probe:

- path `/healthz`
- port 8080
- periodSeconds 30
- timeoutSeconds 5
- failureThreshold 3

`/healthz` is 200 whenever the process can write the JSON, including `refreshing: true` and `comparison_clocks: running`. Do not point liveness at `/readyz` and do not treat `refreshing` as failure. A liveness failure restarts the container and drops the refresh.

Example (parent deploy; this repo does not run it):

```text
gcloud run deploy etf-regime-strategist \
  --region asia-east2 \
  --no-traffic \
  --min-instances 1 \
  --concurrency 8 \
  --timeout 1800 \
  --cpu-boost
```

Then set the startup and liveness probes (console or `gcloud run services update` with the probe flags the current gcloud accepts) and:

```text
gcloud run services update-traffic etf-regime-strategist \
  --region asia-east2 \
  --to-revisions NEW_REVISION=100
```

## Rollback

Send 100% of traffic back to the previous ready revision. The revision that was serving on 2026-11-23 was `etf-regime-strategist-00034-5jh`. Do not delete it before the new revision has answered `/healthz`, `/readyz`, `/`, and `/_dash-layout`.

```text
gcloud run services update-traffic etf-regime-strategist \
  --region asia-east2 \
  --to-revisions etf-regime-strategist-00034-5jh=100
```

## What a healthy body means

`/healthz` (always HTTP 200 when the process answers):

- `live: true` — the process handled the request
- `ready` — the Dash app is mounted
- `phase` — `booting`, `loading`, `clocks`, `serving`, or `failed`
- `comparison_clocks` — `pending`, `running`, `ready`, `failed`, or `skipped`
- `refreshing` — a gated refresh holds the single-flight lock
- `regime` — latest regime label once classification has run, otherwise `unknown`

`/readyz` returns that same JSON with HTTP 200 only when `ready` is true. Until then it is HTTP 503 and `ok` is false.

`comparison_clocks: failed` still allows ready. The page serves the published CSV book. It does not turn the headline gate off.
