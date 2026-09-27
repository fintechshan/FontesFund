"""
20-Year Backtest Validation Script
====================================
Downloads 20 years of ETF + macro data, runs regime detection,
then backtests the Vol-Targeted Regime Strategy to validate:
  - Annual Return >= 16%
  - Max Drawdown < 14.8%
  - Sharpe Ratio >= 1.2

Math: Sharpe = (16% - 1.85%) / σ = 1.2  →  target σ = 11.8%
      Vol-targeting scales weights daily so portfolio vol ≈ 11.8%

NOTE (2026-07-12):
A train-test split analysis was performed:
  - Training Period: 2005 - 2020 (In-Sample MVO Optimization)
  - Testing Period:  2021 - 2026 (Out-of-Sample Validation)
Optimizing weights on the training slice resulted in overfitting, which improved in-sample
performance (+1.13% CAGR, +0.10 Sharpe) but degraded out-of-sample performance by -1.00% CAGR
(11.27% vs 12.27%) and -0.09 Sharpe (0.73 vs 0.82) compared to the baseline macro-theory weights.
Consequently, baseline weights are retained in production for out-of-sample robustness.
"""

import sys
import os
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import logging
import numpy as np
import pandas as pd
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('backtest_20yr')

# ─────────────────────────────────────────────────────────
# 1. LOAD SETTINGS & CONFIGURATION
# ─────────────────────────────────────────────────────────
from config.settings import FRED_API_KEY
from config.regime_rules import (
    REGIME_WEIGHTS, PERFORMANCE_TARGETS,
    MOMENTUM_CONFIG, VOL_TARGET_CONFIG,
)

logger.info("=" * 70)
logger.info("  ETF REGIME STRATEGIST -- 20-YEAR BACKTEST VALIDATION")
logger.info("=" * 70)
logger.info(f"Targets: Return>={PERFORMANCE_TARGETS.min_annual_return:.0%}, "
            f"MaxDD<14.8%, Sharpe>=1.2  (Vol target=11.8%)")

# ─────────────────────────────────────────────────────────
# 2. DOWNLOAD ETF PRICE DATA (20 years)
# ─────────────────────────────────────────────────────────
import yfinance as yf

START_DATE = "2005-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")

# All ETFs in the simplified 7-ticker portfolio (v7)
ALL_TICKERS = [
    "QQQ", "SOXX", "SPY", "SPYI",                   # Equity + Income
    "TLT", "IEF", "GLD",                            # Bonds + Gold
    "DBMF",                                         # Managed futures
    "URA",                                          # Uranium / AI energy
    "AIPO", "XLY", "XEI.TO", "ZWB.TO",              # A/B test tickers
    "CADUSD=X",                                     # Currency rate for CAD conversion
    "SHY", "AGG", "DBC",                            # Required for defense basket and benchmarks
]

import time
from pathlib import Path

CACHE_FILE = Path('data/cache/price_data.csv')
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

def yf_download_with_retry(tickers, start, end, retries=3):
    """Download with retry for transient failures."""
    for attempt in range(retries):
        data = yf.download(tickers, start=start, end=end, auto_adjust=True)
        if isinstance(data.columns, pd.MultiIndex):
            data = data['Close']
        data = data.dropna(axis=1, how='all')
        if len(data.columns) >= len(tickers) * 0.8:  # Got 80%+ tickers
            return data
            
        # Convert to dictionary of series to prevent index truncation when retrying
        downloaded = {t: data[t].dropna() for t in data.columns}
        
        # Retry missing tickers individually
        missing = [t for t in tickers if t not in downloaded]
        if missing:
            logger.info(f"  Retrying {len(missing)} missing tickers: {missing}")
            time.sleep(3)
            for t in missing:
                for retry in range(3):
                    try:
                        time.sleep(1)
                        # Try Ticker.history fallback first (more robust for some tickers)
                        ticker_obj = yf.Ticker(t)
                        single = ticker_obj.history(start=start, end=end)
                        if 'Close' in single.columns:
                            single = single['Close']
                        if single.index.tz is not None:
                            single.index = single.index.tz_localize(None)
                        
                        if single.empty:
                            # Try yf.download
                            single = yf.download(t, start=start, end=end, auto_adjust=True, progress=False)
                            if isinstance(single.columns, pd.MultiIndex):
                                single = single['Close']
                        
                        if not single.empty:
                            if isinstance(single, pd.DataFrame):
                                downloaded[t] = single.iloc[:, 0]
                            else:
                                downloaded[t] = single
                            logger.info(f"    Successfully retrieved {t}")
                            break
                    except Exception as e:
                        if retry < 2:
                            logger.warning(f"  Retry {retry+1} for {t}: {e}")
                            time.sleep(2)
                        else:
                            logger.warning(f"  Failed to get {t} after 3 retries")
                            
        # Combine all series into a single DataFrame, which unions the date indexes
        combined = pd.DataFrame(downloaded)
        return combined
    return pd.DataFrame()

