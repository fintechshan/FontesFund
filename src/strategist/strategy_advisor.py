"""
src/strategist/strategy_advisor.py
===================================
Combines regime classification with analyst sentiment to produce
portfolio allocation recommendations for the ETF Investment Application.

The :class:`StrategyAdvisor` orchestrates the full pipeline:

1. Feature engineering → regime detection → base allocation lookup.
2. Analyst-sentiment adjustment (placeholder — wired up later).
3. Leveraged-ETF eligibility gating (VIX, confidence, regime checks).
4. Weight normalisation and risk-flag detection.
5. Returns a :class:`StrategyRecommendation` dataclass with full context.

Typical usage::

    from src.strategist.data_collector import MacroDataCollector
    from src.strategist.feature_engineer import FeatureEngineer
    from src.strategist.regime_detector import RegimeDetector
    from src.strategist.strategy_advisor import StrategyAdvisor

    advisor = StrategyAdvisor(collector, engineer, detector)
    rec = advisor.generate_recommendation()
    print(rec.regime, rec.target_weights)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from config.etf_universe import get_etf, LEVERAGED_ETFS
from config.regime_rules import (
    LEVERAGED_RULES,
    REGIME_WEIGHTS,
    RISK_LIMITS,
    check_leveraged_eligibility,
    get_base_weights,
)
from src.strategist.data_collector import MacroDataCollector
from src.strategist.feature_engineer import FeatureEngineer
from src.strategist.regime_detector import RegimeDetector

logger = logging.getLogger(__name__)

# Set of leveraged ETF tickers for quick membership checks
_LEVERAGED_TICKERS: set[str] = {etf.ticker for etf in LEVERAGED_ETFS}


# ═══════════════════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StrategyRecommendation:
    """Full strategy recommendation returned by :meth:`StrategyAdvisor.generate_recommendation`.

    Attributes
    ----------
    regime : str
        Detected macro regime (``'goldilocks'``, ``'reflation'``,
        ``'stagflation'``, or ``'deflation'``).
    confidence : float
        Model confidence in the regime classification (0–1).
    target_weights : dict[str, float]
        Recommended portfolio weights (ticker → weight, sums to 1.0).
    analyst_adjustment : dict[str, float]
        Weight adjustments applied by analyst sentiment (ticker → delta).
        Empty when the analyst module is not connected.
    rationale : list[str]
        Human-readable explanation of the recommendation.
    timestamp : datetime
        UTC timestamp when the recommendation was generated.
    macro_snapshot : dict[str, Any]
        Key macro indicator values at recommendation time.
    risk_flags : list[str]
        Any risk warnings that were triggered.
    """

    regime: str
    confidence: float
    target_weights: dict[str, float]
    analyst_adjustment: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    macro_snapshot: dict[str, Any] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Strategy advisor
# ═══════════════════════════════════════════════════════════════════════════

class StrategyAdvisor:
    """Orchestrates regime detection, analyst input, and weight construction.

    Parameters
    ----------
    data_collector : MacroDataCollector
        Provides raw macro / market data.
    feature_engineer : FeatureEngineer
        Transforms raw data into regime-ready features.
    regime_detector : RegimeDetector
        Trained (or loadable) HMM regime classifier.
    """

    def __init__(
        self,
        data_collector: MacroDataCollector,
        feature_engineer: FeatureEngineer,
        regime_detector: RegimeDetector,
    ) -> None:
        self.data_collector = data_collector
        self.feature_engineer = feature_engineer
        self.regime_detector = regime_detector

        logger.info("StrategyAdvisor initialised.")

    # ──────────────────────────────────────────────────────────────────────
    # Primary recommendation
    # ──────────────────────────────────────────────────────────────────────

    def generate_recommendation(self) -> StrategyRecommendation:
        """Generate a full portfolio strategy recommendation.

        Workflow
        --------
        1. Compute regime features via :class:`FeatureEngineer`.
        2. Predict the current regime + confidence via :class:`RegimeDetector`.
        3. Look up base weights from :mod:`config.regime_rules`.
        4. Apply analyst-sentiment adjustment (placeholder).
        5. Gate leveraged ETFs against VIX / confidence thresholds.
        6. Normalise weights to sum to 1.0.
        7. Build the human-readable rationale.
        8. Detect risk flags.
        9. Return a :class:`StrategyRecommendation`.

        Returns
        -------
        StrategyRecommendation
            Complete recommendation with weights, rationale, and flags.
        """
        logger.info("Generating strategy recommendation …")

        # 1. Features
        regime_features = self.feature_engineer.compute_regime_features()
        if regime_features.empty:
            logger.error("Feature computation returned empty — cannot recommend.")
            return self._empty_recommendation("Feature computation failed")

        # 2. Regime + confidence
        regime, confidence = self.regime_detector.predict_regime(regime_features)

        # Macro snapshot for context
        snapshot = self.feature_engineer.get_current_snapshot()
        current_vix = self._extract_vix(snapshot)

        # 3. Base weights
        try:
            base_weights = get_base_weights(regime)
        except KeyError:
            logger.error("Unknown regime '%s' — falling back to deflation.", regime)
            regime = "deflation"
            base_weights = get_base_weights(regime)

        # 4. Analyst adjustment (placeholder)
        adjusted_weights, analyst_adj = self._apply_analyst_adjustment(
            base_weights, regime
        )

        # 5. Leveraged-ETF eligibility
        adjusted_weights = self._check_leveraged_eligibility(
            adjusted_weights, regime, confidence, current_vix
        )

        # 6. Normalise
        adjusted_weights = self._normalise_weights(adjusted_weights)

        # 7. Risk flags
        risk_flags = self._detect_risk_flags(snapshot)

        # 8. Rationale
        rationale = self._generate_rationale(
            regime, confidence, adjusted_weights, risk_flags, snapshot
        )

        rec = StrategyRecommendation(
            regime=regime,
            confidence=confidence,
            target_weights=adjusted_weights,
            analyst_adjustment=analyst_adj,
            rationale=rationale,
            macro_snapshot=snapshot,
            risk_flags=risk_flags,
        )

        logger.info(
            "Recommendation generated: regime=%s confidence=%.1f%% tickers=%d flags=%d",
            rec.regime,
            rec.confidence * 100,
            len(rec.target_weights),
            len(rec.risk_flags),
        )
        return rec

    # ──────────────────────────────────────────────────────────────────────
    # Analyst adjustment (placeholder)
    # ──────────────────────────────────────────────────────────────────────

    def _apply_analyst_adjustment(
        self,
        base_weights: dict[str, float],
        regime: str,
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Apply analyst-sentiment tilts to base weights.

        .. note::
            This is a **placeholder** implementation.  It returns the
            base weights unchanged.  Will be connected to
            ``analyst_monitor.py`` in a future iteration to apply
            ±10 % sentiment tilts.

        Parameters
        ----------
        base_weights : dict[str, float]
            Starting regime weights (ticker → weight).
        regime : str
            Current regime label.

        Returns
        -------
        tuple[dict[str, float], dict[str, float]]
            ``(adjusted_weights, adjustments_dict)``.
            Currently ``adjustments_dict`` is always empty.
        """
        logger.info(
            "Analyst adjustment is a placeholder — returning base weights "
            "unchanged for regime '%s'.  Will be connected to "
            "analyst_monitor.py in a future release.",
            regime,
        )
        return dict(base_weights), {}

    # ──────────────────────────────────────────────────────────────────────
    # Leveraged-ETF eligibility
    # ──────────────────────────────────────────────────────────────────────

    def _check_leveraged_eligibility(
        self,
        weights: dict[str, float],
        regime: str,
        confidence: float,
        current_vix: float,
    ) -> dict[str, float]:
        """Gate leveraged ETFs against eligibility rules and risk limits.

        For each leveraged ETF present in *weights*:

        1. Check that the current regime is in the ETF's allowed regimes.
        2. Check that model confidence exceeds the minimum threshold.
        3. Check that VIX is below the maximum level.
        4. If any check fails, remove the ETF and redistribute its
           weight proportionally to ``SPY`` and ``AGG``.

        After individual checks, enforce the aggregate leveraged cap
        from :data:`config.regime_rules.RISK_LIMITS.max_leveraged_total`.

        Parameters
        ----------
        weights : dict[str, float]
            Proposed portfolio weights.
        regime : str
            Current regime label.
        confidence : float
            Model confidence (0–1).
        current_vix : float
            Latest VIX level.

        Returns
        -------
        dict[str, float]
            Adjusted weights with ineligible leveraged ETFs removed
            and aggregate cap enforced.
        """
        adjusted = dict(weights)
        redistributed: float = 0.0

        # --- Per-ETF eligibility ---
        for ticker in list(adjusted.keys()):
            if ticker not in _LEVERAGED_TICKERS:
                continue

            etf_info = get_etf(ticker)
            regime_allowed = etf_info.regime_allowed if etf_info else []

            # Check regime allowance
            if regime not in regime_allowed:
                logger.info(
                    "Leveraged ETF %s removed: regime '%s' not in allowed %s.",
                    ticker, regime, regime_allowed,
                )
                redistributed += adjusted.pop(ticker)
                continue

            # Check VIX / confidence via config helper
            if not check_leveraged_eligibility(ticker, current_vix, confidence):
                logger.info(
                    "Leveraged ETF %s removed: VIX=%.1f, confidence=%.2f.",
                    ticker, current_vix, confidence,
                )
                redistributed += adjusted.pop(ticker)
                continue

        # --- Aggregate leveraged cap ---
        max_lev = RISK_LIMITS.max_leveraged_total
        total_lev = sum(
            w for t, w in adjusted.items() if t in _LEVERAGED_TICKERS
        )
        if total_lev > max_lev:
            excess = total_lev - max_lev
            logger.info(
                "Total leveraged allocation %.1f%% exceeds cap %.1f%%. "
                "Trimming %.1f%% excess.",
                total_lev * 100, max_lev * 100, excess * 100,
            )
            # Scale down each leveraged ETF proportionally
            for ticker in list(adjusted.keys()):
                if ticker in _LEVERAGED_TICKERS:
                    share = adjusted[ticker] / total_lev
                    trim = excess * share
                    adjusted[ticker] -= trim
                    redistributed += trim

        # --- Redistribute removed weight to SPY and AGG ---
        if redistributed > 0:
            spy_share = 0.6
            agg_share = 0.4
            adjusted["SPY"] = adjusted.get("SPY", 0.0) + redistributed * spy_share
            adjusted["AGG"] = adjusted.get("AGG", 0.0) + redistributed * agg_share
            logger.info(
                "Redistributed %.2f%% from ineligible leveraged ETFs → "
                "SPY (+%.2f%%) / AGG (+%.2f%%).",
                redistributed * 100,
                redistributed * spy_share * 100,
                redistributed * agg_share * 100,
            )

        return adjusted

    # ──────────────────────────────────────────────────────────────────────
    # Rationale generation
    # ──────────────────────────────────────────────────────────────────────

    def _generate_rationale(
        self,
        regime: str,
        confidence: float,
        weights: dict[str, float],
        risk_flags: list[str],
        snapshot: dict[str, Any],
    ) -> list[str]:
        """Generate human-readable explanation strings.

        Parameters
        ----------
        regime : str
            Current regime label.
        confidence : float
            Model confidence (0–1).
        weights : dict[str, float]
            Final portfolio weights.
        risk_flags : list[str]
            Detected risk warnings.
        snapshot : dict[str, Any]
            Current macro indicator values.

        Returns
        -------
        list[str]
            List of explanation strings.
        """
        lines: list[str] = []

        # Regime identification
        lines.append(
            f"Current regime: {regime.title()} "
            f"(confidence: {confidence:.0%})"
        )

        # Growth indicators
        gdp = snapshot.get("gdp_growth")
        unemp_mom = snapshot.get("unemployment_momentum")
        if gdp is not None:
            direction = "positive" if gdp > 0 else "negative"
            lines.append(
                f"Growth indicators {direction}: GDP {gdp:+.1%}"
                + (
                    f", unemployment {'declining' if unemp_mom and unemp_mom < 0 else 'rising'}"
                    if unemp_mom is not None
                    else ""
                )
            )

        # Inflation
        cpi_yoy = snapshot.get("cpi_yoy")
        if cpi_yoy is not None:
            lines.append(f"Inflation: CPI YoY {cpi_yoy:.1%}")

        # Leveraged ETF status
        lev_in_portfolio = [t for t in weights if t in _LEVERAGED_TICKERS]
        vix_level = snapshot.get("vix_level")
        if lev_in_portfolio:
            vix_str = f"VIX at {vix_level:.1f}" if vix_level is not None else "VIX N/A"
            lines.append(
                f"Leveraged ETFs enabled ({', '.join(lev_in_portfolio)}): "
                f"{vix_str}, confidence above threshold"
            )
        else:
            lines.append("Leveraged ETFs excluded from current allocation.")

        # Top holdings
        sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        top5 = sorted_weights[:5]
        top_str = ", ".join(f"{t} {w:.0%}" for t, w in top5)
        lines.append(f"Top holdings: {top_str}")

        # Risk flags
        for flag in risk_flags:
            lines.append(f"Risk flag: {flag}")

        return lines

    # ──────────────────────────────────────────────────────────────────────
    # Risk-flag detection
    # ──────────────────────────────────────────────────────────────────────

    def _detect_risk_flags(
        self,
        snapshot: dict[str, Any],
    ) -> list[str]:
        """Detect risk conditions from the current macro snapshot.

        Checks
        ------
        * VIX > 25 → elevated volatility warning.
        * VIX > 35 → critical VIX spike — defensive posture recommended.
        * yield_curve < 0 → yield curve inverted — recession risk elevated.
        * hy_spread > 5 → credit stress detected.
        * unemployment_momentum > 0 for 3+ months → labour market
          deteriorating.

        Parameters
        ----------
        snapshot : dict[str, Any]
            Current macro indicator values from
            :meth:`FeatureEngineer.get_current_snapshot`.

        Returns
        -------
        list[str]
            Human-readable risk-flag strings (may be empty).
        """
        flags: list[str] = []

        # --- VIX ---
        vix = snapshot.get("vix_level")
        if vix is not None:
            if vix > RISK_LIMITS.vix_spike_threshold:
                flags.append(
                    f"CRITICAL: VIX spike at {vix:.1f} — "
                    "defensive posture recommended"
                )
            elif vix > 25:
                flags.append(f"Elevated volatility: VIX at {vix:.1f}")

        # --- Yield curve ---
        yc = snapshot.get("yield_curve")
        if yc is not None and yc < 0:
            flags.append(
                f"Yield curve inverted ({yc:+.2f}%) — recession risk elevated"
            )

        # --- High-yield spread ---
        hy = snapshot.get("hy_spread")
        if hy is not None and hy > 5:
            flags.append(f"Credit stress detected: HY spread at {hy:.2f}%")

        # --- Labour market ---
        unemp_mom = snapshot.get("unemployment_momentum")
        if unemp_mom is not None and unemp_mom > 0:
            flags.append(
                f"Labour market deteriorating: unemployment momentum +{unemp_mom:.2f}"
            )

        # --- Yield curve flattening (approaching inversion) ---
        if yc is not None and 0 < yc < 0.3:
            flags.append(
                f"Yield curve flattening ({yc:+.2f}%), monitor for inversion"
            )

        if flags:
            logger.warning("Risk flags detected: %s", flags)
        else:
            logger.info("No risk flags detected.")

        return flags

    # ──────────────────────────────────────────────────────────────────────
    # History & comparison
    # ──────────────────────────────────────────────────────────────────────

    def get_regime_history(self, months: int = 60) -> pd.DataFrame:
        """Return historical regime classifications for the past *months*.

        Uses walk-forward prediction to avoid look-ahead bias.

        Parameters
        ----------
        months : int, default 60
            Number of months of history to return.

        Returns
        -------
        pd.DataFrame
            Columns: ``regime``, ``confidence``, ``raw_state``.
        """
        logger.info("Computing regime history for the past %d months …", months)

        features = self.feature_engineer.compute_regime_features()
        if features.empty:
            logger.error("No features available for regime history.")
            return pd.DataFrame(columns=["regime", "confidence", "raw_state"])

        # Use walk-forward for unbiased history
        history = self.regime_detector.walk_forward_predict(
            features,
            initial_train_months=min(60, max(36, len(features) - months)),
            step_months=1,
        )

        # Trim to requested window
        if len(history) > months:
            history = history.iloc[-months:]

        return history

    def get_strategy_comparison(self) -> pd.DataFrame:
        """Compare current weights against all four regime base allocations.

        Returns
        -------
        pd.DataFrame
            Index is ticker symbols.  Columns are
            ``['current', 'goldilocks', 'reflation', 'stagflation', 'deflation']``.
            Missing tickers in any regime are filled with 0.0.
        """
        logger.info("Building strategy comparison table …")

        # Gather current recommendation weights
        try:
            rec = self.generate_recommendation()
            current_weights = rec.target_weights
        except Exception:
            logger.warning(
                "Could not generate current recommendation for comparison.",
                exc_info=True,
            )
            current_weights = {}

        # Collect all tickers across all regimes + current
        all_tickers: set[str] = set(current_weights.keys())
        for regime_name in REGIME_WEIGHTS:
            all_tickers.update(REGIME_WEIGHTS[regime_name].keys())

        sorted_tickers = sorted(all_tickers)

        data: dict[str, list[float]] = {
            "current": [current_weights.get(t, 0.0) for t in sorted_tickers],
        }
        for regime_name in ["goldilocks", "reflation", "stagflation", "deflation"]:
            rw = REGIME_WEIGHTS.get(regime_name, {})
            data[regime_name] = [rw.get(t, 0.0) for t in sorted_tickers]

        comparison = pd.DataFrame(data, index=sorted_tickers)
        comparison.index.name = "ticker"

        logger.info("Strategy comparison: %d tickers.", len(comparison))
        return comparison

    # ──────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_weights(weights: dict[str, float]) -> dict[str, float]:
        """Normalise weights so they sum to exactly 1.0.

        Removes any tickers with zero or negative weight before normalising.

        Parameters
        ----------
        weights : dict[str, float]
            Raw weight dict.

        Returns
        -------
        dict[str, float]
            Normalised weights summing to 1.0.
        """
        # Remove non-positive weights
        positive = {t: w for t, w in weights.items() if w > 0}
        total = sum(positive.values())

        if total == 0:
            logger.warning("All weights are zero — returning equal-weight SPY/AGG.")
            return {"SPY": 0.5, "AGG": 0.5}

        normalised = {t: round(w / total, 6) for t, w in positive.items()}

        # Correct for floating-point drift — adjust the largest position
        drift = 1.0 - sum(normalised.values())
        if abs(drift) > 1e-9:
            largest = max(normalised, key=normalised.get)  # type: ignore[arg-type]
            normalised[largest] = round(normalised[largest] + drift, 6)

        return normalised

    @staticmethod
    def _extract_vix(snapshot: dict[str, Any]) -> float:
        """Extract the current VIX level from a macro snapshot.

        Falls back to 20.0 (long-run average) if unavailable.

        Parameters
        ----------
        snapshot : dict[str, Any]
            Macro snapshot from :meth:`FeatureEngineer.get_current_snapshot`.

        Returns
        -------
        float
            Current VIX level.
        """
        vix = snapshot.get("vix_level")
        if vix is None or (isinstance(vix, float) and np.isnan(vix)):
            logger.warning(
                "VIX level unavailable in snapshot — defaulting to 20.0."
            )
            return 20.0
        return float(vix)

    def _empty_recommendation(self, reason: str) -> StrategyRecommendation:
        """Return a safe default recommendation when generation fails.

        Parameters
        ----------
        reason : str
            Human-readable explanation for the fallback.

        Returns
        -------
        StrategyRecommendation
            Defensive 50/50 SPY/AGG allocation.
        """
        logger.warning("Returning empty/default recommendation: %s", reason)
        return StrategyRecommendation(
            regime="deflation",
            confidence=0.0,
            target_weights={"SPY": 0.50, "AGG": 0.50},
            rationale=[f"Fallback recommendation: {reason}"],
            risk_flags=["Recommendation generation failed — using defensive default"],
        )
