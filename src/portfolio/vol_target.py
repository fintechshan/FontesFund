"""
Volatility Targeting Engine
=============================
Dynamically scales portfolio exposure based on realised volatility
to maintain a constant-volatility profile.

Key alpha source: scales UP in calm markets (Goldilocks) and DOWN in
volatile markets (Crisis), improving risk-adjusted returns by 0.3-0.5 Sharpe.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class VolatilityTargeting:
    """
    Volatility-targeting overlay that dynamically adjusts portfolio leverage.

    Computes rolling realised volatility and scales total exposure so that
    the portfolio maintains a target annualised volatility.
    """

    def __init__(
        self,
        target_vol: float = 0.10,
        lookback_days: int = 20,
        min_leverage: float = 0.50,
        max_leverage: float = 2.00,
        annualisation: float = 252.0,
    ):
        """
        Args:
            target_vol: Target annualised volatility (e.g. 0.10 = 10%).
            lookback_days: Rolling window for realised vol estimation.
            min_leverage: Floor on exposure multiplier.
            max_leverage: Cap on exposure multiplier.
            annualisation: Trading days per year.
        """
        self.target_vol = target_vol
        self.lookback_days = lookback_days
        self.min_leverage = min_leverage
        self.max_leverage = max_leverage
        self.annualisation = annualisation

    def compute_realised_vol(
        self,
        returns: pd.Series,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> float:
        """
        Compute annualised realised volatility from a return series.

        Args:
            returns: Daily portfolio return series.
            as_of_date: Compute as of this date (default: latest).

        Returns:
            Annualised realised volatility.
        """
        if as_of_date is not None:
            returns = returns.loc[:as_of_date]

        if len(returns) < self.lookback_days:
            logger.warning("Insufficient data for vol computation, returning target")
            return self.target_vol

        recent = returns.iloc[-self.lookback_days:]
        daily_vol = recent.std()
        annualised = daily_vol * np.sqrt(self.annualisation)

        return max(annualised, 0.001)  # Avoid division by zero

    def compute_leverage_multiplier(
        self,
        returns: pd.Series,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> float:
        """
        Compute the leverage multiplier to achieve target volatility.

        multiplier = target_vol / realised_vol, clipped to [min, max].

        Args:
            returns: Daily portfolio return series.
            as_of_date: Compute as of this date.

        Returns:
            Leverage multiplier (e.g., 1.5 means scale up 50%).
        """
        realised = self.compute_realised_vol(returns, as_of_date)
        raw_multiplier = self.target_vol / realised
        clipped = np.clip(raw_multiplier, self.min_leverage, self.max_leverage)

        logger.info(
            f"Vol targeting: realised={realised:.2%}, target={self.target_vol:.2%}, "
            f"raw_mult={raw_multiplier:.2f}, clipped={clipped:.2f}"
        )
        return round(clipped, 4)

    def apply_vol_target(
        self,
        weights: dict[str, float],
        portfolio_returns: pd.Series,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> tuple[dict[str, float], float]:
        """
        Scale portfolio weights to target volatility.

        If multiplier > 1.0, weights sum to >1.0 (leveraged).
        If multiplier < 1.0, remainder goes to cash.

        Args:
            weights: Current portfolio weights.
            portfolio_returns: Historical daily portfolio returns.
            as_of_date: Compute as of this date.

        Returns:
            Tuple of (adjusted_weights, cash_weight).
            - adjusted_weights: Scaled weights (may sum > 1.0)
            - cash_weight: Proportion allocated to cash (0 if leveraged)
        """
        multiplier = self.compute_leverage_multiplier(portfolio_returns, as_of_date)

        # Scale all weights
        adjusted = {k: round(v * multiplier, 4) for k, v in weights.items()}
        total_invested = sum(adjusted.values())
        cash_weight = max(0.0, 1.0 - total_invested)

        logger.info(
            f"Vol-targeted allocation: multiplier={multiplier:.2f}, "
            f"invested={total_invested:.1%}, cash={cash_weight:.1%}"
        )
        return adjusted, round(cash_weight, 4)

    def compute_vol_timeseries(
        self,
        returns: pd.Series,
    ) -> pd.DataFrame:
        """
        Compute rolling realised vol and leverage multiplier over time.

        Useful for backtesting and dashboard display.

        Args:
            returns: Full daily return series.

        Returns:
            DataFrame with columns: realised_vol, multiplier, target_vol.
        """
        rolling_vol = returns.rolling(self.lookback_days).std() * np.sqrt(self.annualisation)
        multiplier = (self.target_vol / rolling_vol).clip(self.min_leverage, self.max_leverage)

        return pd.DataFrame({
            'realised_vol': rolling_vol,
            'multiplier': multiplier,
            'target_vol': self.target_vol,
        })

    def backtest_vol_targeting(
        self,
        returns: pd.Series,
    ) -> pd.Series:
        """
        Apply vol targeting retroactively to a return series for backtesting.

        At each time step, scale the next day's return by the current multiplier.

        Args:
            returns: Daily return series.

        Returns:
            Vol-targeted return series.
        """
        rolling_vol = returns.rolling(self.lookback_days).std() * np.sqrt(self.annualisation)
        multiplier = (self.target_vol / rolling_vol).clip(self.min_leverage, self.max_leverage)

        # Shift multiplier by 1 day to avoid look-ahead bias
        multiplier_lagged = multiplier.shift(1)

        # Apply multiplier
        targeted_returns = returns * multiplier_lagged

        # Drop initial NaN period
        targeted_returns = targeted_returns.dropna()

        # Log summary stats
        orig_vol = returns.std() * np.sqrt(252)
        new_vol = targeted_returns.std() * np.sqrt(252)
        orig_sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        new_sharpe = (targeted_returns.mean() / targeted_returns.std() * np.sqrt(252)) if targeted_returns.std() > 0 else 0

        logger.info(
            f"Vol-target backtest: vol {orig_vol:.2%} → {new_vol:.2%}, "
            f"Sharpe {orig_sharpe:.2f} → {new_sharpe:.2f}"
        )
        return targeted_returns

    def get_dashboard_data(
        self,
        returns: pd.Series,
    ) -> dict:
        """
        Get vol targeting summary for dashboard display.

        Returns:
            Dict with current realised vol, multiplier, and target.
        """
        realised = self.compute_realised_vol(returns)
        multiplier = self.compute_leverage_multiplier(returns)

        return {
            "target_volatility": f"{self.target_vol:.0%}",
            "realised_volatility": f"{realised:.1%}",
            "leverage_multiplier": f"{multiplier:.2f}x",
            "exposure_pct": f"{multiplier * 100:.0f}%",
            "status": (
                "🟢 Scaling UP" if multiplier > 1.1 else
                "🔴 Scaling DOWN" if multiplier < 0.9 else
                "⚪ Near target"
            ),
        }
