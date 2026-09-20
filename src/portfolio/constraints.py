"""
src/portfolio/constraints.py
============================
Constraint validation utilities for portfolio risk management.

Provides independent validators for Sharpe ratio, maximum drawdown,
concentration, and leveraged exposure limits, as well as a unified
``validate_all`` method and helper series computations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config.etf_universe import LEVERAGED_ETFS
from config.regime_rules import RISK_LIMITS

logger = logging.getLogger(__name__)

# Tickers that are considered leveraged for constraint checking
_LEVERAGED_TICKERS: set[str] = {etf.ticker for etf in LEVERAGED_ETFS}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class ConstraintValidation:
    """Result of running all portfolio constraints."""

    sharpe_ok: bool = False
    sharpe_value: float = 0.0
    max_dd_ok: bool = False
    max_dd_value: float = 0.0
    concentration_ok: bool = False
    max_position: float = 0.0
    max_position_ticker: str = ""
    leveraged_ok: bool = False
    leveraged_total: float = 0.0
    all_passed: bool = False
    details: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.all_passed = all([
            self.sharpe_ok,
            self.max_dd_ok,
            self.concentration_ok,
            self.leveraged_ok,
        ])


# ---------------------------------------------------------------------------
# Constraint validator
# ---------------------------------------------------------------------------
class ConstraintValidator:
    """Stateless portfolio constraint validation utilities.

    All class methods are static-like but grouped for organisation.
    Default thresholds are pulled from :data:`config.regime_rules.RISK_LIMITS`
    but can be overridden per-call.
    """

    # ── Individual validators ─────────────────────────────────────────

    @staticmethod
    def validate_sharpe(
        returns: pd.Series,
        min_sharpe: float = 1.0,
        risk_free_rate: float = 0.04,
        periods_per_year: int = 252,
    ) -> tuple[bool, float]:
        """Check whether the annualised Sharpe ratio meets the minimum.

        Parameters
        ----------
        returns:
            Daily (or periodic) simple returns.
        min_sharpe:
            Minimum acceptable annualised Sharpe ratio.
        risk_free_rate:
            Annualised risk-free rate for excess-return calculation.
        periods_per_year:
            Trading periods per year (252 for daily).

        Returns
        -------
        tuple[bool, float]
            ``(passes, actual_sharpe)``
        """
        if returns.empty or len(returns) < 30:
            logger.warning("Insufficient return data for Sharpe calculation (%d obs).", len(returns))
            return False, 0.0

        excess = returns - risk_free_rate / periods_per_year
        mean_excess = excess.mean()
        std_excess = excess.std(ddof=1)

        if std_excess == 0 or np.isnan(std_excess):
            logger.warning("Zero or NaN volatility — cannot compute Sharpe.")
            return False, 0.0

        sharpe = (mean_excess / std_excess) * np.sqrt(periods_per_year)
        passes = sharpe >= min_sharpe
        logger.debug("Sharpe ratio: %.3f (min=%.2f, passed=%s)", sharpe, min_sharpe, passes)
        return passes, round(float(sharpe), 4)

    @staticmethod
    def validate_max_drawdown(
        returns: pd.Series,
        max_dd: float = 0.15,
    ) -> tuple[bool, float]:
        """Check whether the maximum drawdown stays within limits.

        Parameters
        ----------
        returns:
            Daily simple returns.
        max_dd:
            Maximum allowable drawdown (positive number, e.g. 0.15 = 15 %).

        Returns
        -------
        tuple[bool, float]
            ``(passes, actual_max_dd)`` — ``actual_max_dd`` is positive.
        """
        if returns.empty or len(returns) < 2:
            logger.warning("Insufficient return data for drawdown calculation.")
            return False, 0.0

        dd_series = ConstraintValidator.compute_drawdown_series(returns)
        actual_dd = float(dd_series.min())  # most negative value
        actual_dd_abs = abs(actual_dd)
        passes = actual_dd_abs <= max_dd
        logger.debug(
            "Max drawdown: %.2f%% (limit=%.2f%%, passed=%s)",
            actual_dd_abs * 100,
            max_dd * 100,
            passes,
        )
        return passes, round(actual_dd_abs, 4)

    @staticmethod
    def validate_concentration(
        weights: dict[str, float],
        max_single: float | None = None,
    ) -> tuple[bool, str]:
        """Check that no single position exceeds the concentration limit.

        Parameters
        ----------
        weights:
            Ticker → portfolio weight mapping.
        max_single:
            Maximum weight for any single position.  Defaults to
            ``RISK_LIMITS.max_single_position``.

        Returns
        -------
        tuple[bool, str]
            ``(passes, detail_string)`` where *detail_string* names the
            largest position and its weight.
        """
        if max_single is None:
            max_single = RISK_LIMITS.max_single_position

        if not weights:
            return True, "No positions"

        largest_ticker = max(weights, key=weights.get)  # type: ignore[arg-type]
        largest_weight = weights[largest_ticker]
        passes = largest_weight <= max_single
        detail = f"{largest_ticker}={largest_weight:.2%} (limit={max_single:.2%})"
        logger.debug("Concentration check: %s, passed=%s", detail, passes)
        return passes, detail

    @staticmethod
    def validate_leveraged_total(
        weights: dict[str, float],
        max_total: float | None = None,
    ) -> tuple[bool, float]:
        """Check that total leveraged ETF exposure is within limits.

        Parameters
        ----------
        weights:
            Ticker → portfolio weight mapping.
        max_total:
            Maximum combined weight for leveraged ETFs.  Defaults to
            ``RISK_LIMITS.max_leveraged_total``.

        Returns
        -------
        tuple[bool, float]
            ``(passes, actual_total)``
        """
        if max_total is None:
            max_total = RISK_LIMITS.max_leveraged_total

        total_lev = sum(
            w for ticker, w in weights.items()
            if ticker in _LEVERAGED_TICKERS
        )
        passes = total_lev <= max_total
        logger.debug(
            "Leveraged total: %.2f%% (limit=%.2f%%, passed=%s)",
            total_lev * 100,
            max_total * 100,
            passes,
        )
        return passes, round(float(total_lev), 4)

    # ── Unified validator ─────────────────────────────────────────────

    @staticmethod
    def validate_all(
        weights: dict[str, float],
        returns: pd.Series,
        min_sharpe: float = 1.0,
        max_dd: float = 0.15,
        risk_free_rate: float = 0.04,
    ) -> ConstraintValidation:
        """Run **all** constraint checks and return a consolidated result.

        Parameters
        ----------
        weights:
            Ticker → portfolio weight mapping.
        returns:
            Daily simple returns of the portfolio.
        min_sharpe:
            Minimum acceptable annualised Sharpe ratio.
        max_dd:
            Maximum allowable drawdown (positive, e.g. 0.15).
        risk_free_rate:
            Annualised risk-free rate.

        Returns
        -------
        ConstraintValidation
        """
        details: list[str] = []

        # Sharpe
        sharpe_ok, sharpe_val = ConstraintValidator.validate_sharpe(
            returns, min_sharpe=min_sharpe, risk_free_rate=risk_free_rate,
        )
        details.append(f"Sharpe={sharpe_val:.3f} ({'PASS' if sharpe_ok else 'FAIL'})")

        # Drawdown
        dd_ok, dd_val = ConstraintValidator.validate_max_drawdown(returns, max_dd=max_dd)
        details.append(f"MaxDD={dd_val:.2%} ({'PASS' if dd_ok else 'FAIL'})")

        # Concentration
        conc_ok, conc_detail = ConstraintValidator.validate_concentration(weights)
        details.append(f"Concentration: {conc_detail} ({'PASS' if conc_ok else 'FAIL'})")

        # Leverage
        lev_ok, lev_val = ConstraintValidator.validate_leveraged_total(weights)
        details.append(f"LeveragedTotal={lev_val:.2%} ({'PASS' if lev_ok else 'FAIL'})")

        # Determine max-position ticker
        max_ticker = max(weights, key=weights.get) if weights else ""  # type: ignore[arg-type]
        max_pos = weights.get(max_ticker, 0.0)

        validation = ConstraintValidation(
            sharpe_ok=sharpe_ok,
            sharpe_value=sharpe_val,
            max_dd_ok=dd_ok,
            max_dd_value=dd_val,
            concentration_ok=conc_ok,
            max_position=max_pos,
            max_position_ticker=max_ticker,
            leveraged_ok=lev_ok,
            leveraged_total=lev_val,
            details=details,
        )
        # __post_init__ sets all_passed
        validation.__post_init__()

        logger.info(
            "Constraint validation: all_passed=%s | %s",
            validation.all_passed,
            " | ".join(details),
        )
        return validation

    # ── Series helpers ────────────────────────────────────────────────

    @staticmethod
    def compute_drawdown_series(returns: pd.Series) -> pd.Series:
        """Compute the drawdown series from daily returns.

        Parameters
        ----------
        returns:
            Daily simple returns.

        Returns
        -------
        pd.Series
            Drawdown values (negative numbers) indexed like *returns*.
        """
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        return drawdown

    @staticmethod
    def compute_rolling_sharpe(
        returns: pd.Series,
        window: int = 252,
        risk_free_rate: float = 0.04,
    ) -> pd.Series:
        """Compute a rolling annualised Sharpe ratio.

        Parameters
        ----------
        returns:
            Daily simple returns.
        window:
            Rolling window in trading days.
        risk_free_rate:
            Annualised risk-free rate.

        Returns
        -------
        pd.Series
            Rolling Sharpe values; first ``window - 1`` entries are ``NaN``.
        """
        daily_rf = risk_free_rate / 252
        excess = returns - daily_rf
        rolling_mean = excess.rolling(window).mean()
        rolling_std = excess.rolling(window).std(ddof=1)
        rolling_sharpe = (rolling_mean / rolling_std) * np.sqrt(252)
        rolling_sharpe.name = "rolling_sharpe"
        return rolling_sharpe
