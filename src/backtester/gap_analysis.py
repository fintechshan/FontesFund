"""
Gap Analysis Module
====================
Tracks discrepancy between backtested performance and live performance.
Computes tracking error, identifies gap sources, and alerts on excessive drift.
"""

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class GapAnalyzer:
    """
    Tracks and analyzes the gap between backtest predictions and live performance.
    
    Records daily live vs. backtest returns in SQLite and computes
    tracking error, gap sources, and drift alerts.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: Path to SQLite database for gap tracking.
        """
        if db_path is None:
            try:
                from config.settings import DB_PATH
                db_path = DB_PATH
            except ImportError:
                db_path = Path("data/db/investment.db")

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create gap tracking table."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS gap_tracking (
                        date TEXT PRIMARY KEY,
                        live_return REAL,
                        backtest_return REAL,
                        gap REAL,
                        cumulative_live REAL,
                        cumulative_backtest REAL,
                        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()

    def record_live_return(
        self,
        date: datetime,
        portfolio_return: float,
        backtest_return: float,
    ) -> None:
        """
        Record a day's live vs. backtest return.

        Args:
            date: Trading date.
            portfolio_return: Actual live portfolio return for the day.
            backtest_return: Expected backtest return for the day.
        """
        gap = portfolio_return - backtest_return
        date_str = date.strftime('%Y-%m-%d')

        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                # Get previous cumulative values
                prev = conn.execute(
                    "SELECT cumulative_live, cumulative_backtest FROM gap_tracking "
                    "ORDER BY date DESC LIMIT 1"
                ).fetchone()

                cum_live = ((prev[0] if prev else 0) + 1) * (1 + portfolio_return) - 1 if prev else portfolio_return
                cum_bt = ((prev[1] if prev else 0) + 1) * (1 + backtest_return) - 1 if prev else backtest_return

                conn.execute(
                    """INSERT OR REPLACE INTO gap_tracking 
                    (date, live_return, backtest_return, gap, cumulative_live, cumulative_backtest)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (date_str, portfolio_return, backtest_return, gap, cum_live, cum_bt),
                )
                conn.commit()

        logger.debug(
            f"Gap recorded [{date_str}]: live={portfolio_return:.4f}, "
            f"backtest={backtest_return:.4f}, gap={gap:+.4f}"
        )

    def compute_tracking_error(self, window_days: int = 252) -> float:
        """
        Compute annualized tracking error (std dev of return differences).

        Args:
            window_days: Number of recent trading days to analyze.

        Returns:
            Annualized tracking error as decimal. 0.0 if insufficient data.
        """
        df = self.get_gap_history()
        if df.empty or len(df) < 20:
            return 0.0

        recent = df.tail(window_days)
        tracking_error = recent['gap'].std() * np.sqrt(252)
        return round(tracking_error, 4)

    def get_gap_history(self) -> pd.DataFrame:
        """
        Retrieve full history of live vs. backtest returns.

        Returns:
            DataFrame with columns: date, live_return, backtest_return, gap,
            cumulative_live, cumulative_backtest.
        """
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                df = pd.read_sql(
                    "SELECT * FROM gap_tracking ORDER BY date",
                    conn,
                    parse_dates=['date'],
                )
        return df

    def identify_gap_sources(self) -> list[str]:
        """
        Analyze and describe likely sources of tracking error.

        Returns:
            List of human-readable gap source descriptions.
        """
        df = self.get_gap_history()
        if df.empty:
            return ["No gap data available yet"]

        sources = []
        gaps = df['gap']

        # Check for systematic bias
        mean_gap = gaps.mean()
        if abs(mean_gap) > 0.001:
            direction = "outperforming" if mean_gap > 0 else "underperforming"
            sources.append(
                f"Systematic bias: live portfolio {direction} backtest by "
                f"{abs(mean_gap):.4f} per day on average"
            )

        # Check for execution slippage
        negative_gaps = gaps[gaps < 0]
        if len(negative_gaps) > len(gaps) * 0.6:
            sources.append(
                "Execution slippage suspected: >60% of days show negative gap "
                "(live underperforms backtest)"
            )

        # Check for timing gaps
        abs_gaps = gaps.abs()
        large_gap_days = abs_gaps[abs_gaps > abs_gaps.quantile(0.95)]
        if len(large_gap_days) > 0:
            sources.append(
                f"Timing gaps: {len(large_gap_days)} days with unusually large gaps "
                f"(>95th percentile = {abs_gaps.quantile(0.95):.4f})"
            )

        # Check for trend in gap
        if len(gaps) > 60:
            recent_gap = gaps.tail(20).mean()
            old_gap = gaps.head(20).mean()
            if abs(recent_gap - old_gap) > 0.002:
                trend = "widening" if abs(recent_gap) > abs(old_gap) else "narrowing"
                sources.append(f"Gap trend: tracking error is {trend} over time")

        if not sources:
            sources.append("No significant gap sources identified — tracking is normal")

        return sources

    def is_gap_excessive(self, threshold: float = 0.02) -> bool:
        """
        Check if annualized tracking error exceeds threshold.

        Args:
            threshold: Maximum acceptable annualized tracking error.

        Returns:
            True if tracking error > threshold.
        """
        te = self.compute_tracking_error()
        excessive = te > threshold
        if excessive:
            logger.warning(
                f"EXCESSIVE GAP: tracking error {te:.4f} > threshold {threshold:.4f}"
            )
        return excessive

    def get_gap_summary(self) -> dict:
        """
        Generate a summary suitable for dashboard display.

        Returns:
            Dict with tracking error, gap statistics, and alert status.
        """
        df = self.get_gap_history()
        if df.empty:
            return {
                "status": "no_data",
                "message": "No gap data recorded yet",
                "tracking_error": 0,
                "days_tracked": 0,
            }

        te = self.compute_tracking_error()
        gaps = df['gap']

        return {
            "status": "alert" if te > 0.02 else "ok",
            "tracking_error": te,
            "mean_daily_gap": round(gaps.mean(), 6),
            "gap_std": round(gaps.std(), 6),
            "max_positive_gap": round(gaps.max(), 4),
            "max_negative_gap": round(gaps.min(), 4),
            "days_tracked": len(df),
            "cumulative_live_return": round(df['cumulative_live'].iloc[-1], 4),
            "cumulative_backtest_return": round(df['cumulative_backtest'].iloc[-1], 4),
            "cumulative_gap": round(
                df['cumulative_live'].iloc[-1] - df['cumulative_backtest'].iloc[-1], 4
            ),
            "gap_sources": self.identify_gap_sources(),
        }
