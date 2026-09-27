"""Side-by-side honesty paths for the Merrill clock.

Writes ``data/backtest_results/lag_honesty.csv``. The targeted-fix row is the
trusted production path (CPI+1 / GDP+4, no month-end look-ahead). The vintage
row uses first-release CPI/GDP (fredapi/ALFRED when a key is set, otherwise
the committed Philadelphia Fed RTDSM table). This script does not change ETF weights.

Usage:
    python scripts/compare_lag_honesty.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("lag_honesty")


def _load():
    price = pd.read_csv(ROOT / "data" / "cache" / "price_data.csv", index_col=0, parse_dates=True)
    price = price.ffill()
    macro_path = ROOT / "data" / "cache" / "macro_data.pkl"
    if not macro_path.exists():
        raise SystemExit(f"Missing {macro_path}. Run run_backtest.py once to cache FRED data.")
    import pickle
    with open(macro_path, "rb") as fh:
        macro = pickle.load(fh)
    return price, macro


def _metrics(res) -> dict:
    return {
        "cagr": res.annual_return,
        "max_dd": res.max_drawdown,
        "sharpe": res.sharpe_ratio,
        "volatility": res.volatility,
        "sortino": res.sortino_ratio,
        "calmar": res.calmar_ratio,
        "total_return": res.total_return,
        "start": res.start_date,
        "end": res.end_date,
    }


def main():
    from config.regime_rules import REGIME_WEIGHTS, STRATEGY_PARAMS
    from src.backtester.engine import BacktestEngine
    from src.backtester.regime_clock import (
        HONESTY_MODES,
        MODE_LOOKAHEAD,
        MODE_TARGETED,
        MODE_VINTAGE,
        classify_regimes,
        load_realtime_vintage,
    )

    price, macro = _load()
    available = set(price.columns)
    weights = {}
    for name, raw in REGIME_WEIGHTS.items():
        filtered = {k: v for k, v in raw.items() if k in available}
        total = sum(filtered.values())
        weights[name] = {k: v / total for k, v in filtered.items()} if total else {}

    vintage = load_realtime_vintage()
    if vintage is None:
        logger.warning("Vintage clock unavailable; that row will be marked fallback.")

    histories = {}
    infos = {}
    for mode in HONESTY_MODES:
        if mode == MODE_VINTAGE and vintage is None:
            continue
        hist, _, info = classify_regimes(
            macro, price, mode=mode,
            vintage=vintage if mode == MODE_VINTAGE else None,
        )
        histories[mode] = hist
        infos[mode] = info
        if info.get("vintage_fallback"):
            logger.warning("Mode %s fell back: %s", mode, info.get("vintage_error"))

    targeted = histories[MODE_TARGETED].set_index("date")["regime"]
    lookahead = histories[MODE_LOOKAHEAD].set_index("date")["regime"]
    both = targeted.index.intersection(lookahead.index)
    disagree = int((targeted.loc[both] != lookahead.loc[both]).sum())
    logger.info(
        "Targeted vs month-end look-ahead: %d / %d months differ (%.1f%%)",
        disagree, len(both), 100.0 * disagree / max(len(both), 1),
    )

    ff = macro.get("ff_rate", pd.Series(dtype=float))
    # DFF is a percent. Average it over the price sample only — a full-history
    # mean (back to the 1950s) is not the rate the book financed against.
    if ff is not None and len(ff):
        ff = ff.copy()
        ff.index = pd.to_datetime(ff.index)
        ff = ff.loc[str(price.index.min().date()):]
        avg_rf = float(ff.mean() / 100.0)
    else:
        avg_rf = 0.02
    logger.info("Sample Fed funds (risk-free): %.4f%%", avg_rf * 100)
    engine = BacktestEngine(price, initial_capital=100_000, risk_free_rate=avg_rf)
    vix = macro.get("vix")

    rows = []
    for mode, hist in histories.items():
        logger.info("Backtesting %s ...", mode)
        res = engine.run_optimized_regime_backtest(
            regime_history=hist,
            regime_weights=weights,
            name=mode,
            vix_data=vix,
            **STRATEGY_PARAMS,
        )
        row = {"mode": mode, **_metrics(res)}
        row["vintage_source"] = (infos.get(mode) or {}).get("vintage_source")
        row["vintage_fallback"] = bool((infos.get(mode) or {}).get("vintage_fallback"))
        rows.append(row)
        logger.info(
            "%s  CAGR %.2f%%  MaxDD %.2f%%  Sharpe %.2f  total %.1f%%",
            mode, 100 * res.annual_return, 100 * res.max_drawdown,
            res.sharpe_ratio, 100 * res.total_return,
        )

    out = pd.DataFrame(rows).set_index("mode")
    dest = ROOT / "data" / "backtest_results" / "lag_honesty.csv"
    out.to_csv(dest)
    logger.info("Wrote %s", dest)
    print(out.to_string())
    return out


if __name__ == "__main__":
    main()
