# ETF Regime Strategist 📊

A Python-based ETF investment application that detects macroeconomic regimes, constructs optimized portfolios, backtests strategies, and executes trades via Interactive Brokers.

> **📌 Current strategy & method live in [`CLAUDE.md`](CLAUDE.md).** Do not copy a CAGR
> out of an old README. Production is `run_optimized_regime_backtest`: the targeted
> clock (CPI+1 month, GDP+4 months, prior-month VIX and momentum) **plus** the daily
> overlay (200-day trend, portfolio vol target, portfolio drawdown). Live orders use
> that same overlay. **7-ETF v7** (QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO). A name with
> no history is dropped and the sleeve is renormalized, not held as cash. DBMF and
> AIPO are missing for most of a 20-year window; see `coverage_windows.csv`.
> Dashboard default is that targeted path, computed each run. The month-end look-ahead
> path, the unlagged diagnostic, the extra Auditor month, and the first-release vintage
> are labeled radios. [`RECOMMENDATION.md`](RECOMMENDATION.md) is the 2026-06 audit, not the current sleeve.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│            1. THE STRATEGIST                        │
│  FRED API → Feature Engineering → HMM Regime       │
│  yfinance    (Growth, Inflation,   Detector         │
│  Finnhub      Risk indicators)     (4 regimes)      │
├─────────────────────────────────────────────────────┤
│            2. PORTFOLIO BUILDER                     │
│  Regime Weights → PyPortfolioOpt → Constrained      │
│  + Analyst Tilt   (Max Sharpe)     Portfolio         │
│                   (Risk Parity)    (Sharpe>1, DD<15%)│
├─────────────────────────────────────────────────────┤
│            3. BACKTESTER                            │
│  Walk-Forward → bt Engine → QuantStats → Gap        │
│  Regime Signals  Benchmarks  Tearsheets  Analysis   │
├─────────────────────────────────────────────────────┤
│            4. EXECUTION & RISK                      │
│  6 Risk Checks → ib_async → IBKR Gateway → Orders  │
│  Circuit Breaker  Paper/Live  Position Monitor      │
└─────────────────────────────────────────────────────┘
```

## Economic Regimes

| Regime | Growth | Inflation | Favored Assets |
|---|---|---|---|
| **Goldilocks** | Rising | Falling | SPY, QQQ, SOXX, TQQQ* |
| **Reflation** | Rising | Rising | GLD, DBC, TIP, VNQ, GGLL* |
| **Stagflation** | Falling | Rising | GLD, TIP, DBMF, BTAL, SHY |
| **Deflation** | Falling | Falling | TLT, IEF, AGG, SHY |

*Leveraged ETFs only when confidence > 80% and VIX < 20

## Quick Start

### 1. Setup
```bash
cd "d:\Software\Antigraivty File\Investment"
pip install -r requirements.txt

