"""Last-day overlay weights shared by the local rebalance scripts.

``scripts/ibkr_rebalance.py`` and ``scripts/moomoo_rebalance.py`` both call
``current_regime_and_weights``. The monthly sleeve is not the order. The
production engine applies the daily overlay and the scripts read
``result.overlay``. Notify keeps its own static ``book_weights`` table; that
table is not this function.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.regime_rules import REGIME_WEIGHTS

PRICE_CACHE = ROOT / "data" / "cache" / "price_data.csv"
MACRO_CACHE = ROOT / "data" / "cache" / "macro_data.pkl"


def current_regime_and_weights():
    """Target notionals from the production engine's last day.

    The monthly regime sleeve is not the order. ``run_optimized_regime_backtest``
    then applies the daily overlay: 200-MA blend, portfolio vol scale, and
    portfolio drawdown shrink. The VIX 28→40 cut is not applied.
    This function runs that same engine and reads ``result.overlay``. Names with
    no price are dropped and the sleeve is renormalized inside the engine. They
    are not left as cash. There is no event-only order mode.
    """
    from config.regime_rules import STRATEGY_PARAMS
    from src.backtester.daily_overlay import policy_lines, weights_from_overlay
    from src.backtester.engine import BacktestEngine
    from src.backtester.regime_clock import MODE_TARGETED, classify_regimes

    price = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True).ffill()
    with open(MACRO_CACHE, "rb") as handle:
        macro = pickle.load(handle)
    history, current, _info = classify_regimes(macro, price, mode=MODE_TARGETED)
    regime = current.get("regime", "goldilocks")
    vix_now = float(current.get("vix", 0.0))

    available = set(price.columns)
    weights_map = {}
    for name, raw in REGIME_WEIGHTS.items():
        filtered = {k: v for k, v in raw.items() if k in available}
        total = sum(filtered.values())
        weights_map[name] = {k: v / total for k, v in filtered.items()} if total else {}

    ff = macro.get("ff_rate", pd.Series(dtype=float))
    if ff is not None and len(ff):
        ff = ff.copy()
        ff.index = pd.to_datetime(ff.index)
        ff = ff.loc[str(price.index.min().date()):]
        avg_rf = float(ff.mean() / 100.0) if len(ff) else 0.02
    else:
        avg_rf = 0.02
    engine = BacktestEngine(price, initial_capital=100_000, risk_free_rate=avg_rf)
    result = engine.run_optimized_regime_backtest(
        regime_history=history,
        regime_weights=weights_map,
        name="live-overlay",
        vix_data=macro.get("vix"),
        **STRATEGY_PARAMS,
    )
    overlay = result.overlay or {}
    weights = weights_from_overlay(overlay)
    last_px = price.ffill().iloc[-1]
    prices = {t: float(last_px[t]) for t in weights if t in last_px.index and pd.notna(last_px[t])}
    weights = {t: w for t, w in weights.items() if t in prices}
    print("\n".join(policy_lines()))
    print(
        f"\nOverlay as of {overlay.get('as_of')}: "
        f"trend_risk_on={overlay.get('trend_risk_on')} "
        f"equity_scale={float(overlay.get('equity_scale') or 1):.3f} "
        f"(vix={float(overlay.get('vix_scale') or 1):.3f}, "
        f"spy_dd={float(overlay.get('spy_dd_scale') or 1):.3f}) "
        f"vol_scale={overlay.get('vol_scale'):.3f} "
        f"dd_scale={overlay.get('dd_scale'):.3f} "
        f"gross={sum(weights.values()):.3f}"
    )
    return regime, vix_now, weights, prices
