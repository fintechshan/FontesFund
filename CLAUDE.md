# CLAUDE.md — Agent Brief (read me first)

> **For any AI agent or model working on this repo (Claude Opus 4.8/4.6, Claude Sonnet,
> Gemini, etc.):** this file is the single source of truth for the *current* strategy,
> results, and deployment. It supersedes any older numbers in `README.md` or in code
> comments. Read this before changing the backtester or the strategy. Last updated
> **2026-09-27** (method, not a frozen CAGR: targeted clock + the daily overlay).

---

## 1. Current production strategy & results (THE numbers)

**Do not paste a CAGR into this file.** Older write-ups froze 20.11%, 14.6%, 14.62%,
14.85%, 13.36%, and 12.21% from whatever cache was on disk that day. Those figures
drift. The method below is the source of truth. Each run writes its own metrics.

### Live book and backtest are one policy

`run_optimized_regime_backtest` is the only production engine
([`src/backtester/engine.py`](src/backtester/engine.py)). `run_backtest.py` and
`run_dashboard.py` call it with `STRATEGY_PARAMS`. The number it prints **includes
the daily overlay**. A calendar of “trade only on CPI/GDP days, or when monthly
VIX > 30” is not that strategy.

The daily overlay, exactly as coded in `src/backtester/daily_overlay.py`. It is
mandatory on the headline path. Live orders apply the same stack:

1. **200-day trend.** Yesterday’s SPY versus yesterday’s 200-day average. If SPY is
   below it, keep `bear_equity_frac` (0.70) of the regime sleeve and move the rest
   to the defense basket.
2. **Equity de-risk.** Yesterday’s VIX scales risk assets linearly from 28 (full
   equity) to 40 (zero equity). SPY versus its trailing 20-session high, window
   ending yesterday, scales risk assets from a 4% drawdown (full) to 10% (zero).
   The tighter scale wins. Freed weight goes to SHY / AGG / GLD / IEF. This cut
   is not a second CPI or GDP lag, and it is not the monthly VIX>30 deflation label.
3. **Portfolio vol target.** `scale = clip(target_vol / lagged own vol, vol_lo, vol_hi)`
   with target 13%, band 0.50–1.50. Production uses the HAR-RV forecast
   (`use_har_vol=True`). The scale uses yesterday’s forecast.
4. **Portfolio drawdown shrink.** If strategy equity is more than `dd_trigger` (7%)
   below its own peak, exposure falls toward `dd_floor` (10%) over a further
   `dd_span` (10%).

`scripts/ibkr_rebalance.py` runs that same engine and sends the last day’s
`result.overlay` (trend blend, then the equity cut, then vol scale × drawdown
scale). Gross exposure can differ from 100%. That is the backtest’s leverage.
The daily scheduler refresh updates caches. It does not send orders.

CPI and GDP **advance** release days, and a VIX or momentum flip, change the
**monthly sleeve only**. They do not turn the daily overlay off. Do not wait an
extra Auditor month. An event-only calendar is not a live mode. It would need
its own backtest and its own metrics before anyone quoted it.

The monthly regime (Merrill clock, CPI+1 / GDP+4, prior-month VIX mean and
SPY momentum) and this daily overlay are both part of the headline. The regime
picks the sleeve. The overlay changes exposure every day.

### Clock (口径)

Regime clock: [`src/backtester/regime_clock.py`](src/backtester/regime_clock.py).
Dashboard default path id: `targeted`.

| Path | Rule | Default? |
|---|---|---|
| **B targeted** | Revised CPI and GDP. CPI **+1 month**, GDP **+4 months**. VIX monthly mean and SPY 12-month momentum each lagged one month (`resample('ME')`, same as month-start `shift(1)`). The market lag is not applied again to CPI or GDP. | Yes |
| **A lookahead** | Same CPI+1 / GDP+4, but VIX and momentum stamped on month-start, so the 1st sees the rest of that month. | Radio only |
| **Unlagged** | Publication lag off, plus same-month market data. | Radio only |
| **Auditor extra month** | Path A, then one more `regime.shift(1)`. Overly conservative. | Radio only |
| **C vintage** | First release of CPI and real GDP on the release date. No extra +1/+4. Market rule matches B. | Radio only |

GDP dated on the quarter start plus 4 months is the advance-release timing. Do not
shorten either lag. Do not replace the clock with GDPNow or WEI.

C should sit at or below B. If C is far above B, the release date is probably
aligned backwards. With `FRED_API_KEY`, C is fredapi
`get_series_first_release` / `get_series_all_releases` / `get_series_as_of_date`
for `GDPC1`, `CPIAUCSL`, and `CPIAUCNS` (NSA; better YoY with a first print).
Without a key, C is the Philadelphia Fed RTDSM monthly vintage
(`pcpiMvMd`, `routputMvQd`), and the NSA row is **not run**. A failed refresh
keeps `data/backtest_results/vintage_release_yoy.csv`. A table with fewer than
24 releases is rejected. Unit tests do not call the network.

