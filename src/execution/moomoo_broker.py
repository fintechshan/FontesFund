"""Thin Moomoo / Futu OpenD adapter for the US paper sleeve.

Orders go out only with ``TrdEnv.SIMULATE``. There is no REAL trading path.
The SDK is imported lazily so unit tests and CI do not need ``moomoo`` or
``futu`` installed.
"""
from __future__ import annotations

import math
import socket
from typing import Any, Optional

# v7 US sleeve. Codes are ``US.<ticker>`` (``US.QQQ``). AIPO must be confirmed
# on the paper account; an unknown code is skipped and not replaced.
US_SLEEVE = ("QQQ", "SOXX", "SPY", "IEF", "GLD", "DBMF", "AIPO")

PREFERRED_SIM_TYPES = ("STOCK_AND_OPTION", "STOCK")
_SKIP_ACCOUNT_STATUS = {"DISABLED", "CANCELLED", "CLOSED"}


class SimulateRequired(RuntimeError):
    """Raised when an order would not be SIMULATE."""


class OpenDError(RuntimeError):
    """OpenD returned an error or could not be reached."""


def moomoo_code(ticker: str) -> str:
    """Map a US sleeve ticker to a Moomoo code (``QQQ`` → ``US.QQQ``)."""
    symbol = str(ticker).strip().upper()
    if symbol.startswith("US."):
        rest = symbol[3:]
        if not rest or "." in rest:
            raise ValueError(f"not a plain US ticker: {ticker}")
        return symbol
    if not symbol or "." in symbol or any(ch.isspace() for ch in symbol):
        raise ValueError(f"not a plain US ticker: {ticker}")
    return f"US.{symbol}"


def sleeve_ticker(code: str) -> Optional[str]:
    """Return the ticker for a ``US.*`` code, or None for any other market."""
    raw = str(code).strip().upper()
    if not raw.startswith("US.") or "." in raw[3:] or not raw[3:]:
        return None
    return raw[3:]


def enum_text(value: Any) -> str:
    """Normalize SDK enums and strings to a bare upper-case token."""
    if value is None:
        return ""
    name = getattr(value, "name", None)
    if isinstance(name, str) and name and name.upper() == name:
        return name.upper()
    raw = getattr(value, "value", value)
    text = str(raw).strip().upper()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def is_simulate_env(value: Any) -> bool:
    return enum_text(value) == "SIMULATE"


def require_simulate(value: Any, *, action: str = "trade") -> None:
    """Hard stop unless ``value`` is the SIMULATE environment."""
    if not is_simulate_env(value):
        raise SimulateRequired(
            f"Refusing to {action}: trd_env must be SIMULATE (got {value!r}). "
            "REAL trading is disabled."
        )


def _market_auth(row: dict) -> list[str]:
    auth = row.get("trdmarket_auth")
    if auth is None:
        return []
    if isinstance(auth, float) and math.isnan(auth):
        return []
    if isinstance(auth, str):
        cleaned = auth.replace("[", " ").replace("]", " ").replace("'", " ").replace('"', " ")
        return [enum_text(part) for part in cleaned.split(",") if part.strip()]
    try:
        return [enum_text(item) for item in list(auth)]
    except TypeError:
        return [enum_text(auth)]


def _eligible_simulate(row: dict) -> bool:
    if not is_simulate_env(row.get("trd_env")):
        return False
    status = enum_text(row.get("acc_status"))
    if status in _SKIP_ACCOUNT_STATUS:
        return False
    auth = _market_auth(row)
    if auth and "US" not in auth:
        return False
    return True


def pick_simulate_account(rows: list[dict]) -> Optional[dict]:
    """Pick a US SIMULATE stock account.

    Preference is ``STOCK_AND_OPTION``, then ``STOCK``. REAL rows are ignored.
    A futures-only paper account is not used for this equity sleeve.
    """
    eligible = [row for row in rows if _eligible_simulate(row)]
    if not eligible:
        return None
    for prefer in PREFERRED_SIM_TYPES:
        matches = [row for row in eligible if enum_text(row.get("sim_acc_type")) == prefer]
        if matches:
            return matches[0]
    non_futures = [
        row for row in eligible if enum_text(row.get("sim_acc_type")) != "FUTURES"
    ]
    return non_futures[0] if non_futures else None


