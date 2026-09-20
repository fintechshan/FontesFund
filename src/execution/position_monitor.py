"""
Position Monitor Module
========================
Real-time position and P&L tracking with snapshot persistence.
Integrates with the broker and risk manager for continuous monitoring.
"""

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from src.execution.broker import IBKRBroker, Position
    from src.execution.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class PositionMonitor:
    """
    Tracks portfolio positions, P&L, and risk alerts in real-time.
    
    Takes periodic snapshots to SQLite for historical analysis.
    Integrates with RiskManager for continuous risk checking.
    """

    def __init__(
        self,
        broker: "IBKRBroker",
        risk_manager: "RiskManager",
        db_path: Optional[Path] = None,
    ):
        """
        Args:
            broker: IBKRBroker instance for position data.
            risk_manager: RiskManager for risk checking.
            db_path: SQLite database path for snapshots.
        """
        self.broker = broker
        self.risk_manager = risk_manager

        if db_path is None:
            try:
                from config.settings import DB_PATH
                db_path = DB_PATH
            except ImportError:
                db_path = Path("data/db/investment.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create position snapshots table."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS position_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ticker TEXT NOT NULL,
                        quantity INTEGER,
                        market_value REAL,
                        weight REAL,
                        unrealized_pnl REAL,
                        portfolio_value REAL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        total_value REAL,
                        unrealized_pnl REAL,
                        daily_return REAL,
                        num_positions INTEGER
                    )
                """)
                conn.commit()

    def get_current_positions(self) -> dict[str, "Position"]:
        """
        Get current positions from broker with computed weights.

        Returns:
            Dict mapping ticker -> Position with weight computed.
        """
        positions = self.broker.get_positions()

        if not positions:
            return {}

        # Compute total portfolio value
        total_value = sum(p.market_value for p in positions.values())

        # Set weights
        if total_value > 0:
            for p in positions.values():
                p.weight = round(p.market_value / total_value, 4)

        return positions

    def get_portfolio_value(self) -> float:
        """
        Get total portfolio value from broker.

        Returns:
            Total portfolio value in USD. 0 if not connected.
        """
        summary = self.broker.get_account_summary()
        return summary.get("net_liquidation", 0.0)

    def get_unrealized_pnl(self) -> float:
        """Get total unrealized P&L."""
        summary = self.broker.get_account_summary()
        return summary.get("unrealized_pnl", 0.0)

    def compute_daily_return(self) -> float:
        """
        Compute today's portfolio return from position snapshots.

        Returns:
            Daily return as decimal. 0 if insufficient data.
        """
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - pd.Timedelta(days=1)).strftime('%Y-%m-%d')

        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                today_val = conn.execute(
                    "SELECT total_value FROM portfolio_snapshots "
                    "WHERE date(snapshot_time) = ? ORDER BY snapshot_time DESC LIMIT 1",
                    (today,),
                ).fetchone()

                yest_val = conn.execute(
                    "SELECT total_value FROM portfolio_snapshots "
                    "WHERE date(snapshot_time) = ? ORDER BY snapshot_time DESC LIMIT 1",
                    (yesterday,),
                ).fetchone()

        if today_val and yest_val and yest_val[0] > 0:
            return round((today_val[0] / yest_val[0]) - 1, 6)
        return 0.0

    def take_snapshot(self) -> None:
        """Record current positions and portfolio value to SQLite."""
        positions = self.get_current_positions()
        portfolio_value = self.get_portfolio_value()
        unrealized_pnl = self.get_unrealized_pnl()
        daily_return = self.compute_daily_return()
        now = datetime.now().isoformat()

        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                # Position snapshots
                for ticker, pos in positions.items():
                    conn.execute(
                        """INSERT INTO position_snapshots
                        (snapshot_time, ticker, quantity, market_value, weight, 
                         unrealized_pnl, portfolio_value)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (now, ticker, pos.quantity, pos.market_value,
                         pos.weight, pos.unrealized_pnl, portfolio_value),
                    )

                # Portfolio snapshot
                conn.execute(
                    """INSERT INTO portfolio_snapshots
                    (snapshot_time, total_value, unrealized_pnl, daily_return, num_positions)
                    VALUES (?, ?, ?, ?, ?)""",
                    (now, portfolio_value, unrealized_pnl, daily_return, len(positions)),
                )
                conn.commit()

        logger.info(
            f"Snapshot taken: {len(positions)} positions, "
            f"value=${portfolio_value:,.2f}, P&L=${unrealized_pnl:+,.2f}"
        )

    def get_position_history(self, days: int = 30) -> pd.DataFrame:
        """
        Get historical position snapshots.

        Args:
            days: Number of days of history.

        Returns:
            DataFrame of position snapshots.
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                df = pd.read_sql(
                    "SELECT * FROM position_snapshots WHERE snapshot_time >= ? "
                    "ORDER BY snapshot_time DESC",
                    conn, params=(cutoff,),
                )
        return df

    def get_portfolio_history(self, days: int = 30) -> pd.DataFrame:
        """Get historical portfolio-level snapshots."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                df = pd.read_sql(
                    "SELECT * FROM portfolio_snapshots WHERE snapshot_time >= ? "
                    "ORDER BY snapshot_time",
                    conn, params=(cutoff,),
                )
        return df

    def check_risk_alerts(self) -> list[str]:
        """
        Run risk checks on current positions.

        Returns:
            List of alert messages.
        """
        positions = self.get_current_positions()
        if not positions:
            return ["No positions — risk check skipped"]

        weights = {t: p.weight for t, p in positions.items()}
        portfolio_value = self.get_portfolio_value()

        # Get current VIX
        try:
            import yfinance as yf
            vix_data = yf.Ticker("^VIX").history(period="1d")
            current_vix = vix_data['Close'].iloc[-1] if not vix_data.empty else 20.0
        except Exception:
            current_vix = 20.0

        assessment = self.risk_manager.run_all_checks(
            proposed_weights=weights,
            current_positions=weights,
            portfolio_value=portfolio_value,
            current_vix=current_vix,
        )

        alerts = []
        for check in assessment.checks:
            if not check.passed:
                alerts.append(f"[{check.severity.upper()}] {check.message}")

        return alerts if alerts else ["✅ All risk checks passed"]

    def get_dashboard_data(self) -> dict:
        """
        Get complete position data formatted for dashboard display.

        Returns:
            Dict with positions, portfolio metrics, risk status, and history.
        """
        positions = self.get_current_positions()
        portfolio_value = self.get_portfolio_value()
        unrealized_pnl = self.get_unrealized_pnl()
        alerts = self.check_risk_alerts()

        position_list = [
            {
                "ticker": t,
                "quantity": p.quantity,
                "market_value": p.market_value,
                "weight": f"{p.weight:.1%}",
                "unrealized_pnl": p.unrealized_pnl,
                "avg_cost": p.avg_cost,
            }
            for t, p in sorted(positions.items(), key=lambda x: -x[1].market_value)
        ]

        return {
            "timestamp": datetime.now().isoformat(),
            "portfolio_value": portfolio_value,
            "unrealized_pnl": unrealized_pnl,
            "daily_return": self.compute_daily_return(),
            "num_positions": len(positions),
            "positions": position_list,
            "risk_alerts": alerts,
            "connected": self.broker.is_connected(),
            "mode": "PAPER" if self.broker.paper_mode else "LIVE",
        }
