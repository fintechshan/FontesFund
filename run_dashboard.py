"""
run_dashboard.py
================
Dashboard launcher: loads cached data, computes current regime, launches Dash app.
"""
import sys
import os
import logging
import pickle
from pathlib import Path
from datetime import datetime

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('dashboard')

import pandas as pd
import numpy as np

from config.settings import FRED_API_KEY
PRICE_CACHE = ROOT / 'data' / 'cache' / 'price_data.csv'
MACRO_CACHE = ROOT / 'data' / 'cache' / 'macro_data.pkl'
BACKTEST_CSV = ROOT / 'data' / 'backtest_results' / '20yr_comparison.csv'

# ── Load cached data ──────────────────────────────────────────────────────
def load_price_data():
    if PRICE_CACHE.exists():
        df = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True)
        logger.info(f"Loaded price data: {df.shape[1]} ETFs, {len(df)} days")
        return df
    logger.warning("No price cache found")
    return pd.DataFrame()

def load_macro_data():
    if MACRO_CACHE.exists():
        with open(MACRO_CACHE, 'rb') as f:
            macro = pickle.load(f)
        logger.info(f"Loaded macro data: {list(macro.keys())}")
        return macro
    logger.warning("No macro cache found")
    return {'vix': pd.Series(dtype=float), 'gdp': pd.Series(dtype=float),
            'cpi': pd.Series(dtype=float), 'unemp': pd.Series(dtype=float),
            't10y': pd.Series(dtype=float), 't2y': pd.Series(dtype=float),
            'ff_rate': pd.Series(dtype=float)}

def load_backtest_results():
    if BACKTEST_CSV.exists():
        df = pd.read_csv(BACKTEST_CSV, index_col=0)
        logger.info(f"Loaded backtest results: {len(df)} strategies")
        return df
    logger.warning("No backtest results found")
    return pd.DataFrame()

# ── Regime classification ─────────────────────────────────────────────────
def classify_regimes(macro, price_data, apply_lag=True):
    """Classify economic regime for each month.
    apply_lag=True applies the CPI+1mo / GDP+4mo publication lag (production, no
    look-ahead). apply_lag=False = UNLAGGED (look-ahead) — used only to measure the
    look-ahead premium for the auditor's lagged-vs-unlagged check."""
    vix = macro.get('vix', pd.Series(dtype=float))
    gdp = macro.get('gdp', pd.Series(dtype=float))
    cpi = macro.get('cpi', pd.Series(dtype=float))

    # Compute derived series.
    # PUBLICATION LAG (no look-ahead): FRED dates CPI/GDP at the period start but
    # publishes them weeks/months later. Shift the index forward by the release
    # lag (CPI +1mo, GDP +4mo) so the live regime uses only data that was actually
    # available — must match run_backtest.py. (Audit: Gemini, 2026-06-22.)
    cpi_yoy = (cpi / cpi.shift(12) - 1) * 100 if len(cpi) > 12 else pd.Series(dtype=float)
    if len(cpi_yoy) > 0:
        cpi_yoy.index = pd.to_datetime(cpi_yoy.index)
        if apply_lag:
            cpi_yoy.index = cpi_yoy.index + pd.DateOffset(months=1)
    if len(gdp) > 0:
        gdp = gdp.copy()
        gdp.index = pd.to_datetime(gdp.index)
        if apply_lag:
            gdp.index = gdp.index + pd.DateOffset(months=4)
    gdp_monthly = gdp.resample('MS').ffill() if len(gdp) > 0 else pd.Series(dtype=float)
    vix_monthly = vix.resample('MS').mean() if len(vix) > 0 else pd.Series(dtype=float)
    cpi_monthly = cpi_yoy.resample('MS').last().ffill() if len(cpi_yoy) > 0 else pd.Series(dtype=float)

    spy_prices = price_data.get('SPY', pd.Series(dtype=float)) if not price_data.empty else pd.Series(dtype=float)
    spy_mom_12m = (spy_prices / spy_prices.shift(252) - 1) if len(spy_prices) > 252 else pd.Series(dtype=float)
    spy_mom_monthly = spy_mom_12m.resample('MS').last().ffill() if len(spy_mom_12m) > 0 else pd.Series(dtype=float)

    # Monthly dates
    if len(vix) > 0:
        monthly_dates = pd.date_range(start='2005-06-01', end=vix.index.max(), freq='MS')
    elif not price_data.empty:
        monthly_dates = pd.date_range(start='2005-06-01', end=price_data.index.max(), freq='MS')
    else:
        return pd.DataFrame(columns=['date', 'regime']), {}, {}

    records = []
    for date in monthly_dates:
        gdp_val = gdp_monthly.asof(date) if len(gdp_monthly) > 0 else 2.0
        spy_val = spy_mom_monthly.asof(date) if len(spy_mom_monthly) > 0 else 0.05
        growth_rising = (gdp_val > 1.5) or (spy_val > 0.05)

        cpi_val = cpi_monthly.asof(date) if len(cpi_monthly) > 0 else 2.0
        cpi_3m_ago = cpi_monthly.asof(date - pd.DateOffset(months=3)) if len(cpi_monthly) > 0 else 2.0
        inflation_rising = (cpi_val > 3.0) and (cpi_val > cpi_3m_ago)

        vix_val = vix_monthly.asof(date) if len(vix_monthly) > 0 else 15.0
        if vix_val > 30:
            regime = 'deflation'
        elif growth_rising and not inflation_rising:
            regime = 'goldilocks'
        elif growth_rising and inflation_rising:
            regime = 'reflation'
        elif not growth_rising and inflation_rising:
            regime = 'stagflation'
        else:
            regime = 'deflation'

        records.append({'date': date, 'regime': regime})

    regime_history = pd.DataFrame(records)

    # Current snapshot values
    current = {
        'regime': records[-1]['regime'] if records else 'goldilocks',
        'vix': float(vix.iloc[-1]) if len(vix) > 0 else 0.0,
        'yield_curve': float((macro['t10y'].iloc[-1] - macro['t2y'].iloc[-1])) if len(macro.get('t10y', [])) > 0 and len(macro.get('t2y', [])) > 0 else 0.0,
        'cpi_yoy': float(cpi_yoy.iloc[-1]) if len(cpi_yoy) > 0 else 0.0,
        'gdp': float(gdp.iloc[-1]) if len(gdp) > 0 else 0.0,
        'spy_momentum': float(spy_mom_12m.iloc[-1]) if len(spy_mom_12m) > 0 else 0.0,
    }

    # Compute confidence (how clearly signals align)
    confidence = 50.0
    r = current['regime']
    if r == 'goldilocks':
        if current['gdp'] > 2.0: confidence += 15
        if current['spy_momentum'] > 0.10: confidence += 15
        if current['vix'] < 18: confidence += 10
        if current['cpi_yoy'] < 3.0: confidence += 10
    elif r == 'reflation':
        if current['gdp'] > 2.0: confidence += 15
        if current['cpi_yoy'] > 3.5: confidence += 15
        if current['spy_momentum'] > 0: confidence += 10
    elif r == 'stagflation':
        if current['gdp'] < 1.0: confidence += 15
        if current['cpi_yoy'] > 4.0: confidence += 15
        if current['vix'] > 25: confidence += 10
    elif r == 'deflation':
        if current['gdp'] < 1.0: confidence += 15
        if current['vix'] > 25: confidence += 15
        if current['yield_curve'] < 0: confidence += 10

    current['confidence'] = min(100, confidence)

    return regime_history, current, {'cpi_yoy': cpi_yoy, 'cpi_monthly': cpi_monthly,
                                      'gdp_monthly': gdp_monthly, 'vix_monthly': vix_monthly,
                                      'spy_mom_monthly': spy_mom_monthly}