# Use persistent CSV cache to avoid yfinance intermittent failures.
# FORCE_REFRESH=1 (set by the /tasks/refresh endpoint) always re-downloads:
# the daily cloud refresh pulls GCS caches at container start, which makes the
# file MTIME look "fresh" even when the DATA inside is days old — without the
# override the pipeline would recycle stale data forever.
use_cache = CACHE_FILE.exists() and not os.getenv('FORCE_REFRESH')
if use_cache:
    cache_age_days = (pd.Timestamp.now() - pd.Timestamp(CACHE_FILE.stat().st_mtime, unit='s')).days
    if cache_age_days >= 1:
        logger.info(f"Cache is {cache_age_days} days old, refreshing...")
        use_cache = False

if use_cache:
    logger.info(f"Loading cached price data from {CACHE_FILE}")
    price_data = pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
    logger.info(f"Loaded {len(price_data.columns)} ETFs from cache")
else:
    logger.info(f"Downloading price data for {len(ALL_TICKERS)} ETFs from {START_DATE}...")
    price_data = yf_download_with_retry(ALL_TICKERS, START_DATE, END_DATE)
    
    # Perform currency conversion for Canadian ETFs (.TO) to USD before caching
    if "CADUSD=X" in price_data.columns:
        fx = price_data["CADUSD=X"].ffill()
        for t in ["XEI.TO", "ZWB.TO"]:
            if t in price_data.columns:
                logger.info(f"Converting {t} from CAD to USD using CADUSD=X...")
                price_data[t] = price_data[t] * fx
        # Drop CADUSD=X so it is not saved as an ETF
        price_data = price_data.drop(columns=["CADUSD=X"])
        
    # Align the index to SPY's trading dates (US calendar) to prevent holiday/weekend distortions
    if "SPY" in price_data.columns:
        logger.info("Aligning price data to SPY trading calendar (US market dates only)...")
        try:
            spy_clean = yf.download("SPY", start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
            if not spy_clean.empty:
                if isinstance(spy_clean.columns, pd.MultiIndex):
                    spy_clean = spy_clean['Close']
                if spy_clean.index.tz is not None:
                    spy_clean.index = spy_clean.index.tz_localize(None)
                price_data = price_data.reindex(spy_clean.index).ffill()
                logger.info(f"Aligned price data index to US market calendar: {len(price_data)} trading days")
        except Exception as e_align:
            logger.warning(f"Failed to align price data to SPY index: {e_align}")
        
    # Save to cache if we got a good download (80%+ of expected tickers, excluding CADUSD=X)
    target_count = len(ALL_TICKERS) - 1
    if len(price_data.columns) >= target_count * 0.8:
        price_data.to_csv(CACHE_FILE)
        logger.info(f"Cached {len(price_data.columns)} ETFs to {CACHE_FILE}")
    else:
        logger.warning(f"Only got {len(price_data.columns)} ETFs, not caching")

available_tickers = list(price_data.columns)
logger.info(f"Got price data for {len(available_tickers)} ETFs: {available_tickers}")
logger.info(f"Date range: {price_data.index[0].date()} to {price_data.index[-1].date()}")

# Forward-fill gaps
price_data = price_data.ffill()

# ─────────────────────────────────────────────────────────
# 3. FETCH MACRO DATA & BUILD REGIME HISTORY
# ─────────────────────────────────────────────────────────
from fredapi import Fred
import pickle

MACRO_CACHE = Path('data/cache/macro_data.pkl')

def fred_safe(series_id, start='2000-01-01', retries=3):
    """Fetch FRED series with retry."""
    for attempt in range(retries):
        try:
            return fred.get_series(series_id, observation_start=start).dropna()
        except Exception as e:
            logger.warning(f"  FRED retry {attempt+1} for {series_id}: {e}")
            time.sleep(3)
    return pd.Series(dtype=float)

# Use cached macro data if available (FORCE_REFRESH=1 always re-fetches — see price cache note)
use_macro_cache = MACRO_CACHE.exists() and not os.getenv('FORCE_REFRESH')
if use_macro_cache:
    cache_age = (pd.Timestamp.now() - pd.Timestamp(MACRO_CACHE.stat().st_mtime, unit='s')).days
    if cache_age >= 1:
        logger.info(f"Macro cache is {cache_age} days old, refreshing...")
        use_macro_cache = False

if use_macro_cache:
    logger.info(f"Loading cached macro data from {MACRO_CACHE}")
    with open(MACRO_CACHE, 'rb') as f:
        macro = pickle.load(f)
    vix = macro['vix']
    gdp = macro['gdp']
    cpi = macro['cpi']
    unemp = macro['unemp']
    t10y = macro['t10y']
    t2y = macro['t2y']
    ff_rate = macro['ff_rate']
else:
    fred = Fred(api_key=FRED_API_KEY)
    logger.info("Fetching macro data from FRED...")

    vix = fred_safe('VIXCLS', START_DATE)
    gdp = fred_safe('A191RL1Q225SBEA')
    cpi = fred_safe('CPIAUCSL')
    unemp = fred_safe('UNRATE')
    t10y = fred_safe('DGS10', START_DATE)
    t2y = fred_safe('DGS2', START_DATE)
    ff_rate = fred_safe('DFF', START_DATE)

    # Cache if we got good data
    if len(vix) > 100:
        macro = {'vix': vix, 'gdp': gdp, 'cpi': cpi, 'unemp': unemp,
                 't10y': t10y, 't2y': t2y, 'ff_rate': ff_rate}
        with open(MACRO_CACHE, 'wb') as f:
            pickle.dump(macro, f)
        logger.info(f"Cached macro data to {MACRO_CACHE}")

logger.info(f"VIX: {len(vix)} points | GDP: {len(gdp)} | CPI: {len(cpi)}")

# ── Data-quality gate (FORCE_REFRESH / automated refresh only) ────────────
# If the FRED fetch failed, the fallbacks below (SPY realized vol for VIX,
# default CPI/GDP in classify_regime) let the backtest "succeed" with garbage
# regimes — a cloud refresh once published 11.82%/15.97% this way (2026-07-12).
# Under FORCE_REFRESH we hard-fail instead, so the caller never uploads bad data.
if os.getenv('FORCE_REFRESH'):
    _problems = []
    if len(vix) < 100:  _problems.append(f"VIX {len(vix)} pts (<100)")
    if len(cpi) < 100:  _problems.append(f"CPI {len(cpi)} pts (<100)")
    if len(gdp) < 40:   _problems.append(f"GDP {len(gdp)} pts (<40)")
    if len(price_data.columns) < 10:
        _problems.append(f"only {len(price_data.columns)} tickers (<10)")
    if not price_data.empty and (pd.Timestamp.now() - price_data.index.max()).days > 7:
        _problems.append(f"prices stale (last {price_data.index.max().date()})")
    if _problems:
        logger.error("FORCE_REFRESH data-quality gate FAILED: " + "; ".join(_problems))
        logger.error("Aborting so the automated refresh does NOT publish degraded results.")
        sys.exit(2)

# ── Regime clock (targeted fix is the saved production path) ─────────────
# CPI stays +1 month and GDP stays +4 months. VIX and SPY momentum are dated
# on the month-end they describe, so a month-start rebalance cannot see the
# rest of that month. The old month-stamped path is MODE_LOOKAHEAD and is not
# what this script writes to 20yr_comparison.csv.
# Unemployment is still not a regime input (Gemini, 2026-06-22).
logger.info("Computing targeted regime classification (no month-end look-ahead)...")
from src.backtester.regime_clock import classify_regimes, MODE_TARGETED

if len(vix) == 0 and 'SPY' in price_data.columns:
    logger.warning("VIX data unavailable — VIX override will use SPY-based proxy")
    vix = price_data['SPY'].pct_change().rolling(21).std() * 16 * 100

macro_for_clock = {
    'vix': vix, 'gdp': gdp, 'cpi': cpi, 'unemp': unemp,
    't10y': t10y, 't2y': t2y, 'ff_rate': ff_rate,
}
regime_history, _current_regime, _clock_info = classify_regimes(
    macro_for_clock, price_data, mode=MODE_TARGETED,
)
logger.info(f"Regime history: {len(regime_history)} months (mode={_clock_info.get('mode')})")

# Print regime distribution
regime_counts = regime_history['regime'].value_counts()
for regime, count in regime_counts.items():
    pct = count / len(regime_history) * 100
    logger.info(f"  {regime}: {count} months ({pct:.1f}%)")

# ─────────────────────────────────────────────────────────
# 4. PREPARE REGIME WEIGHTS (filter to available tickers)
# ─────────────────────────────────────────────────────────
def filter_weights(weights, available):
    """Filter and renormalize weights to available tickers."""
    filtered = {k: v for k, v in weights.items() if k in available}
    total = sum(filtered.values())
    if total > 0:
        filtered = {k: v / total for k, v in filtered.items()}
    return filtered

regime_weights_filtered = {}
for regime_name, weights in REGIME_WEIGHTS.items():
    filtered = filter_weights(weights, available_tickers)
    regime_weights_filtered[regime_name] = filtered
    logger.info(f"  {regime_name}: {len(filtered)} ETFs (from {len(weights)})")

# ─────────────────────────────────────────────────────────
# 5. RUN BACKTESTS
# ─────────────────────────────────────────────────────────
from src.backtester.engine import BacktestEngine

# Use actual average risk-free rate over the backtest window only.
# DFF is in percentage points. A full-history mean (1950s–1980s) is not the
# financing rate of this sample.
if len(ff_rate) > 0:
    _ff = ff_rate.copy()
    _ff.index = pd.to_datetime(_ff.index)
    _ff = _ff.loc[str(price_data.index.min().date()):]
    avg_rf = float(_ff.mean() / 100.0) if len(_ff) else 0.02
else:
    avg_rf = 0.02  # conservative fallback: 2% risk-free rate
logger.info(f"Average Fed Funds Rate (period): {avg_rf:.2%}")

engine = BacktestEngine(
    price_data=price_data,
    initial_capital=100_000,
    risk_free_rate=avg_rf,
)

logger.info("\n" + "=" * 70)
logger.info("  RUNNING BACKTESTS")
logger.info("=" * 70)

# ── PRIMARY: Vol-Targeted Regime Strategy ────────────────────────────────
# Single production strategy. Targets: 16% CAGR | <14.8% MaxDD | Sharpe 1.2
# Vol-targeting: scales weights daily so realised vol tracks 11.8% annualised
# Bear hedge: 60% equity + 40% defense when SPY < 200-day MA (no look-ahead)
# Leveraged gate: TQQQ/SOXL only when yesterday's VIX < 20
# DD breaker: circuit breaker at portfolio drawdown threshold
logger.info("\n[1] Optimized Regime Strategy (PRIMARY)...")
# v5.1 (2026-06-23): Overlay tuning from 160-combination parameter sweep.
# bear=0.60 + dd=0.08 is the optimal balance:
#   14.86% CAGR / 1.03 Sharpe / 15.65% MaxDD / 0.95 Calmar
# vs prior: 15.13% / 1.04 / 16.28% / 0.93
# Tradeoff: -0.27% CAGR for -0.63% MaxDD improvement (Calmar +0.02).
# Overlay params come from the single source of truth (config.regime_rules.STRATEGY_PARAMS)
from config.regime_rules import STRATEGY_PARAMS
vol_result = engine.run_optimized_regime_backtest(
    regime_history=regime_history,
    regime_weights=regime_weights_filtered,
    name="Optimized Regime Strategy",
    vix_data=vix,
    **STRATEGY_PARAMS,
)

# ── BENCHMARKS (reference only) ──────────────────────────────────────────
logger.info("\n[2] Basic Regime Strategy (no overlays — upper bound reference)...")
basic_result = engine.run_regime_backtest(
    regime_history=regime_history,
    regime_weights=regime_weights_filtered,
    name="Basic Regime (upper bound)",
)

logger.info("\n[3] 60/40 Benchmark...")
benchmark_60_40 = engine.run_static_backtest(
    weights={"SPY": 0.60, "AGG": 0.40},
    name="60/40 Benchmark",
)

logger.info("\n[4] S&P 500 (SPY)...")
spy_result = engine.run_static_backtest(
    weights={"SPY": 1.0},
    name="S&P 500",
)

logger.info("\n[5] Nasdaq 100 (QQQ)...")
qqq_result = engine.run_static_backtest(
    weights={"QQQ": 1.0},
    name="Nasdaq 100 (QQQ)",
)

logger.info("\n[6] All Weather...")
all_weather = engine.run_static_backtest(
    weights={"SPY": 0.30, "TLT": 0.40, "IEF": 0.15, "GLD": 0.075, "DBC": 0.075},
    name="All Weather",
)

# ─────────────────────────────────────────────────────────
# 6. RESULTS COMPARISON
# ─────────────────────────────────────────────────────────
results = [vol_result, basic_result, benchmark_60_40, spy_result, qqq_result, all_weather]

comparison = engine.compare_strategies(results)

print("\n" + "=" * 70)
print("  20-YEAR BACKTEST RESULTS")
print("=" * 70)
print(comparison.to_string())

# ─────────────────────────────────────────────────────────
# 7. TARGET VALIDATION
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  TARGET VALIDATION")
print("=" * 70)

# Primary strategy: Vol-Targeted Regime
targets = {
    'Annual Return >= 16.0%': (vol_result.annual_return >= 0.16,
                               f"{vol_result.annual_return:.2%}"),
    'Max Drawdown < 14.8%':   (vol_result.max_drawdown < 0.148,
                               f"{vol_result.max_drawdown:.2%}"),
    'Sharpe Ratio >= 1.2':    (vol_result.sharpe_ratio >= 1.2,
                               f"{vol_result.sharpe_ratio:.2f}"),
}

all_pass = True
for target_name, (passed, actual) in targets.items():
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status}  {target_name}: {actual}")
    if not passed:
        all_pass = False