def limit_near_market(price: float, side: str, cushion: float = 0.005) -> float:
    """Limit price a small step through the last cache print.

    US stocks at or above $1 use 2 decimals; below $1 use 4. Buy lifts, sell eases.
    """
    px = float(price)
    if not math.isfinite(px) or px <= 0:
        raise ValueError(f"price must be positive for a limit order, got {price}")
    side_name = str(side).upper()
    if side_name not in {"BUY", "SELL"}:
        raise ValueError(f"side must be BUY or SELL, got {side}")
    bumped = px * (1.0 + cushion) if side_name == "BUY" else px * (1.0 - cushion)
    bumped = max(bumped, 0.0001)
    decimals = 4 if bumped < 1 else 2
    return round(bumped, decimals)


def build_share_plan(
    nav: float,
    weights: dict,
    prices: dict,
    positions: dict,
    max_weight: float,
    untradeable: Optional[set] = None,
) -> list[dict]:
    """Share deltas from overlay weights, same floor rule as the IBKR script.

    Names in ``untradeable`` stay on the sheet as skips. Their weight is not
    moved onto another ticker. Held names outside the target are sells.
    """
    blocked = {str(name).upper() for name in (untradeable or set())}
    rows: list[dict] = []
    for ticker, weight in sorted(weights.items(), key=lambda item: -item[1]):
        symbol = str(ticker).upper()
        capped = min(float(weight), float(max_weight))
        px = float(prices[ticker])
        target = math.floor(nav * capped / px) if px > 0 else 0
        current = int(positions.get(ticker, positions.get(symbol, 0)) or 0)
        delta = target - current
        code = moomoo_code(symbol)
        status = "flat"
        note = ""
        if symbol in blocked:
            status = "skip_untradeable"
            note = "not tradeable on Moomoo; skipped, no substitute"
        elif delta:
            status = "order"
        rows.append({
            "ticker": symbol,
            "code": code,
            "weight": capped,
            "price": px,
            "target_shares": target,
            "current_shares": current,
            "delta": delta if status != "skip_untradeable" else 0,
            "raw_delta": delta,
            "side": ("BUY" if delta > 0 else "SELL") if delta else "",
            "status": status,
            "note": note,
        })

    target_names = {str(name).upper() for name in weights}
    for ticker, shares in positions.items():
        symbol = str(ticker).upper()
        qty = int(shares or 0)
        if symbol in target_names or not qty:
            continue
        exit_px = prices.get(ticker, prices.get(symbol))
        exit_price = float(exit_px) if exit_px not in (None, "") else None
        if symbol in blocked:
            rows.append({
                "ticker": symbol,
                "code": moomoo_code(symbol),
                "weight": 0.0,
                "price": exit_price,
                "target_shares": 0,
                "current_shares": qty,
                "delta": 0,
                "raw_delta": -qty,
                "side": "SELL",
                "status": "skip_untradeable",
                "note": "held but not tradeable; left in place, no substitute",
            })
            continue
        rows.append({
            "ticker": symbol,
            "code": moomoo_code(symbol),
            "weight": 0.0,
            "price": exit_price,
            "target_shares": 0,
            "current_shares": qty,
            "delta": -qty,
            "raw_delta": -qty,
            "side": "SELL",
            "status": "order",
            "note": "not in the overlay target",
        })
    return rows


def actionable_orders(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["status"] == "order" and row["delta"]]


def format_plan_table(rows: list[dict]) -> str:
    header = f"{'TICKER':8s}{'MOOMOO':12s}{'TARGET%':>9s}{'PRICE':>10s}{'TGT SH':>9s}{'CUR SH':>9s}{'ORDER':>14s}"
    lines = [header, "-" * len(header)]
    for row in rows:
        price = f"{row['price']:.2f}" if row["price"] else "—"
        if row["status"] == "skip_untradeable":
            action = "SKIP"
        elif row["delta"]:
            action = f"{row['side']} {abs(int(row['delta']))}"
        else:
            action = "—"
        lines.append(
            f"{row['ticker']:8s}{row['code']:12s}{row['weight']:>8.1%}"
            f"{price:>10s}{int(row['target_shares']):>9d}{int(row['current_shares']):>9d}"
            f"{action:>14s}"
        )
    return "\n".join(lines)


def ret_ok(api: Any, ret: Any) -> bool:
    ok = getattr(api, "RET_OK", 0)
    return ret == ok or ret == 0


def as_records(data: Any) -> list[dict]:
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        if getattr(data, "empty", False):
            return []
        return list(data.to_dict(orient="records"))
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _empty_positions(data: Any) -> bool:
    text = str(data).lower()
    return "no data" in text or "empty" in text or "无数据" in text or "无持仓" in text


def _market_unsupported(data: Any) -> bool:
    text = str(data).lower()
    keys = (
        "order type",
        "ordertype",
        "not support",
        "unsupported",
        "invalid order type",
        "市场单",
        "订单类型",
    )
    return any(key in text for key in keys)


