# CLAUDE.md — Agent Brief (read me first)

> **For any AI agent or model working on this repo (Claude Opus 4.8/4.6, Claude Sonnet,
> Gemini, etc.):** this file is the single source of truth for the *current* strategy,
> results, and deployment. It supersedes any older numbers in `README.md` or in code
> comments. Read this before changing the backtester or the strategy. Strategy
> numbers last updated **2026-06-22**. Deployment section updated **2026-09-22**
> (Render + GitHub Actions; §1 numbers unchanged).

---

## 1. Current production strategy & results (THE numbers)

**Strategy:** `BacktestEngine.run_optimized_regime_backtest` in
[`src/backtester/engine.py`](src/backtester/engine.py). It is the *single* production
strategy, driven by [`run_backtest.py`](run_backtest.py) (CLI/validation) and
[`run_dashboard.py`](run_dashboard.py) (deployed app). Both call it with identical params.

**20-year backtest (2005-01 → 2026-06), net of 5 bps tx + 1% leverage financing,
NO LOOK-AHEAD (macro signals lagged to their real release dates):**

**8-ETF portfolio (v5.1):** QQQ, SOXX, SPY, SPYI, TLT, GLD, DBMF, URA.

| Metric | Result | Target | Status |
|---|--:|--:|:--:|
| CAGR | **14.52%** | 16.0% | ❌ |
| Max Drawdown | **14.78%** | < 14.8% | ✅ |
| Sharpe | **0.97** | 1.2 | ❌ |
| Volatility | 13.00% | ~11.8% | — |
| Sortino | 1.30 | — | — |
| Calmar | 0.98 | — | — |
| Total Return | 1,730% | — | — |

> **Data-pipeline correction (Gemini audit, 2026-06-27).** Headline updated
> 14.68%/0.99 → **14.52%/0.97** on data through 2026-06-26. Two real bugs in the
> fresh-download path were fixed (a broken download had been giving 13.57%):
> (1) **SHY & AGG were missing** from `ALL_TICKERS`, collapsing the defense basket
> `{SHY,AGG,GLD,TLT}` to GLD+TLT; (2) **CADUSD=X / .TO holiday rows** (5399→5601 days)
> diluted rolling vol via forward-filled flat returns. Fix added SHY/AGG and reindexes
> to SPY's US trading calendar (`run_backtest.py`). The 14.52 vs 14.68 residual is the
> 5 extra market days (Jun 22–26); MaxDD still 14.78% (PASS). Verified by clean run.

> **⚠️ Honest-timing correction (Gemini audit, 2026-06-22).** The earlier headline
> **15.85% / 14.76% / 1.21 contained look-ahead bias**: FRED dates CPI/GDP at the
> period *start*, but the figures aren't released for weeks/months. Lagging the macro
> signals to their actual release dates (CPI +1mo, GDP +4mo) gives the truthful,
> tradable number — currently **14.52% / 14.78% / 0.97** (8-ETF v5.1, data thru 2026-06-26;
> see the data-pipeline correction note above). The DD target is
> met; CAGR/Sharpe fall short of 16/1.2. Still beats SPY (10.9% / 0.48 / 55% DD) and
> 60/40 (8.2% / 0.55) handily. Do not revert the lag to "restore" the targets.

**Production config (do not silently change — these are the validated values):**
```python
risk_parity=True, rp_vol_lookback=60,
target_vol=0.130, vol_lookback=21, vol_lo=0.50, vol_hi=1.50,
bear_equity_frac=0.70, dd_trigger=0.07,        # v5.1 (8-ETF)
transaction_cost_bps=5.0, borrow_spread=0.01,
vix_data=vix, vix_gate_level=20.0,   # zeroes TQQQ/SOXL when yesterday's VIX >= 20
vol_method='realized', use_har_vol=True, # HAR-RV vol overlay engaged
# macro publication lag (in run_backtest.py / run_dashboard.py): CPI +1mo, GDP +4mo
```

## 2. What changed and WHY (do not revert)

This replaced the old `run_vol_targeted_regime_backtest` (13.18% / 19.58% / 0.75). Two
root causes were fixed — **do not reintroduce them:**

