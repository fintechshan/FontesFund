"""CDN auditor rows fail the same way a drifted US book would."""
from __future__ import annotations

import unittest

import pandas as pd

from src.dashboard.app import (
    CDN_BENCH_COLUMN,
    CDN_YEAR_COLUMN,
    build_auditor_tab,
    build_cdn_portfolio_tab,
    cdn_benchmark_year_returns,
    cdn_monthly_heatmap,
    compounded_year_returns,
)
from src.dashboard.auditor import run_independent_audit
from src.dashboard.cdn_audit import (
    CHECK_ARTIFACT,
    CHECK_CLOCK,
    CHECK_CONSISTENCY,
    CHECK_HEATMAP,
    CHECK_PATHS,
    CHECK_PRICE,
    CDN_CHECKS,
    audit_cdn_book,
)
from src.backtester.cdn_clock import cdn_live_regime, prove_cdn_clock
from tests.test_backtest_default import _fixture, _find_id, _texts
from tests.test_backtest_heatmap_spx import _cell, _heatmap


def _by_name(checks):
    return {row["check"]: row for row in checks}


class CdnClockProofTests(unittest.TestCase):
    def test_targeted_clock_is_not_lookahead(self):
        proof = prove_cdn_clock()
        self.assertTrue(proof["ok"], proof)
        self.assertEqual(proof["cpi_lag_months"], 1)
        self.assertEqual(proof["gdp_lag_months"], 4)
        self.assertEqual(proof["momentum_column"], "VFV.TO")
        self.assertFalse(proof["same_month_market"])

    def test_missing_prices_fall_back_explicitly(self):
        regime, source, history = cdn_live_regime({}, pd.DataFrame(), "goldilocks")
        self.assertEqual(regime, "goldilocks")
        self.assertEqual(source, "us_fallback")
        self.assertEqual(len(history), 0)