print()
if all_pass:
    print("  >>> ALL TARGETS MET! Strategy validated over 20 years.")
else:
    print("  WARNING: Some targets not met. Strategy needs tuning.")
    print("  Note: Results depend on available ETF history.")
    print("  Newer ETFs (TQQQ, SOXL, DBMF, BTAL) have limited history.")

# ─────────────────────────────────────────────────────────
# 8. DETAILED AGGRESSIVE STRATEGY STATS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  OPTIMIZED REGIME STRATEGY -- FULL DETAILS")
print("=" * 70)
print(f"  Target:         16.0% CAGR | <14.8% MaxDD | Sharpe >=1.2")
print(f"  Period:         {vol_result.start_date} -> {vol_result.end_date}")
print(f"  Total Return:   {vol_result.total_return:.2%}")
print(f"  Annual Return:  {vol_result.annual_return:.2%}")
print(f"  Volatility:     {vol_result.volatility:.2%}")
print(f"  Sharpe Ratio:   {vol_result.sharpe_ratio:.2f}")
print(f"  Sortino Ratio:  {vol_result.sortino_ratio:.2f}")
print(f"  Max Drawdown:   {vol_result.max_drawdown:.2%}")
print(f"  Calmar Ratio:   {vol_result.calmar_ratio:.2f}")
print(f"  Win Rate:       {vol_result.win_rate:.1%}")
print(f"  Regime Changes: {vol_result.num_trades}")