1. **Wrong vol proxy (the big bug).** The old method scaled the *entire multi-asset
   portfolio by SPY's* volatility. In defensive regimes the book is bonds/gold, so it
   levered bond books in calm markets and de-risked bonds/gold in crises — backwards.
   **Fix:** portfolio-level vol targeting on the strategy's *own* realised vol.
2. **Stacked, fighting overlays** (bear hedge + asymmetric vol scaling + DD breaker)
   that cut CAGR ~23%→13% while barely helping DD. **Fix:** one clean trend hedge +
   portfolio vol target + DD breaker.

The Sharpe gap (1.11 → 1.21) was then closed by **risk-parity (inverse-vol) sleeve
weighting** (`risk_parity=True`): it cuts the regime book's vol 18.9%→9.6%, and the vol
target levers that low-vol book back up — capturing diversification as Sharpe.

A **managed-futures (CTA) proxy** was prototyped and **deliberately left OFF**
(`mf_alloc=0.0`): standalone Sharpe 0.41 and +0.28 correlated with the regime book, so it
never improved risk-adjusted returns in this ETF universe. It is exposed as an optional
knob (`mf_alloc`, `mf_assets`) for a future universe that includes FX/rates futures.

**Vol-estimator A/B (2026, `ab_vol.py`): EWMA and HAR-RV are Sharpe-NEUTRAL vs the simple
21-day realised vol** (Sharpe ties ~0.99–1.03). HAR forecasts lower vol so the strategy
runs hotter (higher CAGR + higher vol at equal Sharpe). **v5.1 deliberately engages HAR
(`use_har_vol=True`)** — with the tuned overlays (`bear=0.70`, `dd=0.07`) it pushes MaxDD
to **14.78% (meets the <14.8% target)** while holding CAGR ~14.7%. This is a DD-constraint
choice, not a Sharpe win; EWMA was tested and dropped. Don't re-litigate the Sharpe question.

### Myth corrected
The earlier claim that "16/14.8/1.2 is mathematically infeasible because of the March
2020 COVID crash" is **false**. In every viable variant **2020 is a positive year**
(+20%). The binding drawdown is **2022** (joint stock+bond selloff), not COVID; 2008 is
**+21%**. A daily DD breaker + daily trend filter engage intra-month regardless of the
monthly rebalance.

## 3. Deployment

**Host: Render Docker web service, deployed by GitHub Actions.** Step-by-step
clicks are in [`docs/DEPLOY_RENDER.md`](docs/DEPLOY_RENDER.md). GitHub Pages is
not part of this path — Dash is a long-running process.

Google Cloud Run, the GCS bucket `montesfund-etf-dashboard-data`, and Cloud
Scheduler job `etf-daily-refresh` are **legacy**. Leave them in place until the
Render URL is serving traffic, then tear them down by hand. This repo does not
delete GCP resources. `src/dashboard/gcs_sync.py` still talks to GCS when
`GCS_BUCKET` is set, and is a no-op otherwise. The Render Blueprint does not set it.

- **App:** Plotly Dash in `run_dashboard.py` (+ `src/dashboard/`), image from
  [`Dockerfile`](Dockerfile). It calls `run_optimized_regime_backtest` at all 4
  sites — **the deployed app matches the config in §1.** If you change the
  production config, update **both** `run_backtest.py` and the 4 call sites in
  `run_dashboard.py`.
- **Process:** Render sets `PORT` (default 10000). The process binds
  `0.0.0.0:$PORT`. Readiness probe is `GET /healthz` (200). Local runs with
  `PORT` unset still use 8050.
- **Ship path:** [`render.yaml`](render.yaml) defines the web service (free
  instance, Docker, `healthCheckPath: /healthz`, `autoDeployTrigger: off`).
  [`.github/workflows/deploy-render.yml`](.github/workflows/deploy-render.yml)
  runs on push to `main` and `POST`s the Render deploy hook
  (`RENDER_DEPLOY_HOOK_URL`). Render builds the Dockerfile. The workflow does
  not build a second image. Auto-deploy is off so a push produces one build.
