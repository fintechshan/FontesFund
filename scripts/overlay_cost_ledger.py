#!/usr/bin/env python3
"""Write the read-only overlay turnover ledger. Do not touch official equity CSVs.

Uses the price and macro caches and the production STRATEGY_PARAMS
(turnover_basis stays the engine default ``legacy``, apply_equity_cut stays
false). HAR-RV is on, because that is the production vol model. The JSON is
diagnostic. It is not a new headline CAGR.

    python scripts/overlay_cost_ledger.py
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.regime_rules import REGIME_WEIGHTS, STRATEGY_PARAMS  # noqa: E402
from src.backtester.engine import BacktestEngine  # noqa: E402
from src.backtester.overlay_cost_ledger import attach_saved_equity_rail  # noqa: E402
from src.backtester.regime_clock import MODE_TARGETED, classify_regimes  # noqa: E402

PRICE_CACHE = ROOT / "data" / "cache" / "price_data.csv"
MACRO_CACHE = ROOT / "data" / "cache" / "macro_data.pkl"
SAVED_EQUITY = ROOT / "data" / "backtest_results" / "aggressive_equity_curve.csv"
OUT = ROOT / "data" / "backtest_results" / "overlay_cost_ledger.json"


def _filter_weights(weights, available):
    filtered = {key: value for key, value in weights.items() if key in available}
    total = sum(filtered.values())
    if total > 0:
        filtered = {key: value / total for key, value in filtered.items()}
    return filtered


def main(argv=None) -> int:
    del argv
    if not PRICE_CACHE.is_file() or not MACRO_CACHE.is_file():
        print(
            "overlay cost ledger not computed: price_data.csv and macro_data.pkl are required. "
            "Official equity CSVs were not modified.",
            file=sys.stderr,
        )
        return 2
    prices = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True).ffill()
    with MACRO_CACHE.open("rb") as handle:
        macro = pickle.load(handle)
    regime_history, _current, _info = classify_regimes(macro, prices, mode=MODE_TARGETED)
    available = list(prices.columns)
    weights = {
        name: _filter_weights(sleeve, available)
        for name, sleeve in REGIME_WEIGHTS.items()
    }
    ff = macro.get("ff_rate")
    if ff is not None and len(ff):
        window = ff.copy()
        window.index = pd.to_datetime(window.index)
        window = window.loc[str(prices.index.min().date()):]
        rf = float(window.mean() / 100.0) if len(window) else 0.02
    else:
        rf = 0.02
    engine = BacktestEngine(prices, initial_capital=100_000, risk_free_rate=rf)
    result = engine.run_optimized_regime_backtest(
        regime_history=regime_history,
        regime_weights=weights,
        name="Optimized Regime Strategy",
        vix_data=macro.get("vix"),
        record_cost_inputs=True,
        **STRATEGY_PARAMS,
    )
    payload = dict(result.cost_ledger or {})
    payload["strategy_params_touched"] = False
    payload["apply_equity_cut"] = False
    payload["turnover_basis"] = payload.get("turnover_basis") or "legacy"
    payload["price_source"] = (
        "Fresh Yahoo adjusted closes and FRED fredgraph CSV downloaded for this "
        "diagnostic. STRATEGY_PARAMS were not changed. This is not a rewrite of "
        "aggressive_equity_curve.csv."
    )
    inputs = getattr(result, "cost_inputs", None)
    if result.equity_curve is not None and SAVED_EQUITY.is_file():
        saved = pd.read_csv(SAVED_EQUITY, index_col=0, parse_dates=True).iloc[:, 0]
        payload = attach_saved_equity_rail(
            payload,
            result.equity_curve,
            saved,
            "data/backtest_results/aggressive_equity_curve.csv",
        )
        if isinstance(inputs, dict) and len(saved):
            from src.backtester.overlay_cost_ledger import build_overlay_cost_ledger
            end = pd.Timestamp(saved.index.max())
            clipped = {}
            for key, value in inputs.items():
                clipped[key] = value.loc[:end]
            published = build_overlay_cost_ledger(
                turnover_basis="legacy",
                apply_equity_cut=False,
                transaction_cost_bps=float(STRATEGY_PARAMS["transaction_cost_bps"]),
                bear_equity_frac=float(STRATEGY_PARAMS["bear_equity_frac"]),
                **clipped,
            )
            payload["vs_published_path_b_window"] = {
                "as_of": str(end.date()),
                "note": (
                    "Same formula, inputs cut to the published aggressive_equity_curve.csv "
                    "end date. Drag is versus this run's unadjusted returns on that window, "
                    "not a replacement for the published CAGR."
                ),
                "sessions": published.get("sessions"),
                "sample_start": published.get("sample_start"),
                "vs_official_unadjusted": published.get("vs_official_unadjusted"),
                "still_uncosted_if_book_basis": published.get("still_uncosted_if_book_basis"),
                "turnover": published.get("turnover"),
            }
    if hasattr(result, "cost_inputs"):
        del result.cost_inputs
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    drag = (payload.get("vs_official_unadjusted") or {}).get("at_5bps") or {}
    print(
        f"wrote {OUT} as_of={payload.get('as_of')} "
        f"cagr_drag_5bps={drag.get('cagr_drag_bps')} "
        "(diagnostic only; official equity CSV not rewritten)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