if vol_result.monthly_returns is not None:
    mr = vol_result.monthly_returns
    print(f"\n  Monthly Returns:")
    print(f"    Mean:       {mr.mean():.2%}")
    print(f"    Median:     {mr.median():.2%}")
    print(f"    Worst:      {mr.min():.2%}")
    print(f"    Best:       {mr.max():.2%}")
    print(f"    % Positive: {(mr > 0).sum() / len(mr):.1%}")

# Save results to CSV
results_dir = ROOT / "data" / "backtest_results"
results_dir.mkdir(parents=True, exist_ok=True)

comparison.to_csv(results_dir / "20yr_comparison.csv")

all_equity = pd.DataFrame()
for r in results:
    if r.equity_curve is not None:
        all_equity[r.name] = r.equity_curve
all_equity.to_csv(results_dir / "all_equity_curves.csv")

# Save primary strategy curves (vol-targeted)
if vol_result.equity_curve is not None:
    vol_result.equity_curve.to_csv(results_dir / "aggressive_equity_curve.csv")
if vol_result.monthly_returns is not None:
    vol_result.monthly_returns.to_csv(results_dir / "aggressive_monthly_returns.csv")

logger.info(f"\nResults saved to {results_dir}")

from src.backtester.consistency import verify_series
_consistency = verify_series(
    vol_result.annual_return,
    vol_result.total_return,
    vol_result.max_drawdown,
    vol_result.equity_curve,
    vol_result.monthly_returns,
)
print("\n" + _consistency.text())
if not _consistency.ok:
    logger.error("Consistency check failed. This run is not publishable.")
    sys.exit(3)

logger.info("Backtest complete!")
