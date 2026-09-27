"""US entry points share one targeted clock, month by month."""
from __future__ import annotations

import pickle
import unittest
from pathlib import Path

import pandas as pd

from src.backtester.regime_clock import (
    CPI_RELEASE_LAG_M,
    GDP_RELEASE_LAG_M,
    MODE_LOOKAHEAD,
    MODE_TARGETED,
    classify_regimes,
)

ROOT = Path(__file__).resolve().parent.parent


class ClassifierParityTests(unittest.TestCase):
    def test_entrypoints_call_targeted_mode_only(self):
        backtest = (ROOT / "run_backtest.py").read_text()
        dashboard = (ROOT / "run_dashboard.py").read_text()
        self.assertNotIn("def classify_regimes", backtest)
        self.assertNotIn("def classify_regimes", dashboard)
        self.assertIn("classify_regimes(\n    macro_for_clock, price_data, mode=MODE_TARGETED,", backtest)
        self.assertIn("classify_regimes(macro, price_data, mode=MODE_TARGETED)", dashboard)
        self.assertIn("classify_regimes(\n                            new_macro, new_price, mode=MODE_TARGETED,", dashboard)

    def test_dashboard_and_backtest_histories_agree(self):
        price_path = ROOT / "data" / "cache" / "price_data.csv"
        macro_path = ROOT / "data" / "cache" / "macro_data.pkl"
        if not price_path.exists() or not macro_path.exists():
            self.skipTest("price/macro cache not present")
        price = pd.read_csv(price_path, index_col=0, parse_dates=True)
        with open(macro_path, "rb") as handle:
            macro = pickle.load(handle)

        # run_backtest.py and the dashboard startup both pass MODE_TARGETED.
        # The dashboard refresh path uses the same explicit mode.
        backtest_hist, _, backtest_info = classify_regimes(
            macro, price, mode=MODE_TARGETED,
        )
        dashboard_hist, _, dashboard_info = classify_regimes(
            macro, price, mode=MODE_TARGETED,
        )
        refresh_hist, _, _ = classify_regimes(macro, price)

        merged = backtest_hist.merge(
            dashboard_hist, on="date", suffixes=("_backtest", "_dashboard"),
        )
        disagree = merged[merged["regime_backtest"] != merged["regime_dashboard"]]
        self.assertEqual(len(disagree), 0)
        self.assertEqual(len(merged), len(backtest_hist))
        self.assertTrue(backtest_hist["regime"].equals(refresh_hist["regime"]))

        self.assertEqual(backtest_info["mode"], MODE_TARGETED)
        self.assertEqual(dashboard_info["mode"], MODE_TARGETED)
        self.assertFalse(backtest_info["same_month_market"])
        self.assertTrue(backtest_info["publication_lag"])
        self.assertEqual(backtest_info["cpi_lag_months"], CPI_RELEASE_LAG_M)
        self.assertEqual(backtest_info["gdp_lag_months"], GDP_RELEASE_LAG_M)
        self.assertEqual(CPI_RELEASE_LAG_M, 1)
        self.assertEqual(GDP_RELEASE_LAG_M, 4)

        lookahead, _, look_info = classify_regimes(macro, price, mode=MODE_LOOKAHEAD)
        self.assertTrue(look_info["same_month_market"])
        self.assertTrue(look_info["publication_lag"])
        both = backtest_hist.merge(lookahead, on="date", suffixes=("_targeted", "_look"))
        # The month-end rule changes some months. CPI/GDP lags stay on both.
        self.assertGreater((both["regime_targeted"] != both["regime_look"]).sum(), 0)


if __name__ == "__main__":
    unittest.main()
