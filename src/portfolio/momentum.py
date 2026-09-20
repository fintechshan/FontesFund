"""
Momentum Overlay Engine
========================
Applies cross-sectional 12-1 momentum to tilt regime allocations
towards winning assets and away from losers.

This is a key alpha engine targeting +4-6% annual excess return.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MomentumOverlay:
    """
    Cross-sectional momentum overlay for regime-based portfolios.

    Computes 12-month return (skipping last month) for each ETF,
    ranks them, and tilts weights towards winners.
    """

    def __init__(
        self,
        lookback_months: int = 12,
        skip_months: int = 1,
        overweight_factor: float = 1.5,
        underweight_factor: float = 0.5,
        top_pct: float = 0.30,
        bottom_pct: float = 0.30,
        min_momentum_6m: float = 0.0,
    ):
        """
        Args:
            lookback_months: Momentum lookback window.
            skip_months: Skip most recent N months (reversal avoidance).
            overweight_factor: Multiply top-ranked weights by this.
            underweight_factor: Multiply bottom-ranked weights by this.
            top_pct: Fraction of assets to overweight.
            bottom_pct: Fraction of assets to underweight.
            min_momentum_6m: Remove assets with 6-month momentum below this.
        """
        self.lookback_months = lookback_months
        self.skip_months = skip_months
        self.overweight_factor = overweight_factor
        self.underweight_factor = underweight_factor
        self.top_pct = top_pct
        self.bottom_pct = bottom_pct
        self.min_momentum_6m = min_momentum_6m

    def compute_momentum_scores(
        self,
        price_data: pd.DataFrame,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> pd.Series:
        """
        Compute 12-1 momentum scores for all available ETFs.

        Args:
            price_data: DataFrame of adjusted close prices (columns = tickers).
            as_of_date: Compute as of this date (default: latest).

        Returns:
            Series of momentum scores indexed by ticker.
        """
        if as_of_date is not None:
            price_data = price_data.loc[:as_of_date]

        if len(price_data) < 252:
            logger.warning("Insufficient price history for momentum computation")
            return pd.Series(dtype=float)

        # 12-1 momentum: return from T-12m to T-1m
        skip_days = self.skip_months * 21  # ~21 trading days per month
        lookback_days = self.lookback_months * 21

        end_idx = len(price_data) - skip_days
        start_idx = end_idx - lookback_days

        if start_idx < 0 or end_idx <= start_idx:
            return pd.Series(dtype=float)

        start_prices = price_data.iloc[start_idx]
        end_prices = price_data.iloc[end_idx]

        # Filter out zero/NaN prices
        valid = (start_prices > 0) & (end_prices > 0) & start_prices.notna() & end_prices.notna()
        momentum = (end_prices[valid] / start_prices[valid]) - 1

        return momentum.sort_values(ascending=False)

    def compute_6m_momentum(
        self,
        price_data: pd.DataFrame,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> pd.Series:
        """Compute 6-month momentum for filtering."""
        if as_of_date is not None:
            price_data = price_data.loc[:as_of_date]

        lookback = 126  # ~6 months
        if len(price_data) < lookback:
            return pd.Series(dtype=float)

        start_prices = price_data.iloc[-lookback]
        end_prices = price_data.iloc[-1]

        valid = (start_prices > 0) & (end_prices > 0) & start_prices.notna() & end_prices.notna()
        return (end_prices[valid] / start_prices[valid]) - 1

    def apply_momentum_tilt(
        self,
        base_weights: dict[str, float],
        price_data: pd.DataFrame,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> dict[str, float]:
        """
        Apply momentum overlay to regime base weights.

        Steps:
        1. Compute 12-1 momentum scores
        2. Remove assets with negative 6-month momentum
        3. Overweight top 30%, underweight bottom 30%
        4. Renormalize to sum to 1.0

        Args:
            base_weights: Regime allocation weights {ticker: weight}.
            price_data: Historical prices DataFrame.
            as_of_date: Compute as of this date.

        Returns:
            Momentum-adjusted weights.
        """
        tickers = list(base_weights.keys())
        available = [t for t in tickers if t in price_data.columns]

        if len(available) < 3:
            logger.info("Too few assets for momentum overlay, returning base weights")
            return dict(base_weights)

        # Step 1: Compute momentum scores
        momentum = self.compute_momentum_scores(price_data[available], as_of_date)
        if momentum.empty:
            return dict(base_weights)

        # Step 2: Remove assets with negative 6-month momentum
        mom_6m = self.compute_6m_momentum(price_data[available], as_of_date)
        filtered = {}
        for ticker, weight in base_weights.items():
            if ticker in mom_6m.index and mom_6m[ticker] < self.min_momentum_6m:
                logger.debug(f"Momentum filter: removing {ticker} (6m={mom_6m[ticker]:.2%})")
                continue
            filtered[ticker] = weight

        if not filtered:
            return dict(base_weights)

        # Step 3: Rank and tilt
        ranked_tickers = [t for t in momentum.index if t in filtered]
        n = len(ranked_tickers)
        n_top = max(1, int(n * self.top_pct))
        n_bottom = max(1, int(n * self.bottom_pct))

        top_tickers = set(ranked_tickers[:n_top])
        bottom_tickers = set(ranked_tickers[-n_bottom:])

        adjusted = {}
        for ticker, weight in filtered.items():
            if ticker in top_tickers:
                adjusted[ticker] = weight * self.overweight_factor
            elif ticker in bottom_tickers:
                adjusted[ticker] = weight * self.underweight_factor
            else:
                adjusted[ticker] = weight

        # Step 4: Renormalize
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: round(v / total, 4) for k, v in adjusted.items() if v > 0.005}

        logger.info(
            f"Momentum overlay applied: {n_top} overweight, {n_bottom} underweight, "
            f"{len(base_weights) - len(adjusted)} filtered out"
        )
        return adjusted

    def get_momentum_report(
        self,
        price_data: pd.DataFrame,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """
        Generate a momentum report for dashboard display.

        Returns:
            DataFrame with ticker, 12-1 momentum, 6m momentum, and rank.
        """
        mom_12_1 = self.compute_momentum_scores(price_data, as_of_date)
        mom_6m = self.compute_6m_momentum(price_data, as_of_date)

        report = pd.DataFrame({
            '12-1 Momentum': mom_12_1,
            '6M Momentum': mom_6m,
        })
        report['Rank'] = range(1, len(report) + 1)
        report['Signal'] = report['12-1 Momentum'].apply(
            lambda x: '🟢 Strong' if x > 0.15 else ('🟡 Moderate' if x > 0 else '🔴 Weak')
        )
        return report.sort_values('12-1 Momentum', ascending=False)
