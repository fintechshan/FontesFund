"""Daily overlay shared by the production backtest and live orders.

The monthly Merrill sleeve is the starting book. The headline path then
applies this overlay every day, in ``run_optimized_regime_backtest`` and in
``scripts/ibkr_rebalance.py``. Both read the same last-day record.

Order:

1. 200-day SPY trend. Yesterday's close versus yesterday's 200-day average.
   If SPY is below it, keep ``bear_equity_frac`` of the sleeve and blend the
   rest into the defense basket.
2. Equity de-risk, the tighter of two scales. Yesterday's VIX is full equity
   at 28 and zero equity at 40, linear in between. SPY versus its trailing
   20-session high (window ending yesterday) is full equity down to a 4%
   drawdown and zero equity at 10%, linear in between. Only risk-asset
   tickers are cut. Freed weight goes to the safe basket. This is not a
   second CPI or GDP lag, and it is not the monthly VIX>30 deflation label.
3. Portfolio vol target. ``scale = clip(target / lagged own vol, vol_lo, vol_hi)``.
   Production uses the HAR-RV forecast. The scale is yesterday's.
4. Portfolio drawdown shrink. If strategy equity is more than ``dd_trigger``
   below its own peak, exposure falls toward ``dd_floor`` over ``dd_span``.

An event-only calendar (trade on CPI/GDP release days, or only when the
monthly VIX mean exceeds 30) is not this policy and is not a live mode.
Quoting that calendar would require a separate backtest and its own metrics.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VIX_FULL_EXPOSURE = 28.0
VIX_ZERO_EQUITY = 40.0
SPY_DD_START = 0.04
SPY_DD_ZERO = 0.10
SPY_DD_WINDOW = 20
SAFE_BASKET = {"SHY": 0.40, "AGG": 0.25, "GLD": 0.20, "IEF": 0.15}

# Risk assets the VIX / SPY-drawdown scale cuts. Bonds and gold stay.
# DBMF is a managed-futures sleeve, not an equity beta cut.
EQUITY_TICKERS = frozenset({
    "SPY", "QQQ", "IWM", "VEA", "VWO", "SOXX", "SMH", "DRAM", "XSD",
    "TQQQ", "SOXL", "SSO", "SPYI", "QQQI", "VNQ", "DBC", "AIPO", "XLY",
    "URA", "MOAT",
})

# Same numbers, kept so older imports still resolve. They are the headline
# equity cut, not a side backtest.
AGGRESSIVE_ONLY = {
    "vix_full_exposure": VIX_FULL_EXPOSURE,
    "vix_zero_equity": VIX_ZERO_EQUITY,
    "spy_dd_start": SPY_DD_START,
    "spy_dd_zero": SPY_DD_ZERO,
    "spy_dd_window": SPY_DD_WINDOW,
    "port_dd_start": 0.08,
}


def vix_linear_scale(vix: float) -> float:
    """Full equity at VIX 28, zero equity at VIX 40, linear between."""
    if vix is None or not np.isfinite(vix) or vix <= VIX_FULL_EXPOSURE:
        return 1.0
    span = VIX_ZERO_EQUITY - VIX_FULL_EXPOSURE
    return float(max(0.0, min(1.0, 1.0 - (float(vix) - VIX_FULL_EXPOSURE) / span)))


def spy_drawdown_scale(drawdown: float) -> float:
    """Full equity until SPY is 4% under its 20-session high, zero at 10%.

    ``drawdown`` is price / high - 1 (negative when below the high).
    """
    if drawdown is None or not np.isfinite(drawdown) or drawdown >= -SPY_DD_START:
        return 1.0
    span = SPY_DD_ZERO - SPY_DD_START
    return float(max(0.0, min(1.0, 1.0 - (abs(float(drawdown)) - SPY_DD_START) / span)))


def equity_scales(index, spy: pd.Series | None, vix_lag: pd.Series | None) -> pd.DataFrame:
    """Daily scales aligned to return dates. Both inputs are already lagged.

    ``vix_lag`` is yesterday's VIX (the caller shifted it). ``spy`` is the
    price series; this function shifts it so the high and the close both end
    yesterday. CPI and GDP are not touched.
    """
    idx = pd.DatetimeIndex(index)
    vix_level = pd.Series(np.nan, index=idx)
    vix_s = pd.Series(1.0, index=idx)
    if vix_lag is not None and len(vix_lag):
        level = pd.Series(vix_lag).reindex(idx)
        vix_level = level
        vix_s = level.map(vix_linear_scale).astype(float)

    spy_dd = pd.Series(np.nan, index=idx)
    spy_s = pd.Series(1.0, index=idx)
    if spy is not None and len(spy):
        yesterday = pd.Series(spy).reindex(idx).shift(1)
        high = yesterday.rolling(SPY_DD_WINDOW).max()
        dd = (yesterday - high) / high
        spy_dd = dd
        spy_s = dd.map(spy_drawdown_scale).astype(float)

    return pd.DataFrame({
        "vix_scale": vix_s,
        "spy_dd_scale": spy_s,
        "equity_scale": np.minimum(vix_s.to_numpy(), spy_s.to_numpy()),
        "vix_yesterday": vix_level,
        "spy_dd": spy_dd,
    }, index=idx)


def derisk_weights(weights: dict, equity_scale: float, tradable) -> dict[str, float]:
    """Cut risk assets by ``equity_scale`` and park the freed weight in the safe basket.

    Safe names that are not in ``tradable`` are skipped. If none of the basket
    is tradable, the freed weight is dropped (the sleeve renormalizes later
    only at the monthly step; here the gap is uninvested).
    """
    scale = 1.0 if equity_scale is None or not np.isfinite(equity_scale) else float(equity_scale)
    scale = min(1.0, max(0.0, scale))
    tradable = set(tradable)
    if scale >= 1.0 - 1e-12:
        return {t: float(w) for t, w in weights.items() if float(w) > 1e-12}
    out: dict[str, float] = {}
    removed = 0.0
    for ticker, weight in weights.items():
        weight = float(weight)
        if ticker in EQUITY_TICKERS:
            out[ticker] = weight * scale
            removed += weight * (1.0 - scale)
        else:
            out[ticker] = weight
    basket = {t: s for t, s in SAFE_BASKET.items() if t in tradable}
    total = sum(basket.values())
    if total > 0 and removed > 0:
        for ticker, share in basket.items():
            out[ticker] = out.get(ticker, 0.0) + removed * share / total
    return {t: w for t, w in out.items() if w > 1e-12}


def derisk_frame(weights: pd.DataFrame, equity_scale: pd.Series) -> pd.DataFrame:
    """Row-wise ``derisk_weights`` for the backtest weight matrix."""
    scale = equity_scale.reindex(weights.index).fillna(1.0).clip(0.0, 1.0)
    out = weights.astype(float).copy()
    equity_cols = [c for c in out.columns if c in EQUITY_TICKERS]
    if not equity_cols:
        return out
    held = out[equity_cols]
    out.loc[:, equity_cols] = held.mul(scale, axis=0)
    removed = held.sum(axis=1) * (1.0 - scale)
    basket = {t: s for t, s in SAFE_BASKET.items() if t in out.columns}
    total = sum(basket.values())
    if total <= 0 or float(removed.abs().sum()) == 0.0:
        return out
    for ticker, share in basket.items():
        out[ticker] = out[ticker] + removed * (share / total)
    return out


def dd_scale(drawdown: float, trigger: float, floor: float, span: float) -> float:
    """Exposure scale from the strategy's own peak-to-trough drawdown.

    ``drawdown`` is negative (equity / peak - 1). Matches the loop in
    ``run_optimized_regime_backtest``.
    """
    if drawdown < -trigger:
        return max(floor, 1.0 - (abs(drawdown) - trigger) / span)
    return 1.0


def weights_from_overlay(overlay: dict) -> dict[str, float]:
    """Target notionals for the last backtest day.

    Trend blend, then the VIX/SPY equity cut, then one gross scale =
    vol scale × drawdown scale. Weights may sum to more or less than 1.
    That gross exposure is the backtest's leverage. Missing ETFs are already
    gone from ``base_weights``: the engine drops a name with no prior-day
    price and renormalizes. It does not park the missing weight in cash.
    """
    if not overlay or overlay.get("policy") != "optimized_daily":
        raise ValueError("overlay is not the optimized daily policy")
    base = dict(overlay.get("base_weights") or {})
    defense = dict(overlay.get("defense_weights") or {})
    if overlay.get("trend_risk_on", True):
        mixed = base
    else:
        bear = float(overlay["bear_equity_frac"])
        names = set(base) | set(defense)
        mixed = {
            t: bear * base.get(t, 0.0) + (1.0 - bear) * defense.get(t, 0.0)
            for t in names
        }
    tradable = overlay.get("tradable")
    if not tradable:
        tradable = set(mixed) | set(SAFE_BASKET)
    mixed = derisk_weights(mixed, float(overlay.get("equity_scale", 1.0)), tradable)
    gross = float(overlay["vol_scale"]) * float(overlay["dd_scale"])
    return {t: w * gross for t, w in mixed.items() if w * gross > 1e-8}


def policy_lines() -> list[str]:
    """Operator text. Thresholds come from this module and STRATEGY_PARAMS."""
    from config.regime_rules import STRATEGY_PARAMS as sp

    return [
        "Live orders use the same daily overlay as run_optimized_regime_backtest. "
        "The monthly sleeve is only the starting book.",
        "1. Monthly sleeve from the targeted clock: CPI +1 month, GDP +4 months, "
        "VIX monthly mean and SPY 12-month momentum lagged to the prior month-end. "
        "That market lag is not a second CPI/GDP lag. Merrill weights stay. "
        "GDPNow is not the clock. The Auditor extra month is not the default.",
        "2. Daily 200-day trend: yesterday's SPY versus yesterday's 200-day average. "
        f"If SPY is below it, keep {sp['bear_equity_frac']:.0%} of the sleeve and "
        f"move {1 - sp['bear_equity_frac']:.0%} into the defense basket.",
        "3. Daily equity de-risk, mandatory on this path: yesterday's VIX scales "
        f"equity from {VIX_FULL_EXPOSURE:.0f} (full) to {VIX_ZERO_EQUITY:.0f} (zero), "
        f"and SPY's drawdown from its prior {SPY_DD_WINDOW:.0f}-session high scales "
        f"equity from {SPY_DD_START:.0%} to {SPY_DD_ZERO:.0%}. The tighter scale wins. "
        "Freed weight goes to SHY/AGG/GLD/IEF. This is not the monthly VIX>30 label.",
        "4. Daily portfolio vol target: scale = clip(target / lagged own vol, "
        f"{sp['vol_lo']:.2f}, {sp['vol_hi']:.2f}) with target {sp['target_vol']:.0%}. "
        "Production uses the HAR-RV forecast (use_har_vol). The scale is yesterday's.",
        "5. Daily portfolio drawdown: if strategy equity is more than "
        f"{sp['dd_trigger']:.0%} below its own peak, exposure falls toward "
        f"{sp['dd_floor']:.0%} over a further {sp['dd_span']:.0%} of drawdown.",
        "CPI and GDP advance release days, and a VIX or momentum regime flip, "
        "change the monthly sleeve. They do not turn the daily overlay off. "
        "The daily data refresh does not send orders. There is no event-only "
        "live mode; that calendar would be a different backtest with its own metrics.",
        "Separate from the equity cut: yesterday's VIX at or above "
        f"{sp['vix_gate_level']:.0f} drops TQQQ/SOXL. The v7 sleeve holds neither. "
        "A latest VIX print above 30 forces the deflation label for the current month.",
    ]
