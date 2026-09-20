"""
Performance Reporter Module
============================
Generates comprehensive performance reports using QuantStats and custom analysis.
Produces HTML tearsheets, metrics summaries, and monthly heatmaps.
"""

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from src.backtester.engine import BacktestResult

logger = logging.getLogger(__name__)


class PerformanceReporter:
    """
    Generates performance analysis reports for backtested strategies.
    
    Uses QuantStats for HTML tearsheets and custom computations
    for metrics summaries, monthly heatmaps, and strategy comparisons.
    """

    def __init__(self, risk_free_rate: float = 0.04):
        """
        Args:
            risk_free_rate: Annual risk-free rate for metric calculations.
        """
        self.risk_free_rate = risk_free_rate

    def generate_html_report(
        self,
        returns: pd.Series,
        benchmark_returns: Optional[pd.Series] = None,
        output_path: Optional[Path] = None,
        title: str = "ETF Strategy Performance Report",
    ) -> Optional[Path]:
        """
        Generate a QuantStats HTML tearsheet.

        Args:
            returns: Daily strategy returns.
            benchmark_returns: Daily benchmark returns (default: SPY).
            output_path: File path for HTML output.
            title: Report title.

        Returns:
            Path to generated HTML file, or None if QuantStats unavailable.
        """
        try:
            import quantstats as qs

            if output_path is None:
                output_path = Path("data/reports/tearsheet.html")
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Ensure returns are properly formatted
            returns = returns.dropna()
            returns.index = pd.to_datetime(returns.index)

            if benchmark_returns is not None:
                benchmark_returns = benchmark_returns.dropna()
                benchmark_returns.index = pd.to_datetime(benchmark_returns.index)
                qs.reports.html(
                    returns,
                    benchmark=benchmark_returns,
                    output=str(output_path),
                    title=title,
                )
            else:
                qs.reports.html(
                    returns,
                    benchmark="SPY",
                    output=str(output_path),
                    title=title,
                )

            logger.info(f"HTML tearsheet generated: {output_path}")
            return output_path

        except ImportError:
            logger.warning("QuantStats not installed. pip install quantstats")
            return None
        except Exception as e:
            logger.error(f"Failed to generate HTML report: {e}")
            return None

    def generate_metrics_summary(self, returns: pd.Series) -> dict[str, float]:
        """
        Compute key performance metrics from a return series.

        Args:
            returns: Daily return series.

        Returns:
            Dict of metric name -> value.
        """
        returns = returns.dropna()
        if returns.empty:
            return {"error": "No return data"}

        n_years = len(returns) / 252
        total_return = (1 + returns).prod() - 1
        annual_return = (1 + total_return) ** (1 / max(n_years, 0.01)) - 1
        volatility = returns.std() * np.sqrt(252)

        # Sharpe
        daily_rf = (1 + self.risk_free_rate) ** (1 / 252) - 1
        excess = returns - daily_rf
        sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

        # Sortino
        downside = returns[returns < 0]
        downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 0
        sortino = (annual_return - self.risk_free_rate) / downside_std if downside_std > 0 else 0

        # Drawdown
        equity = (1 + returns).cumprod()
        max_dd = ((equity / equity.expanding().max()) - 1).min()

        # Calmar
        calmar = annual_return / abs(max_dd) if max_dd != 0 else 0

        # Win rate
        win_rate = (returns > 0).sum() / len(returns)

        # Best / Worst
        monthly = returns.resample('ME').apply(lambda x: (1 + x).prod() - 1)

        return {
            "total_return": round(total_return, 4),
            "annual_return": round(annual_return, 4),
            "volatility": round(volatility, 4),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "max_drawdown": round(max_dd, 4),
            "calmar_ratio": round(calmar, 2),
            "win_rate_daily": round(win_rate, 4),
            "best_month": round(monthly.max(), 4) if not monthly.empty else 0,
            "worst_month": round(monthly.min(), 4) if not monthly.empty else 0,
            "avg_monthly_return": round(monthly.mean(), 4) if not monthly.empty else 0,
            "period_years": round(n_years, 1),
            "num_trading_days": len(returns),
        }

    def generate_monthly_heatmap(self, returns: pd.Series) -> pd.DataFrame:
        """
        Create a monthly returns heatmap (year × month).

        Args:
            returns: Daily return series.

        Returns:
            DataFrame with years as index, months as columns, values as returns.
        """
        returns = returns.dropna()
        monthly = returns.resample('ME').apply(lambda x: (1 + x).prod() - 1)

        # Pivot to year × month
        df = pd.DataFrame({
            'year': monthly.index.year,
            'month': monthly.index.month,
            'return': monthly.values,
        })

        month_names = [
            'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
            'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
        ]

        heatmap = df.pivot(index='year', columns='month', values='return')
        heatmap.columns = [month_names[m - 1] for m in heatmap.columns]

        # Add annual total
        annual = returns.resample('Y').apply(lambda x: (1 + x).prod() - 1)
        heatmap['Annual'] = annual.values[:len(heatmap)] if len(annual) >= len(heatmap) else np.nan

        return heatmap

    def compare_strategies_table(
        self, strategy_results: list["BacktestResult"]
    ) -> pd.DataFrame:
        """
        Create a formatted comparison table of multiple strategies.

        Args:
            strategy_results: List of BacktestResult objects.

        Returns:
            DataFrame with strategies as rows and metrics as columns.
        """
        rows = []
        for r in strategy_results:
            rows.append({
                'Strategy': r.name,
                'Annual Return': f"{r.annual_return:.2%}",
                'Volatility': f"{r.volatility:.2%}",
                'Sharpe': f"{r.sharpe_ratio:.2f}",
                'Sortino': f"{r.sortino_ratio:.2f}",
                'Max DD': f"{r.max_drawdown:.2%}",
                'Calmar': f"{r.calmar_ratio:.2f}",
                'Win Rate': f"{r.win_rate:.1%}",
                'Total Return': f"{r.total_return:.2%}",
                'Period': f"{r.start_date} to {r.end_date}",
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.set_index('Strategy')
        return df