# ── Build DASHBOARD_DATA ──────────────────────────────────────────────────
logger.info("=" * 60)
logger.info("  ETF REGIME STRATEGIST — DASHBOARD LAUNCHER")
logger.info("=" * 60)

# Optional legacy GCS pull before loading. No-op when GCS_BUCKET is unset
# (the Render path). The app then uses files already on disk.
try:
    from src.dashboard.gcs_sync import download_data as _gcs_download
    _gcs_download()
except Exception as _e:
    logger.warning(f"GCS startup sync skipped: {_e}")

price_data = load_price_data()
macro = load_macro_data()
backtest_results = load_backtest_results()
regime_history, current, derived = classify_regimes(macro, price_data)
# Unlagged regime (look-ahead) — only for the auditor's lagged-vs-unlagged check
regime_history_unlagged, _, _ = classify_regimes(macro, price_data, apply_lag=False)

# Get weights for current regime
try:
    from config.regime_rules import REGIME_WEIGHTS
    current_weights = REGIME_WEIGHTS.get(current.get('regime', 'goldilocks'), {})
    # Filter to available tickers
    avail = set(price_data.columns) if not price_data.empty else set()
    current_weights = {k: v for k, v in current_weights.items() if k in avail}
    total = sum(current_weights.values())
    if total > 0:
        current_weights = {k: v / total for k, v in current_weights.items()}
except Exception as e:
    logger.warning(f"Could not load regime weights: {e}")
    current_weights = {}

logger.info(f"Current regime: {current.get('regime', 'unknown')} (confidence: {current.get('confidence', 0):.0f}%)")
logger.info(f"VIX: {current.get('vix', 0):.1f} | Yield Curve: {current.get('yield_curve', 0):.2f} | CPI YoY: {current.get('cpi_yoy', 0):.1f}%")
logger.info(f"Portfolio: {len(current_weights)} ETFs")

# Compute equity curves — load ALL strategies
all_equity_curves = pd.DataFrame()
all_eq_path = ROOT / 'data' / 'backtest_results' / 'all_equity_curves.csv'
if all_eq_path.exists():
    try:
        all_equity_curves = pd.read_csv(all_eq_path, index_col=0, parse_dates=True)
        logger.info(f"Loaded all equity curves: {list(all_equity_curves.columns)}")
    except Exception:
        pass

equity_curve = pd.Series(dtype=float)
# Try the vol-targeted strategy curve first, fall back to any available
for col_name in ['Optimized Regime Strategy', 'Vol-Targeted Regime Strategy', 'Protected Regime Strategy', 'Aggressive Regime Strategy']:
    if col_name in all_equity_curves.columns:
        equity_curve = all_equity_curves[col_name]
        logger.info(f"Equity curve ({col_name}): {len(equity_curve)} points, range {equity_curve.min():.1f} - {equity_curve.max():.1f}")
        break
if equity_curve.empty:
    for eq_file in ['aggressive_equity_curve.csv']:
        eq_path = ROOT / 'data' / 'backtest_results' / eq_file
        if eq_path.exists():
            try:
                eq = pd.read_csv(eq_path, index_col=0, parse_dates=True)
                equity_curve = eq.iloc[:, 0]
                logger.info(f"Loaded equity curve from {eq_file}: {len(equity_curve)} points")
                break
            except Exception:
                pass

# Compute regime change log (for portfolio transparency)
regime_changes = []
if not regime_history.empty and len(regime_history) > 1:
    rh = regime_history.copy()
    prev_regime = None
    for _, row in rh.iterrows():
        r = row['regime']
        d = row['date']
        if prev_regime is not None and r != prev_regime:
            # Compute what weights changed
            try:
                old_w = REGIME_WEIGHTS.get(prev_regime, {})
                new_w = REGIME_WEIGHTS.get(r, {})
                # Filter to available
                old_f = {k: v for k, v in old_w.items() if k in avail}
                new_f = {k: v for k, v in new_w.items() if k in avail}
                t_old = sum(old_f.values()) or 1
                t_new = sum(new_f.values()) or 1
                old_f = {k: v/t_old for k, v in old_f.items()}
                new_f = {k: v/t_new for k, v in new_f.items()}

                # Key changes
                all_tickers = set(list(old_f.keys()) + list(new_f.keys()))
                changes = []
                for t in sorted(all_tickers, key=lambda x: abs(new_f.get(x,0) - old_f.get(x,0)), reverse=True)[:5]:
                    delta = new_f.get(t, 0) - old_f.get(t, 0)
                    if abs(delta) > 0.01:
                        changes.append(f"{t}: {delta:+.1%}")

                regime_changes.append({
                    'date': d.strftime('%Y-%m') if hasattr(d, 'strftime') else str(d)[:7],
                    'from_regime': prev_regime,
                    'to_regime': r,
                    'reason': f"Growth {'rising' if r in ['goldilocks','reflation'] else 'falling'}, "
                              f"Inflation {'rising' if r in ['reflation','stagflation'] else 'falling'}",
                    'key_changes': ' | '.join(changes) if changes else 'Minor rebalance',
                })
            except Exception:
                regime_changes.append({
                    'date': d.strftime('%Y-%m') if hasattr(d, 'strftime') else str(d)[:7],
                    'from_regime': prev_regime, 'to_regime': r,
                    'reason': 'Macro shift', 'key_changes': '—',
                })
        prev_regime = r

