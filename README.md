# ETF Regime Strategist 📊

A Python-based ETF investment application that detects macroeconomic regimes, constructs optimized portfolios, backtests strategies, and executes trades via Interactive Brokers.

> **📌 Current strategy & results live in [`CLAUDE.md`](CLAUDE.md).** Production strategy =
> `run_optimized_regime_backtest` (risk-parity + portfolio-level vol targeting).
> **7-ETF v7** (QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO), sample **2005-01-04 → 2026-09-25**.
> **Dashboard default (Backtest tab, Portfolio CAGR card): targeted fix** — CPI+1 month /
> GDP+4 months, and no month-end look-ahead in VIX or SPY momentum:
> **13.43% CAGR / 14.13% MaxDD / Sharpe 0.93**.
> The old **14.85%** headline (this sample: **14.81% / 13.90% / 1.03**) kept same-month
> market data and is a labeled comparison, not the default.
> The extra Auditor month (**12.17% / 14.10% / 0.83**) is overly conservative and is not the default.
> First-release vintage (Philadelphia Fed RTDSM): **12.65% / 15.23% / 0.87**.
> That production path beats SPY (10.95% / 0.48) and 60/40 (8.15% / 0.55) on the same file.
> Unlagged (publication lag off) is **15.70%** and stays a diagnostic.
> The older 8-ETF v5.1 figure (14.52% / 14.78% / 0.97) is historical. [`RECOMMENDATION.md`](RECOMMENDATION.md) is the 2026-06 audit, not the current sleeve.

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
- **Rebalancing**: Monthly base weights; daily trend/vol/DD overlays
- **Validated targets**: CAGR ≥ 16%, Max Drawdown < 14.8%, Sharpe ≥ 1.2
  (targeted fix, CPI+1mo / GDP+4mo, no month-end look-ahead: 13.43% / 14.13% / 0.93 —
  MaxDD met; CAGR and Sharpe short of 16 / 1.2. Dashboard default is that path.)
- **Live rebalance:** trade on CPI and GDP advance release days, and when VIX or
  momentum flips under the existing rules. The daily data refresh does not place
  trades. Do not wait an extra Auditor month.
- **Production strategy**: `run_optimized_regime_backtest` — risk-parity sleeve
  weighting + portfolio-level vol targeting + 200-MA trend hedge + DD breaker.
  See [`CLAUDE.md`](CLAUDE.md) for the exact config and rationale.
- **Vol-estimator note** (`ab_vol.py` A/B): EWMA and HAR-RV do **not** beat the simple
  21-day realised vol on Sharpe (all ≈1.03); however, the OLS-based walk-forward HAR-RV vol overlay (`use_har_vol=True`) runs hotter/better under tuned overlays to clear the Max Drawdown target.

## Backtest Results (2005-01-04 → 2026-09-25)

Net of 5 bps transaction cost + 1% leverage financing. Regenerate with `python run_backtest.py`.
The production row matches `data/backtest_results/20yr_comparison.csv`. The other clocks are in
`data/backtest_results/lag_honesty.csv` and on the Backtest radios. The heatmap uses the
monthly returns of whichever radio is selected.

Macro signals use CPI +1 month and GDP +4 months. VIX and 12-month momentum use only the
prior month-end. That is the production path and the dashboard default. Do not shorten the
publication lags. The daily scheduler refresh does not place trades; rebalance on CPI and
GDP advance release days and when VIX or momentum flips.

| Strategy | CAGR | Vol | Sharpe | Max DD | Calmar | Total Return |
|---|--:|--:|--:|--:|--:|--:|
| **Targeted fix (default)** | **13.43%** | 12.41% | **0.93** | **14.13%** | 0.95 | 1,438% |
| Old production (month-end look-ahead) | 14.81% | 12.60% | 1.03 | 13.90% | 1.07 | 1,901% |
| First-release vintage | 12.65% | 12.35% | 0.87 | 15.23% | 0.83 | 1,225% |
| Auditor extra month (overly conservative) | 12.17% | 12.40% | 0.83 | 14.10% | 0.86 | 1,108% |
| Unlagged diagnostic | 15.70% | 12.52% | 1.11 | 14.58% | 1.08 | 2,266% |
| 60/40 Benchmark | 8.15% | 11.53% | 0.55 | 34.70% | 0.23 | 447% |
| S&P 500 (SPY) | 10.95% | 18.89% | 0.48 | 55.19% | 0.20 | 853% |
| All Weather | 6.72% | 8.25% | 0.59 | 23.37% | 0.29 | 282% |

> The 16% / 14.8% / 1.2 targets are **not** fully met on the targeted fix. An earlier 15.85% / 1.21 figure
> used CPI/GDP before their release dates. The later **14.85%** figure still used same-month VIX and
> momentum (14.81% on this sample). The number the Backtest tab shows first is the targeted fix
> **13.43% / 0.93 / 14.13%**. A prior estimate of ~13.36% was re-run; do not hardcode it.
> First-release vintage is lower (**12.65%**). That is an honest result, not a bug to tune away.
> The 8-ETF v5.1 result (14.52% / 0.97 / 14.78%, data through 2026-06-26) is historical.
> See [`CLAUDE.md`](CLAUDE.md).

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
