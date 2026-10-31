"""Canadian sleeve on the shared Merrill clock.

The production path is targeted: CPI +1 month, GDP +4 months, then
``lag_vix_and_momentum_one_month`` on the VIX monthly mean and VFV.TO
12-month momentum. Lookahead, unlagged, the extra month, and first-release
vintage are comparison paths. They are not the CDN cards.

Momentum is VFV.TO. Passing SPY here would be a different book.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.cdn_regime_rules import CDN_AB_WINNER, CDN_UNIVERSE
from src.backtester.regime_clock import (
    CPI_RELEASE_LAG_M,
    GDP_RELEASE_LAG_M,
    MODE_AUDITOR,
    MODE_LOOKAHEAD,
    MODE_TARGETED,
    MODE_UNLAGGED,
    MODE_VINTAGE,
    classify_regimes,
    load_realtime_vintage,
)

ROOT = Path(__file__).resolve().parents[2]
CDN_PRICE_CACHE = ROOT / "data" / "cache" / "cdn_price_data.csv"
CDN_COMPARISON = ROOT / "data" / "backtest_results" / "cdn_comparison.csv"
CDN_EQUITY = ROOT / "data" / "backtest_results" / "cdn_equity_curve.csv"
CDN_MONTHLY = ROOT / "data" / "backtest_results" / "cdn_monthly_returns.csv"
CDN_CONFIG = ROOT / "data" / "backtest_results" / "cdn_strategy_config.json"
CDN_BENCHMARK = ROOT / "data" / "backtest_results" / "cdn_benchmark_xiu.csv"
CDN_HONESTY = ROOT / "data" / "backtest_results" / "cdn_lag_honesty.csv"
US_EQUITY = ROOT / "data" / "backtest_results" / "aggressive_equity_curve.csv"
CDN_BENCHMARK_TICKER = "XIU.TO"

# Same labels as data/backtest_results/lag_honesty.csv, plus the two
# comparison clocks the US auditor already scores (unlagged, extra month).
HONESTY_ROWS = {
    MODE_LOOKAHEAD: "A_lookahead",
    MODE_TARGETED: "B_targeted",
    MODE_VINTAGE: "C_vintage",
    MODE_UNLAGGED: "unlagged",
    MODE_AUDITOR: "auditor_extra",
}


def cdn_decision_start(price_data: pd.DataFrame) -> pd.Timestamp | None:
    """First session on which every live sleeve name has a print."""
    if price_data is None or price_data.empty:
        return None
    missing = [ticker for ticker in CDN_UNIVERSE if ticker not in price_data.columns]
    if missing:
        return None
    ready = price_data[list(CDN_UNIVERSE)].dropna()
    if len(ready) == 0:
        return None
    return pd.Timestamp(ready.index[0])


def classify_cdn_regimes(
    macro: dict,
    price_data: pd.DataFrame,
    momentum_ticker: str = "VFV.TO",
    mode: str = MODE_TARGETED,
    vintage: dict | None = None,
):
    """CDN history on one shared-clock mode.

    Returns ``(history, current, info)``. An empty sleeve returns an empty
    history and does not invent a regime.
    """
    start = cdn_decision_start(price_data)
    if start is None:
        empty = pd.DataFrame(columns=["date", "regime"])
        info = {
            "mode": mode,
            "empty": True,
            "momentum_column": momentum_ticker,
            "cpi_lag_months": CPI_RELEASE_LAG_M,
            "gdp_lag_months": GDP_RELEASE_LAG_M,
            "same_month_market": mode in (MODE_LOOKAHEAD, MODE_UNLAGGED),
            "publication_lag": mode != MODE_UNLAGGED,
            "vintage_fallback": False,
        }
        return empty, {}, info
    history, current, info = classify_regimes(
        macro,
        price_data,
        mode=mode,
        vintage=vintage,
        momentum_column=momentum_ticker,
        decision_start=start,
    )
    info = dict(info)
    info["momentum_column"] = momentum_ticker
    info["decision_start"] = str(pd.Timestamp(start).date())
    info["empty"] = False
    return history, current, info


def cdn_live_regime(macro, prices, us_regime: str = "goldilocks"):
    """Targeted CDN label when the TSX cache is loaded. Otherwise the US label.

    The fallback is explicit. It is not a second clock.
    """
    history, current, info = classify_cdn_regimes(macro, prices, mode=MODE_TARGETED)
    if info.get("empty") or not current or not current.get("regime"):
        return us_regime, "us_fallback", history
    return current["regime"], "targeted", history


def prove_cdn_clock() -> dict:
    """Targeted CDN clock matches itself and is not the lookahead calendar.

    Synthetic prices only. No cache and no network. A failure here means
    ``classify_cdn_regimes`` stopped using CPI+1 / GDP+4 with VFV lagged
    one month.
    """
    index = pd.bdate_range("2013-01-02", "2014-06-30")
    prices = pd.DataFrame(
        {ticker: 100.0 + pd.Series(range(len(index)), index=index, dtype=float) for ticker in CDN_UNIVERSE},
        index=index,
    )
    vix = pd.Series(14.0, index=index)
    vix.loc["2013-06-03":"2013-06-28"] = 45.0
    cpi = pd.Series(
        [100 * (1.002 ** i) for i in range(48)],
        index=pd.date_range("2011-01-01", periods=48, freq="MS"),
    )
    gdp = pd.Series(2.2, index=pd.date_range("2011-01-01", "2014-06-01", freq="QS"))
    macro = {"vix": vix, "cpi": cpi, "gdp": gdp}

    history, _current, info = classify_cdn_regimes(macro, prices)
    targeted, _c2, targeted_info = classify_cdn_regimes(macro, prices, mode=MODE_TARGETED)
    lookahead, _c3, look_info = classify_cdn_regimes(macro, prices, mode=MODE_LOOKAHEAD)
    matches = list(history["regime"]) == list(targeted["regime"])
    differs = list(targeted["regime"]) != list(lookahead["regime"])
    lags_ok = (
        info.get("cpi_lag_months") == CPI_RELEASE_LAG_M == 1
        and info.get("gdp_lag_months") == GDP_RELEASE_LAG_M == 4
    )
    ok = bool(
        matches
        and differs
        and info.get("mode") == MODE_TARGETED
        and targeted_info.get("publication_lag") is True
        and targeted_info.get("same_month_market") is False
        and look_info.get("same_month_market") is True
        and info.get("momentum_column") == "VFV.TO"
        and lags_ok
        and not info.get("empty")
    )
    return {
        "ok": ok,
        "matches_targeted": matches,
        "differs_from_lookahead": differs,
        "mode": info.get("mode"),
        "same_month_market": info.get("same_month_market"),
        "publication_lag": info.get("publication_lag"),
        "cpi_lag_months": info.get("cpi_lag_months"),
        "gdp_lag_months": info.get("gdp_lag_months"),
        "momentum_column": info.get("momentum_column"),
    }


def run_cdn_honesty_paths(price_data: pd.DataFrame, macro: dict, vintage: dict | None = None):
    """Targeted CDN book plus comparison clocks. Vintage is omitted on fallback.

    Risk-free rate stays 2%, the CDN engine setting. This does not retune weights.
    """
    from src.backtester.engine import BacktestEngine
    from config.regime_rules import STRATEGY_PARAMS
    from config.cdn_regime_rules import CDN_REGIME_WEIGHTS

    if vintage is None:
        vintage = load_realtime_vintage()

    modes = [MODE_TARGETED, MODE_LOOKAHEAD, MODE_UNLAGGED, MODE_AUDITOR]
    histories = {}
    for mode in modes:
        histories[mode], _current, _info = classify_cdn_regimes(macro, price_data, mode=mode)

    if vintage is not None:
        _hist, _current, info = classify_cdn_regimes(
            macro, price_data, mode=MODE_VINTAGE, vintage=vintage,
        )
        if not info.get("vintage_fallback") and not info.get("empty"):
            histories[MODE_VINTAGE] = _hist

    columns = [ticker for ticker in CDN_UNIVERSE if ticker in price_data.columns]
    engine = BacktestEngine(price_data[columns], initial_capital=100_000, risk_free_rate=0.02)
    vix_series = macro.get("vix")
    names = {
        MODE_TARGETED: CDN_AB_WINNER,
        MODE_LOOKAHEAD: "CDN month-end look-ahead",
        MODE_UNLAGGED: "CDN unlagged",
        MODE_AUDITOR: "CDN extra month",
        MODE_VINTAGE: "CDN first-release vintage",
    }
    results = {}
    for mode, hist in histories.items():
        if hist is None or len(hist) == 0:
            continue
        results[mode] = engine.run_optimized_regime_backtest(
            regime_history=hist,
            regime_weights=CDN_REGIME_WEIGHTS,
            name=names[mode],
            vix_data=vix_series,
            **STRATEGY_PARAMS,
        )
    return results


def load_benchmark_series() -> pd.Series:
    if not CDN_BENCHMARK.exists():
        return pd.Series(dtype=float)
    frame = pd.read_csv(CDN_BENCHMARK, index_col=0, parse_dates=True)
    if frame.shape[1] == 0:
        return pd.Series(dtype=float)
    series = frame.iloc[:, 0].dropna()
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


def load_cdn_prices() -> pd.DataFrame:
    if not CDN_PRICE_CACHE.exists():
        return pd.DataFrame()
    frame = pd.read_csv(CDN_PRICE_CACHE, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index)
    return frame.sort_index()


def dashboard_cdn_payload(macro, us_regime: str = "goldilocks", us_history: pd.DataFrame | None = None) -> dict:
    """Series and weights the CDN tab and the auditor read.

    Live weights follow the targeted CDN clock when the TSX cache is present.
    Without that cache the US regime label is used and ``cdn_regime_source``
    says so.
    """
    import json

    from config.cdn_regime_rules import CDN_REGIME_WEIGHTS

    equity = pd.Series(dtype=float)
    monthly = pd.Series(dtype=float)
    meta: dict = {}
    if CDN_EQUITY.exists():
        equity = pd.read_csv(CDN_EQUITY, index_col=0, parse_dates=True).iloc[:, 0]
    if CDN_MONTHLY.exists():
        monthly = pd.read_csv(CDN_MONTHLY, index_col=0, parse_dates=True).iloc[:, 0]
    if CDN_CONFIG.exists():
        meta = json.loads(CDN_CONFIG.read_text())
    prices = load_cdn_prices()
    regime, source, history = cdn_live_regime(macro, prices, us_regime)
    if history is None or len(history) == 0:
        history = us_history if isinstance(us_history, pd.DataFrame) else pd.DataFrame()
        if len(history) and "date" in history.columns:
            history = history[history["date"] >= "2012-11-01"].copy()
    weights = dict(CDN_REGIME_WEIGHTS.get(regime, CDN_REGIME_WEIGHTS["goldilocks"]))
    changes = []
    if isinstance(history, pd.DataFrame) and not history.empty and "regime" in history.columns:
        prev = None
        ordered = history.sort_values("date") if "date" in history.columns else history
        for _, row in ordered.iterrows():
            label = row["regime"]
            stamp = row["date"] if "date" in history.columns else row.name
            if prev is not None and label != prev:
                old_w = CDN_REGIME_WEIGHTS.get(prev, {})
                new_w = CDN_REGIME_WEIGHTS.get(label, {})
                diffs = []
                for ticker in CDN_UNIVERSE:
                    delta = new_w.get(ticker, 0) - old_w.get(ticker, 0)
                    if abs(delta) > 0.01:
                        diffs.append(f"{ticker}: {delta:+.0%}")
                changes.append({
                    "date": stamp.strftime("%Y-%m") if hasattr(stamp, "strftime") else str(stamp)[:7],
                    "from_regime": str(prev).capitalize(),
                    "to_regime": str(label).capitalize(),
                    "reason": (
                        f"Growth {'rising' if label in ('goldilocks', 'reflation') else 'slowing'}, "
                        f"Inflation {'rising' if label in ('reflation', 'stagflation') else 'cooling'}"
                    ),
                    "key_changes": " | ".join(diffs) if diffs else "Allocation shift",
                })
            prev = label
    return {
        "cdn_equity_curve": equity,
        "cdn_monthly_returns": monthly,
        "cdn_backtest_meta": meta,
        "cdn_current_weights": weights,
        "cdn_all_weights": CDN_REGIME_WEIGHTS,
        "cdn_regime_changes": changes,
        "cdn_benchmark": load_benchmark_series(),
        "cdn_prices": prices,
        "cdn_regime_source": source,
        "cdn_regime": regime,
    }


def honesty_frame(results: dict) -> pd.DataFrame:
    """One row per CDN clock, indexed like ``lag_honesty.csv``."""
    rows = []
    for mode, label in HONESTY_ROWS.items():
        res = results.get(mode)
        if res is None:
            continue
        rows.append({
            "mode": label,
            "cagr": res.annual_return,
            "max_dd": res.max_drawdown,
            "sharpe": res.sharpe_ratio,
            "volatility": res.volatility,
            "sortino": res.sortino_ratio,
            "calmar": res.calmar_ratio,
            "total_return": res.total_return,
            "win_rate": res.win_rate,
        })
    frame = pd.DataFrame(rows)
    if len(frame) == 0:
        return frame
    return frame.set_index("mode")
