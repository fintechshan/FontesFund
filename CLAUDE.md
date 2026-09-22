# CLAUDE.md — Agent Brief (v7 production lock)

> **SoT：** 美金生产已锁定为 **v7 dual sleeve**（live AIPO / backtest XLY）。本文取代旧
> v5.1 8-ETF 生产叙事。旧 headline **14.52% / 14.78% / 0.97 仅为历史对照**，不得再当
> 当前生产数字引用。Read this before changing the backtester or the strategy.
> Last updated **2026-09-21**.

---

## 1. Current production strategy & results (THE numbers)

**Strategy:** `BacktestEngine.run_optimized_regime_backtest` in
[`src/backtester/engine.py`](src/backtester/engine.py). Driven by
[`run_backtest.py`](run_backtest.py) (CLI/validation) and
[`run_dashboard.py`](run_dashboard.py) (deployed app). Overlay kwargs come from
[`config/regime_rules.py`](config/regime_rules.py) `STRATEGY_PARAMS`.

**Live universe (v7):** QQQ, SOXX, SPY, IEF, GLD, DBMF, **AIPO**
**Backtest universe (v7):** QQQ, SOXX, SPY, IEF, GLD, DBMF, **XLY**
（XLY proxies the AIPO sleeve so the slot is investable from 2005）

**Superseded:** v5.1 8-ETF (QQQ, SOXX, SPY, SPYI, TLT, GLD, DBMF, URA)
headline **14.52% CAGR / 14.78% MaxDD / 0.97 Sharpe** — historical only.

### Official dual-sleeve metrics (public FRED, cash 口径)

Macro publication lag: **CPI +1mo, GDP +4mo** via public FRED CSV
(`CPIAUCSL`, `A191RL1Q225SBEA`, `VIXCLS`, `DFF`). Window **2005-01-04 → 2026-09-18**.
Engine: **simplified honest recompute** (`out/v7_fred_dual_recompute.py`) —
**not** bit-identical to full `src/backtester/engine.py`.

| Mode | Sleeve | CAGR | MaxDD | Sharpe | vs 16% / &lt;14.8% / 1.2 |
|---|---|--:|--:|--:|---|
| **backtest** (research default) | XLY | **10.18%** | **-15.44%** | **0.86** | ❌ / ❌ / ❌ |
| **live** | AIPO | **10.88%** | **-14.78%** | **0.98** | ❌ / ✅(~) / ❌ |

Sources: [`docs/V7_FRED_DUAL_RESULTS.md`](docs/V7_FRED_DUAL_RESULTS.md),
[`out/v7_fred_dual_metrics.json`](out/v7_fred_dual_metrics.json).

**Disclaimer — live long-sample ≠ full AIPO allocation historically.**
AIPO listed **2025-07-25**; under live/cash 口径 that sleeve is mostly cash
until then (DBMF similarly cash pre-2019-05-08). Do **not** advertise the
live 20-year CAGR as “seven names fully invested in AIPO.”
Do **not** advertise the short post-AIPO window as a 20-year expectation.

### Backtest 口径（强制）

- Macro publication lag: CPI +1mo, GDP +4mo（禁止用 FRED 期初标签当日交易）
- Inception-aware **cash** for missing tickers（`FONTES_WEIGHT_MODE=cash`，禁止静默重归一）
- Costs 5 bps; `target_vol=0.130`; `bear_equity_frac=0.70`; `dd_trigger=0.07`
- Dual mode: `FONTES_RUN_MODE=backtest` (default for `run_backtest.py`) | `live`

```bash
# 长回测（默认，XLY 代理 AIPO 袖套）
python run_backtest.py
# 等价：FONTES_RUN_MODE=backtest python run_backtest.py

# 实盘权重（AIPO）
FONTES_RUN_MODE=live python run_backtest.py

# 公开 FRED 简化引擎复算（无需 API key）
python out/v7_fred_dual_recompute.py
```

See [`docs/V7_DUAL_SLEEVE.md`](docs/V7_DUAL_SLEEVE.md) and
[`docs/V7_BACKTEST_SPEC.md`](docs/V7_BACKTEST_SPEC.md).

### Production config (do not silently change)

```python
# config/regime_rules.py STRATEGY_PARAMS
risk_parity=True, rp_vol_lookback=60,
target_vol=0.130, vol_lookback=21, vol_lo=0.50, vol_hi=1.50,
bear_equity_frac=0.70, dd_trigger=0.07,
transaction_cost_bps=5.0, borrow_spread=0.01,
vix_data=vix, vix_gate_level=20.0,
vol_method='realized', use_har_vol=True,
# run_backtest.py: FONTES_RUN_MODE=backtest (default), FONTES_WEIGHT_MODE=cash
# macro publication lag: CPI +1mo, GDP +4mo
```