`python scripts/ab_vintage.py` writes the latest A/B/C table, the common-inception
row, sleeve coverage, and publication-lag percentiles. Read those files. Do not
copy the cells back into this brief.

### Missing history

The engine drops a ticker with no prior-day price and **renormalizes** the sleeve.
It does not park the missing weight in cash. Live still holds DBMF and AIPO where
the regime table says so (DBMF is 25% in reflation and stagflation). On a long
window most of the sample never held them. `coverage_windows.csv` records the
fraction of the price index each name actually prints. The common-inception row
in `lag_honesty.csv` starts on the first day every live sleeve name has a print.
That window is short. It is not a substitute for the full-sample path, and the
full-sample path is not “the live book held AIPO for 20 years.”

Risk-free rate in the engine is the mean of FRED DFF over the **price window**,
not the full history back to the 1950s. Costs: 5 bp turnover and 1% borrow spread
on gross exposure above 1.

**7-ETF portfolio (v7):** QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO.
Weights live in `REGIME_WEIGHTS`. Goldilocks QQQ **30%** is intentional AI-trend
exposure and is not clipped. The largest base weight is IEF **35%** (deflation).
`RISK_LIMITS.max_single_position` equals that maximum (`MAX_REGIME_WEIGHT`), so
both the 30% QQQ sleeve and the 35% IEF sleeve are inside the cap. VIX above `REGIME_VIX_DEFENSIVE`
(**30**) forces deflation. `vix_gate_level` 20 only zeroes TQQQ/SOXL; v7 holds neither,
so that gate is idle. The Goldman-style throttle is **off**.

**Where a run stores numbers** (regenerate; do not treat a stale cell as the target):

| File | What a fresh run puts there |
|---|---|
| `data/backtest_results/20yr_comparison.csv` | `python run_backtest.py`. Row `Optimized Regime Strategy` is path B, daily overlay included. |
| `data/backtest_results/lag_honesty.csv` | `python scripts/ab_vintage.py`. Rows A, B, C, and B from common inception. |
| `data/backtest_results/coverage_windows.csv` | Share of the price index each sleeve name actually prints. |
| `data/backtest_results/vintage_publication_lags.csv` | p10 / median / p90 days from period-end to first vintage. |
| `data/cache/vintage_*.csv` | YoY series used to build C. Gitignored. |

The Backtest tab, the Portfolio CAGR card, and the CDN US column display path B
from that run (`pack_lagged_metrics`, path `targeted`). Switching the Backtest
radio changes the CAGR cards, the equity curve, and the monthly heatmap together.
The heatmap is the month-end change of the curve on screen. It does not keep a
production monthly file under another path’s cards. Targets remain 16% CAGR, max drawdown under 14.8%, Sharpe
1.2. Whether the latest run meets them is the CSV’s job, not a sentence in this file.

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

The CAGR and Sharpe figures in this section are the 2026-06 overlay history. They are
not the current headline. The current headline is whatever `run_backtest.py` last wrote
for path B (targeted clock + daily overlay). Path A (month-end look-ahead) and the
Auditor extra month are comparison radios, not the default.

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
- **Live rebalance:** `scripts/ibkr_rebalance.py` runs `run_optimized_regime_backtest`
  and orders the last day’s overlay: 200-MA blend, VIX 28→40 and 20-session SPY
  drawdown equity cut, HAR vol scale, and portfolio drawdown shrink. CPI and GDP
  advance releases change the monthly sleeve. They do not replace the daily overlay.
  The scheduler does not send orders. Do not wait an extra Auditor month. There is
  no event-only live mode.
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
| `scripts/ab_vintage.py` | A/B/C, common inception, coverage, publication-lag percentiles |
| `src/backtester/daily_overlay.py` | Live notionals from the engine’s last-day overlay |
| `scripts/ibkr_snapshot.py` | Read-only IBKR snapshot → `data/cache/ibkr_account.json` (Execution tab) |
| `scripts/ibkr_rebalance.py` | Local paper/live rebalance to current regime weights (`--execute`) |
| `run_backtest.py` | CLI 20-yr validation; regenerates result CSVs |
| `run_dashboard.py` | Deployed Dash app (Cloud Run); calls the production method |
| `config/regime_rules.py` | `REGIME_WEIGHTS`, risk limits, targets |
| `optimize_strategy.py`, `extend_rp_mf.py` | Vectorized research harnesses (RP + MF prototypes) |
| `RECOMMENDATION.md` | Full audit write-up & handoff (more detail than this file) |
| `data/backtest_results/*.csv` | Cached results consumed by the dashboard |