# Copy and edit environment variables
cp .env.example .env
# Edit .env with your FRED and Finnhub API keys
```

### 2. Get API Keys (Free)
- **FRED API**: https://fred.stlouisfed.org/docs/api/api_key.html
- **Finnhub**: https://finnhub.io/register

### 3. Run Dashboard
```bash
python -m src.dashboard.app
# Open http://localhost:8050
```

### 4. Run Backtest (CLI)
```bash
python scripts/run_backtest.py
```

## Portfolio Configuration

- **Initial Capital**: $100,000
- **Monthly Contribution**: $10,000 (paused if 3-month return < -5%)
- **Rebalancing**: Monthly regime sleeve; daily overlay every session (200-MA,
  VIX 28→40, 20-session SPY drawdown, vol target, portfolio drawdown shrink)
- **Validated targets**: CAGR ≥ 16%, Max Drawdown < 14.8%, Sharpe ≥ 1.2.
  The latest run’s distance to those targets is `20yr_comparison.csv`, not a number
  frozen here. Dashboard default is the targeted path (B), including the daily overlay.
- **Live rebalance:** same daily overlay as the backtest. CPI and GDP advance
  releases change the monthly sleeve only. The daily data refresh does not place
  trades. Do not wait an extra Auditor month. There is no event-only live mode.
- **Production strategy**: `run_optimized_regime_backtest` — Merrill risk-parity
  sleeve, then the daily overlay above. See [`CLAUDE.md`](CLAUDE.md).
- **Vol-estimator note** (`ab_vol.py` A/B): EWMA and HAR-RV do **not** beat the simple
  21-day realised vol on Sharpe (all ≈1.03); however, the OLS-based walk-forward HAR-RV vol overlay (`use_har_vol=True`) runs hotter/better under tuned overlays to clear the Max Drawdown target.

## Backtest results

Net of 5 bp turnover and 1% financing on gross exposure above 1. Regenerate; do not
treat an old table in this file as the result.

```bash
python run_backtest.py          # path B → 20yr_comparison.csv
python scripts/ab_vintage.py    # A / B / C, common inception, coverage, release lags
```

Path B is the dashboard default. The Backtest radio drives the CAGR cards, the
equity curve, and the monthly heatmap from that one curve. CPI stays +1 month and
GDP stays +4 months. VIX and 12-month momentum use only the prior month. That
market lag is not a second CPI/GDP lag. The daily overlay (VIX 28→40, 20-session
SPY drawdown, portfolio drawdown shrink, plus the 200-MA and vol target) is on
every honesty path. It is not a separate live calendar.

The full-sample row drops ETFs that have not listed yet and renormalizes. Read
`coverage_windows.csv` before treating that row as what the live book held.
`lag_honesty.csv` also has path B from the first day every live sleeve name exists.

With `FRED_API_KEY`, `ab_vintage.py` adds a CPIAUCNS (not seasonally adjusted)
first-release row. Without a key that row is skipped. Cached YoY series go to
`data/cache/vintage_*.csv`.

See [`CLAUDE.md`](CLAUDE.md). The 8-ETF v5.1 result is historical.

## Portfolio / ETF Universe

**Tested universe (23 ETFs with usable history in `data/cache/price_data.csv`):**
SPY, QQQ, IWM, VEA, VWO, TLT, IEF, SHY, AGG, TIP, GLD, DBC, VNQ, SOXX, SMH, XSD, DRAM, SPYI, QQQI, TQQQ, SOXL, DBMF, BTAL

**AI-trend complex (all part of the strategy):** SOXX, SMH, XSD, DRAM (semis/memory),
QQQ + TQQQ (AI software/leverage), SOXL (3x semis). SMH/XSD have full history; DRAM lists
Apr-2026 so it contributes only recently.

**Production sleeve (v7, `REGIME_WEIGHTS`):** QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO.
Names that are not in that sleeve are renormalized away when they have no price.

**Configured but not in the v7 sleeve** (and, for some, missing from the price cache):
SSO, MOAT, VOO. (GGLL was removed entirely. AIPO is in the v7 sleeve.)

- **Leveraged** (TQQQ, SOXL): regime-restricted, VIX-gated.
- **Limited history**: SPYI (2022), QQQI (2024), DBMF (2019), BTAL (2011), TQQQ/SOXL (2010)
  — per-date availability is handled, but early-period weights differ from late-period.
- Allocation per regime is set in `config/regime_rules.py:REGIME_WEIGHTS`; the production
  strategy then applies **inverse-vol (risk-parity)** weighting across the held sleeves.

## Risk Management

| Check | Rule | Action |
|---|---|---|
| Position Limit | ≤ max sleeve in `REGIME_WEIGHTS` (35% today: IEF in deflation). Goldilocks QQQ 30% is accepted AI-trend exposure and is not reduced to 25% | Auto-reduce only above that cap |
| Daily Turnover | ≤ 25% of portfolio | Queue excess |
| Drawdown Breaker | Trigger at 12% DD | Cut equity 50% |
| VIX Guard | VIX > 30 (`REGIME_VIX_DEFENSIVE`) forces deflation | Defensive regime |
| Correlation | No 3+ correlated > 60% | Diversify |
| Liquidity | Min 500K avg volume | Skip illiquid |

## Project Structure

```
Investment/
├── config/           # Settings, ETF universe, regime rules
├── src/
│   ├── strategist/   # Data collection, features, regime detection
│   ├── portfolio/    # Optimization, allocation, constraints
│   ├── backtester/   # Engine, benchmarks, reporting, gap analysis
│   ├── execution/    # Risk manager, IBKR broker, orders, monitoring
│   └── dashboard/    # Plotly Dash web UI
├── data/             # SQLite DB and cached data
├── scripts/          # CLI tools
└── tests/            # Unit tests
```

## IBKR Integration

The app connects to Interactive Brokers via `ib_async`:
- **Paper Trading**: Port 4002 (IB Gateway) or 7497 (TWS)
- **Live Trading**: Port 4001 (IB Gateway) or 7496 (TWS)
- Default: Paper trading mode with dry-run safety

## Tech Stack

Python 3.11+ | fredapi | yfinance | finnhub | hmmlearn | PyPortfolioOpt | bt | QuantStats | ib_async | Plotly Dash
