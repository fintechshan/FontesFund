"""
Portfolio Optimizer Module
==========================
Optimizes ETF portfolio weights using PyPortfolioOpt with hard constraints:
- Sharpe ratio ≥ 1.0
- Maximum drawdown ≤ 15%
- No single position > 30%
- Total leveraged ETF allocation ≤ 15%

Supports max_sharpe, min_volatility, risk_parity (HRP), and target_return methods.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class OptimizedPortfolio:
    """Result of portfolio optimization."""
    weights: dict[str, float]
    expected_annual_return: float
    expected_volatility: float
    expected_sharpe: float
    method: str
    constraints_met: bool
    optimization_log: list[str] = field(default_factory=list)


@dataclass
class ConstraintValidation:
    """Result of constraint validation checks."""
    sharpe_ok: bool = True
    sharpe_value: float = 0.0
    max_dd_ok: bool = True
    max_dd_value: float = 0.0
    concentration_ok: bool = True
    max_position: float = 0.0
    max_position_ticker: str = ""
    leveraged_ok: bool = True
    leveraged_total: float = 0.0
    all_passed: bool = True
    details: list[str] = field(default_factory=list)


class PortfolioOptimizer:
    """
    Portfolio optimizer using PyPortfolioOpt.
    
    Constructs efficient portfolios from regime-based target weights,
    applying hard risk constraints and iterative re-optimization.
    """

    def __init__(self, risk_free_rate: float = 0.04):
        """
        Args:
            risk_free_rate: Annual risk-free rate for Sharpe ratio calculation.
        """
        self.risk_free_rate = risk_free_rate

    def optimize(
        self,
        target_weights: dict[str, float],
        price_data: pd.DataFrame,
        method: str = "max_sharpe",
    ) -> OptimizedPortfolio:
        """
        Optimize portfolio weights.

        Args:
            target_weights: Regime-based target weights (ticker -> weight).
            price_data: Historical price DataFrame (columns = tickers, index = dates).
            method: Optimization method — 'max_sharpe', 'min_volatility',
                     'risk_parity', or 'target_return'.

        Returns:
            OptimizedPortfolio with cleaned weights and performance metrics.
        """
        log = []
        tickers = [t for t in target_weights if t in price_data.columns]
        if not tickers:
            logger.error("No matching tickers between target_weights and price_data")
            return OptimizedPortfolio(
                weights=target_weights, expected_annual_return=0,
                expected_volatility=0, expected_sharpe=0,
                method=method, constraints_met=False,
                optimization_log=["ERROR: No matching tickers"],
            )

        prices = price_data[tickers].dropna()
        if len(prices) < 252:
            log.append(f"WARNING: Only {len(prices)} days of price data (< 1 year)")

        try:
            from pypfopt import expected_returns, risk_models, EfficientFrontier
            from pypfopt import HRPOpt

            # Compute expected returns and covariance
            mu = expected_returns.capm_return(prices, risk_free_rate=self.risk_free_rate)
            S = risk_models.CovarianceShrinkage(prices).ledoit_wolf()
            log.append(f"Computed CAPM returns and Ledoit-Wolf covariance for {len(tickers)} assets")

            if method == "risk_parity":
                opt = HRPOpt(returns=prices.pct_change().dropna())
                raw_weights = opt.optimize()
                perf = opt.portfolio_performance(
                    verbose=False, risk_free_rate=self.risk_free_rate
                )
                log.append("Optimized using Hierarchical Risk Parity (HRP)")
            else:
                ef = EfficientFrontier(
                    mu, S,
                    weight_bounds=(0.02, 0.30),
                )

                if method == "max_sharpe":
                    raw_weights = ef.max_sharpe(risk_free_rate=self.risk_free_rate)
                    log.append("Optimized for maximum Sharpe ratio")
                elif method == "min_volatility":
                    raw_weights = ef.min_volatility()
                    log.append("Optimized for minimum volatility")
                elif method == "target_return":
                    target_ret = 0.10  # 10% target
                    try:
                        raw_weights = ef.efficient_return(target_ret)
                        log.append(f"Optimized for target return of {target_ret:.1%}")
                    except Exception:
                        raw_weights = ef.max_sharpe(risk_free_rate=self.risk_free_rate)
                        log.append("Target return infeasible, fell back to max_sharpe")
                else:
                    raw_weights = ef.max_sharpe(risk_free_rate=self.risk_free_rate)
                    log.append(f"Unknown method '{method}', defaulting to max_sharpe")

                perf = ef.portfolio_performance(
                    verbose=False, risk_free_rate=self.risk_free_rate
                )

            # Clean weights (remove < 1%)
            cleaned = {
                k: round(v, 4) for k, v in raw_weights.items() if v > 0.01
            }
            # Re-normalize
            total = sum(cleaned.values())
            if total > 0:
                cleaned = {k: round(v / total, 4) for k, v in cleaned.items()}

            exp_ret, exp_vol, exp_sharpe = perf
            log.append(f"Expected return: {exp_ret:.2%}, volatility: {exp_vol:.2%}, Sharpe: {exp_sharpe:.2f}")

            return OptimizedPortfolio(
                weights=cleaned,
                expected_annual_return=round(exp_ret, 4),
                expected_volatility=round(exp_vol, 4),
                expected_sharpe=round(exp_sharpe, 2),
                method=method,
                constraints_met=True,  # Validated separately
                optimization_log=log,
            )

        except ImportError:
            logger.error("PyPortfolioOpt not installed. pip install pyportfolioopt")
            log.append("FALLBACK: PyPortfolioOpt unavailable, using target weights directly")
            return OptimizedPortfolio(
                weights=target_weights,
                expected_annual_return=0, expected_volatility=0,
                expected_sharpe=0, method="fallback",
                constraints_met=False, optimization_log=log,
            )
        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            log.append(f"ERROR: {e} — falling back to target weights")
            return OptimizedPortfolio(
                weights=target_weights,
                expected_annual_return=0, expected_volatility=0,
                expected_sharpe=0, method="fallback",
                constraints_met=False, optimization_log=log,
            )

    def validate_constraints(
        self,
        weights: dict[str, float],
        price_data: pd.DataFrame,
        min_sharpe: float = 1.0,
        max_drawdown: float = 0.15,
        max_single_position: float = 0.30,
        max_leveraged: float = 0.15,
    ) -> ConstraintValidation:
        """
        Validate portfolio against hard constraints using historical simulation.

        Args:
            weights: Portfolio weights (ticker -> weight).
            price_data: Historical price data.
            min_sharpe: Minimum acceptable Sharpe ratio.
            max_drawdown: Maximum acceptable drawdown (as positive decimal).
            max_single_position: Maximum single-position weight.
            max_leveraged: Maximum total leveraged ETF weight.

        Returns:
            ConstraintValidation with pass/fail for each constraint.
        """
        from src.portfolio.constraints import ConstraintValidator

        # Compute portfolio returns
        tickers = [t for t in weights if t in price_data.columns]
        if not tickers:
            return ConstraintValidation(
                all_passed=False,
                details=["No matching tickers in price data"],
            )

        daily_returns = price_data[tickers].pct_change().dropna()
        w = pd.Series({t: weights[t] for t in tickers})
        w = w / w.sum()  # Renormalize
        portfolio_returns = daily_returns.dot(w)

        validator = ConstraintValidator()
        return validator.validate_all(
            weights=weights,
            returns=portfolio_returns,
            min_sharpe=min_sharpe,
            max_drawdown=max_drawdown,
            max_single_position=max_single_position,
            max_leveraged=max_leveraged,
        )

    def optimize_with_constraints(
        self,
        target_weights: dict[str, float],
        price_data: pd.DataFrame,
    ) -> OptimizedPortfolio:
        """
        Iteratively optimize until constraints are met.

        Tries max_sharpe → adjustments → risk_parity fallback.

        Args:
            target_weights: Regime-based starting weights.
            price_data: Historical price data.

        Returns:
            Best portfolio meeting constraints, or closest if none fully meet.
        """
        methods = ["max_sharpe", "min_volatility", "risk_parity"]
        best_result = None
        best_validation = None

        for method in methods:
            result = self.optimize(target_weights, price_data, method=method)
            validation = self.validate_constraints(result.weights, price_data)
            result.constraints_met = validation.all_passed

            if validation.all_passed:
                result.optimization_log.append(f"✅ All constraints met with method: {method}")
                return result

            # Track best attempt
            if best_result is None or validation.sharpe_value > (best_validation.sharpe_value if best_validation else 0):
                best_result = result
                best_validation = validation

            result.optimization_log.append(
                f"⚠ Constraints not fully met with {method}: "
                f"Sharpe={validation.sharpe_value:.2f} (need≥1.0), "
                f"MaxDD={validation.max_dd_value:.2%} (need≤15%)"
            )

        # If none fully pass, adjust the best attempt
        if best_result:
            best_result.optimization_log.append(
                "NOTICE: No method fully met all constraints. Returning best attempt."
            )
            best_result.constraints_met = False

        return best_result or OptimizedPortfolio(
            weights=target_weights,
            expected_annual_return=0, expected_volatility=0,
            expected_sharpe=0, method="fallback",
            constraints_met=False,
            optimization_log=["All optimization methods failed"],
        )

    def compute_efficient_frontier(
        self,
        price_data: pd.DataFrame,
        tickers: list[str],
        n_points: int = 50,
    ) -> pd.DataFrame:
        """
        Compute efficient frontier points for visualization.

        Args:
            price_data: Historical price data.
            tickers: List of tickers to include.
            n_points: Number of frontier points.

        Returns:
            DataFrame with columns: return, volatility, sharpe.
        """
        try:
            from pypfopt import expected_returns, risk_models, EfficientFrontier

            available = [t for t in tickers if t in price_data.columns]
            prices = price_data[available].dropna()
            mu = expected_returns.capm_return(prices, risk_free_rate=self.risk_free_rate)
            S = risk_models.CovarianceShrinkage(prices).ledoit_wolf()

            # Generate frontier points
            results = []
            min_ret = mu.min()
            max_ret = mu.max()
            target_returns = np.linspace(min_ret * 1.1, max_ret * 0.9, n_points)

            for target in target_returns:
                try:
                    ef = EfficientFrontier(mu, S, weight_bounds=(0, 0.4))
                    ef.efficient_return(target)
                    ret, vol, sharpe = ef.portfolio_performance(
                        risk_free_rate=self.risk_free_rate
                    )
                    results.append({
                        'return': ret, 'volatility': vol, 'sharpe': sharpe,
                    })
                except Exception:
                    continue

            return pd.DataFrame(results)

        except Exception as e:
            logger.error(f"Efficient frontier computation failed: {e}")
            return pd.DataFrame(columns=['return', 'volatility', 'sharpe'])