- **Public URL:** `https://fontesfund-dashboard.onrender.com`, unless that
  hostname is already taken — then use the `onrender.com` URL shown on the
  service page.
- **What the cold start shows:** `data/backtest_results/*.csv` is in git and is
  copied into the image. `data/cache/*` (prices, macro, IBKR snapshot) is
  gitignored, so a fresh instance does not have those files. Regime/backtest
  tabs still render from the committed result CSVs.
- **Refresh:** `POST /tasks/refresh` with header `X-Refresh-Token` runs
  `run_backtest.py` inside the container.
  [`.github/workflows/refresh-dashboard.yml`](.github/workflows/refresh-dashboard.yml)
  calls it weekdays at 11:00 UTC (the old scheduler clock). On the free
  instance the disk is ephemeral and the process sleeps after 15 idle minutes,
  which drops those writes. The next cold start shows the image-baked CSVs
  again. A durable update is `python run_backtest.py` wherever you have the
  RAM, then commit the regenerated `data/backtest_results/*.csv` and push so
  the deploy workflow rebuilds the image. Free instances cannot attach a
  persistent disk, so the Blueprint does not define one.
- **RAM:** Free and Starter are both 512 MB. The Blueprint sets
  `FINBERT_ENABLED=0` (display-only lexicon sentiment) and
  `DISABLE_STARTUP_REFRESH=1` so boot does not load FinBERT or spawn a
  backtest. If the process is still killed for memory, change `plan: free` to
  `plan: standard` (2 GB) and you can set `FINBERT_ENABLED=1`. Starter does
  not add RAM.
- **Secrets:** `FRED_API_KEY` is read from the environment (`config/settings.py`;
  no hardcoded key). On Render, set `FRED_API_KEY`, `FINNHUB_API_KEY`, and
  `REFRESH_TOKEN` in the service env (the Blueprint prompts). GitHub Actions
  secrets, exact names: `RENDER_DEPLOY_HOOK_URL`, `DASHBOARD_URL`,
  `REFRESH_TOKEN` (same token as the Render env). The old FRED key (`534c2e45…`)
  and the `REFRESH_TOKEN` that leaked into a gcloud log still need rotation on
  any host where they remain.
- **Startup fragility:** the Dash layout is built before the port opens. A crash
  in a `build_*_tab` fails the health check (Render waits up to 15 minutes).
  Render-test a tab offline before deploying UI changes (see the `_row`-shadowing
  incident, 2026-07-05).
- **Reproduce:** `python run_backtest.py` (full engine, ~30s). Fast parameter
  exploration: `python optimize_strategy.py` and `python extend_rp_mf.py`
  (vectorized harnesses, <2s; same data/regime logic as production).
  Production-faithful variant A/B: `ab_universe.py`.

## 4. Data integrity (known issues — fix before live trading)

- Cache `data/cache/price_data.csv` has **20 of 22** tickers — **SSO and MOAT are
  silently missing** but appear in `REGIME_WEIGHTS`; weights renormalise away, so the
  *documented* allocation ≠ the *tested* one. The cache-load path never re-downloads them.
- `run_regime_backtest` (the "upper bound" reference only) parks weight in not-yet-listed
  ETFs (QQQI 2024, SPYI 2022, DBMF 2019…) as phantom cash → understates it (~20% vs true
  ~23%). The production method handles per-date availability correctly.
- Limited-history ETFs make the early backtest structurally different from the late one;
  treat cross-era comparisons with care.

### Gemini audit fixes (2026-06-22) — all applied
- **Macro look-ahead removed** (the big one): CPI/GDP signals lagged to release dates in
  `run_backtest.py` + `run_dashboard.py`. Headline 15.85%→13.82% (see §1).
- **VIX gate ported to production**: `run_optimized_regime_backtest` now zeroes TQQQ/SOXL
  and redirects to QQQ/SOXX when yesterday's VIX ≥ 20 (`vix_data`/`vix_gate_level` params).
  Previously only the legacy `run_protected_regime_backtest` had it.
