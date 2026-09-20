"""
Order Manager Module
=====================
Order lifecycle management with SQLite persistence.
Tracks all orders from submission through fill/cancellation.
"""

import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from src.execution.broker import OrderResult

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Manages order lifecycle with persistent SQLite storage.
    
    Records all orders, provides history queries, daily summaries,
    and reconciliation between broker and expected positions.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: Path to SQLite database.
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
        """Create orders table."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        order_id INTEGER,
                        ticker TEXT NOT NULL,
                        action TEXT NOT NULL,
                        status TEXT NOT NULL,
                        filled_qty INTEGER DEFAULT 0,
                        avg_price REAL DEFAULT 0,
                        message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()

    def record_order(self, order: OrderResult) -> None:
        """
        Record an order result to the database.

        Args:
            order: OrderResult from the broker.
        """
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    """INSERT INTO orders 
                    (order_id, ticker, action, status, filled_qty, avg_price, message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        order.order_id, order.ticker, order.action,
                        order.status, order.filled_qty, order.avg_price,
                        order.message, order.timestamp.isoformat(),
                    ),
                )
                conn.commit()

        logger.debug(
            f"Order recorded: {order.action} {order.filled_qty} {order.ticker} "
            f"[{order.status}] @ {order.avg_price}"
        )

    def record_orders(self, orders: list[OrderResult]) -> None:
        """Record multiple order results."""
        for order in orders:
            self.record_order(order)

    def get_pending_orders(self) -> list[dict]:
        """
        Get all pending (non-final) orders.

        Returns:
            List of order dicts with status PENDING or PARTIAL.
        """
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM orders WHERE status IN ('PENDING', 'PARTIAL', 'SUBMITTED') "
                    "ORDER BY created_at DESC"
                ).fetchall()
                return [dict(row) for row in rows]

    def get_order_history(self, days: int = 30) -> pd.DataFrame:
        """
        Get order history for the last N days.

        Args:
            days: Number of days of history to retrieve.

        Returns:
            DataFrame of historical orders.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                df = pd.read_sql(
                    f"SELECT * FROM orders WHERE created_at >= ? ORDER BY created_at DESC",
                    conn,
                    params=(cutoff,),
                )
        return df

    def get_daily_summary(self, date: Optional[datetime] = None) -> dict:
        """
        Get summary of orders for a specific day.

        Args:
            date: Date to summarize (default: today).

        Returns:
            Dict with order counts, fills, and total traded value.
        """
        if date is None:
            date = datetime.now()
        date_str = date.strftime('%Y-%m-%d')

        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM orders WHERE date(created_at) = ?",
                    (date_str,),
                ).fetchall()

        orders = [dict(row) for row in rows]
        if not orders:
            return {
                "date": date_str,
                "total_orders": 0,
                "filled": 0,
                "cancelled": 0,
                "failed": 0,
                "simulated": 0,
                "total_traded_value": 0,
            }

        filled = [o for o in orders if o['status'] == 'FILLED']
        return {
            "date": date_str,
            "total_orders": len(orders),
            "filled": len(filled),
            "cancelled": sum(1 for o in orders if o['status'] == 'CANCELLED'),
            "failed": sum(1 for o in orders if o['status'] == 'FAILED'),
            "simulated": sum(1 for o in orders if o['status'] == 'SIMULATED'),
            "total_traded_value": sum(
                o['filled_qty'] * o['avg_price'] for o in filled
            ),
            "buys": sum(1 for o in orders if o['action'] == 'BUY'),
            "sells": sum(1 for o in orders if o['action'] == 'SELL'),
        }

    def reconcile(
        self,
        broker_positions: dict[str, float],
        expected_positions: dict[str, float],
        tolerance: float = 0.02,
    ) -> list[str]:
        """
        Compare broker positions against expected positions.

        Args:
            broker_positions: Actual positions from broker (ticker -> value).
            expected_positions: Expected positions from our records.
            tolerance: Acceptable difference as fraction of position value.

        Returns:
            List of discrepancy descriptions.
        """
        discrepancies = []
        all_tickers = set(list(broker_positions.keys()) + list(expected_positions.keys()))

        for ticker in all_tickers:
            broker_val = broker_positions.get(ticker, 0.0)
            expected_val = expected_positions.get(ticker, 0.0)
            diff = broker_val - expected_val
            ref = max(abs(broker_val), abs(expected_val), 1.0)

            if abs(diff) / ref > tolerance:
                discrepancies.append(
                    f"{ticker}: broker=${broker_val:,.2f} vs expected=${expected_val:,.2f} "
                    f"(diff=${diff:+,.2f}, {diff/ref:+.1%})"
                )

        if discrepancies:
            logger.warning(f"Reconciliation found {len(discrepancies)} discrepancies")
        else:
            logger.info("Reconciliation: all positions match")

        return discrepancies
