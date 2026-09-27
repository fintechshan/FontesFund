"""Daily overlay shared by the production backtest and live orders.

``run_optimized_regime_backtest`` applies three daily rules on top of the
monthly regime sleeve. The headline path includes all three. A live book
that only rebalances on CPI/GDP release days, or only when monthly VIX
exceeds 30, is a different strategy.

This module is the order-side view of those rules. The engine records the
last day's inputs on ``BacktestResult.overlay``. ``weights_from_overlay``
turns that record into target notionals.

The VIX 28→40 linear cut and the 20-day SPY-high cut are **not** in this
policy. They are implemented only in ``run_aggressive_backtest``. Do not
describe them as the live rule for the optimized path.
"""
from __future__ import annotations

# Thresholds inside run_aggressive_backtest. Documented so they are not
# confused with the production overlay. Not used to size the live book.
AGGRESSIVE_ONLY = {
    "vix_full_exposure": 28.0,
    "vix_zero_equity": 40.0,
    "spy_dd_start": 0.04,
    "spy_dd_zero": 0.10,
    "spy_dd_window": 20,
    "port_dd_start": 0.08,
}


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

    Trend blend, then one gross scale = vol scale × drawdown scale.
    Weights may sum to more or less than 1. That gross exposure is the
    backtest's leverage. Missing ETFs are already gone from ``base_weights``:
    the engine drops a name with no prior-day price and renormalizes. It does
    not park the missing weight in cash.
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
    gross = float(overlay["vol_scale"]) * float(overlay["dd_scale"])
    return {t: w * gross for t, w in mixed.items() if w * gross > 1e-8}


def policy_lines() -> list[str]:
    """Operator text. Thresholds come from STRATEGY_PARAMS, not from a CAGR."""
    from config.regime_rules import STRATEGY_PARAMS as sp

    return [
        "Live orders use the same daily overlay as run_optimized_regime_backtest. "
        "The monthly sleeve is only the starting book.",
        "1. Monthly sleeve from the targeted clock: CPI +1 month, GDP +4 months, "
        "VIX monthly mean and SPY 12-month momentum lagged to the prior month-end. "
        "That market lag is not a second CPI/GDP lag.",
        "2. Daily 200-day trend: yesterday's SPY versus yesterday's 200-day average. "
        f"If SPY is below it, keep {sp['bear_equity_frac']:.0%} of the sleeve and "
        f"move {1 - sp['bear_equity_frac']:.0%} into the defense basket.",
        "3. Daily portfolio vol target: scale = clip(target / lagged own vol, "
        f"{sp['vol_lo']:.2f}, {sp['vol_hi']:.2f}) with target {sp['target_vol']:.0%}. "
        "Production uses the HAR-RV forecast (use_har_vol). The scale is yesterday's.",
        "4. Daily portfolio drawdown: if strategy equity is more than "
        f"{sp['dd_trigger']:.0%} below its own peak, exposure falls toward "
        f"{sp['dd_floor']:.0%} over a further {sp['dd_span']:.0%} of drawdown.",
        "CPI and GDP advance release days, and a VIX or momentum regime flip, "
        "change the monthly sleeve. They do not turn the daily overlay off. "
        "The daily data refresh does not send orders.",
        "Separate rule, not this overlay: yesterday's VIX at or above "
        f"{sp['vix_gate_level']:.0f} drops TQQQ/SOXL. The v7 sleeve holds neither. "
        "A latest VIX print above 30 forces the deflation label. That is the "
        "monthly regime rule, not the 28→40 equity cut.",
        "The 28→40 VIX cut and the 20-day SPY-high cut exist only in "
        "run_aggressive_backtest. They are not part of this live book.",
    ]
