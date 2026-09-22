"""
20-Year Backtest Validation Script
====================================
Downloads 20 years of ETF + macro data, runs regime detection,
then backtests the Vol-Targeted Regime Strategy (v7 dual sleeve).

  FONTES_RUN_MODE=backtest  (default) — XLY proxies the AIPO sleeve
  FONTES_RUN_MODE=live                — AIPO live book
  FONTES_WEIGHT_MODE=cash   (default) — missing history stays cash
  FONTES_WEIGHT_MODE=renorm           — legacy silent renorm A/B

Official public-FRED numbers (simplified engine) live in
docs/V7_FRED_DUAL_RESULTS.md — do not cite the old v5.1 8-ETF headline.

Aspirational gates still printed:
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
    get_universe, get_regime_weights_for_mode,
    get_run_mode, get_weight_mode,
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

# Dual mode (v7):
#   live     -> AIPO sleeve (real production book)
#   backtest -> XLY proxy for that sleeve (long history from 2005)
# This script is the research/backtest entrypoint → default BACKTEST mode.
# FONTES_WEIGHT_MODE=cash (default) keeps missing-history weight as cash;
# pass FONTES_WEIGHT_MODE=renorm for the legacy silent-renorm A/B.
RUN_MODE = get_run_mode("backtest")          # "backtest" | "live"
WEIGHT_MODE = get_weight_mode("cash")        # "cash" | "renorm"
V7_TICKERS = get_universe(RUN_MODE)
ALL_TICKERS = V7_TICKERS + [
    "SHY", "AGG",          # defense basket / circuit breaker
    "CADUSD=X",            # FX if CAD sleeves used in A/B
]
# Always download both sleeve tickers so mode can flip without re-fetch.
for _extra in ("AIPO", "XLY"):
    if _extra not in ALL_TICKERS:
        ALL_TICKERS.append(_extra)
logger.info("FONTES_RUN_MODE=%s  FONTES_WEIGHT_MODE=%s  universe=%s",
            RUN_MODE, WEIGHT_MODE, V7_TICKERS)

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

# Compute regime classification using rules-based approach
# (More robust than HMM for 20-year backtest)
logger.info("Computing regime classification...")

# monthly_dates always derived from price_data (never depends on FRED)
monthly_dates = price_data.resample('MS').first().index

# ── PUBLICATION LAG (no look-ahead) ──────────────────────────────────────
# FRED dates macro series at the PERIOD START, but the figures are not released
# until weeks/months later (CPI ~1mo after month start; GDP advance ~1mo after
# quarter end = ~4mo after the quarter-start observation date). Shifting the
# index forward by the release lag prevents the backtest from "knowing" macro
# data before it was actually published. (Audit: Gemini, 2026-06-22 — removing
# this look-ahead changes 15.85%/1.21 to ~14.05%/1.06; honest numbers stand.)
CPI_RELEASE_LAG_M = 1   # CPI for month M is published ~mid-M+1
GDP_RELEASE_LAG_M = 4   # GDP advance estimate ~1mo after quarter end

# CPI YoY inflation rate — guard against empty FRED data
if len(cpi) > 12:
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_yoy.index = pd.to_datetime(cpi_yoy.index) + pd.DateOffset(months=CPI_RELEASE_LAG_M)
    cpi_monthly = cpi_yoy.resample('MS').last().ffill()
else:
    logger.warning("CPI data unavailable — using fallback constant 2.5%")
    cpi_monthly = pd.Series(dtype=float)

# GDP growth (quarterly, forward-fill to monthly) — lagged to the release date
if len(gdp) > 0:
    gdp.index = pd.to_datetime(gdp.index) + pd.DateOffset(months=GDP_RELEASE_LAG_M)
    gdp_monthly = gdp.resample('MS').last().ffill()
else:
    logger.warning("GDP data unavailable — growth signal will use SPY momentum only")
    gdp_monthly = pd.Series(dtype=float)

# S&P 500 momentum (12-month) — always available from price_data
spy_prices = price_data['SPY'] if 'SPY' in price_data.columns else None
if spy_prices is not None:
    spy_monthly = spy_prices.resample('MS').last()
    spy_mom_12m = spy_monthly.pct_change(12)  # 12-month return
else:
    spy_mom_12m = pd.Series(dtype=float)

# VIX monthly average
if len(vix) > 0:
    vix.index = pd.to_datetime(vix.index)
    vix_monthly = vix.resample('MS').mean()
else:
    logger.warning("VIX data unavailable — VIX override will use SPY-based proxy")
    # Proxy VIX from SPY 21-day realised vol × 16 (annualisation ≈ VIX)
    spy_rv = price_data['SPY'].pct_change().rolling(21).std() * 16 * 100
    vix_monthly = spy_rv.resample('MS').mean()
    vix = spy_rv  # use as fallback throughout

# Yield curve (10Y - 2Y)
if len(t10y) > 0 and len(t2y) > 0:
    t10y.index = pd.to_datetime(t10y.index)
    t2y.index  = pd.to_datetime(t2y.index)
    yield_curve = (t10y - t2y).resample('MS').last()
else:
    yield_curve = pd.Series(dtype=float)

# ─────────────────────────────────────────────────────────
# REGIME CLASSIFICATION RULES
# ─────────────────────────────────────────────────────────
# Goldilocks: Rising growth + Falling/Low inflation
# Reflation:  Rising growth + Rising inflation
# Stagflation: Falling growth + Rising inflation
# Deflation:  Falling growth + Falling inflation

def classify_regime(date):
    """Rules-based regime classification for a given monthly date."""
    # Growth signal: lagged GDP > 1.5% OR SPY 12m momentum > 5%.
    # NOTE: unemployment (UNRATE) is deliberately NOT used here. Both a
    # "falling-unemployment = growth" rule (worsens MaxDD 15.5%->17.2%, it's a
    # lagging indicator that stays risk-on into downturns) and a Sahm-rule
    # "rising-unemployment = defensive" rule (cuts CAGR ~1.5pp, no DD benefit)
    # were tested and degrade results — the daily 200-MA/vol-target/DD-breaker
    # controls already react faster than a monthly labour signal. UNRATE is
    # still fetched for the dashboard's macro display. (Audit: Gemini, 2026-06-22.)
    gdp_val = gdp_monthly.asof(date) if len(gdp_monthly) > 0 else 2.0
    spy_val = spy_mom_12m.asof(date) if len(spy_mom_12m) > 0 else 0.05

    growth_rising = (gdp_val > 1.5) or (spy_val > 0.05)
    
    # Inflation signal: CPI YoY > 3% AND rising
    cpi_val = cpi_monthly.asof(date) if len(cpi_monthly) > 0 else 2.0
    cpi_3m_ago = cpi_monthly.asof(date - pd.DateOffset(months=3)) if len(cpi_monthly) > 0 else 2.0
    
    inflation_rising = (cpi_val > 3.0) and (cpi_val > cpi_3m_ago)
    
    # VIX override: if VIX > 30, force defensive
    vix_val = vix_monthly.asof(date) if len(vix_monthly) > 0 else 15.0
    if vix_val > 30:
        return 'deflation'  # Crisis mode
    
    if growth_rising and not inflation_rising:
        return 'goldilocks'
    elif growth_rising and inflation_rising:
        return 'reflation'
    elif not growth_rising and inflation_rising:
        return 'stagflation'
    else:
        return 'deflation'


# Build full regime history
regime_records = []
for date in monthly_dates:
    if date >= pd.Timestamp('2005-06-01'):  # Need 6m warmup
        regime = classify_regime(date)
        regime_records.append({'date': date, 'regime': regime})
regime_history = pd.DataFrame(regime_records)
logger.info(f"Regime history: {len(regime_history)} months")

# Print regime distribution
regime_counts = regime_history['regime'].value_counts()
for regime, count in regime_counts.items():
    pct = count / len(regime_history) * 100
    logger.info(f"  {regime}: {count} months ({pct:.1f}%)")

# ─────────────────────────────────────────────────────────
# 4. PREPARE REGIME WEIGHTS (filter to available tickers)
# ─────────────────────────────────────────────────────────
def filter_weights(weights, available, renormalize=False):
    """Filter weights to available tickers.

    Default renormalize=False = v7 cash 口径 (missing weight stays cash).
    Pass renormalize=True for legacy silent renorm A/B.
    See out/v7_fred_dual_recompute.py and docs/V7_BACKTEST_SPEC.md.
    """
    filtered = {k: v for k, v in weights.items() if k in available}
    if renormalize:
        total = sum(filtered.values())
        if total > 0:
            filtered = {k: v / total for k, v in filtered.items()}
    return filtered

# Weights follow RUN_MODE (backtest remaps AIPO → XLY)
REGIME_WEIGHTS_MODE = get_regime_weights_for_mode(RUN_MODE)
regime_weights_filtered = {}
for regime_name, weights in REGIME_WEIGHTS_MODE.items():
    filtered = filter_weights(weights, available_tickers, renormalize=(WEIGHT_MODE == "renorm"))
    regime_weights_filtered[regime_name] = filtered
    logger.info(
        f"  {regime_name} [{RUN_MODE}/{WEIGHT_MODE}]: "
        f"{len(filtered)} ETFs {list(filtered)} (from {len(weights)})"
    )

# ─────────────────────────────────────────────────────────
# 5. RUN BACKTESTS
# ─────────────────────────────────────────────────────────
from src.backtester.engine import BacktestEngine

# Use actual average risk-free rate over the backtest period
# Fall back to 2% if FRED DFF data was unavailable
if len(ff_rate) > 0:
    avg_rf = ff_rate.mean() / 100  # FRED DFF is in percentage points
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
# v7 dual sleeve (2026-09): live AIPO / backtest XLY. Overlay knobs from
# config.regime_rules.STRATEGY_PARAMS (bear=0.70, dd=0.07, HAR). Official
# public-FRED numbers are in docs/V7_FRED_DUAL_RESULTS.md — not the old
# v5.1 8-ETF 14.52%/14.78%/0.97 headline.
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

logger.info("\n[5] All Weather...")
all_weather = engine.run_static_backtest(
    weights={"SPY": 0.30, "TLT": 0.40, "IEF": 0.15, "GLD": 0.075, "DBC": 0.075},
    name="All Weather",
)

# ─────────────────────────────────────────────────────────
# 6. RESULTS COMPARISON
# ─────────────────────────────────────────────────────────
results = [vol_result, basic_result, benchmark_60_40, spy_result, all_weather]

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
logger.info("Backtest complete!")
