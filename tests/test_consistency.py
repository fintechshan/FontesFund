"""Reported CAGR, equity curve, and heatmap are one series."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.backtester.consistency import verify_series


def _book():
    idx = pd.bdate_range("2010-01-04", periods=80)
    rng = np.random.default_rng(7)
    returns = pd.Series(rng.normal(0.0005, 0.01, len(idx)), index=idx)
    # An intra-month crash that is gone by month-end. Daily max DD is deeper
    # than the month-end snapshot.
    crash = idx[12]
    recover = idx[13]
    returns.loc[crash] = -0.12
    returns.loc[recover] = 0.12 / 0.88 - 1e-6
    equity = (1.0 + returns).cumprod()
    monthly = returns.resample("ME").apply(lambda x: (1.0 + x).prod() - 1.0)
    total = float(equity.iloc[-1] - 1.0)
    cagr = (1.0 + total) ** (1.0 / (len(returns) / 252.0)) - 1.0
    daily_dd = float(abs((equity / equity.cummax() - 1.0).min()))
    return equity, monthly, total, cagr, daily_dd


class ConsistencyTests(unittest.TestCase):
    def test_same_series_passes_and_records_the_sampling_gap(self):
        equity, monthly, total, cagr, daily_dd = _book()
        report = verify_series(cagr, total, daily_dd, equity, monthly)
        self.assertTrue(report.ok, report.text())
        self.assertLess(report.details["gap_heatmap_total"], 1e-9)
        self.assertGreater(report.details["max_dd_sampling_gap"], 0.01)
        self.assertIn("year-count gap", report.text())
        self.assertIn("daily peak-to-trough", report.text())

    def test_foreign_heatmap_fails(self):
        equity, monthly, total, cagr, daily_dd = _book()
        foreign = monthly * 0.0 + 0.05
        report = verify_series(cagr, total, daily_dd, equity, foreign)
        self.assertFalse(report.ok)
        self.assertTrue(any(line.startswith("heatmap_total") for line in report.messages))

    def test_missing_heatmap_fails(self):
        equity, _monthly, total, cagr, daily_dd = _book()
        report = verify_series(cagr, total, daily_dd, equity, None)
        self.assertFalse(report.ok)
        self.assertIn("monthly heatmap series is missing", report.messages)


class SavedRunTests(unittest.TestCase):
    def test_published_headline_files_are_one_series(self):
        from pathlib import Path

        from src.backtester.consistency import verify_files

        root = Path(__file__).resolve().parents[1] / "data" / "backtest_results"
        report = verify_files(
            root / "20yr_comparison.csv",
            root / "aggressive_equity_curve.csv",
            root / "aggressive_monthly_returns.csv",
        )
        self.assertTrue(report.ok, report.text())


if __name__ == "__main__":
    unittest.main()
