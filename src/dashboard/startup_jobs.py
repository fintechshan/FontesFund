"""Startup work that must not hold the dashboard process's GIL.

Comparison clocks are the same stack ``run_dashboard`` used to run inline:
targeted, month-end look-ahead, unlagged, auditor extra month, and
first-release vintage when the release table loads. They run in a spawned
child so ``/healthz`` can answer while they run. The child must not import
``run_dashboard`` (that module's boot is the parent).

AI-trend fetches are display-only. A hung news or Reddit call used to sit
in front of ``app.run``. The child is killed when ``AI_TREND_TIMEOUT_SEC``
elapses and the page keeps the empty payload the old ``except`` already used.
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import traceback

import pandas as pd

logger = logging.getLogger("dashboard.startup")

DEFAULT_CLOCK_TIMEOUT = 240
DEFAULT_AI_TIMEOUT = 45


def sample_risk_free(ff_rate, price_data):
    """Mean fed funds over the price sample, as a decimal.

    DFF is stored in percent. A full-history mean (back to the 1950s) is not
    the financing rate of this backtest.
    """
    if ff_rate is None or len(ff_rate) == 0:
        return 0.0185
    ff = ff_rate.copy()
    ff.index = pd.to_datetime(ff.index)
    if price_data is not None and not price_data.empty:
        ff = ff.loc[str(price_data.index.min().date()):]
    if len(ff) == 0:
        return 0.0185
    return float(ff.mean() / 100.0)


def run_honesty_paths(price_data, macro, weights):
    """Targeted fix plus the comparison clocks. Vintage is skipped if unavailable."""
    from src.backtester.engine import BacktestEngine
    from src.backtester.regime_clock import (
        MODE_AUDITOR,
        MODE_LOOKAHEAD,
        MODE_TARGETED,
        MODE_UNLAGGED,
        MODE_VINTAGE,
        classify_regimes,
        load_realtime_vintage,
    )
    from config.regime_rules import STRATEGY_PARAMS

    refresh_vintage = os.getenv("USE_REALTIME_VINTAGE", "").strip().lower() in {"1", "true", "yes"}
    vintage = load_realtime_vintage(refresh=refresh_vintage)

    modes = [MODE_TARGETED, MODE_LOOKAHEAD, MODE_UNLAGGED, MODE_AUDITOR]
    histories = {}
    for mode in modes:
        hist, _, _info = classify_regimes(macro, price_data, mode=mode)
        histories[mode] = hist
    if vintage is not None:
        hist, _, info = classify_regimes(
            macro, price_data, mode=MODE_VINTAGE, vintage=vintage,
        )
        if not info.get("vintage_fallback"):
            histories[MODE_VINTAGE] = hist

    ff_rate = macro.get("ff_rate", pd.Series(dtype=float))
    engine = BacktestEngine(
        price_data, initial_capital=100000, risk_free_rate=sample_risk_free(ff_rate, price_data),
    )
    vix_series = macro.get("vix")
    results = {}
    names = {
        MODE_TARGETED: "Targeted fix",
        MODE_LOOKAHEAD: "Month-end look-ahead",
        MODE_UNLAGGED: "Unlagged",
        MODE_AUDITOR: "Auditor extra month",
        MODE_VINTAGE: "First-release vintage",
    }
    for mode, hist in histories.items():
        results[mode] = engine.run_optimized_regime_backtest(
            regime_history=hist,
            regime_weights=weights,
            name=names[mode],
            vix_data=vix_series,
            **STRATEGY_PARAMS,
        )
    return results, histories[MODE_TARGETED]


def build_clock_bundle(price_data, macro, weights):
    """Picklable clocks: display metrics plus the targeted curve."""
    from src.backtester.regime_clock import MODE_TARGETED
    from src.dashboard.app import pack_lagged_metrics

    results, _hist = run_honesty_paths(price_data, macro, weights)
    lagged = pack_lagged_metrics(results=results)
    targeted = results.get(MODE_TARGETED)
    equity = getattr(targeted, "equity_curve", None) if targeted is not None else None
    monthly = getattr(targeted, "monthly_returns", None) if targeted is not None else None
    return {
        "lagged_metrics": lagged,
        "equity_curve": equity if isinstance(equity, pd.Series) else None,
        "monthly_returns": monthly if isinstance(monthly, pd.Series) else None,
    }


def _clock_child(price_data, macro, weights, queue):
    try:
        queue.put({"ok": True, "bundle": build_clock_bundle(price_data, macro, weights)})
    except Exception:
        queue.put({"ok": False, "error": traceback.format_exc()})


def _ai_child(price_data, regime, weights, queue):
    try:
        from src.strategist.ai_trend import build_ai_trend_intelligence
        queue.put({"ok": True, "payload": build_ai_trend_intelligence(price_data, regime, weights)})
    except Exception:
        queue.put({"ok": False, "error": traceback.format_exc()})


def _run_child(target, args, timeout, label):
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=target, args=(*args, queue), name=label, daemon=True)
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        logger.error("%s exceeded %ss; terminating the child", label, timeout)
        proc.terminate()
        proc.join(10)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        return None
    try:
        payload = queue.get(timeout=5)
    except Exception as exc:
        logger.error("%s child returned nothing (%s), exit=%s", label, exc, proc.exitcode)
        return None
    if not payload.get("ok"):
        logger.error("%s child failed:\n%s", label, payload.get("error"))
        return None
    return payload


def _clock_timeout():
    raw = os.environ.get("HONESTY_JOB_TIMEOUT_SEC", "").strip()
    try:
        return int(raw) if raw else DEFAULT_CLOCK_TIMEOUT
    except ValueError:
        return DEFAULT_CLOCK_TIMEOUT


def _ai_timeout():
    raw = os.environ.get("AI_TREND_TIMEOUT_SEC", "").strip()
    try:
        return int(raw) if raw else DEFAULT_AI_TIMEOUT
    except ValueError:
        return DEFAULT_AI_TIMEOUT


def compute_clocks_subprocess(price_data, macro, weights, timeout=None):
    """Return the clock bundle, or None when there is nothing to run or it fails.

    An empty price cache cannot run the engine. The published CSV book still
    renders. A timeout or a child error is the same outcome: None, and the
    caller marks comparison clocks failed without refusing traffic.
    """
    from src.dashboard.runtime_state import STATE

    if price_data is None or getattr(price_data, "empty", True):
        logger.info("Comparison clocks skipped: price cache is empty.")
        STATE.clocks = "skipped"
        return None
    STATE.clocks = "running"
    if STATE.phase != "serving":
        STATE.phase = "clocks"
    timeout = _clock_timeout() if timeout is None else timeout
    logger.info("Comparison clocks running in a child process (budget %ss).", timeout)
    payload = _run_child(_clock_child, (price_data, macro, weights), timeout, "honesty-clocks")
    if not payload:
        STATE.clocks = "failed"
        return None
    STATE.clocks = "ready"
    return payload.get("bundle")


def compute_ai_subprocess(price_data, regime, weights, timeout=None):
    """Display-only AI trend payload. Empty dict when the child misses the budget."""
    timeout = _ai_timeout() if timeout is None else timeout
    logger.info("AI trend running in a child process (budget %ss).", timeout)
    payload = _run_child(_ai_child, (price_data, regime, weights), timeout, "ai-trend")
    if not payload:
        return {}
    body = payload.get("payload")
    return body if isinstance(body, dict) else {}