# Get previous month's weights for comparison
prev_weights = {}
if len(regime_history) >= 2:
    prev_regime_name = regime_history.iloc[-2]['regime']
    try:
        prev_w = REGIME_WEIGHTS.get(prev_regime_name, {})
        prev_w = {k: v for k, v in prev_w.items() if k in avail}
        t = sum(prev_w.values()) or 1
        prev_weights = {k: v/t for k, v in prev_w.items()}
    except Exception:
        pass

# Monthly returns for heatmap
monthly_returns = pd.Series(dtype=float)
mr_path = ROOT / 'data' / 'backtest_results' / 'aggressive_monthly_returns.csv'
if mr_path.exists():
    try:
        mr = pd.read_csv(mr_path, index_col=0, parse_dates=True)
        monthly_returns = mr.iloc[:, 0]
    except Exception:
        pass

# ── Run Look-Ahead Bias Lagged Backtest Simulation ─────────────────────────
logger.info("Running Look-Ahead Bias lagged simulation...")
lagged_metrics = {}
try:
    from src.backtester.engine import BacktestEngine
    
    # Risk-free rate
    ff_rate = macro.get('ff_rate', pd.Series(dtype=float))
    avg_rf = ff_rate.mean() / 100 if not ff_rate.empty else 0.0185
    
    # Initialize engine
    engine = BacktestEngine(price_data, initial_capital=100000, risk_free_rate=avg_rf)
    
    # Optimized Regime Strategy — the single production strategy
    # (risk-parity + portfolio-level vol targeting; see CLAUDE.md / RECOMMENDATION.md).
    # Replaces the old run_vol_targeted_* (SPY-vol-proxy bug). Honest, no-look-ahead
    # headline is currently ~14.52% CAGR / 14.78% MaxDD / 0.97 Sharpe (data thru 2026-06;
    # this comment is not displayed — the UI reads the live result CSVs).
    vix_series = macro.get('vix')
    from config.regime_rules import STRATEGY_PARAMS  # single source of truth
    standard_res = engine.run_optimized_regime_backtest(
        regime_history=regime_history,
        regime_weights=REGIME_WEIGHTS,
        name="Optimized Regime Strategy",
        vix_data=vix_series,
        **STRATEGY_PARAMS,
    )

    # 1-Month Lagged Backtest (simulates macro release reporting lag)
    lagged_rh = regime_history.copy()
    lagged_rh['regime'] = lagged_rh['regime'].shift(1).bfill()
    lagged_res = engine.run_optimized_regime_backtest(
        regime_history=lagged_rh,
        regime_weights=REGIME_WEIGHTS,
        name="Optimized Regime Strategy (Lagged)",
        vix_data=vix_series,
        **STRATEGY_PARAMS,
    )

    # UNLAGGED backtest (look-ahead) — for the auditor's lagged-vs-unlagged check.
    # Production = standard_res (lagged). If unlagged ≈ standard, the lag isn't being
    # applied (look-ahead risk). If unlagged >> standard, the lag is removing a real
    # look-ahead premium (working as intended).
    unlagged_res = engine.run_optimized_regime_backtest(
        regime_history=regime_history_unlagged,
        regime_weights=REGIME_WEIGHTS,
        name="Optimized Regime Strategy (Unlagged)",
        vix_data=vix_series,
        **STRATEGY_PARAMS,
    )

    lagged_metrics = {
        'standard': {
            'annual_return': f"{standard_res.annual_return:.2%}",
            'sharpe': f"{standard_res.sharpe_ratio:.2f}",
            'max_dd': f"{standard_res.max_drawdown:.2%}",
            'total_return': f"{standard_res.total_return:.2%}"
        },
        'lagged': {
            'annual_return': f"{lagged_res.annual_return:.2%}",
            'sharpe': f"{lagged_res.sharpe_ratio:.2f}",
            'max_dd': f"{lagged_res.max_drawdown:.2%}",
            'total_return': f"{lagged_res.total_return:.2%}"
        },
        'unlagged': {
            'annual_return': f"{unlagged_res.annual_return:.2%}",
            'sharpe': f"{unlagged_res.sharpe_ratio:.2f}",
            'max_dd': f"{unlagged_res.max_drawdown:.2%}",
            'total_return': f"{unlagged_res.total_return:.2%}"
        },
        'standard_curve': standard_res.equity_curve,
        'lagged_curve': lagged_res.equity_curve
    }
    logger.info("Look-Ahead Bias lagged simulation completed successfully.")
except Exception as e:
    logger.error(f"Error running lagged backtest simulation: {e}")
    lagged_metrics = {}

# ── Run Independent Audit ─────────────────────────────────────────────────
logger.info("Running Independent Audit...")
audit_results = {}
try:
    from src.dashboard.auditor import run_independent_audit
    audit_results = run_independent_audit(price_data, macro, backtest_results, regime_history, all_equity_curves, lagged_metrics)
    audit_results['lagged_metrics'] = lagged_metrics
    logger.info("Independent Audit completed successfully.")
except Exception as e:
    logger.error(f"Error running independent audit: {e}")
    audit_results = {'lagged_metrics': lagged_metrics}