def _detail(data: Any) -> str:
    records = as_records(data)
    if records:
        order_id = records[0].get("order_id", "")
        status = records[0].get("order_status", "")
        if order_id or status:
            return f"order_id={order_id} status={status}"
    text = str(data).replace("\n", " ")
    return text[:240]


def load_trade_api():
    """Import ``moomoo`` if installed, otherwise ``futu``."""
    errors = []
    for name in ("moomoo", "futu"):
        try:
            module = __import__(name)
        except ImportError as exc:
            errors.append(f"{name}: {exc}")
            continue
        return module, name
    raise ImportError(
        "OpenD client library is not installed. "
        "Run `pip install moomoo-api` or `pip install futu-api` on the machine "
        "where OpenD is logged in. Do not run this on Cloud Run. "
        + " | ".join(errors)
    )


class OpenDSession:
    """One trade context (and an optional quote context) for a US paper run."""

    def __init__(self, api: Any, ctx: Any, quote_ctx: Any = None, quote_warning: str = ""):
        self.api = api
        self.ctx = ctx
        self.quote_ctx = quote_ctx
        self.quote_warning = quote_warning

    def close(self) -> None:
        for obj in (self.quote_ctx, self.ctx):
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
        self.quote_ctx = None
        self.ctx = None

    def accounts(self) -> list[dict]:
        ret, data = self.ctx.get_acc_list()
        if not ret_ok(self.api, ret):
            raise OpenDError(f"get_acc_list failed: {data}")
        return as_records(data)

    def funds(self, acc_id: int) -> float:
        """NAV in USD from the SIMULATE account. Never queries REAL."""
        require_simulate(self.api.TrdEnv.SIMULATE, action="read paper funds")
        kwargs = {"trd_env": self.api.TrdEnv.SIMULATE, "acc_id": int(acc_id)}
        currency = getattr(self.api, "Currency", None)
        if currency is not None and hasattr(currency, "USD"):
            kwargs["currency"] = currency.USD
        try:
            ret, data = self.ctx.accinfo_query(**kwargs)
        except TypeError:
            kwargs.pop("currency", None)
            ret, data = self.ctx.accinfo_query(**kwargs)
        if not ret_ok(self.api, ret):
            raise OpenDError(f"accinfo_query failed: {data}")
        records = as_records(data)
        if not records or records[0].get("total_assets") is None:
            raise OpenDError(f"accinfo_query returned no total_assets: {data}")
        return float(records[0]["total_assets"])

    def positions(self, acc_id: int) -> tuple[dict, list]:
        """US ticker → shares, plus non-US codes that this script will not touch."""
        require_simulate(self.api.TrdEnv.SIMULATE, action="read paper positions")
        ret, data = self.ctx.position_list_query(
            trd_env=self.api.TrdEnv.SIMULATE,
            acc_id=int(acc_id),
        )
        if not ret_ok(self.api, ret):
            if _empty_positions(data):
                return {}, []
            raise OpenDError(f"position_list_query failed: {data}")
        held: dict[str, int] = {}
        non_us: list[str] = []
        for row in as_records(data):
            qty = row.get("qty", 0)
            try:
                shares = int(float(qty))
            except (TypeError, ValueError):
                continue
            if not shares:
                continue
            ticker = sleeve_ticker(str(row.get("code", "")))
            if ticker is None:
                code = str(row.get("code", "")).strip()
                if code:
                    non_us.append(code)
                continue
            held[ticker] = held.get(ticker, 0) + shares
        return held, non_us

    def untradeable(self, tickers: list[str]) -> tuple[set, Optional[str]]:
        """Tickers whose snapshot is missing. A quote outage does not mark every name."""
        if self.quote_ctx is None:
            note = self.quote_warning or (
                "OpenQuoteContext unavailable. Tradability was not checked. "
                "Confirm US.AIPO on the paper account before --execute."
            )
            return set(), note
        missing = set()
        for ticker in tickers:
            code = moomoo_code(ticker)
            try:
                ret, data = self.quote_ctx.get_market_snapshot([code])
            except Exception as exc:
                return set(), (
                    f"Quote snapshot failed ({exc}). Tradability was not checked. "
                    "Confirm US.AIPO on the paper account before --execute."
                )
            if not ret_ok(self.api, ret) or not as_records(data):
                missing.add(str(ticker).upper())
        return missing, None

    def place_simulate(
        self,
        *,
        code: str,
        qty: int,
        side: str,
        price: float,
        acc_id: int,
    ) -> dict:
        """Place one order with ``trd_env=TrdEnv.SIMULATE`` only.

        Uses a market order when the SDK exposes ``OrderType.MARKET``. If that
        type is rejected, retries once as a limit near ``price``. Unknown-code
        failures are returned to the caller and are not retried into a different symbol.
        """
        require_simulate(self.api.TrdEnv.SIMULATE, action="place_order")
        shares = int(abs(qty))
        if shares <= 0:
            raise ValueError("qty must be non-zero")
        side_name = str(side).upper()
        if side_name not in {"BUY", "SELL"}:
            raise ValueError(f"side must be BUY or SELL, got {side}")
        trd_side = self.api.TrdSide.BUY if side_name == "BUY" else self.api.TrdSide.SELL
        trd_env = self.api.TrdEnv.SIMULATE
        require_simulate(trd_env, action="place_order")

        order_type = getattr(self.api.OrderType, "MARKET", None)
        px = float(price or 0.0)
        if order_type is not None:
            ret, data = self.ctx.place_order(
                price=px,
                qty=shares,
                code=code,
                trd_side=trd_side,
                order_type=order_type,
                trd_env=trd_env,
                acc_id=int(acc_id),
            )
            if ret_ok(self.api, ret):
                return {"ok": True, "mode": "MARKET", "detail": _detail(data)}
            if not _market_unsupported(data):
                return {"ok": False, "mode": "MARKET", "detail": _detail(data)}
            if px <= 0:
                return {
                    "ok": False,
                    "mode": "MARKET",
                    "detail": "market order unsupported and no cache price for a limit",
                }
            limit = limit_near_market(px, side_name)
            ret, data = self.ctx.place_order(
                price=limit,
                qty=shares,
                code=code,
                trd_side=trd_side,
                order_type=self.api.OrderType.NORMAL,
                trd_env=trd_env,
                acc_id=int(acc_id),
            )
            if ret_ok(self.api, ret):
                return {
                    "ok": True,
                    "mode": f"LIMIT {limit:.4f}".rstrip("0").rstrip("."),
                    "detail": _detail(data),
                }
            return {"ok": False, "mode": "LIMIT", "detail": _detail(data)}

        if px <= 0:
            return {
                "ok": False,
                "mode": "LIMIT",
                "detail": "SDK has no market order and no cache price for a limit",
            }
        limit = limit_near_market(px, side_name)
        ret, data = self.ctx.place_order(
            price=limit,
            qty=shares,
            code=code,
            trd_side=trd_side,
            order_type=self.api.OrderType.NORMAL,
            trd_env=trd_env,
            acc_id=int(acc_id),
        )
        if ret_ok(self.api, ret):
            return {"ok": True, "mode": f"LIMIT {limit}", "detail": _detail(data)}
        return {"ok": False, "mode": "LIMIT", "detail": _detail(data)}


