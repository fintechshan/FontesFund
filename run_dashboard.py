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

def refresh_qqq_vegas_market_cache():
    """Best-effort QQQ/QLD price and PE cache. Never raises.

    Cloud Scheduler hits ``/tasks/refresh`` once a day. This runs
    ``scripts/refresh_qqq_vegas_market.py`` and leaves the previous files in
    place when Yahoo does not answer. It does not recompute the v9 signal
    and it does not change the Merrill backtest.
    """
    import subprocess
    try:
        res = subprocess.run(
            [sys.executable, 'scripts/refresh_qqq_vegas_market.py'],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:
        logger.warning(f"/tasks/refresh: QQQ/QLD market pack skipped: {exc}")
        return False
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or '')[-300:]
        logger.warning(f"/tasks/refresh: QQQ/QLD market pack unchanged (rc={res.returncode}): {detail}")
        return False
    logger.info(f"/tasks/refresh: QQQ/QLD market pack updated: {(res.stdout or '').strip()[-300:]}")
    return True


def _upload_qqq_vegas_market():
    """Push the QQQ/QLD pack when the Merrill upload is not going to run."""
    try:
        from src.dashboard.gcs_sync import upload_vegas_market
        upload_vegas_market()
    except Exception as exc:
        logger.warning(f"/tasks/refresh: QQQ/QLD market upload skipped: {exc}")


def refresh_qqq_vegas_signal_cache():
    """Best-effort extension of the locked v9 sleeve. Never raises.

    Same scheduler hit as the price cache. Runs
    ``scripts/refresh_qqq_vegas_signal.py``, which appends sessions only when
    the recomputed Vegas and expanding-Q80 gate matches the stored series.
    The same run rewrites ``rebalances.csv`` and ``last_rebalance`` from
    ``pos`` changes. A download failure or a gate mismatch leaves the previous
    pack in place. It does not change the Merrill backtest.
    """
    import subprocess
    try:
        res = subprocess.run(
            [sys.executable, 'scripts/refresh_qqq_vegas_signal.py'],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:
        logger.warning(f"/tasks/refresh: QQQ Vegas signal pack skipped: {exc}")
        return False
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or '')[-300:]
        logger.warning(f"/tasks/refresh: QQQ Vegas signal pack unchanged (rc={res.returncode}): {detail}")
        return False
    logger.info(f"/tasks/refresh: QQQ Vegas signal pack updated: {(res.stdout or '').strip()[-300:]}")
    return True


def _upload_qqq_vegas_signal():
    """Push the v9 sleeve when the Merrill upload is not going to run."""
    try:
        from src.dashboard.gcs_sync import upload_vegas_signal
        upload_vegas_signal()
    except Exception as exc:
        logger.warning(f"/tasks/refresh: QQQ Vegas signal upload skipped: {exc}")
    try:
        from src.dashboard.gcs_sync import upload_vegas_shadow
        upload_vegas_shadow()
    except Exception as exc:
        logger.warning(f"/tasks/refresh: QQQ Vegas shadow upload skipped: {exc}")


def refresh_cdn_backtest():
    """Best-effort CDN curve, XIU benchmark, and path A/B/C table.

    Runs after the US backtest so the macro cache is already fresh. A failure
    leaves the previous CDN files in place and does not fail the US upload.
    It does not change REGIME_WEIGHTS.
    """
    import subprocess
    try:
        res = subprocess.run(
            [sys.executable, 'scripts/run_cdn_backtest.py'],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:
        logger.warning(f"/tasks/refresh: CDN backtest skipped: {exc}")
        return False
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or '')[-300:]
        logger.warning(f"/tasks/refresh: CDN backtest unchanged (rc={res.returncode}): {detail}")
        return False
    logger.info(f"/tasks/refresh: CDN backtest updated: {(res.stdout or '').strip()[-300:]}")
    return True


def refresh_risk_flags_cache():
    """Best-effort notify-only scorecard. Never raises and never sizes the book."""
    import subprocess
    try:
        res = subprocess.run(
            [sys.executable, 'scripts/refresh_risk_flags.py'],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:
        logger.warning(f"/tasks/refresh: risk flags skipped: {exc}")
        return False
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or '')[-300:]
        logger.warning(f"/tasks/refresh: risk flags unchanged (rc={res.returncode}): {detail}")
        return False
    logger.info(f"/tasks/refresh: risk flags updated: {(res.stdout or '').strip()[-300:]}")
    return True