Helpers: `LIVE_UNIVERSE`, `BACKTEST_UNIVERSE`, `BACKTEST_TICKER_PROXY`,
`get_universe()`, `get_regime_weights_for_mode()`, `get_run_mode()`,
`get_weight_mode()`.

---

## 2. What changed and WHY (do not revert)

**v7 vs v5.1 universe (locked 2026-09):**
1. Combined SPY + SPYI into **SPY** (covered-call redundancy removed).
2. Replaced URA with **AIPO** (Defiance AI & Power Infrastructure).
3. Replaced TLT with **IEF** (7–10Y Treasuries — balanced duration).
4. Dual sleeve: live keeps AIPO; long backtests map that slot to **XLY**.

**Why official CAGR is below the old 14.52% copy:** the book changed
(IEF for TLT, no SPYI, URA→AIPO/XLY); missing history is cash, not silent
renorm; cited numbers are the simplified honest engine + lagged public FRED,
not a v5.1 full-engine reprint.

**Overlays architecture (unchanged — do not reintroduce the old bugs):**

1. **Wrong vol proxy (the big bug).** The old method scaled the *entire
   multi-asset portfolio by SPY's* volatility. In defensive regimes the book
   is bonds/gold, so it levered bond books in calm markets and de-risked
   bonds/gold in crises — backwards. **Fix:** portfolio-level vol targeting
   on the strategy's *own* realised vol.
2. **Stacked, fighting overlays** (bear hedge + asymmetric vol scaling + DD
   breaker) that cut CAGR ~23%→13% while barely helping DD. **Fix:** one
   clean trend hedge + portfolio vol target + DD breaker.
3. **Risk-parity sleeve weighting** (`risk_parity=True`) cuts the regime
   book's vol, then the vol target levers that low-vol book back up.
4. **Managed-futures overlay stays OFF** (`mf_alloc=0.0`). DBMF is a sleeve
   inside `REGIME_WEIGHTS`, not a second overlay.
5. **HAR-RV stays ON** (`use_har_vol=True`) — a DD-constraint choice from
   the v5.1 sweep, not a Sharpe win. Don't re-litigate.

A **managed-futures (CTA) proxy** was prototyped and deliberately left off
as a *second* overlay. It remains an optional knob (`mf_alloc`, `mf_assets`).

### Myth corrected
The earlier claim that "16/14.8/1.2 is mathematically infeasible because of
the March 2020 COVID crash" is **false**. In every viable v5.1 variant
**2020 is a positive year**. The binding drawdown historically was **2022**
(joint stock+bond selloff). v7 official numbers still miss the 16/1.2
targets; that is a universe + cash-口径 + honest-engine fact, not a reason
to restore look-ahead or silent renorm.

---

## 3. Deployment

- **App:** the Plotly Dash dashboard in `run_dashboard.py` (+ `src/dashboard/`),
  containerised via [`Dockerfile`](Dockerfile), shipped to **Google Cloud Run**
  (see `.gcloudignore`). It calls `run_optimized_regime_backtest` at all 4
  sites with `REGIME_WEIGHTS` (live AIPO book) and `STRATEGY_PARAMS`.
  If you change the production config, update **both** `run_backtest.py` and
  the 4 call sites in `run_dashboard.py`.
- **Auto-refresh architecture (2026-07):** caches persist in GCS bucket
  `montesfund-etf-dashboard-data` (`src/dashboard/gcs_sync.py`).
  - *Backtest/regime data:* Cloud Scheduler job `etf-daily-refresh` (11:00 UTC)
    POSTs `/tasks/refresh` (token-protected, `REFRESH_TOKEN` env) → runs
    `run_backtest.py` in-container → uploads fresh CSVs/caches to GCS.
    Containers pull from GCS at startup (`download_data()`).
    **Note:** `run_backtest.py` now defaults to `FONTES_RUN_MODE=backtest`
    (XLY). Cloud Run live refresh should set `FONTES_RUN_MODE=live` if the
    published curves must show the AIPO book.
  - *IBKR account snapshot:* Windows task `ETF-IBKR-Snapshot` (daily 9:00 China
    time) runs `scripts/refresh_ibkr_snapshot.ps1` → `ibkr_snapshot.py` →
    pushes `ibkr_account.json` to GCS. Execution tab re-pulls every 10 min.