- **`PERFORMANCE_TARGETS` corrected** to the validated 16%/14.8%/1.2 (was 17%/10%/1.8).
- **`GGLL` removed** entirely from the ETF universe (`etf_universe.py`, `LEVERAGED_RULES`).
- **SQLiteCache deleted** from `data_collector.py` — it was dead code (never used at
  runtime; the CSV/pickle caches are the source of truth, and SQLite-on-disk gives no
  cross-instance benefit on ephemeral Cloud Run). Replaced by a tiny in-memory cache that
  preserves the `MacroDataCollector` interface; `data/db/` removed.

### AI-trend ETFs added to the strategy (2026-06-22)
**SMH** (VanEck semis), **DRAM** (AI memory/HBM), **XSD** (equal-weight semis) added to
`REGIME_WEIGHTS` (goldilocks + reflation) and the price cache — so every ETF shown in the
dashboard's AI Trend signal table is now actually traded by the strategy, not just
monitored. Impact is ~neutral (13.82%→13.72%; SMH overlaps SOXX, risk-parity rebalances by
inverse-vol). DRAM has short history (lists Apr-2026) so it only contributes recently.

### Live IBKR account integration in the Execution tab (2026-06-25)
The Execution tab now shows the **real IBKR account** (paper `DUQ963925`, repointable to the
live account later), not just a simulated/offline broker view. The hosted container
(Render, and the legacy Cloud Run service) cannot reach the local TWS socket, so the
bridge is a **snapshot file**:
- `scripts/ibkr_snapshot.py` (read-only; run locally with TWS up) writes
  `data/cache/ibkr_account.json` (+ `ibkr_equity_history.csv`): NAV, positions, weights, P&L,
  TWR. Works for the paper account now and the real account later (`--allow-live` guards non-`DU`).
- `build_ibkr_live_panel()` in `src/dashboard/app.py` reads that JSON and renders a
  **live-vs-target drift / tracking analysis** (active-share), an NAV-since-inception curve,
  and headline NAV/P&L/TWR cards. Falls back to a "run the snapshot script" hint if absent.
- **To refresh:** rerun `python scripts/ibkr_snapshot.py`. The Execution tab reads
  `data/cache/ibkr_account.json` off the container disk. That directory is gitignored,
  so a Render rebuild includes a new snapshot only if the file is force-added before
  the deploy. A GCS push still runs when `GCS_BUCKET` is set; the Render Blueprint
  leaves that variable unset.
- ⚠️ Account base currency is **CAD** while the 8 ETFs are **USD** → IBKR auto-financed the USD
  buys with a USD margin loan (displayed leverage ~1.37). This is a currency-financing artifact,
  not strategy leverage; surfaced in the panel's note. To remove it, convert CAD→USD in TWS first.

## 5. File map

| Path | Role |
|---|---|
| `src/backtester/engine.py` | `run_optimized_regime_backtest` = **production strategy** |
| `scripts/ibkr_snapshot.py` | Read-only IBKR snapshot → `data/cache/ibkr_account.json` (Execution tab) |
| `scripts/ibkr_rebalance.py` | Local paper/live rebalance to current regime weights (`--execute`) |
| `run_backtest.py` | CLI 20-yr validation; regenerates result CSVs |
| `run_dashboard.py` | Deployed Dash app (Render); calls the production method |
| `render.yaml` | Render Blueprint: Docker web service, health check, env vars |
| `.github/workflows/deploy-render.yml` | Push to `main` → Render deploy hook |
| `.github/workflows/refresh-dashboard.yml` | Weekday 11:00 UTC `POST /tasks/refresh` |
| `docs/DEPLOY_RENDER.md` | One-time Render + GitHub secret checklist |
| `config/regime_rules.py` | `REGIME_WEIGHTS`, risk limits, targets |
| `optimize_strategy.py`, `extend_rp_mf.py` | Vectorized research harnesses (RP + MF prototypes) |
| `RECOMMENDATION.md` | Full audit write-up & handoff (more detail than this file) |
| `data/backtest_results/*.csv` | Cached results consumed by the dashboard |
