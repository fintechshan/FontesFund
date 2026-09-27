# CLAUDE.md — Agent Brief (read me first)

> **For any AI agent or model working on this repo (Claude Opus 4.8/4.6, Claude Sonnet,
> Gemini, etc.):** this file is the single source of truth for the *current* strategy,
> results, and deployment. It supersedes any older numbers in `README.md` or in code
> comments. Read this before changing the backtester or the strategy. Last updated
> **2026-09-27** (targeted fix is the default: CPI+1 / GDP+4, no month-end look-ahead).

---

## 1. Current production strategy & results (THE numbers)

**Strategy:** `BacktestEngine.run_optimized_regime_backtest` in
[`src/backtester/engine.py`](src/backtester/engine.py). It is the *single* production
strategy, driven by [`run_backtest.py`](run_backtest.py) (CLI/validation) and
[`run_dashboard.py`](run_dashboard.py) (deployed app). Both call it with identical params.
The regime clock is [`src/backtester/regime_clock.py`](src/backtester/regime_clock.py),
mode `targeted`.

**Sample 2005-01-04 → 2026-09-25, net of 5 bps tx + 1% leverage financing.**
Risk-free rate is the mean of FRED DFF over that price window (**1.87%**), not the
full history back to the 1950s. Weights, `REGIME_WEIGHTS`, and live allocation stay
on the targeted path. The dashboard **display default** is the targeted fix.

The bug that produced the old **14.85%** headline was not the CPI+1 / GDP+4 offset.
Those offsets stay. The bug was stamping the full calendar month's average VIX and
the month-end SPY close onto month-start, so a rebalance on the 1st saw the rest of
that month. On this fresh Yahoo sample that old path prints **14.81%** (the published
14.85% was the same path through 2026-09-21). Removing only that stamp, and keeping
CPI+1 / GDP+4, is the targeted fix. An earlier note estimated ~13.36% CAGR; the
re-run below is **13.43%**. Do not hardcode the estimate.

| View | What it is | Where it shows | CAGR | MaxDD | Sharpe |
|---|---|---|--:|--:|--:|
| **Targeted fix (default)** | CPI+1 / GDP+4. VIX and SPY momentum dated on the month-end they describe, so the next month-start is the first time they are knowable | Backtest tab on first load, Portfolio CAGR card, CDN tab US column, `20yr_comparison.csv` | **13.43%** | **14.13%** | **0.93** |
| **Old production (month-end look-ahead)** | Same CPI+1 / GDP+4, but same-month VIX and momentum | Backtest radio, not the default | **14.81%** | **13.90%** | **1.03** |
| **Unlagged diagnostic** | Publication lag off, plus same-month market data | Backtest radio | **15.70%** | 14.58% | 1.11 |
| **Auditor extra month** | Old month-stamped regime, then one extra `regime.shift(1)` | Backtest radio. Overly conservative | **12.17%** | **14.10%** | **0.83** |
| **First-release vintage** | Philadelphia Fed RTDSM first prints of CPI and real GDP, dated on the mid-month vintage. No extra +1/+4. Market rule matches targeted | Backtest radio when the vintage table loads | **12.65%** | **15.23%** | **0.87** |

Targeted-fix detail: vol **12.41%**, Sortino **1.25**, Calmar **0.95**, total return
**1,438.39%**. Twelve of 256 months (4.7%) differ from the month-end look-ahead path.
Vintage detail: vol **12.35%**, Sortino **1.15**, Calmar **0.83**, total return
**1,225.00%**, source `philadelphia_fed_rtdsm` (not a fallback). Side-by-side file:
`data/backtest_results/lag_honesty.csv`.

The vintage path is lower than the targeted fix. That is the expected cost of using
the first print and the real release date instead of a revised final shoved by a
fixed offset. It is a comparison, not a new weight target. Do not shorten CPI+1 or
GDP+4 to chase the old 14.81% / 14.85% number, and do not put the extra Auditor month
back as the default. Turning the publication lag off is the unlagged diagnostic
(**15.70%**), which is look-ahead.

`fredapi` `get_series_first_release('GDPC1')`, `get_series_first_release('CPIAUCSL')`,
`get_series_all_releases`, and `get_series_as_of_date` are the refresh path when
`FRED_API_KEY` is set (`USE_REALTIME_VINTAGE=1`). With no key, the same flag downloads
Philadelphia Fed RTDSM workbooks `pcpiMvMd.xlsx` and `routputMvQd.xlsx`. A failed
refresh keeps `data/backtest_results/vintage_release_yoy.csv`. A one-row or collapsed
"latest print" file is rejected. Unit tests do not call the network.