class CdnAuditTests(unittest.TestCase):
    def test_published_files_pass_consistency_heatmap_and_clock(self):
        checks = _by_name(audit_cdn_book())
        for name in CDN_CHECKS:
            self.assertIn(name, checks)
        self.assertEqual(checks[CHECK_CONSISTENCY]["status"], "PASS", checks[CHECK_CONSISTENCY]["desc"])
        self.assertEqual(checks[CHECK_HEATMAP]["status"], "PASS", checks[CHECK_HEATMAP]["desc"])
        self.assertEqual(checks[CHECK_CLOCK]["status"], "PASS", checks[CHECK_CLOCK]["desc"])
        self.assertEqual(checks[CHECK_ARTIFACT]["status"], "PASS", checks[CHECK_ARTIFACT]["desc"])
        self.assertIn("TSX60", checks[CHECK_HEATMAP]["desc"])
        # No TSX cache in git. The row is present and failing, not omitted.
        self.assertEqual(checks[CHECK_PRICE]["status"], "FAIL")
        self.assertIn("missing", checks[CHECK_PRICE]["desc"].lower())
        # Path table is written by scripts/run_cdn_backtest.py. Until that file
        # exists the row warns. It does not disappear.
        self.assertEqual(checks[CHECK_PATHS]["status"], "WARNING")
        self.assertIn("not loaded", checks[CHECK_PATHS]["desc"].lower())

    def test_prices_behind_the_us_sample_fail(self):
        idx_us = pd.bdate_range("2026-09-01", "2026-09-25")
        idx_cdn = pd.bdate_range("2026-08-01", "2026-09-01")
        checks = _by_name(audit_cdn_book(
            prices=pd.DataFrame({"VFV.TO": 1.0}, index=idx_cdn),
            us_prices=pd.DataFrame({"SPY": 1.0}, index=idx_us),
            load_defaults=True,
        ))
        self.assertEqual(checks[CHECK_PRICE]["status"], "FAIL")
        self.assertIn("behind", checks[CHECK_PRICE]["desc"])

    def test_curve_behind_the_us_book_fails(self):
        us = pd.Series([1.0, 1.1], index=pd.to_datetime(["2026-09-25", "2026-10-20"]))
        checks = _by_name(audit_cdn_book(us_equity=us))
        self.assertEqual(checks[CHECK_ARTIFACT]["status"], "FAIL", checks[CHECK_ARTIFACT]["desc"])

    def test_lookahead_published_book_fails(self):
        honesty = pd.DataFrame(
            {"cagr": [0.1203, 0.20, 0.11, 0.18, 0.10]},
            index=["B_targeted", "A_lookahead", "C_vintage", "unlagged", "auditor_extra"],
        )
        # Published file is ~12.03%, which matches A here and not B.
        honesty.loc["A_lookahead", "cagr"] = 0.1203
        honesty.loc["B_targeted", "cagr"] = 0.09
        checks = _by_name(audit_cdn_book(honesty=honesty))
        self.assertEqual(checks[CHECK_PATHS]["status"], "FAIL")
        self.assertIn("lookahead", checks[CHECK_PATHS]["desc"].lower())

    def test_vintage_above_targeted_fails(self):
        honesty = pd.DataFrame(
            {"cagr": [0.1203, 0.14, 0.15, 0.16, 0.11]},
            index=["B_targeted", "A_lookahead", "C_vintage", "unlagged", "auditor_extra"],
        )
        checks = _by_name(audit_cdn_book(honesty=honesty))
        self.assertEqual(checks[CHECK_PATHS]["status"], "FAIL")
        self.assertIn("Vintage", checks[CHECK_PATHS]["desc"])

    def test_honest_paths_pass(self):
        honesty = pd.DataFrame(
            {"cagr": [0.1203, 0.1300, 0.1100, 0.1400, 0.1000]},
            index=["B_targeted", "A_lookahead", "C_vintage", "unlagged", "auditor_extra"],
        )
        checks = _by_name(audit_cdn_book(honesty=honesty))
        self.assertEqual(checks[CHECK_PATHS]["status"], "PASS", checks[CHECK_PATHS]["desc"])

    def test_optimistic_clock_config_fails(self):
        checks = _by_name(audit_cdn_book(clock_config={
            "mode": "lookahead",
            "cpi_lag_months": 0,
            "gdp_lag_months": 0,
            "momentum": "SPY",
            "same_month_market": True,
            "publication_lag": True,
        }))
        self.assertEqual(checks[CHECK_CLOCK]["status"], "FAIL")

    def test_missing_benchmark_fails_the_heatmap_check(self):
        monthly = pd.Series([0.01, 0.02], index=pd.to_datetime(["2019-01-31", "2019-02-28"]))
        checks = _by_name(audit_cdn_book(
            monthly=monthly,
            benchmark=pd.Series(dtype=float),
            cdn_equity=pd.Series([1.0, 1.01], index=pd.to_datetime(["2019-01-02", "2019-02-28"])),
            load_defaults=False,
        ))
        self.assertEqual(checks[CHECK_HEATMAP]["status"], "FAIL")

    def test_independent_audit_lists_every_cdn_check(self):
        audit = run_independent_audit(
            pd.DataFrame(), {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        )
        names = [row["check"] for row in audit["data_checks"]]
        for name in CDN_CHECKS:
            self.assertIn(name, names)
        self.assertEqual(
            [row["check"] for row in audit["cdn_checks"]],
            list(CDN_CHECKS),
        )


class CdnHeatmapTests(unittest.TestCase):
    def test_strategy_year_sits_beside_tsx60(self):
        monthly = pd.Series(
            [0.10, -0.05],
            index=pd.to_datetime(["2019-01-31", "2019-06-28"]),
        )
        prices = pd.Series(
            [100.0, 110.0],
            index=pd.to_datetime(["2019-01-02", "2019-06-28"]),
        )
        equity = pd.Series(
            [1.0, 1.1, 1.045],
            index=pd.to_datetime(["2019-01-02", "2019-01-31", "2019-06-28"]),
        )
        data = {"cdn_benchmark": prices, "cdn_equity_curve": equity}
        fig = cdn_monthly_heatmap(monthly, data)
        trace = fig.data[0]
        self.assertEqual(list(trace.x)[-2:], [CDN_YEAR_COLUMN, CDN_BENCH_COLUMN])
        self.assertEqual(fig.layout.title.text, "Monthly Returns Heatmap (%) — Strategy vs TSX60")
        strat_z, strat_text = _cell(trace, 2019, CDN_YEAR_COLUMN)
        expected = float(compounded_year_returns(monthly).loc[2019])
        self.assertAlmostEqual(strat_z, expected, places=6)
        self.assertEqual(strat_text, f"{strat_z:+.1f}%")
        bench_z, bench_text = _cell(trace, 2019, CDN_BENCH_COLUMN)
        # Sample ends 2019-06-28, so the December print is outside the CDN window.
        clipped = float(cdn_benchmark_year_returns(prices, equity).loc[2019])
        self.assertAlmostEqual(bench_z, clipped, places=4)
        self.assertEqual(bench_text, f"{bench_z:+.1f}%")
        self.assertGreater(bench_z, 0.0)

    def test_tab_labels_strategy_and_tsx60(self):
        data = _fixture()
        monthly = pd.Series(
            [0.01, -0.02],
            index=pd.to_datetime(["2020-01-31", "2020-02-28"]),
        )
        data["cdn_monthly_returns"] = monthly
        data["cdn_equity_curve"] = pd.Series(
            [1.0, 1.01, 0.99],
            index=pd.to_datetime(["2020-01-02", "2020-01-31", "2020-02-28"]),
        )
        data["cdn_benchmark"] = pd.Series(
            [50.0, 55.0],
            index=pd.to_datetime(["2020-01-02", "2020-02-28"]),
        )
        tab = build_cdn_portfolio_tab(data)
        fig = _heatmap(tab)[0]
        self.assertEqual(list(fig.data[0].x)[-2:], ["Strategy", "TSX60"])
        blob = " ".join(_texts(tab))
        self.assertIn("Strategy vs TSX60", blob)
        self.assertIn("XIU.TO", blob)
        self.assertIn("S&P/TSX 60", blob)

    def test_auditor_page_shows_the_cdn_table(self):
        data = _fixture()
        data["audit"]["cdn_checks"] = audit_cdn_book()
        tab = build_auditor_tab(data)
        table = _find_id(tab, "cdn-audit-table")
        self.assertIsNotNone(table)
        names = [row["Check"] for row in table.data]
        for name in CDN_CHECKS:
            self.assertIn(name, names)
        blob = "\n".join(_texts(tab))
        self.assertIn("path A/B/C", blob)
        self.assertIn("XIU.TO", blob)


if __name__ == "__main__":
    unittest.main()