# Get modification timestamps for cache files
price_mtime = datetime.fromtimestamp(PRICE_CACHE.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S') if PRICE_CACHE.exists() else 'N/A'
macro_mtime = datetime.fromtimestamp(MACRO_CACHE.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S') if MACRO_CACHE.exists() else 'N/A'
backtest_mtime = datetime.fromtimestamp(BACKTEST_CSV.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S') if BACKTEST_CSV.exists() else 'N/A'
audit_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ── AI Trend Intelligence (SemiAnalysis feed + bank research + sector signals) ──
try:
    from src.strategist.ai_trend import build_ai_trend_intelligence
    ai_trend = build_ai_trend_intelligence(
        price_data, current.get('regime', 'goldilocks'), current_weights)
    logger.info(f"AI Trend Intelligence: sector={ai_trend['signals'].get('sector_signal')} "
                f"verdict={ai_trend['verification'].get('verdict')} "
                f"({len(ai_trend['semianalysis'])} SemiAnalysis items)")
except Exception as e:
    logger.warning(f"AI Trend Intelligence unavailable: {e}")
    ai_trend = {}

# ── Initialize IBKR Execution Modules ─────────────────────────────────────
# SUSPENDED: IBKR integration paused while evaluating switch to MOOMOO Canada.
# Set ENABLE_IBKR=1 to re-enable.
_ibkr_broker = None
_ibkr_risk_mgr = None
_ibkr_order_mgr = None
if os.environ.get('ENABLE_IBKR', '0') == '1':
    logger.info("Initializing IBKR execution modules...")
    try:
        from src.execution.broker import IBKRBroker
        from src.execution.risk_manager import RiskManager
        from src.execution.order_manager import OrderManager
        _ibkr_host = os.environ.get('IBKR_HOST', '127.0.0.1')
        _ibkr_port = int(os.environ.get('IBKR_PORT', '7497'))
        _ibkr_client_id = int(os.environ.get('IBKR_CLIENT_ID', '1'))
        _ibkr_broker = IBKRBroker(host=_ibkr_host, port=_ibkr_port, client_id=_ibkr_client_id)
        _ibkr_risk_mgr = RiskManager()
        _ibkr_order_mgr = OrderManager()
        logger.info(f"Execution modules initialized — IBKR target: {_ibkr_host}:{_ibkr_port}")

        # Auto-connect when running on Cloud Run with IB Gateway VM (non-localhost)
        if _ibkr_host != '127.0.0.1':
            try:
                if _ibkr_broker.connect():
                    accounts = _ibkr_broker._ib.managedAccounts() if _ibkr_broker._ib else []
                    logger.info(f"IBKR auto-connect SUCCESS — accounts: {accounts}")
                else:
                    logger.warning(f"IBKR auto-connect to {_ibkr_host}:{_ibkr_port} failed — check IB Gateway VM")
            except Exception as conn_err:
                logger.warning(f"IBKR auto-connect error: {conn_err}")
        else:
            logger.info("Local mode — click Connect in Execution tab to link TWS")
    except Exception as exec_err:
        logger.warning(f"Execution module init failed: {exec_err} — Execution tab will show OFFLINE")
else:
    logger.info("IBKR execution modules SUSPENDED (ENABLE_IBKR not set). Execution tab is inactive.")

# ── Load Canadian ETF Portfolio Data ──────────────────────────────────────
CDN_EQUITY_CURVE    = pd.Series(dtype=float)
CDN_MONTHLY_RETURNS = pd.Series(dtype=float)
CDN_BACKTEST_META   = {}
CDN_WEIGHTS         = {}
CDN_ALL_WEIGHTS     = {}
try:
    from config.cdn_regime_rules import CDN_REGIME_WEIGHTS, CDN_UNIVERSE, CDN_VERSION
    CDN_ALL_WEIGHTS = CDN_REGIME_WEIGHTS
    _cdn_eq_path = ROOT / 'data' / 'backtest_results' / 'cdn_equity_curve.csv'
    _cdn_mr_path = ROOT / 'data' / 'backtest_results' / 'cdn_monthly_returns.csv'
    _cdn_cfg_path = ROOT / 'data' / 'backtest_results' / 'cdn_strategy_config.json'
    if _cdn_eq_path.exists():
        CDN_EQUITY_CURVE = pd.read_csv(_cdn_eq_path, index_col=0, parse_dates=True).iloc[:, 0]
    if _cdn_mr_path.exists():
        CDN_MONTHLY_RETURNS = pd.read_csv(_cdn_mr_path, index_col=0, parse_dates=True).iloc[:, 0]
    if _cdn_cfg_path.exists():
        import json as _json
        CDN_BACKTEST_META = _json.loads(_cdn_cfg_path.read_text())
    # Current CDN weights for the live regime
    _cdn_r = current.get('regime', 'goldilocks')
    CDN_WEIGHTS = CDN_REGIME_WEIGHTS.get(_cdn_r, CDN_REGIME_WEIGHTS['goldilocks'])
    
    # Compute Canadian rebalancing history
    CDN_REGIME_CHANGES = []
    if not regime_history.empty:
        _rh_cdn = regime_history[regime_history['date'] >= '2012-11-01'].copy()
        _prev_r = None
        for _, _row in _rh_cdn.iterrows():
            _r = _row['regime']
            _d = _row['date']
            if _prev_r is not None and _r != _prev_r:
                _old_w = CDN_REGIME_WEIGHTS.get(_prev_r, {})
                _new_w = CDN_REGIME_WEIGHTS.get(_r, {})
                _diffs = []
                for _t in CDN_UNIVERSE:
                    _delta = _new_w.get(_t, 0) - _old_w.get(_t, 0)
                    if abs(_delta) > 0.01:
                        _diffs.append(f"{_t}: {_delta:+.0%}")
                _g_desc = 'rising' if _r in ['goldilocks','reflation'] else 'slowing'
                _i_desc = 'rising' if _r in ['reflation','stagflation'] else 'cooling'
                CDN_REGIME_CHANGES.append({
                    'date': _d.strftime('%Y-%m') if hasattr(_d, 'strftime') else str(_d)[:7],
                    'from_regime': _prev_r.capitalize(),
                    'to_regime': _r.capitalize(),
                    'reason': f"Growth {_g_desc}, Inflation {_i_desc}",
                    'key_changes': ' | '.join(_diffs) if _diffs else 'Allocation shift'
                })
            _prev_r = _r
    
    logger.info(f"CDN portfolio loaded: {CDN_VERSION}, regime={_cdn_r}, {len(CDN_WEIGHTS)} ETFs, {len(CDN_REGIME_CHANGES)} rebalance events")
except Exception as _cdn_err:
    logger.warning(f"CDN portfolio data load failed: {_cdn_err}")
    CDN_REGIME_CHANGES = []

DASHBOARD_DATA = {

    'price_data': price_data,
    'macro': macro,
    'derived': derived,
    'ai_trend': ai_trend,
    'backtest_results': backtest_results,
    'regime_history': regime_history,
    'current_regime': current.get('regime', 'goldilocks'),
    'current_weights': current_weights,
    'prev_weights': prev_weights,
    'vix_current': current.get('vix', 0.0),
    'yield_curve_current': current.get('yield_curve', 0.0),
    'cpi_yoy_current': current.get('cpi_yoy', 0.0),
    'gdp_current': current.get('gdp', 0.0),
    'spy_momentum': current.get('spy_momentum', 0.0),
    'regime_confidence': current.get('confidence', 50.0),
    'equity_curve': equity_curve,
    'all_equity_curves': all_equity_curves,
    'monthly_returns': monthly_returns,
    'regime_changes': regime_changes,
    'all_regime_weights': REGIME_WEIGHTS,
    'audit': audit_results,
    # Canadian ETF Portfolio
    'cdn_equity_curve':    CDN_EQUITY_CURVE,
    'cdn_monthly_returns': CDN_MONTHLY_RETURNS,
    'cdn_backtest_meta':   CDN_BACKTEST_META,
    'cdn_current_weights': CDN_WEIGHTS,
    'cdn_all_weights':     CDN_ALL_WEIGHTS,
    'cdn_regime_changes':  CDN_REGIME_CHANGES,

    # Goldman Sachs Bull/Bear Market Indicator (GSBLBR)
    'gsblbr_data': (lambda: (
        pd.read_csv(ROOT / 'data' / 'cache' / 'gsblbr_history.csv', index_col=0, parse_dates=True)
        if (ROOT / 'data' / 'cache' / 'gsblbr_history.csv').exists() else pd.DataFrame()
    ))(),

    'timestamps': {
        'price_data': price_mtime,
        'macro_data': macro_mtime,
        'backtest_results': backtest_mtime,
        'audit_run': audit_time,
    },
    # IBKR Execution objects (underscore-prefixed for internal use)
    '_broker': _ibkr_broker,
    '_risk_manager': _ibkr_risk_mgr,
    '_order_manager': _ibkr_order_mgr,
}

# ── Hermes Agent Integration ───────────────────────────────────────────────
# Determine if regime has changed on startup compared to previous month
startup_alert_level = 'INFO'
startup_alert_msg = 'No active rebalance required. Portfolio matches current economic regime.'
prev_regime_val = None
if not regime_history.empty and len(regime_history) >= 2:
    prev_regime_val = regime_history.iloc[-2]['regime']
    curr_regime_val = regime_history.iloc[-1]['regime']
    if curr_regime_val != prev_regime_val:
        startup_alert_level = 'CRITICAL'
        startup_alert_msg = f"Economic regime changed from {prev_regime_val} to {curr_regime_val}. Portfolio rebalancing is required."

HERMES_DATA = {
    'latest_alert': {
        'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'type': 'rebalance_alert',
        'alert_level': startup_alert_level,
        'message': startup_alert_msg,
        'current_regime': current.get('regime', 'goldilocks'),
        'target_weights': current_weights
    }
}
if prev_regime_val and startup_alert_level == 'CRITICAL':
    HERMES_DATA['latest_alert']['previous_regime'] = prev_regime_val
    HERMES_DATA['latest_alert']['new_regime'] = current.get('regime', 'goldilocks')

def generate_regime_report(app_data):
    return {
        "timestamp": datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        "type": "daily_regime_report",
        "status": "success",
        "current_regime": app_data.get('current_regime', 'goldilocks'),
        "confidence_score": float(app_data.get('regime_confidence', 50.0)),
        "macro_snapshot": {
            "vix": float(app_data.get('vix_current', 0.0)),
            "yield_curve_10y2y": float(app_data.get('yield_curve_current', 0.0)),
            "cpi_yoy": float(app_data.get('cpi_yoy_current', 0.0)),
            "gdp_current": float(app_data.get('gdp_current', 0.0)),
            "spy_momentum_12m": float(app_data.get('spy_momentum', 0.0))
        },
        "portfolio_allocation": app_data.get('current_weights', {})
    }

def send_hermes_notification(payload):
    import os
    import requests
    url = os.environ.get('HERMES_WEBHOOK_URL')
    if not url:
        logger.warning("HERMES_WEBHOOK_URL not configured in environment. Skipping webhook push.")
        return False
    try:
        logger.info(f"Sending webhook notification to Hermes Agent: {payload.get('type')}")
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code in [200, 201, 202, 204]:
            logger.info("Webhook delivered successfully to Hermes Agent.")
            return True
        else:
            logger.error(f"Failed to deliver webhook to Hermes: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending webhook to Hermes Agent: {e}")
        return False

# ── Background Updater ──────────────────────────────────────────────────────
def start_background_updater(app_data):
    """Start background data updater thread."""
    import threading
    
    def worker():
        import time
        import subprocess
        
        # Wait for the main Dash server to start up
        time.sleep(10)
        
        # Send initial startup report and alert to Hermes Agent
        try:
            report = generate_regime_report(app_data)
            send_hermes_notification(report)
            
            # Send initial rebalance alert if it's CRITICAL on startup
            if HERMES_DATA['latest_alert'].get('alert_level') == 'CRITICAL':
                send_hermes_notification(HERMES_DATA['latest_alert'])
        except Exception as he:
            logger.error(f"Error sending initial Hermes report/alert: {he}")

        # Render free/starter is 512 MB and the price/macro caches are not in
        # the image. An automatic run_backtest.py here OOM-kills the web process.
        # The Blueprint sets DISABLE_STARTUP_REFRESH=1. Unset locally and on the
        # legacy Cloud Run service, so this block keeps the old behavior there.
        if os.environ.get("DISABLE_STARTUP_REFRESH", "0").strip().lower() in {"1", "true", "yes", "on"}:
            logger.info(
                "DISABLE_STARTUP_REFRESH is set; serving baked files. "
                "POST /tasks/refresh to regenerate on this instance."
            )
            return

        logger.info("Checking if data caches are stale or missing...")
        stale = False
        
        # Check price data cache age
        if not PRICE_CACHE.exists() or not MACRO_CACHE.exists():
            stale = True
        else:
            price_age = (time.time() - PRICE_CACHE.stat().st_mtime) / 86400.0
            macro_age = (time.time() - MACRO_CACHE.stat().st_mtime) / 86400.0
            if price_age >= 1.0 or macro_age >= 1.0:
                stale = True
                
        if stale:
            logger.info("Data cache is missing or older than 1 day. Starting background update via run_backtest.py...")
            try:
                # Run the backtest script as a subprocess to refresh caches and CSVs
                res = subprocess.run([sys.executable, 'run_backtest.py'], capture_output=True, text=True)
                if res.returncode == 0:
                    logger.info("run_backtest.py succeeded. Reloading data in memory...")
                    # Reload the data files
                    new_price = load_price_data()
                    new_macro = load_macro_data()
                    new_backtest = load_backtest_results()
                    
                    if not new_price.empty and new_macro:
                        new_rh, new_curr, new_derived = classify_regimes(new_macro, new_price)
                        
                        # Get weights
                        from config.regime_rules import REGIME_WEIGHTS
                        new_weights = REGIME_WEIGHTS.get(new_curr.get('regime', 'goldilocks'), {})
                        avail = set(new_price.columns)
                        new_weights = {k: v for k, v in new_weights.items() if k in avail}
                        tot = sum(new_weights.values())
                        if tot > 0:
                            new_weights = {k: v / tot for k, v in new_weights.items()}
                            
                        # Prior weights
                        prev_weights = {}
                        if len(new_rh) > 1:
                            prev_regime = new_rh.iloc[-2]['regime']
                            prev_weights = REGIME_WEIGHTS.get(prev_regime, {})
                            prev_weights = {k: v for k, v in prev_weights.items() if k in avail}
                            tot_p = sum(prev_weights.values())
                            if tot_p > 0:
                                prev_weights = {k: v / tot_p for k, v in prev_weights.items()}
                                
                        # Recent changes
                        regime_changes = []
                        if not new_rh.empty and len(new_rh) > 1:
                            rh = new_rh.copy()
                            prev_regime = None
                            for _, row in rh.iterrows():
                                r = row['regime']
                                d = row['date']
                                if prev_regime is not None and r != prev_regime:
                                    try:
                                        old_w = REGIME_WEIGHTS.get(prev_regime, {})
                                        new_w = REGIME_WEIGHTS.get(r, {})
                                        old_f = {k: v for k, v in old_w.items() if k in avail}
                                        new_f = {k: v for k, v in new_w.items() if k in avail}
                                        t_old = sum(old_f.values()) or 1
                                        t_new = sum(new_f.values()) or 1
                                        old_f = {k: v/t_old for k, v in old_f.items()}
                                        new_f = {k: v/t_new for k, v in new_f.items()}
                                        all_tickers = set(list(old_f.keys()) + list(new_f.keys()))
                                        changes = []
                                        for t in sorted(all_tickers, key=lambda x: abs(new_f.get(x,0) - old_f.get(x,0)), reverse=True)[:5]:
                                            delta = new_f.get(t, 0) - old_f.get(t, 0)
                                            if abs(delta) > 0.01:
                                                changes.append(f"{t}: {delta:+.1%}")
                                        regime_changes.append({
                                            'date': d.strftime('%Y-%m') if hasattr(d, 'strftime') else str(d)[:7],
                                            'from_regime': prev_regime,
                                            'to_regime': r,
                                            'reason': f"Growth {'rising' if r in ['goldilocks','reflation'] else 'falling'}, "
                                                      f"Inflation {'rising' if r in ['reflation','stagflation'] else 'falling'}",
                                            'key_changes': ' | '.join(changes) if changes else 'Minor rebalance',
                                        })
                                    except Exception:
                                        regime_changes.append({
                                            'date': d.strftime('%Y-%m') if hasattr(d, 'strftime') else str(d)[:7],
                                            'from_regime': prev_regime, 'to_regime': r,
                                            'reason': 'Macro shift', 'key_changes': '—',
                                        })
                                prev_regime = r
                                
                        # Monthly returns
                        monthly_returns = pd.Series(dtype=float)
                        mr_path = ROOT / 'data' / 'backtest_results' / 'aggressive_monthly_returns.csv'
                        if mr_path.exists():
                            try:
                                mr = pd.read_csv(mr_path, index_col=0, parse_dates=True)
                                monthly_returns = mr.iloc[:, 0]
                            except Exception:
                                pass
                                
                        # Reload curves
                        all_eq_path = ROOT / 'data' / 'backtest_results' / 'all_equity_curves.csv'
                        all_equity_curves = pd.DataFrame()
                        if all_eq_path.exists():
                            try:
                                all_equity_curves = pd.read_csv(all_eq_path, index_col=0, parse_dates=True)
                            except Exception:
                                pass
                                
                        equity_curve = pd.Series(dtype=float)
                        for col_name in ['Optimized Regime Strategy', 'Vol-Targeted Regime Strategy', 'Protected Regime Strategy', 'Aggressive Regime Strategy']:
                            if col_name in all_equity_curves.columns:
                                equity_curve = all_equity_curves[col_name]
                                break
                            
                        # Lagged
                        from src.backtester.engine import BacktestEngine
                        ff_rate = new_macro.get('ff_rate', pd.Series(dtype=float))
                        avg_rf = ff_rate.mean() / 100 if not ff_rate.empty else 0.0185
                        engine = BacktestEngine(new_price, initial_capital=100000, risk_free_rate=avg_rf)
                        vix_series_new = new_macro.get('vix')
                        from config.regime_rules import STRATEGY_PARAMS  # single source
                        standard_res = engine.run_optimized_regime_backtest(
                            new_rh, REGIME_WEIGHTS, name="Optimized Regime Strategy",
                            vix_data=vix_series_new, **STRATEGY_PARAMS,
                        )
                        lagged_rh = new_rh.copy()
                        lagged_rh['regime'] = lagged_rh['regime'].shift(1).bfill()
                        lagged_res = engine.run_optimized_regime_backtest(
                            lagged_rh, REGIME_WEIGHTS, name="Optimized Regime Strategy (Lagged)",
                            vix_data=vix_series_new, **STRATEGY_PARAMS,
                        )
                        # Unlagged (look-ahead) — keeps the auditor's lagged-vs-unlagged
                        # check alive after an in-app refresh (not just on cold start).
                        new_rh_unlag, _, _ = classify_regimes(new_macro, new_price, apply_lag=False)
                        unlagged_res = engine.run_optimized_regime_backtest(
                            new_rh_unlag, REGIME_WEIGHTS, name="Optimized Regime Strategy (Unlagged)",
                            vix_data=vix_series_new, **STRATEGY_PARAMS,
                        )
                        lagged_metrics = {
                            'standard': {
                                'annual_return': f"{standard_res.annual_return:.2%}",
                                'sharpe': f"{standard_res.sharpe_ratio:.2f}",
                                'max_dd': f"{standard_res.max_drawdown:.2%}",
                                'total_return': f"{standard_res.total_return:.2%}"
                            },
                            'lagged': {
                                'annual_return': f"{lagged_res.annual_return:.2%}",
                                'sharpe': f"{lagged_res.sharpe_ratio:.2f}",
                                'max_dd': f"{lagged_res.max_drawdown:.2%}",
                                'total_return': f"{lagged_res.total_return:.2%}"
                            },
                            'unlagged': {
                                'annual_return': f"{unlagged_res.annual_return:.2%}",
                                'sharpe': f"{unlagged_res.sharpe_ratio:.2f}",
                                'max_dd': f"{unlagged_res.max_drawdown:.2%}",
                                'total_return': f"{unlagged_res.total_return:.2%}"
                            },
                            'standard_curve': standard_res.equity_curve,
                            'lagged_curve': lagged_res.equity_curve
                        }

                        # Auditor
                        from src.dashboard.auditor import run_independent_audit
                        new_audit = run_independent_audit(new_price, new_macro, new_backtest, new_rh, all_equity_curves, lagged_metrics)
                        new_audit['lagged_metrics'] = lagged_metrics
                        
                        # Timestamps
                        price_mtime = datetime.fromtimestamp(PRICE_CACHE.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        macro_mtime = datetime.fromtimestamp(MACRO_CACHE.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        backtest_mtime = datetime.fromtimestamp(BACKTEST_CSV.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        audit_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Store old regime before applying updates
                        old_regime = app_data.get('current_regime', 'goldilocks')
                        
                        # Apply atomically
                        app_data['price_data'] = new_price
                        app_data['macro'] = new_macro
                        app_data['derived'] = new_derived
                        app_data['backtest_results'] = new_backtest
                        app_data['regime_history'] = new_rh
                        app_data['current_regime'] = new_curr.get('regime', 'goldilocks')
                        app_data['current_weights'] = new_weights
                        app_data['prev_weights'] = prev_weights
                        app_data['vix_current'] = new_curr.get('vix', 0.0)
                        app_data['yield_curve_current'] = new_curr.get('yield_curve', 0.0)
                        app_data['cpi_yoy_current'] = new_curr.get('cpi_yoy', 0.0)
                        app_data['gdp_current'] = new_curr.get('gdp', 0.0)
                        app_data['spy_momentum'] = new_curr.get('spy_momentum', 0.0)
                        app_data['regime_confidence'] = new_curr.get('confidence', 50.0)
                        app_data['equity_curve'] = equity_curve
                        app_data['all_equity_curves'] = all_equity_curves
                        app_data['monthly_returns'] = monthly_returns
                        app_data['regime_changes'] = regime_changes
                        try:
                            from src.strategist.ai_trend import build_ai_trend_intelligence
                            app_data['ai_trend'] = build_ai_trend_intelligence(
                                new_price, new_curr.get('regime', 'goldilocks'), new_weights)
                        except Exception as _e:
                            logger.warning(f"AI Trend refresh failed: {_e}")
                        app_data['audit'] = new_audit
                        app_data['timestamps'] = {
                            'price_data': price_mtime,
                            'macro_data': macro_mtime,
                            'backtest_results': backtest_mtime,
                            'audit_run': audit_time,
                        }
                        
                        logger.info("DASHBOARD_DATA has been updated in-memory with fresh values!")
                        
                        # Hermes notifications
                        try:
                            # Push daily report
                            report = generate_regime_report(app_data)
                            send_hermes_notification(report)
                            
                            # Push rebalance alert if regime changed
                            new_regime = new_curr.get('regime', 'goldilocks')
                            if new_regime != old_regime:
                                alert = {
                                    "timestamp": datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                    "type": "rebalance_alert",
                                    "alert_level": "CRITICAL",
                                    "message": f"Economic regime changed from {old_regime} to {new_regime}. Portfolio rebalancing is required.",
                                    "previous_regime": old_regime,
                                    "new_regime": new_regime,
                                    "target_weights": new_weights
                                }
                                HERMES_DATA['latest_alert'] = alert
                                send_hermes_notification(alert)
                        except Exception as he:
                            logger.error(f"Error executing Hermes webhook notifications: {he}")
                else:
                    logger.error(f"run_backtest.py subprocess failed: {res.stderr}")
            except Exception as e:
                logger.error(f"Error in background update worker: {e}", exc_info=True)
        else:
            logger.info("Data cache is fresh. No background update required.")
            
    threading.Thread(target=worker, daemon=True).start()

# ── Launch ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from src.dashboard.app import create_app
    app = create_app(DASHBOARD_DATA)
    
    # ── Hermes API Endpoints ───────────────────────────────────────────────
    server = app.server
    from flask import jsonify, request
    
    @server.route('/api/hermes/regime-report', methods=['GET'])
    def hermes_regime_report():
        report = generate_regime_report(DASHBOARD_DATA)
        return jsonify(report)
        
    @server.route('/api/hermes/rebalance-alert', methods=['GET'])
    def hermes_rebalance_alert():
        return jsonify(HERMES_DATA['latest_alert'])

    # Render (and any other proxy) probes this before sending traffic.
    # It is registered only once the Dash app has finished building, which is
    # when the process is actually able to serve pages.
    @server.route('/healthz', methods=['GET'])
    def healthz():
        return jsonify({'ok': True, 'service': 'fontesfund-dashboard'}), 200

    # ── IBKR Status API Endpoint ──────────────────────────────────────────
    @server.route('/api/ibkr/status', methods=['GET'])
    def ibkr_status():
        broker = DASHBOARD_DATA.get('_broker')
        if not broker:
            return jsonify({'connected': False, 'status': 'OFFLINE', 'message': 'Broker not initialized'})
        connected = broker.is_connected()
        result = {'connected': connected, 'status': 'CONNECTED' if connected else 'OFFLINE'}
        if connected:
            try:
                summary = broker.get_account_summary()
                positions = broker.get_positions()
                result['account_summary'] = summary
                result['position_count'] = len(positions)
            except Exception as e:
                result['error'] = str(e)
        return jsonify(result)
    
    # ── Daily refresh endpoint ────────────────────────────────────────────
    # Token-protected (header X-Refresh-Token or ?token=). The GitHub Actions
    # workflow refresh-dashboard.yml POSTs here. The legacy Cloud Scheduler job
    # etf-daily-refresh used the same route.
    # Runs the backtest in-process, then pushes caches to GCS only when
    # GCS_BUCKET is set. On Render that variable is unset, so the new files stay
    # on this instance's disk until the next spin-down or deploy.
    @server.route('/tasks/refresh', methods=['POST', 'GET'])
    def tasks_refresh():
        import subprocess
        token = os.environ.get('REFRESH_TOKEN', '')
        sent = request.headers.get('X-Refresh-Token', '') or request.args.get('token', '')
        if not token or sent != token:
            return jsonify({'ok': False, 'error': 'unauthorized'}), 401
        try:
            def _headline():
                try:
                    _df = load_backtest_results()
                    if not _df.empty:
                        _r = _df.iloc[0]
                        return (float(str(_r.get('Annual Return', '0%')).replace('%', '')),
                                float(str(_r.get('Max Drawdown', '99%')).replace('%', '')))
                except Exception:
                    pass
                return None

            prev = _headline()
            # FORCE_REFRESH: the GCS download at container start gives caches a fresh
            # mtime even when their DATA is old, so the age check alone would skip the
            # re-download and recycle stale data forever (bug found 2026-07-12).
            res = subprocess.run([sys.executable, 'run_backtest.py'],
                                 capture_output=True, text=True, timeout=540,
                                 env={**os.environ, 'FORCE_REFRESH': '1'})
            if res.returncode != 0:
                logger.error(f"/tasks/refresh: run_backtest.py failed (rc={res.returncode}): "
                             f"{(res.stderr or res.stdout)[-500:]}")
                return jsonify({'ok': False, 'error': 'backtest_failed',
                                'stderr': (res.stderr or res.stdout)[-500:]}), 500

            # Regression tripwire: one day of new data moves the 21-yr CAGR by basis
            # points; a data problem moves it by whole points (11.82% vs 14.60% on
            # 2026-07-12, when an in-container FRED failure produced garbage regimes).
            new = _headline()
            if prev and new and (abs(new[0] - prev[0]) > 1.0 or (new[1] - prev[1]) > 1.0):
                logger.error(f"/tasks/refresh: headline jump {prev} -> {new}; data problem "
                             f"suspected — NOT uploading to GCS.")
                return jsonify({'ok': False, 'error': 'quality_gate_headline_jump',
                                'previous': prev, 'new': new}), 500

            from src.dashboard.gcs_sync import upload_data, upload_ibkr
            uploaded = upload_data()

            # Refresh & push IBKR live/paper account snapshot as part of daily refresh
            # SUSPENDED: IBKR integration paused. Set ENABLE_IBKR=1 to re-enable.
            ibkr_uploaded = []
            if os.environ.get('ENABLE_IBKR', '0') == '1':
                try:
                    ib_host = os.environ.get('IBKR_HOST', '10.128.0.2')
                    ib_port = os.environ.get('IBKR_PORT', '4002')
                    ib_cid = os.environ.get('IBKR_SNAP_CLIENT_ID', '99')
                    logger.info(f"/tasks/refresh: Fetching fresh IBKR account snapshot from {ib_host}:{ib_port} (clientId={ib_cid})...")
                    snap_res = subprocess.run(
                        [sys.executable, 'scripts/ibkr_snapshot.py', '--host', str(ib_host), '--port', str(ib_port), '--client-id', str(ib_cid)],
                        capture_output=True, text=True, timeout=60
                    )
                    if snap_res.returncode == 0:
                        logger.info(f"/tasks/refresh: IBKR snapshot generated successfully.")
                        ibkr_uploaded = upload_ibkr()
                    else:
                        logger.warning(f"/tasks/refresh: IBKR snapshot notice (rc={snap_res.returncode}): {(snap_res.stderr or snap_res.stdout)[-300:]}")
                except Exception as ib_err:
                    logger.warning(f"/tasks/refresh: IBKR snapshot refresh error: {ib_err}")
            else:
                logger.info("/tasks/refresh: IBKR snapshot skipped (ENABLE_IBKR not set).")

            # Best-effort: surface the fresh headline from the regenerated CSV.
            headline = {}
            try:
                _df = load_backtest_results()
                if not _df.empty:
                    _r = _df.iloc[0]
                    headline = {'strategy': str(_df.index[0]),
                                'annual_return': str(_r.get('Annual Return', '')),
                                'sharpe': str(_r.get('Sharpe Ratio', '')),
                                'max_drawdown': str(_r.get('Max Drawdown', ''))}
            except Exception:
                pass
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if os.environ.get('GCS_BUCKET', '').strip():
                gcs_note = (f"uploaded {len(uploaded)} backtest + {len(ibkr_uploaded)} IBKR files to GCS")
            else:
                gcs_note = "GCS_BUCKET unset; caches updated on local disk only"
            logger.info(f"/tasks/refresh OK at {ts}; {gcs_note}.")
            return jsonify({'ok': True, 'refreshed_at': ts, 'uploaded': uploaded, 'ibkr_uploaded': ibkr_uploaded,
                            'headline': headline, 'gcs': gcs_note})
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'timeout'}), 504
        except Exception as e:
            logger.error(f"/tasks/refresh error: {e}", exc_info=True)
            return jsonify({'ok': False, 'error': str(e)}), 500

    # Start background data check and update thread
    start_background_updater(DASHBOARD_DATA)
    
    import os
    port = int(os.environ.get('PORT', 8050))
    logger.info(f"Starting dashboard on port {port}")
    # threaded so /healthz still answers while /tasks/refresh runs the backtest.
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