- **Reproduce:** `python run_backtest.py` (full engine, ~30s). Dual-sleeve
  FRED numbers: `python out/v7_fred_dual_recompute.py` (public CSV, no key).
  Fast research harnesses: `python optimize_strategy.py`, `python extend_rp_mf.py`.
- **Secrets:** `config/settings.py` reads `FRED_API_KEY` from `.env`/env vars
  (hardcoded key removed 2026-06-27). Do **not** commit `.env`. The exposed
  key `534c2e45…` and `REFRESH_TOKEN` still need rotation.
- **Startup fragility note:** the Dash layout is built eagerly at container
  start; a crash anywhere in a `build_*_tab` bricks the revision. Render-test
  UI tabs offline before deploying.

---

## 4. Data integrity (known issues — fix before live trading)

- **AIPO listed ~2025-07-25** — cannot carry a 20-year AIPO narrative alone.
  Live long-sample is 6 core sleeves + cash for AIPO (and cash/partial for
  DBMF pre-2019). Backtest mode uses XLY for that slot; **do not mix the
  two numbers in external copy**.
- **DBMF from ~2019-05-08.** Cash 口径 applies.
- Never claim documented weights == tested weights if tickers are missing
  from the price cache. `filter_weights(..., renormalize=False)` is the
  default; `FONTES_WEIGHT_MODE=renorm` is A/B only.
- Cache `data/cache/price_data.csv` must include the live *and* backtest
  sleeve tickers (AIPO + XLY) plus SHY/AGG for the defense basket.
- `run_regime_backtest` (upper-bound reference only) still parks weight in
  not-yet-listed ETFs as phantom cash. Production
  `run_optimized_regime_backtest` handles per-date availability; the official
  v7 FRED numbers come from the *simplified* cash engine, not that path.
- Limited-history ETFs make the early backtest structurally different from
  the late one; treat cross-era comparisons with care.
- Full `src/backtester/engine.py` still renormalises on a per-date basis
  inside the monthly rebalance. Official public-FRED figures are from
  `out/v7_fred_dual_recompute.py` (cash, no silent renorm). Do not treat a
  full-engine reprint as a replacement for those figures unless you re-run
  and document the delta.

### Gemini audit fixes (2026-06-22) — still applied
- Macro look-ahead removed (CPI +1mo, GDP +4mo). Do not revert the lag to
  "restore" old targets.
- VIX gate in `run_optimized_regime_backtest` (zero TQQQ/SOXL, redirect to
  QQQ/SOXX when yesterday's VIX ≥ 20).
- `PERFORMANCE_TARGETS` remain the aspirational 16% / 14.8% / 1.2 gate
  (v7 official numbers do not clear all three).
- `GGLL` stays removed. SQLiteCache stays deleted.

### Live IBKR account integration (Execution tab)
`scripts/ibkr_snapshot.py` (read-only; run locally with TWS up) writes
`data/cache/ibkr_account.json`. Paper account `DUQ963925`. Account base
currency is **CAD** while the 7 ETFs are **USD** — IBKR may auto-finance
USD buys with a USD margin loan; that is a currency-financing artifact,
not strategy leverage.

---

## 5. File map

| Path | Role |
|---|---|
| `src/backtester/engine.py` | `run_optimized_regime_backtest` = production engine |
| `config/regime_rules.py` | `REGIME_WEIGHTS` (live AIPO), dual-mode helpers, `STRATEGY_PARAMS` |
| `run_backtest.py` | CLI 20-yr validation; `FONTES_RUN_MODE` / `FONTES_WEIGHT_MODE` |
| `run_dashboard.py` | Deployed Dash app (live AIPO weights) |
| `docs/V7_DUAL_SLEEVE.md` | How to run live vs backtest modes |
| `docs/V7_BACKTEST_SPEC.md` | Locked 口径 (lags, cash, costs) |
| `docs/V7_FRED_DUAL_RESULTS.md` | Official public-FRED dual-sleeve table |
| `out/v7_fred_dual_recompute.py` | Simplified honest engine (public FRED CSV, no key) |
| `out/v7_fred_dual_metrics.json` | Frozen official metrics payload |
| `scripts/ibkr_snapshot.py` | Read-only IBKR snapshot → Execution tab |
| `scripts/ibkr_rebalance.py` | Local paper/live rebalance to current regime weights |
| `optimize_strategy.py`, `extend_rp_mf.py` | Vectorized research harnesses |
| `RECOMMENDATION.md` | v5.1-era audit write-up (**historical**; see banner) |
| `data/backtest_results/*.csv` | Cached dashboard result CSVs |
