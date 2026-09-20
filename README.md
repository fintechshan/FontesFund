# ETF Regime Strategist 📊

A Python-based ETF investment application that detects macroeconomic regimes, constructs optimized portfolios, backtests strategies, and executes trades via Interactive Brokers.

> **📌 Current strategy & results live in [`CLAUDE.md`](CLAUDE.md) (agent brief).**
> Production is **v7 dual sleeve** (live AIPO / backtest XLY), not the old 8-ETF v5.1 book.
> Official public-FRED numbers (simplified honest engine, CPI +1mo / GDP +4mo, cash 口径,
> 2005-01-04→2026-09-18): **backtest/XLY 10.18% / -15.44% / 0.86** ·
> **live/AIPO 10.88% / -14.78% / 0.98**. Live long-sample ≠ full historical AIPO allocation
> (AIPO listed 2025-07-25). v5.1 14.52% / 14.78% / 0.97 is **historical only**.
> See [`docs/V7_DUAL_SLEEVE.md`](docs/V7_DUAL_SLEEVE.md).

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
# v7 research default = XLY proxy for the AIPO sleeve
python run_backtest.py

# live AIPO book
FONTES_RUN_MODE=live python run_backtest.py

# public-FRED simplified recompute (no API key)
python out/v7_fred_dual_recompute.py
```

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

## Backtest Results (v7 dual sleeve, 2005-01-04 → 2026-09-18)

Official figures: public FRED CSV, CPI +1mo / GDP +4mo, 5 bps, cash 口径
(missing history stays cash — no silent renorm). Simplified honest engine —
**not** bit-identical to `src/backtester/engine.py`. Frozen payload:
[`out/v7_fred_dual_metrics.json`](out/v7_fred_dual_metrics.json).

| Strategy | CAGR | Vol | Sharpe | Max DD |
|---|--:|--:|--:|--:|
| **v7 backtest / XLY** (research default) | **10.18%** | 9.68% | **0.86** | **-15.44%** |
| **v7 live / AIPO** | **10.88%** | 9.22% | **0.98** | **-14.78%** |
| 60/40 (SPY/IEF) | 8.30% | 10.88% | 0.59 | -31.39% |
| S&P 500 (SPY) | 10.90% | 18.89% | 0.48 | -55.19% |

> Live long-sample is mostly 6 core sleeves + cash for AIPO until 2025-07-25.
> Do not describe it as twenty years of a fully invested AIPO book.
> Targets 16% / &lt;14.8% / 1.2 are **not** fully met. v5.1 8-ETF
> 14.52% / 14.78% / 0.97 is retained only as a historical footnote.
> Details: [`CLAUDE.md`](CLAUDE.md), [`docs/V7_FRED_DUAL_RESULTS.md`](docs/V7_FRED_DUAL_RESULTS.md).

## Portfolio / ETF Universe

**v7 live book:** QQQ, SOXX, SPY, IEF, GLD, DBMF, **AIPO**
**v7 backtest book:** QQQ, SOXX, SPY, IEF, GLD, DBMF, **XLY** (AIPO-sleeve proxy)

Switch with `FONTES_RUN_MODE=backtest|live`. Missing history defaults to cash
(`FONTES_WEIGHT_MODE=cash`); do not silently renormalise.

- **Limited history:** AIPO (2025-07-25), DBMF (2019-05-08). XLY has history from 2005.
- Allocation per regime is set in `config/regime_rules.py:REGIME_WEIGHTS` (live AIPO);
  `get_regime_weights_for_mode("backtest")` remaps AIPO → XLY. The production
  strategy then applies **inverse-vol (risk-parity)** weighting across the held sleeves.
- Defense basket auxiliaries (SHY, AGG) are still downloaded for the bear overlay.
- Broader monitor universe (SMH/DRAM/XSD, covered-call, leveraged) remains in
  `config/etf_universe.py` but is **not** the v7 production book.

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
