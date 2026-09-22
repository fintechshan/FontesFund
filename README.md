# ETF Regime Strategist 📊

A Python-based ETF investment application that detects macroeconomic regimes, constructs optimized portfolios, backtests strategies, and executes trades via Interactive Brokers.

> **📌 Current strategy & results live in [`CLAUDE.md`](CLAUDE.md) (agent brief) and
> [`RECOMMENDATION.md`](RECOMMENDATION.md).** Production strategy =
> `run_optimized_regime_backtest` (risk-parity + portfolio-level vol targeting + VIX gate).
> 20-yr backtest, **no look-ahead** (macro signals lagged to release dates), **8-ETF v5.1**:
> **14.52% CAGR / 14.78% MaxDD / Sharpe 0.97** (DD target met; CAGR/Sharpe short of 16/1.2; data thru 2026-06-26).
> Beats SPY (10.9% / 0.48) and 60/40 (8.2% / 0.55). Supersedes older numbers below.

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
python run_backtest.py
```

## Deployment (Render)

The live dashboard is a Docker web service on **Render**, triggered by GitHub
Actions. GitHub Pages is not used. Google Cloud Run, GCS, and Cloud Scheduler
are legacy — the new path does not need them.

Full one-time checklist (account, Blueprint, secret names, URL):
[`docs/DEPLOY_RENDER.md`](docs/DEPLOY_RENDER.md).

Expected URL: `https://fontesfund-dashboard.onrender.com` (Render will show the
real hostname if that one is taken). Health check: `GET /healthz`.

## Portfolio Configuration

- **Initial Capital**: $100,000
- **Monthly Contribution**: $10,000 (paused if 3-month return < -5%)
- **Rebalancing**: Monthly base weights; daily trend/vol/DD overlays
- **Validated targets**: CAGR ≥ 16%, Max Drawdown < 14.8%, Sharpe ≥ 1.2
  (achieved: 15.85%/14.76%/1.21 at 1% margin; 16.07%/14.76%/1.23 at 0.5% margin)
- **Production strategy**: `run_optimized_regime_backtest` — risk-parity sleeve
  weighting + portfolio-level vol targeting + 200-MA trend hedge + DD breaker.
  See [`CLAUDE.md`](CLAUDE.md) for the exact config and rationale.
- **Vol-estimator note** (`ab_vol.py` A/B): EWMA and HAR-RV do **not** beat the simple
  21-day realised vol on Sharpe (all ≈1.03); however, the OLS-based walk-forward HAR-RV vol overlay (`use_har_vol=True`) runs hotter/better under tuned overlays to clear the Max Drawdown target.

## Backtest Results (20yr: 2005-01 → 2026-06)

Net of 5 bps transaction cost + 1% leverage financing. Regenerate with `python run_backtest.py`.

Macro signals are lagged to their real release dates (no look-ahead).

| Strategy | CAGR | Vol | Sharpe | Max DD | Calmar | Total Return |
|---|--:|--:|--:|--:|--:|--:|
| **Optimized Regime (production, no look-ahead)** | **14.52%** | 13.00% | **0.97** | **14.78%** | 0.98 | 1,730% |
| 60/40 Benchmark | 8.21% | 11.57% | 0.55 | 34.70% | 0.24 | 442% |
| S&P 500 (SPY) | 10.92% | 18.96% | 0.48 | 55.19% | 0.20 | 820% |
| All Weather | 6.87% | 8.26% | 0.61 | 23.37% | 0.29 | 286% |

> The 16% / 14.8% / 1.2 targets are **not** fully met once macro look-ahead is removed (an
> earlier 15.85%/1.21 figure was look-ahead-biased). The honest **14.52% / 0.97 / 14.78%**
> meets the <14.8% MaxDD limit and still beats SPY and 60/40 handily on risk-adjusted terms. Full rationale & audit trail:
> [`RECOMMENDATION.md`](RECOMMENDATION.md), [`CLAUDE.md`](CLAUDE.md).

## Portfolio / ETF Universe

**Tested universe (23 ETFs with usable history in `data/cache/price_data.csv`):**
SPY, QQQ, IWM, VEA, VWO, TLT, IEF, SHY, AGG, TIP, GLD, DBC, VNQ, SOXX, SMH, XSD, DRAM, SPYI, QQQI, TQQQ, SOXL, DBMF, BTAL

**AI-trend complex (all part of the strategy):** SOXX, SMH, XSD, DRAM (semis/memory),
QQQ + TQQQ (AI software/leverage), SOXL (3x semis). SMH/XSD have full history; DRAM lists
Apr-2026 so it contributes only recently.

**Configured but not in cache** (silently renormalised away — re-download before live use):
SSO, MOAT, VOO, AIPO. (GGLL was removed entirely.)

- **Leveraged** (TQQQ, SOXL): regime-restricted, VIX-gated.
- **Limited history**: SPYI (2022), QQQI (2024), DBMF (2019), BTAL (2011), TQQQ/SOXL (2010)
  — per-date availability is handled, but early-period weights differ from late-period.
- Allocation per regime is set in `config/regime_rules.py:REGIME_WEIGHTS`; the production
  strategy then applies **inverse-vol (risk-parity)** weighting across the held sleeves.

## Risk Management

| Check | Rule | Action |
|---|---|---|
| Position Limit | ≤ 30% single ETF | Auto-reduce |
| Daily Turnover | ≤ 25% of portfolio | Queue excess |
| Drawdown Breaker | Trigger at 12% DD | Cut equity 50% |
| VIX Guard | Halt buys if VIX > 35 | Bonds & gold only |
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
