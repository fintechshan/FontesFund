"""
Portfolio Allocator Module
==========================
Maps regime + strategy to concrete dollar allocations with capital management.
Handles monthly contributions, rebalancing trades, and contribution pause logic.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """A single trade to execute."""
    ticker: str
    action: str  # 'BUY' or 'SELL'
    shares: int
    dollar_amount: float
    weight_change: float
    current_weight: float
    target_weight: float


@dataclass
class AllocationResult:
    """Result of an allocation computation."""
    target_weights: dict[str, float]
    dollar_amounts: dict[str, float]
    total_capital: float
    trades: list[Trade]
    contribution_applied: float
    timestamp: datetime


class PortfolioAllocator:
    """
    Converts portfolio weights to dollar allocations and computes rebalance trades.
    
    Supports monthly contribution management with performance-based pausing.
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        monthly_contribution: float = 10_000,
    ):
        """
        Args:
            initial_capital: Starting portfolio value in USD.
            monthly_contribution: Monthly contribution amount in USD.
        """
        self.initial_capital = initial_capital
        self.monthly_contribution = monthly_contribution
        logger.info(
            f"PortfolioAllocator initialized: "
            f"capital=${initial_capital:,.0f}, "
            f"monthly=${monthly_contribution:,.0f}"
        )

    def compute_target_allocation(
        self,
        weights: dict[str, float],
        total_capital: float,
    ) -> dict[str, float]:
        """
        Convert percentage weights to dollar amounts.

        Args:
            weights: Target weights (ticker -> decimal weight, should sum to ~1.0).
            total_capital: Total portfolio value in USD.

        Returns:
            Dict of ticker -> dollar amount.
        """
        # Normalize weights to ensure they sum to 1.0
        total_w = sum(weights.values())
        if total_w == 0:
            logger.warning("All weights are zero")
            return {}

        normalized = {k: v / total_w for k, v in weights.items()}
        allocations = {
            ticker: round(weight * total_capital, 2)
            for ticker, weight in normalized.items()
            if weight > 0.005  # Skip very tiny allocations
        }

        logger.debug(
            f"Allocation computed: {len(allocations)} positions, "
            f"total=${sum(allocations.values()):,.2f}"
        )
        return allocations

    def compute_rebalance_trades(
        self,
        current_positions: dict[str, float],
        target_weights: dict[str, float],
        total_capital: float,
        current_prices: Optional[dict[str, float]] = None,
        min_trade_value: float = 100.0,
    ) -> list[Trade]:
        """
        Compute trades needed to rebalance from current to target allocation.

        Args:
            current_positions: Current dollar value per ticker.
            target_weights: Target portfolio weights.
            total_capital: Total portfolio value.
            current_prices: Current prices per ticker (for share calculation).
            min_trade_value: Minimum trade size in dollars (skip smaller).

        Returns:
            List of Trade objects, sells ordered before buys.
        """
        target_dollars = self.compute_target_allocation(target_weights, total_capital)

        # Get all tickers involved
        all_tickers = set(list(current_positions.keys()) + list(target_dollars.keys()))

        trades = []
        for ticker in all_tickers:
            current_val = current_positions.get(ticker, 0.0)
            target_val = target_dollars.get(ticker, 0.0)
            delta = target_val - current_val

            if abs(delta) < min_trade_value:
                continue

            current_weight = current_val / total_capital if total_capital > 0 else 0
            target_weight = target_weights.get(ticker, 0.0)

            # Estimate shares
            shares = 0
            if current_prices and ticker in current_prices and current_prices[ticker] > 0:
                shares = int(abs(delta) / current_prices[ticker])

            trade = Trade(
                ticker=ticker,
                action="BUY" if delta > 0 else "SELL",
                shares=max(1, shares),
                dollar_amount=round(abs(delta), 2),
                weight_change=round(target_weight - current_weight, 4),
                current_weight=round(current_weight, 4),
                target_weight=round(target_weight, 4),
            )
            trades.append(trade)

        # Sort: sells first (to free cash), then buys
        trades.sort(key=lambda t: (0 if t.action == "SELL" else 1, -t.dollar_amount))

        logger.info(
            f"Rebalance: {len(trades)} trades, "
            f"sells={sum(1 for t in trades if t.action == 'SELL')}, "
            f"buys={sum(1 for t in trades if t.action == 'BUY')}, "
            f"total turnover=${sum(t.dollar_amount for t in trades):,.2f}"
        )
        return trades

    def should_contribute(
        self,
        trailing_3m_return: float,
        threshold: float = -0.05,
    ) -> bool:
        """
        Determine whether to apply monthly contribution based on performance.

        Contributions are paused if the trailing 3-month return is below threshold.

        Args:
            trailing_3m_return: Portfolio return over the last 3 months.
            threshold: Pause threshold (default -5%).

        Returns:
            True if contribution should proceed.
        """
        should = trailing_3m_return > threshold
        if not should:
            logger.warning(
                f"Monthly contribution PAUSED: trailing 3m return "
                f"{trailing_3m_return:.2%} < {threshold:.2%} threshold"
            )
        else:
            logger.info(
                f"Monthly contribution ACTIVE: trailing 3m return "
                f"{trailing_3m_return:.2%} > {threshold:.2%}"
            )
        return should

    def compute_contribution_allocation(
        self,
        contribution: float,
        target_weights: dict[str, float],
    ) -> dict[str, float]:
        """
        Allocate a monthly contribution according to current target weights.

        Args:
            contribution: Dollar amount to allocate.
            target_weights: Current target portfolio weights.

        Returns:
            Dict of ticker -> dollar amount for the contribution.
        """
        return self.compute_target_allocation(target_weights, contribution)

    def generate_rebalance_report(
        self,
        trades: list[Trade],
        total_capital: float,
    ) -> dict:
        """
        Generate a summary report of proposed rebalance trades.

        Args:
            trades: List of computed trades.
            total_capital: Total portfolio value.

        Returns:
            Report dict with trade summary, turnover metrics, etc.
        """
        total_buy = sum(t.dollar_amount for t in trades if t.action == "BUY")
        total_sell = sum(t.dollar_amount for t in trades if t.action == "SELL")
        turnover = (total_buy + total_sell) / (2 * total_capital) if total_capital > 0 else 0

        return {
            "timestamp": datetime.now().isoformat(),
            "total_capital": total_capital,
            "num_trades": len(trades),
            "num_buys": sum(1 for t in trades if t.action == "BUY"),
            "num_sells": sum(1 for t in trades if t.action == "SELL"),
            "total_buy_value": round(total_buy, 2),
            "total_sell_value": round(total_sell, 2),
            "turnover_pct": round(turnover, 4),
            "trades": [
                {
                    "ticker": t.ticker,
                    "action": t.action,
                    "shares": t.shares,
                    "dollar_amount": t.dollar_amount,
                    "weight_change": f"{t.weight_change:+.2%}",
                    "target_weight": f"{t.target_weight:.2%}",
                }
                for t in trades
            ],
        }
