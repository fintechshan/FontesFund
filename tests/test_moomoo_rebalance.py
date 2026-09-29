"""Moomoo paper rebalance: mapping, SIMULATE guard, dry-run. No OpenD."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import moomoo_rebalance as mr  # noqa: E402
from src.execution.moomoo_broker import (  # noqa: E402
    US_SLEEVE,
    OpenDError,
    OpenDSession,
    SimulateRequired,
    actionable_orders,
    build_share_plan,
    format_plan_table,
    is_simulate_env,
    limit_near_market,
    moomoo_code,
    open_session,
    pick_simulate_account,
    require_simulate,
    sleeve_ticker,
)


class _Tok:
    def __init__(self, name: str):
        self.name = name
        self.value = name

    def __repr__(self):
        return self.name


class _Env:
    SIMULATE = _Tok("SIMULATE")
    REAL = _Tok("REAL")


class _OrderType:
    MARKET = _Tok("MARKET")
    NORMAL = _Tok("NORMAL")


class _Side:
    BUY = _Tok("BUY")
    SELL = _Tok("SELL")


class _Market:
    US = _Tok("US")


class _Currency:
    USD = _Tok("USD")


class FakeAPI:
    RET_OK = 0
    TrdEnv = _Env
    OrderType = _OrderType
    TrdSide = _Side
    TrdMarket = _Market
    Currency = _Currency

    def __init__(self, ctx=None, quote=None):
        self.ctx = ctx
        self.quote = quote
        self.trade_kwargs = []
        self.quote_kwargs = []

    def OpenSecTradeContext(self, **kwargs):
        self.trade_kwargs.append(kwargs)
        return self.ctx

    def OpenQuoteContext(self, **kwargs):
        self.quote_kwargs.append(kwargs)
        return self.quote


class FakeCtx:
    def __init__(self, accounts, nav=100_000.0, positions=None, orders=None, market_error=None):
        self.accounts = accounts
        self.nav = nav
        self.positions = positions or []
        self.orders = orders if orders is not None else []
        self.market_error = market_error
        self.closed = False

    def get_acc_list(self):
        return 0, self.accounts

    def accinfo_query(self, **kwargs):
        self.orders.append(("funds", kwargs))
        return 0, [{"total_assets": self.nav}]

    def position_list_query(self, **kwargs):
        self.orders.append(("positions", kwargs))
        return 0, self.positions

    def place_order(self, **kwargs):
        self.orders.append(("place", kwargs))
        if kwargs.get("order_type") is _OrderType.MARKET and self.market_error:
            return -1, self.market_error
        return 0, [{"order_id": "99", "order_status": "SUBMITTED"}]

    def close(self):
        self.closed = True


class FakeQuote:
    def __init__(self, missing=None, fail=False):
        self.missing = {m.upper() for m in (missing or set())}
        self.fail = fail
        self.closed = False

    def get_market_snapshot(self, codes):
        if self.fail:
            raise ConnectionError("quote down")
        code = codes[0]
        ticker = code.split(".", 1)[-1]
        if ticker.upper() in self.missing:
            return -1, f"unknown {code}"
        return 0, [{"code": code, "last_price": 10.0}]

    def close(self):
        self.closed = True


def _acc(acc_id, env, sim_type, auth=("US",), status="ACTIVE"):
    return {
        "acc_id": acc_id,
        "trd_env": env,
        "sim_acc_type": sim_type,
        "trdmarket_auth": list(auth),
        "acc_status": status,
    }


class MappingTests(unittest.TestCase):
    def test_us_sleeve_codes(self):
        self.assertEqual(US_SLEEVE, ("QQQ", "SOXX", "SPY", "IEF", "GLD", "DBMF", "AIPO"))
        for ticker in US_SLEEVE:
            self.assertEqual(moomoo_code(ticker), f"US.{ticker}")
            self.assertEqual(moomoo_code(ticker.lower()), f"US.{ticker}")
            self.assertEqual(sleeve_ticker(f"US.{ticker}"), ticker)
        self.assertEqual(moomoo_code("US.QQQ"), "US.QQQ")
        self.assertIsNone(sleeve_ticker("HK.00700"))
        with self.assertRaises(ValueError):
            moomoo_code("BRK.B")


class SimulateGuardTests(unittest.TestCase):
    def test_require_simulate(self):
        require_simulate("SIMULATE")
        require_simulate(_Tok("SIMULATE"))
        self.assertTrue(is_simulate_env("TrdEnv.SIMULATE"))
        with self.assertRaises(SimulateRequired):
            require_simulate("REAL")
        with self.assertRaises(SimulateRequired):
            require_simulate(_Tok("REAL"))
        with self.assertRaises(SimulateRequired):
            require_simulate(None)

    def test_pick_prefers_stock_and_option_and_ignores_real(self):
        rows = [
            _acc(1, "SIMULATE", "FUTURES"),
            _acc(2, "SIMULATE", "STOCK"),
            _acc(3, "REAL", "STOCK_AND_OPTION"),
            _acc(4, "SIMULATE", "STOCK_AND_OPTION"),
            _acc(5, "SIMULATE", "STOCK_AND_OPTION", auth=("HK",)),
        ]
        picked = pick_simulate_account(rows)
        self.assertEqual(picked["acc_id"], 4)

    def test_pick_stock_when_no_combined_account(self):
        rows = [
            _acc(2, "SIMULATE", "STOCK"),
            _acc(9, "REAL", "STOCK"),
        ]
        self.assertEqual(pick_simulate_account(rows)["acc_id"], 2)

    def test_pick_rejects_futures_only_and_non_us(self):
        self.assertIsNone(pick_simulate_account([_acc(1, "SIMULATE", "FUTURES")]))
        self.assertIsNone(pick_simulate_account([_acc(1, "SIMULATE", "STOCK", auth=("HK",))]))
        self.assertIsNone(pick_simulate_account([_acc(1, "REAL", "STOCK_AND_OPTION")]))
        disabled = _acc(8, "SIMULATE", "STOCK_AND_OPTION", status="DISABLED")
        self.assertIsNone(pick_simulate_account([disabled]))

    def test_place_simulate_sends_simulate_only(self):
        ctx = FakeCtx(accounts=[])
        session = OpenDSession(FakeAPI(), ctx, FakeQuote())
        result = session.place_simulate(
            code="US.QQQ", qty=3, side="BUY", price=100.0, acc_id=4,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "MARKET")
        placed = [item for item in ctx.orders if item[0] == "place"]
        self.assertEqual(len(placed), 1)
        kwargs = placed[0][1]
        self.assertIs(kwargs["trd_env"], _Env.SIMULATE)
        self.assertEqual(enum_name(kwargs["trd_env"]), "SIMULATE")
        self.assertIs(kwargs["order_type"], _OrderType.MARKET)
        self.assertEqual(kwargs["code"], "US.QQQ")
        self.assertEqual(kwargs["qty"], 3)

    def test_place_refuses_when_simulate_constant_is_not_simulate(self):
        class BrokenEnv:
            SIMULATE = _Tok("REAL")
            REAL = _Tok("REAL")

        api = FakeAPI()
        api.TrdEnv = BrokenEnv
        ctx = FakeCtx(accounts=[])
        session = OpenDSession(api, ctx)
        with self.assertRaises(SimulateRequired):
            session.place_simulate(code="US.SPY", qty=1, side="BUY", price=10, acc_id=1)
        self.assertEqual(ctx.orders, [])

    def test_market_rejection_falls_back_to_limit_once(self):
        ctx = FakeCtx(accounts=[], market_error="order type not supported")
        session = OpenDSession(FakeAPI(), ctx)
        result = session.place_simulate(
            code="US.IEF", qty=4, side="SELL", price=100.0, acc_id=4,
        )
        self.assertTrue(result["ok"])
        self.assertIn("LIMIT", result["mode"])
        placed = [item[1] for item in ctx.orders if item[0] == "place"]
        self.assertEqual(len(placed), 2)
        self.assertIs(placed[0]["order_type"], _OrderType.MARKET)
        self.assertIs(placed[1]["order_type"], _OrderType.NORMAL)
        self.assertEqual(placed[1]["price"], limit_near_market(100.0, "SELL"))
        self.assertIs(placed[1]["trd_env"], _Env.SIMULATE)

    def test_unknown_code_is_not_retried(self):
        ctx = FakeCtx(accounts=[], market_error="unknown security US.AIPO")
        session = OpenDSession(FakeAPI(), ctx)
        result = session.place_simulate(
            code="US.AIPO", qty=2, side="BUY", price=20.0, acc_id=4,
        )
        self.assertFalse(result["ok"])
        placed = [item for item in ctx.orders if item[0] == "place"]
        self.assertEqual(len(placed), 1)

    def test_open_session_filters_us_market(self):
        ctx = FakeCtx(accounts=[])
        quote = FakeQuote()
        api = FakeAPI(ctx=ctx, quote=quote)
        session = open_session(host="127.0.0.1", port=11111, api=api, probe=False)
        self.assertEqual(api.trade_kwargs[0]["filter_trdmarket"], _Market.US)
        self.assertEqual(api.trade_kwargs[0]["port"], 11111)
        self.assertNotIn("security_firm", api.trade_kwargs[0])
        session.close()
        self.assertTrue(ctx.closed)
        self.assertTrue(quote.closed)

    def test_closed_port_does_not_construct_a_context(self):
        api = FakeAPI(ctx=FakeCtx([]), quote=FakeQuote())
        with self.assertRaises(OpenDError) as caught:
            open_session(host="127.0.0.1", port=1, api=api, probe=True)
        self.assertIn("No orders placed", str(caught.exception))
        self.assertEqual(api.trade_kwargs, [])
        self.assertEqual(api.quote_kwargs, [])

    def test_funds_and_positions_use_simulate(self):
        ctx = FakeCtx(
            accounts=[],
            positions=[
                {"code": "US.QQQ", "qty": 5},
                {"code": "HK.00700", "qty": 100},
            ],
        )
        session = OpenDSession(FakeAPI(), ctx)
        nav = session.funds(4)
        held, non_us = session.positions(4)
        self.assertEqual(nav, 100_000.0)
        self.assertEqual(held, {"QQQ": 5})
        self.assertEqual(non_us, ["HK.00700"])
        for kind, kwargs in ctx.orders:
            self.assertIs(kwargs["trd_env"], _Env.SIMULATE)
            self.assertEqual(kwargs["acc_id"], 4)
            self.assertIn(kind, {"funds", "positions"})

    def test_snapshot_skips_only_the_missing_code(self):
        session = OpenDSession(FakeAPI(), FakeCtx([]), FakeQuote(missing={"AIPO"}))
        missing, note = session.untradeable(["QQQ", "AIPO"])
        self.assertEqual(missing, {"AIPO"})
        self.assertIsNone(note)
        down = OpenDSession(FakeAPI(), FakeCtx([]), FakeQuote(fail=True))
        missing, note = down.untradeable(["QQQ", "AIPO"])
        self.assertEqual(missing, set())
        self.assertIn("Tradability was not checked", note)


def enum_name(value) -> str:
    return value.name


class PlanTests(unittest.TestCase):
    def test_share_floor_matches_ibkr_and_skips_untradeable(self):
        rows = build_share_plan(
            nav=10_000,
            weights={"QQQ": 0.30, "AIPO": 0.10, "SPY": 0.50},
            prices={"QQQ": 100.0, "AIPO": 25.0, "SPY": 50.0},
            positions={"QQQ": 10, "GLD": 4},
            max_weight=0.35,
            untradeable={"AIPO"},
        )
        by_ticker = {row["ticker"]: row for row in rows}
        self.assertEqual(by_ticker["QQQ"]["target_shares"], 30)
        self.assertEqual(by_ticker["QQQ"]["delta"], 20)
        self.assertEqual(by_ticker["QQQ"]["side"], "BUY")
        # 0.50 is capped at max_weight 0.35 → floor(10000 * 0.35 / 50) = 70
        self.assertEqual(by_ticker["SPY"]["weight"], 0.35)
        self.assertEqual(by_ticker["SPY"]["target_shares"], 70)
        self.assertEqual(by_ticker["AIPO"]["status"], "skip_untradeable")
        self.assertEqual(by_ticker["AIPO"]["delta"], 0)
        self.assertEqual(by_ticker["AIPO"]["code"], "US.AIPO")
        self.assertEqual(by_ticker["GLD"]["side"], "SELL")
        self.assertEqual(by_ticker["GLD"]["delta"], -4)
        sent = actionable_orders(rows)
        self.assertEqual([row["ticker"] for row in sent], ["SPY", "QQQ", "GLD"])
        table = format_plan_table(rows)
        self.assertIn("US.AIPO", table)
        self.assertIn("SKIP", table)
        self.assertNotIn("SUBSTITUTE", table.upper())

    def test_limit_near_market_decimals(self):
        self.assertEqual(limit_near_market(100, "BUY"), 100.50)
        self.assertEqual(limit_near_market(100, "SELL"), 99.50)
        self.assertEqual(limit_near_market(0.5, "BUY"), 0.5025)


class _Session:
    def __init__(self, accounts, nav=50_000.0, positions=None, non_us=None, missing=None, note=""):
        self._accounts = accounts
        self.nav = nav
        self._positions = positions or {}
        self._non_us = non_us or []
        self._missing = missing or set()
        self._note = note
        self.placed = []
        self.closed = False

    def accounts(self):
        return self._accounts

    def funds(self, acc_id):
        return self.nav

    def positions(self, acc_id):
        return dict(self._positions), list(self._non_us)

    def untradeable(self, tickers):
        return set(self._missing), self._note or None

    def place_simulate(self, **kwargs):
        if kwargs.get("trd_env") not in (None,) and str(kwargs.get("trd_env")) != "SIMULATE":
            raise AssertionError(kwargs)
        self.placed.append(kwargs)
        return {"ok": True, "mode": "MARKET", "detail": "order_id=1 status=SUBMITTED"}

    def close(self):
        self.closed = True


class CliTests(unittest.TestCase):
    def _weights(self):
        def fake():
            print("overlay-from-cache")
            return "goldilocks", 16.0, {"QQQ": 0.5, "SPY": 0.5, "AIPO": 0.05}, {
                "QQQ": 100.0, "SPY": 50.0, "AIPO": 20.0,
            }
        return fake

    def test_dry_run_prints_plan_and_places_nothing(self):
        session = _Session(
            accounts=[_acc(42, "SIMULATE", "STOCK_AND_OPTION")],
            positions={"QQQ": 10},
            missing={"AIPO"},
        )
        buf = io.StringIO()
        with patch.object(mr, "current_regime_and_weights", self._weights()), \
                patch.object(mr, "open_session", return_value=session), \
                redirect_stdout(buf):
            code = mr.run([])
        text = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("overlay-from-cache", text)
        self.assertIn("DRY-RUN", text)
        self.assertIn("US.QQQ", text)
        self.assertIn("US.AIPO", text)
        self.assertIn("SKIP", text)
        self.assertIn("SIMULATE", text)
        self.assertEqual(session.placed, [])
        self.assertTrue(session.closed)

    def test_execute_on_real_account_aborts(self):
        session = _Session(accounts=[_acc(7, "REAL", "STOCK_AND_OPTION")])
        buf = io.StringIO()
        with patch.object(mr, "current_regime_and_weights", self._weights()), \
                patch.object(mr, "open_session", return_value=session), \
                redirect_stdout(buf):
            code = mr.run(["--execute"])
        text = buf.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("No SIMULATE", text)
        self.assertIn("No orders placed.", text)
        self.assertEqual(session.placed, [])
        self.assertNotIn("Placing", text)
        self.assertTrue(session.closed)

    def test_execute_simulate_places_without_real_env(self):
        session = _Session(
            accounts=[_acc(42, "SIMULATE", "STOCK")],
            positions={"QQQ": 0},
        )
        buf = io.StringIO()
        with patch.object(mr, "current_regime_and_weights", self._weights()), \
                patch.object(mr, "open_session", return_value=session), \
                redirect_stdout(buf):
            code = mr.run(["--execute"])
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(session.placed), 1)
        for call in session.placed:
            self.assertNotIn("trd_env", call)
            self.assertTrue(str(call["code"]).startswith("US."))
        codes = {call["code"] for call in session.placed}
        self.assertIn("US.QQQ", codes)
        self.assertIn("US.SPY", codes)
        self.assertIn("US.AIPO", codes)
        self.assertIn("Placing", buf.getvalue())
        self.assertIn("trd_env=SIMULATE only", buf.getvalue())

    def test_execute_skips_untradeable_aipo(self):
        session = _Session(
            accounts=[_acc(42, _Tok("SIMULATE"), "STOCK_AND_OPTION")],
            missing={"AIPO"},
        )
        buf = io.StringIO()
        with patch.object(mr, "current_regime_and_weights", self._weights()), \
                patch.object(mr, "open_session", return_value=session), \
                redirect_stdout(buf):
            code = mr.run(["--execute"])
        self.assertEqual(code, 0)
        codes = [call["code"] for call in session.placed]
        self.assertNotIn("US.AIPO", codes)
        self.assertIn("US.QQQ", codes)
        self.assertIn("no substitute", buf.getvalue())

    def test_connect_failure_keeps_cache_weights(self):
        buf = io.StringIO()
        with patch.object(mr, "current_regime_and_weights", self._weights()), \
                patch.object(mr, "open_session", side_effect=ConnectionError("connection refused")), \
                redirect_stdout(buf):
            code = mr.run([])
        text = buf.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("overlay-from-cache", text)
        self.assertIn("QQQ", text)
        self.assertIn("No orders placed.", text)
        self.assertIn("11111", text)

    def test_missing_sdk_after_weights(self):
        buf = io.StringIO()
        with patch.object(mr, "current_regime_and_weights", self._weights()), \
                patch.object(mr, "open_session", side_effect=ImportError("pip install moomoo-api")), \
                redirect_stdout(buf):
            code = mr.run([])
        text = buf.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("moomoo-api", text)
        self.assertIn("No orders placed.", text)
        self.assertIn("overlay-from-cache", text)

    def test_missing_cache_is_graceful(self):
        buf = io.StringIO()

        def boom():
            raise FileNotFoundError("data/cache/price_data.csv")

        with patch.object(mr, "current_regime_and_weights", boom), redirect_stdout(buf):
            code = mr.run([])
        text = buf.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("cache is missing", text)
        self.assertIn("No orders placed.", text)

    def test_help(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as caught:
                mr.run(["--help"])
        self.assertEqual(caught.exception.code, 0)
        text = buf.getvalue()
        self.assertIn("SIMULATE", text)
        self.assertIn("OpenD", text)
        self.assertIn("moomoo-api", text)
        self.assertIn("11111", text)


class SharedHelperTests(unittest.TestCase):
    def test_ibkr_and_moomoo_use_the_same_overlay_function(self):
        import ibkr_rebalance
        from src.execution.overlay_targets import current_regime_and_weights

        self.assertIs(ibkr_rebalance.current_regime_and_weights, current_regime_and_weights)
        self.assertIs(mr.current_regime_and_weights, current_regime_and_weights)


if __name__ == "__main__":
    unittest.main()
