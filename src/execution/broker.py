"""
IBKR Broker Connector Module
==============================
Connects to Interactive Brokers via ib_async for order execution and position management.
Supports paper trading (port 4002) and live trading (port 4001).
Operates in simulated mode when IBKR is not connected.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Current position in a security."""
    ticker: str
    quantity: int = 0
    avg_cost: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    weight: float = 0.0


@dataclass
class TradeOrder:
    """A trade order to execute."""
    ticker: str
    action: str  # 'BUY' or 'SELL'
    quantity: int = 0
    estimated_value: float = 0.0
    order_type: str = "LMT"  # 'MKT', 'LMT', 'MOC'


@dataclass
class OrderResult:
    """Result of an order placement."""
    order_id: int = 0
    ticker: str = ""
    action: str = ""
    status: str = "PENDING"  # FILLED, PARTIAL, FAILED, SIMULATED, CANCELLED
    filled_qty: int = 0
    avg_price: float = 0.0
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class IBKRBroker:
    """
    Interactive Brokers connector via ib_async.
    
    Handles connection management, position queries, and order execution.
    Falls back to SIMULATED mode when IBKR is not available.
    """

    PAPER_PORTS = {4002, 7497}
    LIVE_PORTS = {4001, 7496}

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 1,
    ):
        """
        Args:
            host: IBKR Gateway/TWS host address.
            port: Connection port (4002=Gateway Paper, 7497=TWS Paper,
                  4001=Gateway Live, 7496=TWS Live).
            client_id: Unique client ID for this connection.
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.paper_mode = port in self.PAPER_PORTS
        self.connected = False
        self._ib = None

        mode = "PAPER" if self.paper_mode else "LIVE"
        logger.info(f"IBKRBroker initialized: {host}:{port} ({mode} mode), clientId={client_id}")

    # ------------------------------------------------------------------ #
    #                     CONNECTION                                      #
    # ------------------------------------------------------------------ #

    def connect(self) -> bool:
        """
        Connect to IB Gateway/TWS.

        If a previous IB instance exists but is no longer connected (stale),
        it will be cleaned up before establishing a fresh connection.

        Returns:
            True if connection successful, False otherwise.
        """
        # Handle stale connections: _ib exists but is no longer connected
        if self._ib is not None:
            try:
                if not self._ib.isConnected():
                    logger.warning(
                        "Stale IBKR connection detected — cleaning up before reconnecting"
                    )
                    try:
                        self._ib.disconnect()
                    except Exception:
                        pass  # Best-effort cleanup
                    self._ib = None
                    self.connected = False
                else:
                    # Already connected, nothing to do
                    logger.debug("Already connected to IBKR")
                    return True
            except Exception:
                # isConnected() itself failed — treat as stale
                logger.warning("Unable to verify IBKR connection state — reconnecting")
                self._ib = None
                self.connected = False

        try:
            from ib_async import IB
            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id)
            self.connected = True

            # Log account info
            accounts = self._ib.managedAccounts()
            mode = "PAPER" if self.paper_mode else "LIVE"
            logger.info(
                f"Connected to IBKR ({mode}): accounts={accounts}"
            )
            return True

        except ImportError:
            logger.warning(
                "ib_async not installed. Running in SIMULATED mode. "
                "Install with: pip install ib_async"
            )
            self.connected = False
            return False

        except Exception as e:
            logger.error(f"IBKR connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Cleanly disconnect from IBKR."""
        if self._ib and self.connected:
            try:
                self._ib.disconnect()
                logger.info("Disconnected from IBKR")
            except Exception as e:
                logger.warning(f"Disconnect error: {e}")
        self.connected = False
        self._ib = None

    def reconnect(self) -> bool:
        """
        Disconnect from IBKR (if connected) and establish a fresh connection.

        Returns:
            True if reconnection successful, False otherwise.
        """
        logger.info("Reconnecting to IBKR...")
        self.disconnect()
        result = self.connect()
        if result:
            logger.info("IBKR reconnection successful")
        else:
            logger.error("IBKR reconnection failed")
        return result

    def is_connected(self) -> bool:
        """Check if actively connected to IBKR."""
        if self._ib is None:
            return False
        try:
            return self._ib.isConnected()
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #                     ACCOUNT & POSITIONS                             #
    # ------------------------------------------------------------------ #

    def get_account_summary(self) -> dict:
        """
        Get account summary (net liquidation, cash, buying power, P&L).

        Returns:
            Dict with account metrics. Empty dict if not connected.
        """
        if not self.is_connected():
            logger.warning("Not connected to IBKR — returning simulated account summary")
            return {
                "net_liquidation": 0,
                "total_cash": 0,
                "buying_power": 0,
                "unrealized_pnl": 0,
                "realized_pnl": 0,
                "simulated": True,
            }

        try:
            summary = {}
            account_values = self._ib.accountSummary()
            for item in account_values:
                if item.tag == "NetLiquidation":
                    summary["net_liquidation"] = float(item.value)
                elif item.tag == "TotalCashValue":
                    summary["total_cash"] = float(item.value)
                elif item.tag == "BuyingPower":
                    summary["buying_power"] = float(item.value)
                elif item.tag == "UnrealizedPnL":
                    summary["unrealized_pnl"] = float(item.value)
                elif item.tag == "RealizedPnL":
                    summary["realized_pnl"] = float(item.value)
            summary["simulated"] = False
            return summary

        except Exception as e:
            logger.error(f"Failed to get account summary: {e}")
            return {"error": str(e), "simulated": True}

    def get_positions(self) -> dict[str, Position]:
        """
        Get current positions from IBKR.

        Returns:
            Dict mapping ticker -> Position. Empty if not connected.
        """
        if not self.is_connected():
            logger.debug("Not connected — returning empty positions")
            return {}

        try:
            positions = {}
            for pos in self._ib.positions():
                ticker = pos.contract.symbol
                positions[ticker] = Position(
                    ticker=ticker,
                    quantity=int(pos.position),
                    avg_cost=pos.avgCost,
                    market_value=pos.position * pos.avgCost,
                    unrealized_pnl=0,  # Computed separately
                )
            logger.debug(f"Retrieved {len(positions)} positions from IBKR")
            return positions

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return {}

    def get_current_prices(self, tickers: list[str]) -> dict[str, float]:
        """
        Fetch current prices for a list of tickers.

        When connected to IBKR, uses reqMktData() for real-time prices.
        When not connected, falls back to the most recent prices from
        the cached CSV at data/cache/price_data.csv.

        Args:
            tickers: List of ticker symbols (e.g. ['SPY', 'QQQ', 'VTI']).

        Returns:
            Dict mapping ticker -> current price. Tickers that could not
            be resolved are omitted from the result.
        """
        prices: dict[str, float] = {}

        if self.is_connected():
            # ---- Live prices via ib_async ----
            try:
                from ib_async import Stock

                for ticker in tickers:
                    try:
                        contract = Stock(ticker, "SMART", "USD")
                        self._ib.qualifyContracts(contract)
                        md = self._ib.reqMktData(contract)
                        self._ib.sleep(2)  # Allow time for snapshot

                        price = None
                        if md.last and md.last > 0:
                            price = float(md.last)
                        elif md.close and md.close > 0:
                            price = float(md.close)
                        elif md.bid and md.ask and md.bid > 0 and md.ask > 0:
                            price = round((float(md.bid) + float(md.ask)) / 2, 4)

                        if price is not None:
                            prices[ticker] = price
                        else:
                            logger.warning(f"No price data from IBKR for {ticker}")

                        # Cancel the subscription to free resources
                        self._ib.cancelMktData(contract)

                    except Exception as e:
                        logger.warning(f"Failed to get live price for {ticker}: {e}")

                logger.info(f"Fetched live prices for {len(prices)}/{len(tickers)} tickers")
                return prices

            except ImportError:
                logger.warning("ib_async not available for live prices — falling back to cache")

        # ---- Fallback: read from cached CSV ----
        cache_path = Path("data/cache/price_data.csv")
        if not cache_path.exists():
            logger.warning(f"Price cache not found at {cache_path} — no prices available")
            return prices

        try:
            df = pd.read_csv(cache_path)

            # Expect columns: Date (or similar), plus one column per ticker
            # Use the last row as the most recent prices
            if df.empty:
                logger.warning("Price cache CSV is empty")
                return prices

            last_row = df.iloc[-1]
            for ticker in tickers:
                if ticker in df.columns:
                    val = last_row[ticker]
                    if pd.notna(val):
                        prices[ticker] = float(val)

            logger.info(
                f"Loaded cached prices for {len(prices)}/{len(tickers)} tickers "
                f"from {cache_path}"
            )

        except Exception as e:
            logger.error(f"Failed to read price cache: {e}")

        return prices

    def get_portfolio_snapshot(self) -> dict:
        """
        Get a complete portfolio snapshot in a single call.

        Combines account summary, positions, current prices, connection
        status, and a timestamp.  Designed for the dashboard to retrieve
        all broker state at once.

        Returns:
            Dict with keys:
                - account_summary (dict):  Output of get_account_summary().
                - positions       (dict):  Output of get_positions() serialised to dicts.
                - prices          (dict):  Current prices for all held tickers.
                - timestamp       (str):   ISO-8601 timestamp of the snapshot.
                - connected       (bool):  Whether IBKR is currently connected.
        """
        connected = self.is_connected()
        account_summary = self.get_account_summary()
        positions = self.get_positions()

        # Gather prices for every ticker we hold
        held_tickers = list(positions.keys())
        prices = self.get_current_prices(held_tickers) if held_tickers else {}

        # Serialise Position dataclasses to plain dicts
        positions_dict = {
            ticker: {
                "ticker": pos.ticker,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "market_value": pos.market_value,
                "unrealized_pnl": pos.unrealized_pnl,
                "weight": pos.weight,
            }
            for ticker, pos in positions.items()
        }

        snapshot = {
            "account_summary": account_summary,
            "positions": positions_dict,
            "prices": prices,
            "timestamp": datetime.now().isoformat(),
            "connected": connected,
        }

        logger.debug(
            f"Portfolio snapshot: connected={connected}, "
            f"{len(positions_dict)} positions, {len(prices)} prices"
        )
        return snapshot

    # ------------------------------------------------------------------ #
    #                     TRADE COMPUTATION                               #
    # ------------------------------------------------------------------ #

    def compute_required_trades(
        self,
        current_positions: dict[str, float],
        target_weights: dict[str, float],
        total_equity: float,
        current_prices: Optional[dict[str, float]] = None,
        min_trade_value: float = 100.0,
    ) -> list[TradeOrder]:
        """
        Compute trades needed to move from current to target allocation.

        Args:
            current_positions: Current dollar value per ticker.
            target_weights: Target portfolio weights.
            total_equity: Total portfolio equity.
            current_prices: Current prices per ticker.
            min_trade_value: Minimum trade size in dollars.

        Returns:
            List of TradeOrder objects (sells first, then buys).
        """
        trades = []
        all_tickers = set(list(current_positions.keys()) + list(target_weights.keys()))

        for ticker in all_tickers:
            current_val = current_positions.get(ticker, 0.0)
            target_val = target_weights.get(ticker, 0.0) * total_equity
            delta = target_val - current_val

            if abs(delta) < min_trade_value:
                continue

            # Estimate shares
            shares = 0
            if current_prices and ticker in current_prices and current_prices[ticker] > 0:
                shares = int(abs(delta) / current_prices[ticker])
            shares = max(1, shares)

            trades.append(TradeOrder(
                ticker=ticker,
                action="BUY" if delta > 0 else "SELL",
                quantity=shares,
                estimated_value=round(abs(delta), 2),
            ))

        # Sells first, then buys (free up cash)
        trades.sort(key=lambda t: (0 if t.action == "SELL" else 1, -t.estimated_value))
        return trades

    # ------------------------------------------------------------------ #
    #                     ORDER EXECUTION                                 #
    # ------------------------------------------------------------------ #

    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        order_type: str = "LMT",
    ) -> OrderResult:
        """
        Place a single order via IBKR.

        Args:
            ticker: Stock/ETF ticker symbol.
            action: 'BUY' or 'SELL'.
            quantity: Number of shares.
            order_type: 'MKT', 'LMT', or 'MOC'.

        Returns:
            OrderResult with fill status.
        """
        if not self.is_connected():
            logger.info(f"SIMULATED order: {action} {quantity} {ticker} ({order_type})")
            return OrderResult(
                order_id=0, ticker=ticker, action=action,
                status="SIMULATED", filled_qty=quantity,
                avg_price=0.0,
                message=f"Simulated — IBKR not connected",
            )

        try:
            from ib_async import Stock, MarketOrder, LimitOrder

            contract = Stock(ticker, "SMART", "USD")
            self._ib.qualifyContracts(contract)

            if order_type == "MKT":
                order = MarketOrder(action, quantity)
            elif order_type == "LMT":
                # Get current midpoint
                ticker_data = self._ib.reqMktData(contract)
                self._ib.sleep(2)  # Wait for data
                mid = (ticker_data.bid + ticker_data.ask) / 2 if ticker_data.bid > 0 else 0
                if mid <= 0:
                    order = MarketOrder(action, quantity)
                    order_type = "MKT (LMT fallback)"
                else:
                    order = LimitOrder(action, quantity, mid)
            else:
                order = MarketOrder(action, quantity)

            trade = self._ib.placeOrder(contract, order)
            self._ib.sleep(1)  # Brief wait

            status = trade.orderStatus.status
            filled = trade.orderStatus.filled
            avg_price = trade.orderStatus.avgFillPrice

            logger.info(
                f"Order placed: {action} {quantity} {ticker} @ {avg_price} "
                f"[{status}] (type={order_type})"
            )

            return OrderResult(
                order_id=trade.order.orderId,
                ticker=ticker, action=action,
                status=status, filled_qty=int(filled),
                avg_price=avg_price,
                message=f"Order {status}",
            )

        except Exception as e:
            logger.error(f"Order failed for {ticker}: {e}")
            return OrderResult(
                order_id=0, ticker=ticker, action=action,
                status="FAILED", filled_qty=0, avg_price=0,
                message=f"Error: {e}",
            )

    def place_portfolio_orders(
        self,
        trades: list[TradeOrder],
        dry_run: bool = True,
    ) -> list[OrderResult]:
        """
        Execute a list of portfolio rebalance orders.

        Args:
            trades: List of TradeOrder objects.
            dry_run: If True, simulate without placing real orders.

        Returns:
            List of OrderResult objects.
        """
        results = []

        if dry_run:
            logger.info(f"DRY RUN: {len(trades)} trades would be placed")
            for trade in trades:
                results.append(OrderResult(
                    order_id=0, ticker=trade.ticker,
                    action=trade.action, status="SIMULATED",
                    filled_qty=trade.quantity, avg_price=0,
                    message=f"Dry run — ${trade.estimated_value:,.2f}",
                ))
            return results

        # Execute sells first, then buys
        for trade in trades:
            result = self.place_order(
                ticker=trade.ticker,
                action=trade.action,
                quantity=trade.quantity,
                order_type=trade.order_type,
            )
            results.append(result)

            # Brief pause between orders
            if self.is_connected():
                import time
                time.sleep(0.5)

        return results

    def cancel_order(self, order_id: int) -> bool:
        """Cancel an open order by ID."""
        if not self.is_connected():
            logger.warning("Cannot cancel — not connected")
            return False

        try:
            for trade in self._ib.openTrades():
                if trade.order.orderId == order_id:
                    self._ib.cancelOrder(trade.order)
                    logger.info(f"Order {order_id} cancelled")
                    return True
            logger.warning(f"Order {order_id} not found in open trades")
            return False
        except Exception as e:
            logger.error(f"Cancel failed for order {order_id}: {e}")
            return False

    def get_order_status(self, order_id: int) -> str:
        """Get current status of an order."""
        if not self.is_connected():
            return "UNKNOWN (not connected)"

        try:
            for trade in self._ib.openTrades():
                if trade.order.orderId == order_id:
                    return trade.orderStatus.status
            return "NOT_FOUND"
        except Exception as e:
            return f"ERROR: {e}"
