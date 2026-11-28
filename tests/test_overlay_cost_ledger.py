"""Locks the read-only final-position turnover formula. No network."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtester.overlay_cost_ledger import (  # noqa: E402
    FORMULA_ID,
    PRODUCTION_BPS,
    SENSITIVITY_BPS,
    build_overlay_cost_ledger,
    embedded_cost,
    final_position_weights,
    one_way_turnover,
)


def _load_weekly():
    path = ROOT / "scripts" / "weekly_audit_snapshot.py"
    spec = importlib.util.spec_from_file_location("weekly_audit_snapshot_ledger", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FormulaTests(unittest.TestCase):
    def test_one_way_is_half_l1_and_first_row_is_zero(self):
        weights = pd.DataFrame(
            {"SPY": [1.0, 0.5, 0.5], "IEF": [0.0, 0.5, 0.0]},
            index=pd.bdate_range("2020-01-02", periods=3),
        )
        turnover = one_way_turnover(weights)
        self.assertEqual(float(turnover.iloc[0]), 0.0)
        self.assertAlmostEqual(float(turnover.iloc[1]), 0.5)
        self.assertAlmostEqual(float(turnover.iloc[2]), 0.25)

    def test_scale_change_is_missed_when_the_book_does_not_trade(self):
        index = pd.bdate_range("2020-01-02", periods=2)
        book = pd.DataFrame({"SPY": [1.0, 1.0]}, index=index)
        vol = pd.Series([1.0, 1.5], index=index)
        dd = pd.Series([1.0, 1.0], index=index)
        final = final_position_weights(book, vol, dd)
        self.assertAlmostEqual(float(final["SPY"].iloc[1]), 1.5)
        one_way = one_way_turnover(final)
        self.assertAlmostEqual(float(one_way.iloc[1]), 0.25)
        blend = pd.Series(1.0, index=index)
        official = pd.Series([0.0, 0.01], index=index)
        ledger = build_overlay_cost_ledger(
            w_book=book,
            w_base=book,
            vol_scale=vol,
            dd_scale=dd,
            blend=blend,
            official_returns=official,
            turnover_basis="legacy",
            apply_equity_cut=False,
            transaction_cost_bps=5.0,
            bear_equity_frac=0.70,
        )
        self.assertEqual(ledger["formula_id"], FORMULA_ID)
        self.assertFalse(ledger["changes_official_equity"])
        self.assertFalse(ledger["changes_live_positions"])
        self.assertEqual(ledger["bps_assumptions"]["production_one_way_bps"], PRODUCTION_BPS)
        self.assertEqual(ledger["bps_assumptions"]["sensitivity_one_way_bps"], SENSITIVITY_BPS)
        cost_5 = 0.25 * 5.0 / 10_000.0
        cost_8 = 0.25 * 8.0 / 10_000.0
        missed_5 = ledger["vs_official_unadjusted"]["at_5bps"]
        missed_8 = ledger["vs_official_unadjusted"]["at_8bps"]
        # Legacy W_base does not trade, so the whole scale turnover is missed.
        self.assertAlmostEqual(missed_5["sum_of_daily_drag"], cost_5)
        self.assertAlmostEqual(missed_8["sum_of_daily_drag"], cost_8)
        self.assertGreater(missed_5["cagr_drag"], 0.0)
        self.assertGreater(missed_8["cagr_drag"], missed_5["cagr_drag"])
        # Official returns passed in are not rewritten.
        self.assertEqual(list(official), [0.0, 0.01])

    def test_legacy_embedded_cost_is_scaled_sleeve_turnover(self):
        index = pd.bdate_range("2020-01-02", periods=2)
        base = pd.DataFrame({"SPY": [1.0, 0.0], "IEF": [0.0, 1.0]}, index=index)
        book = base.copy()
        vol = pd.Series([1.0, 2.0], index=index)
        dd = pd.Series([1.0, 0.5], index=index)
        blend = pd.Series([1.0, 0.7], index=index)
        embedded = embedded_cost(
            turnover_basis="legacy",
            w_base=base,
            w_book=book,
            blend=blend,
            vol_scale=vol,
            dd_scale=dd,
            transaction_cost_bps=5.0,
        )
        # Day 1 one-way sleeve turnover is 1. Embedded = 0.7 * 1 * 5bps * 2 * 0.5.
        self.assertAlmostEqual(float(embedded.iloc[0]), 0.0)
        self.assertAlmostEqual(float(embedded.iloc[1]), 0.7 * (5.0 / 10_000.0) * 2.0 * 0.5)
        final = final_position_weights(book, vol, dd)
        # [1, 0] -> [0, 1.0] because 2 * 0.5 * IEF.
        self.assertAlmostEqual(float(final["IEF"].iloc[1]), 1.0)
        one_way = float(one_way_turnover(final).iloc[1])
        self.assertAlmostEqual(one_way, 1.0)
        official = pd.Series(0.0, index=index)
        ledger = build_overlay_cost_ledger(
            w_book=book,
            w_base=base,
            vol_scale=vol,
            dd_scale=dd,
            blend=blend,
            official_returns=official,
        )
        # cost(5) = 1.0 * 5bps; embedded is smaller, so missed is positive.
        self.assertAlmostEqual(
            ledger["vs_official_unadjusted"]["at_5bps"]["sum_of_daily_drag"],
            one_way * (5.0 / 10_000.0) - float(embedded.iloc[1]),
        )

    def test_book_basis_still_misses_scale_turnover(self):
        index = pd.bdate_range("2020-01-02", periods=2)
        book = pd.DataFrame({"SPY": [1.0, 1.0]}, index=index)
        vol = pd.Series([1.0, 1.5], index=index)
        dd = pd.Series(1.0, index=index)
        blend = pd.Series(1.0, index=index)
        ledger = build_overlay_cost_ledger(
            w_book=book,
            w_base=book,
            vol_scale=vol,
            dd_scale=dd,
            blend=blend,
            official_returns=pd.Series(0.0, index=index),
            turnover_basis="book",
        )
        # Book turnover is 0, so embedding book cost does not pay for the scale change.
        still = ledger["still_uncosted_if_book_basis"]["at_5bps"]["sum_of_daily_drag"]
        self.assertAlmostEqual(still, 0.25 * 5.0 / 10_000.0)
        self.assertAlmostEqual(ledger["vs_official_unadjusted"]["at_5bps"]["sum_of_daily_drag"], still)


class EngineAttachmentTests(unittest.TestCase):
    def test_ledger_is_attached_without_changing_the_overlay_contract(self):
        from src.backtester.engine import BacktestEngine

        index = pd.bdate_range("2020-01-02", periods=40)
        price = pd.DataFrame({
            "SPY": np.linspace(100.0, 110.0, len(index)),
            "IEF": np.linspace(100.0, 101.0, len(index)),
            "SHY": 100.0,
            "AGG": 100.0,
            "GLD": 100.0,
        }, index=index)
        regime = pd.DataFrame({"regime": ["goldilocks"] * len(index)}, index=index)
        engine = BacktestEngine(price, risk_free_rate=0.0)
        result = engine.run_optimized_regime_backtest(
            regime,
            {"goldilocks": {"SPY": 0.6, "IEF": 0.4}},
            use_har_vol=False,
            risk_parity=False,
            target_vol=0.50,
            vol_lo=1.0,
            vol_hi=1.0,
            transaction_cost_bps=5.0,
        )
        self.assertEqual(result.overlay["policy"], "optimized_daily")
        self.assertEqual(result.overlay["equity_scale"], 1.0)
        self.assertIn("base_weights", result.overlay)
        self.assertIsInstance(result.cost_ledger, dict)
        self.assertEqual(result.cost_ledger["formula_id"], FORMULA_ID)
        self.assertFalse(result.cost_ledger["changes_official_equity"])
        self.assertEqual(result.cost_ledger["turnover_basis"], "legacy")
        self.assertFalse(result.cost_ledger["apply_equity_cut"])
        self.assertFalse(hasattr(result, "cost_inputs"))
        official_cagr = result.cost_ledger["vs_official_unadjusted"]["at_5bps"]["official_cagr"]
        self.assertAlmostEqual(official_cagr, result.annual_return, places=3)

    def test_production_params_are_unchanged(self):
        from config.regime_rules import STRATEGY_PARAMS

        self.assertEqual(STRATEGY_PARAMS["dd_trigger"], 0.07)
        self.assertEqual(STRATEGY_PARAMS["vol_hi"], 1.50)
        self.assertEqual(STRATEGY_PARAMS["vix_gate_level"], 20.0)
        self.assertEqual(STRATEGY_PARAMS["transaction_cost_bps"], 5.0)
        self.assertTrue(STRATEGY_PARAMS["use_har_vol"])
        self.assertNotIn("turnover_basis", STRATEGY_PARAMS)
        self.assertNotIn("apply_equity_cut", STRATEGY_PARAMS)


class Section7Tests(unittest.TestCase):
    def test_ledger_fail_does_not_change_overall_status(self):
        module = _load_weekly()
        module.load_overlay_cost_ledger = lambda path=None: {
            "status": "FAIL",
            "diagnostic_only": True,
            "changes_official_equity": False,
        }
        snap = module.build_snapshot(refresh=False)
        self.assertEqual(snap["overlay_cost_ledger"]["status"], "FAIL")
        bt = snap["backtest_consistency"]["status"]
        pack = snap["strategy_packs"]["status"]
        fresh = snap["freshness"]["status"]
        if bt == "FAIL" or pack == "FAIL":
            expected = "FAIL"
        elif fresh == "WARNING" or bt == "WARNING" or pack == "WARNING":
            expected = "WARNING"
        else:
            expected = "PASS"
        self.assertEqual(snap["overall_status"], expected)

    def test_section_renders_the_formula(self):
        from src.dashboard.auditor import build_weekly_audit_section

        section = build_weekly_audit_section({
            "overall_status": "PASS",
            "generated_at": "2026-11-28 00:00 UTC",
            "freshness": {"status": "PASS", "backtest_end": "2026-10-30"},
            "backtest_consistency": {
                "status": "PASS",
                "reported_cagr": 0.131,
                "cagr_diff_bps": 0.0,
                "reported_total_return": 1.0,
                "total_diff_bps": 0.0,
                "reported_max_dd": 0.14,
            },
            "live_market_check": {},
            "overlay_cost_ledger": {
                "status": "computed",
                "as_of": "2026-10-30",
                "turnover_basis": "legacy",
                "apply_equity_cut": False,
                "formula": "w_final = vol_scale * dd_scale * w_book",
                "formula_id": FORMULA_ID,
                "diagnostic_only": True,
                "changes_official_equity": False,
                "bps_assumptions": {"embedded_bps": 5.0},
                "vs_official_unadjusted": {
                    "at_5bps": {
                        "official_cagr": 0.131,
                        "adjusted_cagr": 0.129,
                        "cagr_drag_bps": 20.0,
                        "total_return_drag_bps": 40.0,
                        "arithmetic_annual_drag_bps": 15.0,
                    },
                    "at_8bps": {
                        "official_cagr": 0.131,
                        "adjusted_cagr": 0.128,
                        "cagr_drag_bps": 30.0,
                        "total_return_drag_bps": 50.0,
                        "arithmetic_annual_drag_bps": 24.0,
                    },
                },
            },
        })
        blob = "\n".join(_texts(section))
        self.assertIn("7b. Overlay turnover cost ledger", blob)
        self.assertIn("DIAGNOSTIC ONLY", blob)
        self.assertIn("w_final = vol_scale * dd_scale * w_book", blob)
        self.assertIn("2026-10-30", blob)
        self.assertIn("20.0 bps", blob)
        self.assertIn("Overall Status: PASS", blob)
        self.assertNotIn("HEADLINE_GATE_RESET", blob)


def _texts(node):
    acc = []

    def _walk(item):
        if item is None or isinstance(item, (int, float, bool)):
            return
        if isinstance(item, str):
            acc.append(item)
            return
        if isinstance(item, dict):
            for value in item.values():
                _walk(value)
            return
        if isinstance(item, (list, tuple)):
            for value in item:
                _walk(value)
            return
        _walk(getattr(item, "children", None))

    _walk(node)
    return acc


if __name__ == "__main__":
    unittest.main()
