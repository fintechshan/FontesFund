"""
config/regime_rules.py
======================
Macro-regime allocation rules for the ETF Investment Application.

Defines four macro regimes (goldilocks, reflation, stagflation, deflation),
their base portfolio weights, leveraged-instrument constraints, capital
management parameters, and risk limits.

All weights in each regime sum to **1.0** and serve as starting points
before the optimizer refines them.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

Mode = Literal["live", "backtest"]
WeightMode = Literal["cash", "renorm"]


# ═══════════════════════════════════════════════════════════════════════════
# Regime base allocations  (weights must sum to 1.0)
# ═══════════════════════════════════════════════════════════════════════════

REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    # -----------------------------------------------------------------
    # SIMPLIFIED 7-TICKER PORTFOLIO (v7, 2026-09-12)
    # Reduced from 8 to 7 tickers with balanced intermediate bond duration:
    # 1. Combined SPY + SPYI into SPY (eliminates covered-call redundancy).
    # 2. Replaced URA with AIPO (Defiance AI & Power Infrastructure ETF)
    #    to capture broader AI datacenter/nuclear/utility power infrastructure.
    # 3. Replaced TLT with IEF (iShares 7-10 Year Treasury Bond ETF)
    #    as the balanced middle-ground Treasury sleeve.
    # 4. Retained GLD as the un-correlated crisis safe haven.
    #
    # Universe: QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO
    # -----------------------------------------------------------------

    # -----------------------------------------------------------------
    # Goldilocks — Rising growth, Falling inflation (AGGRESSIVE)
    # QQQ 30% + SOXX 20% = concentrated AI/tech exposure.
    # SPY 25% = broad equity core (SPY 15% + SPYI 10%).
    # AIPO 3% = AI datacenter & power infrastructure thesis.
    # -----------------------------------------------------------------
    "goldilocks": {
        "QQQ":  0.30,   # Nasdaq-100 -- AI mega-cap
        "SOXX": 0.20,   # Semiconductors -- AI chip exposure
        "SPY":  0.25,   # S&P 500 -- broad equity core (combined SPY + SPYI)
        "IEF":  0.08,   # Intermediate Treasuries (7-10Y) -- balanced hedge
        "GLD":  0.10,   # Gold -- tail hedge
        "DBMF": 0.04,   # Managed futures -- uncorrelated alpha
        "AIPO": 0.03,   # AI & Power Infrastructure ETF
    },
    # -----------------------------------------------------------------
    # Reflation — Rising growth, Rising inflation (GROWTH TILT)
    # Gold/DBMF rise with inflation. AIPO 7% (power infra + inflation hedge).
    # -----------------------------------------------------------------
    "reflation": {
        "QQQ":  0.15,
        "SOXX": 0.10,
        "SPY":  0.18,   # S&P 500 (combined SPY 10% + SPYI 8%)
        "GLD":  0.20,   # Gold -- inflation hedge
        "AIPO": 0.07,   # AI & Power Infrastructure ETF
        "IEF":  0.05,   # Intermediate Treasuries (7-10Y)
        "DBMF": 0.25,   # Managed futures -- trend-following in inflation
    },
    # -----------------------------------------------------------------
    # Stagflation — Falling growth, Rising inflation (DEFENSIVE + ALTS)
    # Gold/DBMF/IEF dominate. AIPO 5% (inelastic power infrastructure demand).
    # -----------------------------------------------------------------
    "stagflation": {
        "GLD":  0.30,   # Gold -- dominant safe haven
        "DBMF": 0.25,   # Managed futures -- crisis alpha
        "IEF":  0.20,   # Intermediate Treasuries (7-10Y)
        "SPY":  0.15,   # Minimal equity (combined SPY 5% + SPYI 10%)
        "AIPO": 0.05,   # AI & Power Infrastructure ETF
        "QQQ":  0.03,
        "SOXX": 0.02,
    },
    # -----------------------------------------------------------------
    # Deflation — Falling growth, Falling inflation (MAX DEFENSE)
    # IEF 35% + GLD 20% dominate. DBMF 15% for crisis alpha.
    # -----------------------------------------------------------------
    "deflation": {
        "IEF":  0.35,   # Intermediate Treasuries (7-10Y) -- dominant flight to safety
        "GLD":  0.20,   # Gold -- safe haven
        "DBMF": 0.15,   # Managed futures -- crisis alpha
        "SPY":  0.20,   # Minimal equity (combined SPY 10% + SPYI 10%)
        "QQQ":  0.05,
        "SOXX": 0.03,
        "AIPO": 0.02,   # Power infra
    },
}


# ── Validate at import time ──────────────────────────────────────────────
for _regime, _weights in REGIME_WEIGHTS.items():
    _total = round(sum(_weights.values()), 10)
    if _total != 1.0:
        raise ValueError(
            f"Regime '{_regime}' weights sum to {_total}, expected 1.0. "
            f"Tickers: {_weights}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Leveraged-instrument gating rules
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LeveragedRule:
    """Conditions that must be satisfied before a leveraged ETF is included."""

    max_vix: float
    min_confidence: float          # 0-1 probability from the regime model
    max_allocation: float          # hard cap on portfolio weight


# Simplified 10-ticker portfolio contains no leveraged ETFs.
# TQQQ/SOXL/SSO were removed in v4 (2026-06-23) — their beta is captured
# by larger QQQ (28%) and SOXX (18%) positions without leverage decay risk.
LEVERAGED_RULES: dict[str, LeveragedRule] = {}


# ═══════════════════════════════════════════════════════════════════════════
# Capital management
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CapitalConfig:
    """Parameters governing capital deployment and contributions."""

    initial_capital: float = 100_000.0
    monthly_contribution: float = 10_000.0
    contribution_pause_threshold: float = -0.05
    """Pause monthly contributions when trailing drawdown exceeds this level."""


CAPITAL_CONFIG = CapitalConfig()


# ═══════════════════════════════════════════════════════════════════════════
# Risk limits
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RiskLimits:
    """Hard risk constraints enforced at rebalance and intra-day."""

    max_single_position: float = 0.25
    """No single ETF may exceed 25 % of the portfolio."""

    max_leveraged_total: float = 0.25
    """Combined leveraged exposure capped at 25 % (aggressive Goldilocks)."""

    max_daily_turnover: float = 0.30
    """Maximum portfolio turnover in a single rebalance (30 % — faster pivots)."""

    drawdown_circuit_breaker: float = 0.08
    """De-risk to defensive posture if drawdown from peak hits 8 % (tight for <10% DD target)."""

    vix_spike_threshold: float = 28.0
    """Override regime to deflation stance when VIX > 28 (earlier defensive pivot)."""


RISK_LIMITS = RiskLimits()


# ═══════════════════════════════════════════════════════════════════════════
# Production strategy overlay parameters — SINGLE SOURCE OF TRUTH (v7)
# ═══════════════════════════════════════════════════════════════════════════
# These are the exact kwargs passed to `run_optimized_regime_backtest` by BOTH
# run_backtest.py (CLI) and run_dashboard.py (deployed app), AND read by the
# dashboard's Rebalancing-Rules panel — so the displayed rules can never drift
# from what is actually run. Change the strategy HERE, in one place.
#
# v7 universe: live AIPO / backtest XLY (see dual-mode helpers below).
# Overlay knobs are unchanged from the v5.1 tuning (bear=0.70, dd=0.07, HAR).
STRATEGY_PARAMS: dict = {
    "risk_parity": True,
    "rp_vol_lookback": 60,
    "target_vol": 0.130,
    "vol_lookback": 21,
    "vol_lo": 0.50,
    "vol_hi": 1.50,
    "bear_equity_frac": 0.70,   # 70% regime book + 30% defense when SPY < 200-MA
    "dd_trigger": 0.07,         # daily drawdown circuit breaker
    "transaction_cost_bps": 5.0,
    "borrow_spread": 0.01,
    "vix_gate_level": 20.0,     # zero TQQQ/SOXL when yesterday's VIX >= this
    "mf_alloc": 0.0,
    "use_har_vol": True,        # HAR-RV vol overlay
}


# ═══════════════════════════════════════════════════════════════════════════
# Momentum overlay settings
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MomentumConfig:
    """Configuration for the cross-sectional momentum overlay."""

    lookback_months: int = 12
    """Momentum lookback window."""

    skip_months: int = 1
    """Skip most recent month (reversal effect)."""

    overweight_factor: float = 1.5
    """Multiply top-ranked weights by this factor."""

    underweight_factor: float = 0.5
    """Multiply bottom-ranked weights by this factor."""

    top_pct: float = 0.30
    """Top 30% of assets get overweight."""

    bottom_pct: float = 0.30
    """Bottom 30% of assets get underweight."""

    min_momentum: float = 0.0
    """Remove any ETF with 6-month momentum below this threshold."""


MOMENTUM_CONFIG = MomentumConfig()


# ═══════════════════════════════════════════════════════════════════════════
# Volatility targeting settings
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class VolTargetConfig:
    """Configuration for the volatility-targeting overlay."""

    target_volatility: float = 0.10
    """Annualised target volatility (10 %)."""

    vol_lookback_days: int = 20
    """Rolling window for realised-volatility estimation."""

    min_leverage: float = 0.50
    """Never scale below 50 % exposure."""

    max_leverage: float = 2.00
    """Never scale above 200 % exposure."""

    annualisation_factor: float = 252.0
    """Trading days per year."""


VOL_TARGET_CONFIG = VolTargetConfig()


# ═══════════════════════════════════════════════════════════════════════════
# Performance targets (backtest validation thresholds)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PerformanceTargets:
    """Hard targets the strategy is validated against in backtest.

    These are the SINGLE source of truth and match run_backtest.py / CLAUDE.md.
    (The earlier 17%/10%/1.80 values were obsolete aspirational targets and were
    corrected on 2026-06-22 to the validated set.)
    """

    min_annual_return: float = 0.16
    """Target 16 % annualised return."""

    max_drawdown: float = 0.148
    """Maximum 14.8 % peak-to-trough drawdown."""

    min_sharpe: float = 1.20
    """Minimum Sharpe ratio of 1.20."""

    backtest_years: int = 20
    """Validate over 20 years of history."""


PERFORMANCE_TARGETS = PerformanceTargets()


# ═══════════════════════════════════════════════════════════════════════════
# Convenience helpers
# ═══════════════════════════════════════════════════════════════════════════

def get_regime_tickers(regime: str) -> list[str]:
    """Return the list of tickers in the base allocation for *regime*.

    Parameters
    ----------
    regime:
        One of ``"goldilocks"``, ``"reflation"``, ``"stagflation"``,
        ``"deflation"``.

    Returns
    -------
    list[str]
        Ticker symbols.

    Raises
    ------
    KeyError
        If *regime* is not recognised.
    """
    return list(REGIME_WEIGHTS[regime].keys())


def get_base_weights(regime: str) -> dict[str, float]:
    """Return a **copy** of the base weight dict for *regime*.

    Callers may mutate the returned dict without affecting the canonical
    weights stored in :data:`REGIME_WEIGHTS`.
    """
    return dict(REGIME_WEIGHTS[regime])


def check_leveraged_eligibility(
    ticker: str,
    current_vix: float,
    regime_confidence: float,
) -> bool:
    """Return ``True`` if the leveraged ETF *ticker* passes its gating rules.

    Parameters
    ----------
    ticker:
        Leveraged ETF ticker (e.g. ``"TQQQ"``).
    current_vix:
        Latest VIX level.
    regime_confidence:
        Model confidence (0-1) in the current regime classification.

    Returns
    -------
    bool
        Whether the position is eligible to be included.
    """
    rule = LEVERAGED_RULES.get(ticker)
    if rule is None:
        logger.warning("No leveraged rule defined for '%s'.", ticker)
        return False
    eligible = current_vix <= rule.max_vix and regime_confidence >= rule.min_confidence
    if not eligible:
        logger.info(
            "Leveraged ETF %s ineligible: VIX=%.1f (max %.1f), "
            "confidence=%.2f (min %.2f).",
            ticker,
            current_vix,
            rule.max_vix,
            regime_confidence,
            rule.min_confidence,
        )
    return eligible


# ═══════════════════════════════════════════════════════════════════════════
# DUAL MODE: live AIPO / backtest XLY
# ═══════════════════════════════════════════════════════════════════════════
# Live production keeps the AIPO sleeve (AI & power infrastructure thesis).
# Long-history backtests map that sleeve onto XLY (consumer discretionary)
# so the weight is investable from 2005 instead of sitting in cash until
# AIPO's 2025-07 listing. Thesis differs — disclose both numbers separately.
#
# Usage:
#   from config.regime_rules import get_universe, get_regime_weights_for_mode
#   tickers = get_universe("backtest")             # includes XLY, not AIPO
#   weights = get_regime_weights_for_mode("live")  # AIPO as in REGIME_WEIGHTS
#
# Env:
#   FONTES_RUN_MODE=backtest|live     (run_backtest.py defaults to backtest)
#   FONTES_WEIGHT_MODE=cash|renorm    (cash = missing history stays cash)

LIVE_UNIVERSE: list[str] = ["QQQ", "SOXX", "SPY", "IEF", "GLD", "DBMF", "AIPO"]
BACKTEST_UNIVERSE: list[str] = ["QQQ", "SOXX", "SPY", "IEF", "GLD", "DBMF", "XLY"]

# Sleeve role -> ticker per mode. Keys are logical sleeve names.
SLEEVE_MAP: dict[str, dict[Mode, str]] = {
    "ai_power_or_proxy": {"live": "AIPO", "backtest": "XLY"},
}

# Direct ticker remap applied when building backtest weights from REGIME_WEIGHTS.
BACKTEST_TICKER_PROXY: dict[str, str] = {
    "AIPO": "XLY",
}


def get_run_mode(default: Mode = "live") -> Mode:
    """Return ``FONTES_RUN_MODE`` (``live`` or ``backtest``)."""
    raw = os.getenv("FONTES_RUN_MODE", default)
    if raw not in ("live", "backtest"):
        raise ValueError(f"Unknown FONTES_RUN_MODE {raw!r}; expected 'live' or 'backtest'")
    return raw  # type: ignore[return-value]


def get_weight_mode(default: WeightMode = "cash") -> WeightMode:
    """Return ``FONTES_WEIGHT_MODE`` (``cash`` or ``renorm``)."""
    raw = os.getenv("FONTES_WEIGHT_MODE", default)
    if raw not in ("cash", "renorm"):
        raise ValueError(f"Unknown FONTES_WEIGHT_MODE {raw!r}; expected 'cash' or 'renorm'")
    return raw  # type: ignore[return-value]


def get_universe(mode: Mode = "live") -> list[str]:
    """Return the ETF list for *mode* (``live`` or ``backtest``)."""
    if mode == "live":
        return list(LIVE_UNIVERSE)
    if mode == "backtest":
        return list(BACKTEST_UNIVERSE)
    raise ValueError(f"Unknown mode {mode!r}; expected 'live' or 'backtest'")


def _remap_weights(weights: dict[str, float], mode: Mode) -> dict[str, float]:
    if mode == "live":
        return dict(weights)
    out: dict[str, float] = {}
    for t, w in weights.items():
        t2 = BACKTEST_TICKER_PROXY.get(t, t)
        out[t2] = out.get(t2, 0.0) + w
    return out


def get_regime_weights_for_mode(mode: Mode = "live") -> dict[str, dict[str, float]]:
    """Copy of REGIME_WEIGHTS with sleeve tickers remapped for *mode*."""
    return {reg: _remap_weights(w, mode) for reg, w in REGIME_WEIGHTS.items()}


def get_base_weights_for_mode(regime: str, mode: Mode = "live") -> dict[str, float]:
    """Base weights for one regime under *mode*."""
    return _remap_weights(REGIME_WEIGHTS[regime], mode)