**7-ETF portfolio (v7):** QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO.
Weights live in `REGIME_WEIGHTS`. Goldilocks QQQ **30%** is intentional AI-trend
exposure and is not clipped. The largest base weight is IEF **35%** (deflation).
`RISK_LIMITS.max_single_position` equals that maximum (`MAX_REGIME_WEIGHT`), so
both the 30% QQQ sleeve and the 35% IEF sleeve are inside the cap. VIX above `REGIME_VIX_DEFENSIVE`
(**30**) forces deflation. `vix_gate_level` 20 only zeroes TQQQ/SOXL; v7 holds neither,
so that gate is idle. The Goldman-style throttle is **off**.

**Production path** (engine, live weights, CSV, and the Backtest default — one series):

| Metric | Result | Target | Status |
|---|--:|--:|:--:|
| CAGR | **13.43%** | 16.0% | ❌ |
| Max Drawdown | **14.13%** | < 14.8% | ✅ |
| Sharpe | **0.93** | 1.2 | ❌ |
| Volatility | 12.41% | ~11.8% | — |
| Sortino | 1.25 | — | — |
| Calmar | 0.95 | — | — |
| Total Return | 1,438% | — | — |

Source: `data/backtest_results/20yr_comparison.csv`, row `Optimized Regime Strategy`.
Same file, same sample: SPY 10.95% / Sharpe 0.48 / 55.19% DD; 60/40 8.15% / 0.55 / 34.70% DD.
Regenerate with `python run_backtest.py`. The Backtest tab default is this row
(`pack_lagged_metrics`, path `targeted`). The monthly heatmap uses that same path's
monthly returns. It must not fall back to a different clock's file.

**CDN:** `scripts/run_cdn_backtest.py` has no extra-month run, so the CDN cards stay the
TSX production book. The US column and the bold US curve on that tab follow the targeted
fix when the US series is loaded. The dotted curve is the old month-end look-ahead path.

> **Historical — 8-ETF v5.1 (do not quote as current).** Sleeve was QQQ, SOXX, SPY,
> SPYI, TLT, GLD, DBMF, URA. Honest lagged headline through 2026-06-26 was
> **14.52% / 14.78% MaxDD / Sharpe 0.97**. The 2026-06-22 look-ahead correction
> (an earlier 15.85% / 1.21 used unpublished CPI/GDP dates) and the 2026-06-27
> SHY/AGG + US-calendar fix still describe how the engine is run. They are not
> the live v7 result.

**Production config (do not silently change — these are the validated overlay values):**
```python
risk_parity=True, rp_vol_lookback=60,
target_vol=0.130, vol_lookback=21, vol_lo=0.50, vol_hi=1.50,
bear_equity_frac=0.70, dd_trigger=0.07,  # overlay knobs; sleeve is v7
transaction_cost_bps=5.0, borrow_spread=0.01,
vix_data=vix, vix_gate_level=20.0,  # TQQQ/SOXL only; idle on v7
vol_method='realized', use_har_vol=True,
# publication lag: CPI +1mo, GDP +4mo (do not shorten)
# market timing: month-end VIX and SPY momentum, visible next month-start
# (mode='targeted'). Do not stamp those on month-start.
# regime VIX override: REGIME_VIX_DEFENSIVE = 30
# position cap: MAX_REGIME_WEIGHT (currently 0.35)
```

## 2. What changed and WHY (do not revert)

The CAGR and Sharpe figures in this section are the 2026-06 overlay history. The production
CSV headline is §1 (v7 targeted fix, 13.43% / 14.13% / 0.93). The old 14.85% / 13.90% / 1.03
row is the month-end look-ahead path (14.81% on the 2026-09-25 sample). The Auditor extra
month (12.17% on this sample; previously quoted 12.21%) is a comparison radio, not the default.

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

- **App:** the Plotly Dash dashboard in `run_dashboard.py` (+ `src/dashboard/`),
  containerised via [`Dockerfile`](Dockerfile), shipped to **Google Cloud Run**
  (see `.gcloudignore`). It now calls `run_optimized_regime_backtest` at all 4 sites —
  **the deployed app matches the config in §1.** If you change the production config,
  update **both** `run_backtest.py` and the 4 call sites in `run_dashboard.py`.