def _upload_risk_flags():
    try:
        from src.dashboard.gcs_sync import upload_risk_flags
        upload_risk_flags()
    except Exception as exc:
        logger.warning(f"/tasks/refresh: risk-flag upload skipped: {exc}")


def load_backtest_results():
    if BACKTEST_CSV.exists():
        df = pd.read_csv(BACKTEST_CSV, index_col=0)
        logger.info(f"Loaded backtest results: {len(df)} strategies")
        return df
    logger.warning("No backtest results found")
    return pd.DataFrame()

# ── Regime classification ─────────────────────────────────────────────────
# Source of truth: src/backtester/regime_clock.py. Default mode is the targeted
# fix (CPI+1 / GDP+4, then shift(1) on VIX mean and momentum only).
from src.backtester.regime_clock import (  # noqa: E402
    MODE_TARGETED,
    classify_regimes,
)

DASHBOARD_DATA = None
HERMES_DATA = {
    'latest_alert': {
        'timestamp': '',
        'type': 'rebalance_alert',
        'alert_level': 'INFO',
        'message': 'Dashboard has not finished loading.',
        'current_regime': 'unknown',
        'target_weights': {},
    }
}


def assemble_dashboard(*, sync_gcs=True):
    """Build DASHBOARD_DATA from the cache, the comparison clocks, and the auditor.

    Clocks and the AI-trend fetch run in child processes so this process can
    keep answering ``/healthz``. ``sync_gcs=False`` is the gated refresh path:
    the local files were just written and must not be replaced by a download.
    The first call's dict object is kept so Dash callbacks that closed over it
    see later updates.
    """
    global DASHBOARD_DATA, HERMES_DATA
    previous = DASHBOARD_DATA
    clock_status = "pending"

    # ── Build DASHBOARD_DATA ──────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  ETF REGIME STRATEGIST — DASHBOARD LAUNCHER")
    logger.info("=" * 60)

    # Pull the latest daily-refreshed caches from GCS before loading (no-op if
    # GCS_BUCKET is unset). This is what lets fresh data survive Cloud Run scale-to-zero.
    # The gated refresh calls assemble_dashboard(sync_gcs=False) so this download
    # cannot replace the files that refresh just wrote.
    if sync_gcs:
        try:
            from src.dashboard.gcs_sync import download_data as _gcs_download
            _gcs_download()
        except Exception as _e:
            logger.warning(f"GCS startup sync skipped: {_e}")

    price_data = load_price_data()
    macro = load_macro_data()
    backtest_results = load_backtest_results()
    # Live allocation uses the targeted clock (CPI+1 / GDP+4, no month-end look-ahead).
    regime_history, current, derived = classify_regimes(macro, price_data, mode=MODE_TARGETED)

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
    try:
        from src.dashboard.runtime_state import STATE
        STATE.regime = current.get('regime')
    except Exception:
        pass

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

    # ── Targeted fix (default) plus comparison clocks ────────────────────────
    # Same stack as before (targeted, look-ahead, unlagged, auditor, vintage).
    # The child process keeps this process able to answer /healthz.
    logger.info("Running targeted fix and comparison clocks...")
    lagged_metrics = {}
    if os.environ.get("DASHBOARD_SKIP_CLOCKS", "").strip() == "1":
        clock_status = "skipped"
        logger.info("Comparison clocks skipped (DASHBOARD_SKIP_CLOCKS=1).")
    else:
        try:
            from config.regime_rules import REGIME_WEIGHTS as _RW
            from src.dashboard.startup_jobs import compute_clocks_subprocess
            _bundle = compute_clocks_subprocess(price_data, macro, _RW)
            lagged_metrics = (_bundle or {}).get("lagged_metrics") or {}
            _eq = (_bundle or {}).get("equity_curve")
            _mo = (_bundle or {}).get("monthly_returns")
            if isinstance(_eq, pd.Series) and len(_eq):
                equity_curve = _eq
            if isinstance(_mo, pd.Series) and len(_mo):
                monthly_returns = _mo
            if _bundle and lagged_metrics:
                clock_status = "ready"
                logger.info("Honesty-path runs completed.")
            elif price_data is None or price_data.empty:
                clock_status = "skipped"
            else:
                clock_status = "failed"
                logger.error("Honesty-path runs produced no bundle; serving the published CSV book.")
        except Exception as e:
            clock_status = "failed"
            logger.error(f"Error running honesty-path backtests: {e}")
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

    # ── AI Trend Intelligence (display only; not a weight or backtest input) ──
    ai_trend = {}
    if os.environ.get("DASHBOARD_SKIP_AI", "").strip() == "1":
        logger.info("AI trend startup skipped (DASHBOARD_SKIP_AI=1).")
    else:
        try:
            from src.dashboard.startup_jobs import compute_ai_subprocess
            ai_trend = compute_ai_subprocess(
                price_data, current.get('regime', 'goldilocks'), current_weights) or {}
            if ai_trend:
                _semi = ai_trend.get('semianalysis') or {}
                _n = len(_semi.get('items', [])) if isinstance(_semi, dict) else len(_semi)
                logger.info(
                    f"AI Trend Intelligence: sector={ai_trend.get('signals', {}).get('sector_signal')} "
                    f"verdict={ai_trend.get('verification', {}).get('verdict')} "
                    f"({_n} SemiAnalysis items)"
                )
            else:
                logger.warning("AI Trend Intelligence unavailable within the startup budget.")
        except Exception as e:
            logger.warning(f"AI Trend Intelligence unavailable: {e}")
            ai_trend = {}

    # ── Execution Modules (Disabled for Public Deployment) ───────────────────
    _ibkr_broker = None
    _ibkr_risk_mgr = None
    _ibkr_order_mgr = None

    # ── Load Canadian ETF Portfolio Data ──────────────────────────────────────
    # Live weights use the targeted CDN clock (VFV.TO momentum) when the TSX
    # cache exists. Without it they follow the US label and the auditor says so.
    try:
        from src.backtester.cdn_clock import dashboard_cdn_payload
        from src.dashboard.cdn_audit import merge_cdn_audit
        _cdn_payload = dashboard_cdn_payload(macro, current.get('regime', 'goldilocks'), regime_history)
        audit_results = merge_cdn_audit(
            audit_results,
            prices=_cdn_payload.get('cdn_prices'),
            us_prices=price_data,
            us_equity=equity_curve,
        )
        logger.info(
            "CDN portfolio loaded: regime=%s source=%s benchmark=%s",
            _cdn_payload.get('cdn_regime'),
            _cdn_payload.get('cdn_regime_source'),
            len(_cdn_payload.get('cdn_benchmark', [])),
        )
    except Exception as _cdn_err:
        logger.warning(f"CDN portfolio data load failed: {_cdn_err}")
        _cdn_payload = {}

    fresh = {

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
        'cdn_equity_curve':    _cdn_payload.get('cdn_equity_curve', pd.Series(dtype=float)),
        'cdn_monthly_returns': _cdn_payload.get('cdn_monthly_returns', pd.Series(dtype=float)),
        'cdn_backtest_meta':   _cdn_payload.get('cdn_backtest_meta', {}),
        'cdn_current_weights': _cdn_payload.get('cdn_current_weights', {}),
        'cdn_all_weights':     _cdn_payload.get('cdn_all_weights', {}),
        'cdn_regime_changes':  _cdn_payload.get('cdn_regime_changes', []),
        'cdn_benchmark':       _cdn_payload.get('cdn_benchmark', pd.Series(dtype=float)),
        'cdn_prices':          _cdn_payload.get('cdn_prices', pd.DataFrame()),
        'cdn_regime_source':   _cdn_payload.get('cdn_regime_source', 'us_fallback'),

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

    if previous is None:
        DASHBOARD_DATA = fresh
    else:
        previous.clear()
        previous.update(fresh)
        DASHBOARD_DATA = previous
    try:
        from src.dashboard.runtime_state import STATE
        STATE.regime = (DASHBOARD_DATA or {}).get("current_regime")
        STATE.clocks = clock_status
    except Exception:
        pass
    return clock_status


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
import threading

_updater_lock = threading.Lock()
_updater_started = False


def _cache_is_stale():
    import time
    if not PRICE_CACHE.exists() or not MACRO_CACHE.exists():
        return True
    price_age = (time.time() - PRICE_CACHE.stat().st_mtime) / 86400.0
    macro_age = (time.time() - MACRO_CACHE.stat().st_mtime) / 86400.0
    return price_age >= 1.0 or macro_age >= 1.0


def start_background_updater(app_data):
    """Hermes notify once per process. Does not run a backtest.

    A background ``run_backtest.py`` skipped the headline gate and then
    recomputed the comparison clocks in this process. That holds the GIL, so
    ``/healthz`` cannot answer, and under Cloud Run CPU throttling the
    backtest did not finish unless a request was already in flight. The
    scheduler endpoint is the only writer.
    """
    global _updater_started
    with _updater_lock:
        if _updater_started:
            logger.info("Background updater already running in this process.")
            return False
        _updater_started = True

    def worker():
        import time
        time.sleep(1)
        try:
            report = generate_regime_report(app_data)
            send_hermes_notification(report)
            alert = HERMES_DATA.get("latest_alert") or {}
            if alert.get("alert_level") == "CRITICAL":
                send_hermes_notification(alert)
        except Exception as he:
            logger.error(f"Error sending initial Hermes report/alert: {he}")
        if _cache_is_stale():
            logger.warning(
                "Price or macro cache is missing or older than 1 day. "
                "/tasks/refresh is the gated update. This thread will not "
                "start an ungated backtest."
            )
        else:
            logger.info("Data cache is fresh. No background update required.")

    threading.Thread(target=worker, name="dashboard-updater", daemon=True).start()
    return True


def _reload_published_book():
    """Rebuild in-memory state from the files a gated refresh just wrote.

    ``sync_gcs=False`` keeps the local book. A newer image file is not the
    case here: this process is the one that just wrote the files.
    """
    from src.dashboard.runtime_state import STATE
    from src.dashboard.app import mount_layout
    assemble_dashboard(sync_gcs=False)
    if STATE.dash_app is not None and DASHBOARD_DATA is not None:
        mount_layout(STATE.dash_app, DASHBOARD_DATA)


def register_routes(server):
    """Hermes, IBKR status, and the scheduler refresh. One implementation."""
    from flask import jsonify, request
    from src.dashboard.runtime_state import STATE

    @server.route("/api/hermes/regime-report", methods=["GET"])
    def hermes_regime_report():
        report = generate_regime_report(DASHBOARD_DATA or {})
        return jsonify(report)

    @server.route("/api/hermes/rebalance-alert", methods=["GET"])
    def hermes_rebalance_alert():
        return jsonify(HERMES_DATA["latest_alert"])

    @server.route("/api/ibkr/status", methods=["GET"])
    def ibkr_status():
        # Read-only status of an in-process broker object. The public server
        # leaves ``_broker`` unset, so this returns OFFLINE and does not open
        # a TWS socket. Snapshot refresh stays behind ENABLE_IBKR on
        # /tasks/refresh and is not called from here.
        broker = (DASHBOARD_DATA or {}).get("_broker")
        if not broker:
            return jsonify({"connected": False, "status": "OFFLINE", "message": "Broker not initialized"})
        connected = broker.is_connected()
        result = {"connected": connected, "status": "CONNECTED" if connected else "OFFLINE"}
        if connected:
            try:
                summary = broker.get_account_summary()
                positions = broker.get_positions()
                result["account_summary"] = summary
                result["position_count"] = len(positions)
            except Exception as e:
                result["error"] = str(e)
        return jsonify(result)

    @server.route("/tasks/refresh", methods=["POST", "GET"])
    def tasks_refresh():
        import subprocess
        token = os.environ.get("REFRESH_TOKEN", "")
        sent = request.headers.get("X-Refresh-Token", "") or request.args.get("token", "")
        if not token or sent != token:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        if not STATE.ready or STATE.phase != "serving":
            return jsonify({"ok": False, "error": "starting", "phase": STATE.phase}), 503
        if not STATE.begin_refresh():
            return jsonify({"ok": False, "error": "refresh_in_progress"}), 409
        try:
            # Test-only latch. Production does not set this, so the gated
            # backtest below is what Cloud Scheduler runs.
            hold = os.environ.get("DASHBOARD_TEST_REFRESH_HOLD", "").strip()
            if hold:
                import time
                time.sleep(float(hold))
                return jsonify({"ok": True, "test_hold": True})
            return _tasks_refresh_body(subprocess)
        finally:
            STATE.end_refresh()

    return server


def _tasks_refresh_body(subprocess):
    from flask import jsonify
    try:
        from src.dashboard.headline_gate import (
            BASELINE_REL,
            LAG_HONESTY_REL,
            evaluate_headline_gate,
            headline_from_comparison_frame,
            load_same_path_headline,
            load_uploaded_baseline,
            reset_requested,
            write_uploaded_baseline,
        )

        def _headline():
            try:
                return headline_from_comparison_frame(load_backtest_results())
            except Exception:
                return None

        # Read before run_backtest.py rewrites 20yr_comparison.csv.
        # The comparison row may be an older look-ahead upload pulled
        # from GCS at startup. The gate compares the new targeted run
        # to the last accepted B_targeted package, or to lag_honesty
        # B_targeted when that row is a different methodology.
        prev = _headline()
        same_path = load_same_path_headline(ROOT / LAG_HONESTY_REL)
        uploaded_baseline = load_uploaded_baseline(ROOT / BASELINE_REL)
        # FORCE_REFRESH: the GCS download at container start gives caches a fresh
        # mtime even when their DATA is old, so the age check alone would skip the
        # re-download and recycle stale data forever (bug found 2026-07-12).
        res = subprocess.run([sys.executable, "run_backtest.py"],
                             capture_output=True, text=True, timeout=540,
                             env={**os.environ, "FORCE_REFRESH": "1"})
        if res.returncode != 0:
            logger.error(f"/tasks/refresh: run_backtest.py failed (rc={res.returncode}): "
                         f"{(res.stderr or res.stdout)[-500:]}")
            vegas_market = refresh_qqq_vegas_market_cache()
            if vegas_market:
                _upload_qqq_vegas_market()
            vegas_signal = refresh_qqq_vegas_signal_cache()
            if vegas_signal:
                _upload_qqq_vegas_signal()
            risk_flags = refresh_risk_flags_cache()
            if risk_flags:
                _upload_risk_flags()
            return jsonify({"ok": False, "error": "backtest_failed",
                            "qqq_vegas_market": vegas_market,
                            "qqq_vegas_signal": vegas_signal,
                            "risk_flags": risk_flags,
                            "stderr": (res.stderr or res.stdout)[-500:]}), 500

        # Regression tripwire: one day of new data moves the 21-yr CAGR by basis
        # points; a data problem moves it by whole points (11.82% vs 14.60% on
        # 2026-07-12, when an in-container FRED failure produced garbage regimes).
        # The baseline is the last accepted targeted upload, or B_targeted when
        # the on-disk row is a different clock (look-ahead ~14.47% / 13.9% vs
        # targeted ~13.1% / 14.13%). HEADLINE_GATE_RESET=1 skips one refresh.
        # run_backtest.py also exits 3 when the equity curve, the monthly
        # heatmap, and the reported CAGR/total/daily max DD are not one series.
        new = _headline()
        gate = evaluate_headline_gate(
            previous=prev,
            new=new,
            same_path=same_path,
            uploaded=uploaded_baseline,
            allow_reset=reset_requested(),
        )
        if gate.baseline_source == "reset":
            logger.warning(
                f"/tasks/refresh: {gate.reason} would_block={gate.would_block} "
                f"baseline={gate.baseline} previous={prev} new={new}"
            )
        elif gate.baseline_source == "same_path" and prev is not None:
            logger.warning(
                f"/tasks/refresh: {gate.reason} previous={prev} "
                f"baseline={gate.baseline} new={new}"
            )
        if gate.block:
            logger.error(
                f"/tasks/refresh: headline jump baseline {gate.baseline_source} "
                f"{gate.baseline} -> {new} (on-disk previous {prev}); "
                f"data problem suspected — NOT uploading US backtest to GCS."
            )
            vegas_market = refresh_qqq_vegas_market_cache()
            if vegas_market:
                _upload_qqq_vegas_market()
            vegas_signal = refresh_qqq_vegas_signal_cache()
            if vegas_signal:
                _upload_qqq_vegas_signal()
            risk_flags = refresh_risk_flags_cache()
            if risk_flags:
                _upload_risk_flags()
            body = gate.as_dict()
            body.update({
                "ok": False,
                "error": "quality_gate_headline_jump",
                "qqq_vegas_market": vegas_market,
                "qqq_vegas_signal": vegas_signal,
                "risk_flags": risk_flags,
                "previous": list(prev) if prev is not None else None,
                "new": list(new) if new is not None else None,
            })
            return jsonify(body), 500

        # Push the US curves before CDN / Vegas. Those steps have their own
        # multi-minute budgets, and the scheduler deadline has to cover them
        # too. The heatmap inputs should already be in GCS if that later
        # work is cut off.
        if new is not None:
            try:
                write_uploaded_baseline(ROOT / BASELINE_REL, new)
            except Exception as baseline_err:
                logger.warning(f"/tasks/refresh: headline baseline not recorded: {baseline_err}")
        from src.dashboard.gcs_sync import upload_data, upload_ibkr, upload_us_backtest
        us_uploaded = upload_us_backtest()

        cdn_backtest = refresh_cdn_backtest()
        vegas_market = refresh_qqq_vegas_market_cache()
        vegas_signal = refresh_qqq_vegas_signal_cache()
        risk_flags = refresh_risk_flags_cache()
        uploaded_files = list(dict.fromkeys([*us_uploaded, *upload_data()]))

        # Refresh & push IBKR live/paper account snapshot as part of daily refresh
        # SUSPENDED: IBKR integration paused. Set ENABLE_IBKR=1 to re-enable.
        # Tests and health checks must not set ENABLE_IBKR. This block is the
        # only place a refresh opens a broker connection, and only when that
        # flag is set.
        ibkr_uploaded = []
        if os.environ.get("ENABLE_IBKR", "0") == "1":
            try:
                ib_host = os.environ.get("IBKR_HOST", "10.128.0.2")
                ib_port = os.environ.get("IBKR_PORT", "4002")
                ib_cid = os.environ.get("IBKR_SNAP_CLIENT_ID", "99")
                logger.info(f"/tasks/refresh: Fetching fresh IBKR account snapshot from {ib_host}:{ib_port} (clientId={ib_cid})...")
                snap_res = subprocess.run(
                    [sys.executable, "scripts/ibkr_snapshot.py", "--host", str(ib_host), "--port", str(ib_port), "--client-id", str(ib_cid)],
                    capture_output=True, text=True, timeout=60
                )
                if snap_res.returncode == 0:
                    logger.info("/tasks/refresh: IBKR snapshot generated successfully.")
                    ibkr_uploaded = upload_ibkr()
                else:
                    logger.warning(f"/tasks/refresh: IBKR snapshot notice (rc={snap_res.returncode}): {(snap_res.stderr or snap_res.stdout)[-300:]}")
            except Exception as ib_err:
                logger.warning(f"/tasks/refresh: IBKR snapshot refresh error: {ib_err}")
        else:
            logger.info("/tasks/refresh: IBKR snapshot skipped (ENABLE_IBKR not set).")

        headline = {}
        try:
            _df = load_backtest_results()
            if not _df.empty:
                _r = _df.iloc[0]
                headline = {"strategy": str(_df.index[0]),
                            "annual_return": str(_r.get("Annual Return", "")),
                            "sharpe": str(_r.get("Sharpe Ratio", "")),
                            "max_drawdown": str(_r.get("Max Drawdown", ""))}
        except Exception:
            pass
        memory_reload = False
        try:
            _reload_published_book()
            memory_reload = True
        except Exception as reload_err:
            logger.warning(f"/tasks/refresh: in-memory reload failed: {reload_err}")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(
            f"/tasks/refresh OK at {ts}; uploaded {len(uploaded_files)} backtest + "
            f"{len(ibkr_uploaded)} IBKR files to GCS. "
            f"headline gate {gate.baseline_source} baseline={gate.baseline} new={new}"
        )
        return jsonify({"ok": True, "refreshed_at": ts, "uploaded": uploaded_files,
                        "ibkr_uploaded": ibkr_uploaded,
                        "qqq_vegas_market": vegas_market, "qqq_vegas_signal": vegas_signal,
                        "risk_flags": risk_flags, "cdn_backtest": cdn_backtest,
                        "headline": headline, "headline_gate": gate.as_dict(),
                        "memory_reload": memory_reload})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "timeout"}), 504
    except Exception as e:
        logger.error(f"/tasks/refresh error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    from src.dashboard.wsgi_app import serve
    serve()
