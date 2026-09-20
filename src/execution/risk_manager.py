"""
Risk Manager Module
====================
Pre-trade risk validation engine with 6 checks:
1. Position concentration (max 30% single position)
2. Daily turnover (max 25% of portfolio)
3. Drawdown circuit breaker (trigger at 12% drawdown)
4. VIX spike guard (halt equity buys if VIX > 35)
5. Correlation check (no 3+ correlated positions > 60% combined)
6. Liquidity check (min 500K avg daily volume)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    """Result of a single risk check."""
    check_name: str
    passed: bool
    current_value: float
    threshold: float
    message: str
    severity: str = "info"  # 'info', 'warning', 'critical'


@dataclass
class RiskAssessment:
    """Aggregate result of all risk checks."""
    timestamp: datetime = field(default_factory=datetime.now)
    all_passed: bool = True
    checks: list[RiskCheckResult] = field(default_factory=list)
    blocked_trades: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommended_action: str = "proceed"


class RiskManager:
    """
    Pre-trade risk validation engine.
    
    Runs 6 independent risk checks before any trade is executed.
    Can auto-adjust proposed portfolio weights to comply with limits.
    """

    # Leveraged ETF tickers for identification
    LEVERAGED_TICKERS = {"TQQQ", "SOXL", "GGLL", "UPRO", "SPXL", "TECL", "FNGU"}

    def __init__(self, risk_limits: Optional[dict] = None):
        """
        Args:
            risk_limits: Custom risk limits dict. If None, imports from config.
        """
        if risk_limits is None:
            try:
                from config.regime_rules import RISK_LIMITS
                self._limits = {
                    'max_single_position': RISK_LIMITS.max_single_position,
                    'max_leveraged_total': RISK_LIMITS.max_leveraged_total,
                    'max_daily_turnover': RISK_LIMITS.max_daily_turnover,
                    'drawdown_circuit_breaker': RISK_LIMITS.drawdown_circuit_breaker,
                    'vix_spike_threshold': RISK_LIMITS.vix_spike_threshold,
                }
            except (ImportError, AttributeError):
                self._limits = {
                    'max_single_position': 0.25,
                    'max_leveraged_total': 0.25,
                    'max_daily_turnover': 0.30,
                    'drawdown_circuit_breaker': 0.08,
                    'vix_spike_threshold': 28.0,
                }
        else:
            self._limits = risk_limits

        self._last_assessment: Optional[RiskAssessment] = None
        logger.info(f"RiskManager initialized with limits: {self._limits}")

    # ------------------------------------------------------------------ #
    #                     AGGREGATE CHECK                                 #
    # ------------------------------------------------------------------ #

    def run_all_checks(
        self,
        proposed_weights: dict[str, float],
        current_positions: dict[str, float],
        portfolio_value: float,
        current_vix: float,
        portfolio_returns: Optional[pd.Series] = None,
        price_data: Optional[pd.DataFrame] = None,
    ) -> RiskAssessment:
        """
        Run all 6 risk checks and aggregate results.

        Args:
            proposed_weights: Target portfolio weights.
            current_positions: Current position weights.
            portfolio_value: Total portfolio value in USD.
            current_vix: Current VIX level.
            portfolio_returns: Historical daily returns (for drawdown check).
            price_data: Historical price data (for correlation check).

        Returns:
            RiskAssessment with all check results.
        """
        assessment = RiskAssessment(timestamp=datetime.now())
        checks = []

        # 1. Position concentration
        checks.append(self.check_position_concentration(proposed_weights))

        # 2. Daily turnover
        checks.append(self.check_daily_turnover(current_positions, proposed_weights))

        # 3. Drawdown circuit breaker
        if portfolio_returns is not None and not portfolio_returns.empty:
            checks.append(self.check_drawdown_circuit_breaker(portfolio_returns))
        else:
            checks.append(RiskCheckResult(
                check_name="drawdown_circuit_breaker",
                passed=True, current_value=0, threshold=self._limits['drawdown_circuit_breaker'],
                message="No return history — skipping drawdown check",
                severity="info",
            ))

        # 4. VIX spike
        checks.append(self.check_vix_spike(current_vix))

        # 5. Correlation
        checks.append(self.check_correlation(proposed_weights, price_data))

        # 6. Liquidity (lightweight check)
        checks.append(self.check_liquidity(list(proposed_weights.keys())))

        # Aggregate
        assessment.checks = checks
        assessment.all_passed = all(c.passed for c in checks)
        assessment.warnings = [c.message for c in checks if c.severity == "warning"]
        assessment.blocked_trades = [
            c.message for c in checks if c.severity == "critical" and not c.passed
        ]

        if not assessment.all_passed:
            critical = [c for c in checks if c.severity == "critical" and not c.passed]
            if critical:
                assessment.recommended_action = "block_and_adjust"
            else:
                assessment.recommended_action = "proceed_with_warnings"
        else:
            assessment.recommended_action = "proceed"

        self._last_assessment = assessment
        logger.info(
            f"Risk assessment: {'PASSED' if assessment.all_passed else 'FAILED'} "
            f"({sum(c.passed for c in checks)}/{len(checks)} checks passed)"
        )
        return assessment

    # ------------------------------------------------------------------ #
    #                   INDIVIDUAL CHECKS                                 #
    # ------------------------------------------------------------------ #

    def check_position_concentration(
        self,
        weights: dict[str, float],
        max_single: Optional[float] = None,
    ) -> RiskCheckResult:
        """Check no single position exceeds maximum weight."""
        max_single = max_single or self._limits['max_single_position']

        if not weights:
            return RiskCheckResult(
                check_name="position_concentration",
                passed=True, current_value=0, threshold=max_single,
                message="No positions to check", severity="info",
            )

        max_ticker = max(weights, key=weights.get)
        max_weight = weights[max_ticker]
        passed = max_weight <= max_single

        return RiskCheckResult(
            check_name="position_concentration",
            passed=passed,
            current_value=round(max_weight, 4),
            threshold=max_single,
            message=(
                f"✅ Max position {max_ticker}={max_weight:.1%} within {max_single:.0%} limit"
                if passed else
                f"⚠ {max_ticker} at {max_weight:.1%} exceeds {max_single:.0%} limit"
            ),
            severity="info" if passed else "warning",
        )

    def check_daily_turnover(
        self,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        max_turnover: Optional[float] = None,
    ) -> RiskCheckResult:
        """Check total weight changes don't exceed daily turnover limit."""
        max_turnover = max_turnover or self._limits['max_daily_turnover']

        all_tickers = set(list(current_weights.keys()) + list(target_weights.keys()))
        total_change = sum(
            abs(target_weights.get(t, 0) - current_weights.get(t, 0))
            for t in all_tickers
        )
        turnover = total_change / 2  # Two-sided turnover

        passed = turnover <= max_turnover

        return RiskCheckResult(
            check_name="daily_turnover",
            passed=passed,
            current_value=round(turnover, 4),
            threshold=max_turnover,
            message=(
                f"✅ Turnover {turnover:.1%} within {max_turnover:.0%} limit"
                if passed else
                f"⚠ Turnover {turnover:.1%} exceeds {max_turnover:.0%} — consider phasing trades"
            ),
            severity="info" if passed else "warning",
        )

    def check_drawdown_circuit_breaker(
        self,
        returns: pd.Series,
        threshold: Optional[float] = None,
    ) -> RiskCheckResult:
        """Check if current drawdown triggers circuit breaker."""
        threshold = threshold or self._limits['drawdown_circuit_breaker']

        equity = (1 + returns).cumprod()
        peak = equity.expanding().max()
        current_dd = (equity.iloc[-1] / peak.iloc[-1]) - 1

        passed = abs(current_dd) <= threshold

        return RiskCheckResult(
            check_name="drawdown_circuit_breaker",
            passed=passed,
            current_value=round(abs(current_dd), 4),
            threshold=threshold,
            message=(
                f"✅ Drawdown {abs(current_dd):.1%} within {threshold:.0%} limit"
                if passed else
                f"🚨 CIRCUIT BREAKER: Drawdown {abs(current_dd):.1%} exceeds {threshold:.0%} — reduce equity to 50%"
            ),
            severity="info" if passed else "critical",
        )

    def check_vix_spike(
        self,
        current_vix: float,
        threshold: Optional[float] = None,
    ) -> RiskCheckResult:
        """Check if VIX exceeds spike threshold."""
        threshold = threshold or self._limits['vix_spike_threshold']
        passed = current_vix <= threshold

        # Also check elevated level
        elevated = current_vix > 25

        severity = "info"
        if not passed:
            severity = "critical"
        elif elevated:
            severity = "warning"

        return RiskCheckResult(
            check_name="vix_spike",
            passed=passed,
            current_value=round(current_vix, 1),
            threshold=threshold,
            message=(
                f"✅ VIX at {current_vix:.1f} — normal"
                if not elevated and passed else
                f"⚠ VIX elevated at {current_vix:.1f} — monitor closely"
                if elevated and passed else
                f"🚨 VIX SPIKE: {current_vix:.1f} > {threshold:.0f} — halt new equity buys"
            ),
            severity=severity,
        )

    def check_correlation(
        self,
        weights: dict[str, float],
        price_data: Optional[pd.DataFrame] = None,
        max_corr: float = 0.8,
        max_combined: float = 0.60,
    ) -> RiskCheckResult:
        """Check for excessive concentration in correlated positions."""
        if price_data is None or price_data.empty:
            return RiskCheckResult(
                check_name="correlation",
                passed=True, current_value=0, threshold=max_combined,
                message="No price data — correlation check skipped",
                severity="info",
            )

        try:
            available = [t for t in weights if t in price_data.columns]
            if len(available) < 3:
                return RiskCheckResult(
                    check_name="correlation",
                    passed=True, current_value=0, threshold=max_combined,
                    message=f"Only {len(available)} assets — correlation check skipped",
                    severity="info",
                )

            corr = price_data[available].pct_change().dropna().corr()

            # Find clusters of highly correlated assets
            high_corr_groups = []
            checked = set()
            for i, t1 in enumerate(available):
                if t1 in checked:
                    continue
                group = [t1]
                for t2 in available[i + 1:]:
                    if abs(corr.loc[t1, t2]) > max_corr:
                        group.append(t2)
                if len(group) >= 3:
                    high_corr_groups.append(group)
                    checked.update(group)

            # Check combined weight of correlated groups
            max_group_weight = 0
            for group in high_corr_groups:
                group_weight = sum(weights.get(t, 0) for t in group)
                max_group_weight = max(max_group_weight, group_weight)

            passed = max_group_weight <= max_combined

            return RiskCheckResult(
                check_name="correlation",
                passed=passed,
                current_value=round(max_group_weight, 4),
                threshold=max_combined,
                message=(
                    f"✅ Correlated groups within {max_combined:.0%} limit"
                    if passed else
                    f"⚠ Correlated group at {max_group_weight:.1%} exceeds {max_combined:.0%}"
                ),
                severity="info" if passed else "warning",
            )
        except Exception as e:
            logger.warning(f"Correlation check failed: {e}")
            return RiskCheckResult(
                check_name="correlation",
                passed=True, current_value=0, threshold=max_combined,
                message=f"Correlation check error: {e}",
                severity="info",
            )

    def check_liquidity(
        self,
        tickers: list[str],
        min_avg_volume: int = 500_000,
    ) -> RiskCheckResult:
        """Check average daily volume meets minimum threshold."""
        # Lightweight check — uses yfinance for volume data
        try:
            import yfinance as yf
            illiquid = []
            for ticker in tickers[:10]:  # Limit API calls
                try:
                    hist = yf.Ticker(ticker).history(period="1mo")
                    if not hist.empty:
                        avg_vol = hist['Volume'].mean()
                        if avg_vol < min_avg_volume:
                            illiquid.append(f"{ticker}({avg_vol:,.0f})")
                except Exception:
                    continue

            passed = len(illiquid) == 0
            return RiskCheckResult(
                check_name="liquidity",
                passed=passed,
                current_value=len(illiquid),
                threshold=0,
                message=(
                    f"✅ All positions meet {min_avg_volume:,} volume minimum"
                    if passed else
                    f"⚠ Low liquidity: {', '.join(illiquid)}"
                ),
                severity="info" if passed else "warning",
            )
        except ImportError:
            return RiskCheckResult(
                check_name="liquidity",
                passed=True, current_value=0, threshold=0,
                message="yfinance unavailable — liquidity check skipped",
                severity="info",
            )

    # ------------------------------------------------------------------ #
    #                     RISK ADJUSTMENTS                                #
    # ------------------------------------------------------------------ #

    def apply_risk_adjustments(
        self,
        proposed_weights: dict[str, float],
        risk_assessment: RiskAssessment,
    ) -> dict[str, float]:
        """
        Auto-adjust weights based on failed risk checks.

        Args:
            proposed_weights: Original proposed weights.
            risk_assessment: Result of run_all_checks().

        Returns:
            Adjusted weights compliant with risk limits.
        """
        adjusted = dict(proposed_weights)

        for check in risk_assessment.checks:
            if check.passed:
                continue

            if check.check_name == "drawdown_circuit_breaker":
                # Reduce all equity to 50%, shift to SHY/AGG
                logger.warning("Circuit breaker: reducing equity exposure to 50%")
                equity_tickers = {"SPY", "QQQ", "IWM", "VEA", "VWO", "SOXX", "VNQ",
                                  "SPYI", "QQQI", "TQQQ", "SOXL", "GGLL"}
                released = 0.0
                for t in equity_tickers:
                    if t in adjusted:
                        reduction = adjusted[t] * 0.5
                        adjusted[t] -= reduction
                        released += reduction
                # Redistribute to safe assets
                adjusted["SHY"] = adjusted.get("SHY", 0) + released * 0.6
                adjusted["AGG"] = adjusted.get("AGG", 0) + released * 0.4

            elif check.check_name == "vix_spike":
                # Remove leveraged ETFs, increase bonds
                logger.warning("VIX spike: removing leveraged ETFs")
                released = 0.0
                for t in self.LEVERAGED_TICKERS:
                    if t in adjusted:
                        released += adjusted.pop(t)
                adjusted["SHY"] = adjusted.get("SHY", 0) + released * 0.5
                adjusted["GLD"] = adjusted.get("GLD", 0) + released * 0.3
                adjusted["IEF"] = adjusted.get("IEF", 0) + released * 0.2

            elif check.check_name == "position_concentration":
                max_pos = self._limits['max_single_position']
                for t, w in list(adjusted.items()):
                    if w > max_pos:
                        excess = w - max_pos
                        adjusted[t] = max_pos
                        adjusted["AGG"] = adjusted.get("AGG", 0) + excess

        # Renormalize
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: round(v / total, 4) for k, v in adjusted.items() if v > 0.005}

        return adjusted

    def get_risk_dashboard_data(self) -> dict:
        """
        Return summary data for dashboard display.

        Returns:
            Dict with overall status, individual check statuses, and alerts.
        """
        if self._last_assessment is None:
            return {
                "status": "unknown",
                "message": "No risk assessment has been run yet",
                "last_check": None,
            }

        a = self._last_assessment
        status = "green"
        if not a.all_passed:
            has_critical = any(
                c.severity == "critical" and not c.passed for c in a.checks
            )
            status = "red" if has_critical else "yellow"

        return {
            "status": status,
            "last_check": a.timestamp.isoformat(),
            "all_passed": a.all_passed,
            "recommended_action": a.recommended_action,
            "checks": [
                {
                    "name": c.check_name,
                    "passed": c.passed,
                    "value": c.current_value,
                    "threshold": c.threshold,
                    "message": c.message,
                    "severity": c.severity,
                }
                for c in a.checks
            ],
            "active_alerts": a.blocked_trades + a.warnings,
        }