- **Auto-refresh architecture (2026-07, replaces "redeploy to refresh"):** the caches
  persist in GCS bucket `montesfund-etf-dashboard-data` (`src/dashboard/gcs_sync.py`).
  - *Backtest/regime data:* Cloud Scheduler job `etf-daily-refresh` (11:00 UTC daily)
    POSTs `/tasks/refresh` (token-protected, `REFRESH_TOKEN` env) → runs
    `run_backtest.py` in-container → uploads fresh CSVs/caches to GCS. Containers pull
    from GCS at startup (`download_data()`), so scale-to-zero no longer freezes data.
  - *IBKR account snapshot:* Windows task `ETF-IBKR-Snapshot` (daily 9:00 China time)
    runs `scripts/refresh_ibkr_snapshot.ps1` → `ibkr_snapshot.py` (needs TWS/Gateway UP,
    else fails cleanly without clobbering GCS) → pushes `ibkr_account.json` to GCS. The
    Execution tab **re-pulls from GCS every 10 min** (`ibkr-snapshot-refresh` interval →
    `download_ibkr()`), so new snapshots appear on the live site without a redeploy.
  - Manual refresh of results is still `python run_backtest.py` (~30s) + deploy, or just
    hit `/tasks/refresh`.
- **Live rebalance:** trade on CPI and GDP **advance release days**, and when VIX or
  momentum flips under the existing rules (VIX above 30 forces deflation; the daily
  trend hedge and drawdown breaker still run inside the book). The daily scheduler
  refresh updates caches and the dashboard. It does not place trades. Do not wait an
  extra Auditor month after the release. The live weight call is
  `classify_regimes(..., mode='targeted')`.
- **Reproduce:** `python run_backtest.py` (full engine, ~30s). Fast parameter
  exploration: `python optimize_strategy.py` and `python extend_rp_mf.py` (vectorized
  harnesses, <2s; same data/regime logic as production). Production-faithful variant
  A/B: `ab_universe.py`.
- **Secrets:** `config/settings.py` reads `FRED_API_KEY` from `.env`/env vars (hardcoded
  key removed 2026-06-27; the exposed key `534c2e45…` is set as a Cloud Run env var —
  **still needs rotation**, as does `REFRESH_TOKEN` which leaked into a gcloud log).
- **Startup fragility note:** the Dash layout is built eagerly at container start; a
  crash anywhere in a `build_*_tab` bricks the revision (probe timeout). Before deploying
  UI changes, render-test the tab offline (see the `_row`-shadowing incident, 2026-07-05).

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
The Execution tab previously referenced an IBKR paper trading account, which has been removed for public deployment. Because Cloud Run is stateless
and cannot reach the local TWS socket, the bridge is a **snapshot file**:
- `scripts/ibkr_snapshot.py` (read-only; run locally with TWS up) writes
  `data/cache/ibkr_account.json` (+ `ibkr_equity_history.csv`): NAV, positions, weights, P&L,
  TWR. Works for the paper account now and the real account later (`--allow-live` guards non-`DU`).
- `build_ibkr_live_panel()` in `src/dashboard/app.py` reads that JSON and renders a
  **live-vs-target drift / tracking analysis** (active-share), an NAV-since-inception curve,
  and headline NAV/P&L/TWR cards. Falls back to a "run the snapshot script" hint if absent.
- **To refresh:** rerun `python scripts/ibkr_snapshot.py` then redeploy (the JSON is baked into
  the image via `COPY . .`; it is NOT in `.gcloudignore`/`.dockerignore`).
- ⚠️ Account base currency is **CAD** while the 8 ETFs are **USD** → IBKR auto-financed the USD
  buys with a USD margin loan (displayed leverage ~1.37). This is a currency-financing artifact,
  not strategy leverage; surfaced in the panel's note. To remove it, convert CAD→USD in TWS first.

## 5. File map

| Path | Role |
|---|---|
| `src/backtester/engine.py` | `run_optimized_regime_backtest` = **production strategy** |
| `src/backtester/regime_clock.py` | Targeted clock (default), look-ahead / unlagged / auditor / first-release vintage |
| `scripts/compare_lag_honesty.py` | Side-by-side CAGR table → `data/backtest_results/lag_honesty.csv` |
| `scripts/ibkr_snapshot.py` | Read-only IBKR snapshot → `data/cache/ibkr_account.json` (Execution tab) |
| `scripts/ibkr_rebalance.py` | Local paper/live rebalance to current regime weights (`--execute`) |
| `run_backtest.py` | CLI 20-yr validation; regenerates result CSVs |
| `run_dashboard.py` | Deployed Dash app (Cloud Run); calls the production method |
| `config/regime_rules.py` | `REGIME_WEIGHTS`, risk limits, targets |
| `optimize_strategy.py`, `extend_rp_mf.py` | Vectorized research harnesses (RP + MF prototypes) |
| `RECOMMENDATION.md` | Full audit write-up & handoff (more detail than this file) |
| `data/backtest_results/*.csv` | Cached results consumed by the dashboard |