def opend_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """True when something accepts TCP on the OpenD port.

    The moomoo/futu client retries forever when the port is closed. A short
    probe lets the script print the overlay and exit instead of sleeping.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def open_session(
    host: str = "127.0.0.1",
    port: int = 11111,
    security_firm: str = "",
    api: Any = None,
    probe: bool = True,
):
    """Connect ``OpenSecTradeContext(filter_trdmarket=TrdMarket.US)``."""
    if probe and not opend_port_open(host, port):
        raise OpenDError(
            f"Nothing is listening on {host}:{port}. "
            "Start OpenD and log in. No orders placed."
        )
    if api is None:
        api, _name = load_trade_api()
    kwargs = {
        "filter_trdmarket": api.TrdMarket.US,
        "host": host,
        "port": int(port),
    }
    firm_name = (security_firm or "").strip()
    if firm_name:
        firms = getattr(api, "SecurityFirm", None)
        firm = getattr(firms, firm_name, None) if firms is not None else None
        if firm is None:
            raise OpenDError(
                f"Security firm {firm_name!r} is not on this SDK. "
                "Leave --security-firm empty to use the SDK default, or pass a "
                "SecurityFirm name such as FUTUINC."
            )
        kwargs["security_firm"] = firm
    try:
        ctx = api.OpenSecTradeContext(**kwargs)
    except Exception as exc:
        raise OpenDError(
            f"Could not connect to OpenD at {host}:{port} ({exc}). "
            "Start OpenD and log in. No orders placed."
        ) from exc

    quote_ctx = None
    quote_warning = ""
    opener = getattr(api, "OpenQuoteContext", None)
    if opener is None:
        quote_warning = "This SDK has no OpenQuoteContext. Tradability was not checked."
    else:
        try:
            quote_ctx = opener(host=host, port=int(port))
        except Exception as exc:
            quote_warning = (
                f"Quote context did not connect ({exc}). Tradability was not checked."
            )
    return OpenDSession(api, ctx, quote_ctx, quote_warning)
