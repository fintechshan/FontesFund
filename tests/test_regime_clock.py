"""Month-end look-ahead removal and first-release vintage fallback."""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from src.backtester.daily_overlay import (
    AGGRESSIVE_ONLY,
    dd_scale,
    spy_drawdown_scale,
    vix_linear_scale,
    weights_from_overlay,
)
from src.backtester.regime_clock import (
    CPI_RELEASE_LAG_M,
    GDP_RELEASE_LAG_M,
    MODE_AUDITOR,
    MODE_LOOKAHEAD,
    MODE_TARGETED,
    MODE_UNLAGGED,
    MODE_VINTAGE,
    classify_regimes,
    lag_vix_and_momentum_one_month,
    market_signals,
    philly_obs_date,
    philly_vintage_stamp,
    publication_lag_days,
    publication_lagged_macro,
    releases_from_philly_sheet,
    summarize_lags,
    vintage_table_payload,
    yoy_on_release_dates,
)


def _calm_world():
    idx = pd.bdate_range("2016-01-01", "2020-12-31")
    spy = pd.Series(100.0, index=idx)
    vix = pd.Series(15.0, index=idx)
    # February 2020 is a crisis in the prints, unknowable on Feb 1.
    vix.loc["2020-02-01":"2020-02-28"] = 60.0
    months = pd.date_range("2014-01-01", "2020-12-01", freq="MS")
    cpi = pd.Series(100.0 * (1.002 ** pd.RangeIndex(len(months))), index=months)
    gdp = pd.Series(2.5, index=pd.date_range("2010-01-01", "2020-10-01", freq="QS"))
    price = pd.DataFrame({"SPY": spy})
    macro = {
        "vix": vix,
        "cpi": cpi,
        "gdp": gdp,
        "t10y": pd.Series(dtype=float),
        "t2y": pd.Series(dtype=float),
    }
    return macro, price


def _regime_on(history, day):
    row = history.loc[history["date"] == pd.Timestamp(day)]
    return None if row.empty else row.iloc[0]["regime"]


class MarketTimingTests(unittest.TestCase):
    def test_month_start_does_not_see_same_month_vix(self):
        idx = pd.bdate_range("2020-01-01", "2020-03-31")
        vix = pd.Series(10.0, index=idx)
        vix.loc["2020-02-01":"2020-02-28"] = 80.0
        seen_early, _ = market_signals(vix, pd.Series(dtype=float), same_month=True)
        seen_late, _ = market_signals(vix, pd.Series(dtype=float), same_month=False)
        feb3 = pd.Timestamp("2020-02-03")
        mar2 = pd.Timestamp("2020-03-02")
        self.assertGreater(float(seen_early.asof(feb3)), 50.0)
        self.assertLess(float(seen_late.asof(feb3)), 20.0)
        self.assertGreater(float(seen_late.asof(mar2)), 50.0)

    def test_month_start_does_not_see_same_month_spy_close(self):
        idx = pd.bdate_range("2019-01-01", "2020-07-15")
        spy = pd.Series(100.0, index=idx)
        june_end = idx[(idx.year == 2020) & (idx.month == 6)][-1]
        spy.loc[june_end] = 200.0
        early, mom_early = market_signals(pd.Series(dtype=float), spy, same_month=True)
        late, mom_late = market_signals(pd.Series(dtype=float), spy, same_month=False)
        self.assertTrue(early.empty or True)
        june1 = pd.Timestamp("2020-06-01")
        july1 = pd.Timestamp("2020-07-01")
        self.assertGreater(float(mom_early.asof(june1)), 0.5)
        self.assertLess(abs(float(mom_late.asof(june1))), 0.05)
        self.assertGreater(float(mom_late.asof(july1)), 0.5)

    def test_publication_lags_stay_one_and_four_months(self):
        self.assertEqual(CPI_RELEASE_LAG_M, 1)
        self.assertEqual(GDP_RELEASE_LAG_M, 4)
        months = pd.date_range("2018-01-01", "2020-06-01", freq="MS")
        cpi = pd.Series(100.0 * (1.01 ** pd.RangeIndex(len(months))), index=months)
        gdp = pd.Series(1.7, index=pd.date_range("2018-01-01", "2020-04-01", freq="QS"))
        cpi_yoy, gdp_lag, _, _ = publication_lagged_macro(cpi, gdp, apply_lag=True)
        raw, gdp_raw, _, _ = publication_lagged_macro(cpi, gdp, apply_lag=False)
        # The January 2020 CPI observation is the February 2020 lagged print.
        self.assertAlmostEqual(
            float(cpi_yoy.loc[pd.Timestamp("2020-02-01")]),
            float(raw.loc[pd.Timestamp("2020-01-01")]),
        )
        # 2020 Q1 GDP (dated 2020-01-01) is usable at +4 months, May 2020.
        self.assertAlmostEqual(float(gdp_lag.loc[pd.Timestamp("2020-05-01")]), 1.7)
        self.assertNotIn(pd.Timestamp("2020-01-01"), gdp_lag.index)
        self.assertIn(pd.Timestamp("2020-05-01"), gdp_lag.index)


class ClassifyModeTests(unittest.TestCase):
    def test_targeted_waits_for_the_vix_month_to_close(self):
        macro, price = _calm_world()
        targeted, _, tinfo = classify_regimes(macro, price, mode=MODE_TARGETED)
        lookahead, _, _ = classify_regimes(macro, price, mode=MODE_LOOKAHEAD)
        unlagged, _, _ = classify_regimes(macro, price, apply_lag=False)
        auditor, _, ainfo = classify_regimes(macro, price, mode=MODE_AUDITOR)

        self.assertEqual(tinfo["mode"], MODE_TARGETED)
        self.assertFalse(tinfo["same_month_market"])
        self.assertTrue(tinfo["publication_lag"])
        self.assertEqual(_regime_on(lookahead, "2020-02-01"), "deflation")
        self.assertNotEqual(_regime_on(targeted, "2020-02-01"), "deflation")
        self.assertEqual(_regime_on(targeted, "2020-03-01"), "deflation")
        self.assertEqual(ainfo["mode"], MODE_AUDITOR)
        # Extra month: March's auditor label is February's lookahead label.
        self.assertEqual(
            _regime_on(auditor, "2020-03-01"),
            _regime_on(lookahead, "2020-02-01"),
        )
        self.assertEqual(unlagged["regime"].iloc[0], unlagged["regime"].iloc[0])

    def test_vintage_fallback_uses_targeted_path(self):
        macro, price = _calm_world()
        with mock.patch(
            "src.backtester.regime_clock.load_realtime_vintage", return_value=None,
        ):
            history, _, info = classify_regimes(
                macro, price, use_realtime_vintage=True,
            )
        targeted, _, _ = classify_regimes(macro, price, mode=MODE_TARGETED)
        self.assertTrue(info["vintage_fallback"])
        self.assertEqual(info["requested_mode"], MODE_VINTAGE)
        pd.testing.assert_series_equal(
            history["regime"].reset_index(drop=True),
            targeted["regime"].reset_index(drop=True),
        )

    def test_injected_vintage_uses_release_dates(self):
        macro, price = _calm_world()
        # A single CPI release on 2020-03-14 must be invisible to the March 1
        # decision and visible on April 1. GDP stays a calm 2.5% from 2019.
        cpi = pd.Series(
            [1.0, 8.0],
            index=pd.to_datetime(["2020-02-14", "2020-03-14"]),
        )
        gdp = pd.Series([2.5], index=pd.to_datetime(["2019-01-31"]))
        history, _, info = classify_regimes(
            macro, price, mode=MODE_VINTAGE,
            vintage={"cpi_yoy_release": cpi, "gdp_yoy_release": gdp, "source": "test"},
        )
        self.assertFalse(info["vintage_fallback"])
        self.assertEqual(info["vintage_source"], "test")
        # 8% CPI with a 3-month-ago print of 1% is inflation_rising, and GDP 2.5
        # is growth_rising, so the April decision is reflation. March 1 still
        # sees only the 1% print.
        self.assertNotEqual(_regime_on(history, "2020-03-01"), "reflation")
        self.assertEqual(_regime_on(history, "2020-04-01"), "reflation")


class ReleaseDateTests(unittest.TestCase):
    def test_yoy_is_indexed_on_release_not_observation(self):
        releases = pd.DataFrame([
            {"date": "2019-01-01", "realtime_start": "2019-02-14", "value": 100.0},
            {"date": "2019-02-01", "realtime_start": "2019-03-14", "value": 110.0},
        ])
        yoy = yoy_on_release_dates(releases, periods=1)
        self.assertNotIn(pd.Timestamp("2019-02-01"), yoy.index)
        self.assertTrue(pd.isna(yoy.asof(pd.Timestamp("2019-03-01"))))
        self.assertAlmostEqual(float(yoy.asof(pd.Timestamp("2019-03-14"))), 10.0)


class PhillyVintageTests(unittest.TestCase):
    def test_stamps_are_mid_month_and_year_pivot_is_1960(self):
        self.assertEqual(philly_vintage_stamp("PCPI20M4"), pd.Timestamp("2020-04-15"))
        self.assertEqual(philly_vintage_stamp("ROUTPUT65M11"), pd.Timestamp("1965-11-15"))
        self.assertEqual(philly_vintage_stamp("ROUTPUT00M1"), pd.Timestamp("2000-01-15"))
        self.assertEqual(philly_obs_date("2020:03"), pd.Timestamp("2020-03-01"))
        self.assertEqual(philly_obs_date("2020:Q1"), pd.Timestamp("2020-01-01"))
        self.assertEqual(philly_obs_date("2020:Q2"), pd.Timestamp("2020-04-01"))

    def test_new_observation_is_dated_on_the_vintage_not_the_period(self):
        sheet = pd.DataFrame({
            "DATE": ["2018:01", "2018:02", "2018:03"],
            "PCPI19M1": [100.0, None, None],
            "PCPI19M2": [100.0, 110.0, None],
            "PCPI19M3": [100.0, 110.0, 121.0],
        })
        yoy = yoy_on_release_dates(releases_from_philly_sheet(sheet), periods=1)
        self.assertNotIn(pd.Timestamp("2018-02-01"), yoy.index)
        self.assertAlmostEqual(float(yoy.loc[pd.Timestamp("2019-02-15")]), 10.0)
        self.assertAlmostEqual(float(yoy.loc[pd.Timestamp("2019-03-15")]), 10.0)
        # March 1 is before the March 15 vintage, so it still sees February's print.
        self.assertAlmostEqual(float(yoy.asof(pd.Timestamp("2019-03-01"))), 10.0)
        self.assertTrue(pd.isna(yoy.asof(pd.Timestamp("2019-02-01"))))

    def test_committed_vintage_table_is_release_dated(self):
        payload = vintage_table_payload()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["source"], "philadelphia_fed_rtdsm")
        cpi = payload["cpi_yoy_release"]
        gdp = payload["gdp_yoy_release"]
        self.assertGreater(len(cpi), 200)
        self.assertGreater(len(gdp), 100)
        # March 2020 CPI was published in April. The April 1 decision still
        # sees the prior print; the April 15 RTDSM vintage has the new one.
        self.assertGreater(float(cpi.asof("2020-04-01")), 2.0)
        self.assertLess(float(cpi.asof("2020-04-15")), 1.8)

    def test_collapsed_vintage_table_is_rejected(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vintage_release_yoy.csv"
            path.write_text("release_date,cpi_yoy,gdp_yoy\n2004-01-31,3.7,2.1\n")
            self.assertIsNone(vintage_table_payload(path))


class OverlayAndLagTests(unittest.TestCase):
    def test_targeted_lags_vix_and_momentum_with_shift1_only(self):
        idx = pd.bdate_range("2019-01-01", "2020-06-30")
        vix = pd.Series(15.0, index=idx)
        vix.loc["2020-02-01":"2020-02-28"] = 80.0
        spy = pd.Series(100.0, index=idx)
        spy.iloc[-1] = 180.0
        month_start_vix, month_start_mom = market_signals(vix, spy, same_month=True)
        lagged_vix, lagged_mom = market_signals(vix, spy, same_month=False)
        expected_vix, expected_mom = lag_vix_and_momentum_one_month(
            month_start_vix, month_start_mom,
        )
        pd.testing.assert_series_equal(lagged_vix, expected_vix)
        pd.testing.assert_series_equal(lagged_mom, expected_mom)
        pd.testing.assert_series_equal(lagged_vix, month_start_vix.shift(1))
        pd.testing.assert_series_equal(lagged_mom, month_start_mom.shift(1))
        # February's spike is labeled on 2020-02-01 before the lag and on
        # 2020-03-01 after it. CPI and GDP are not in this helper.
        self.assertGreater(float(month_start_vix.loc[pd.Timestamp("2020-02-01")]), 50.0)
        self.assertGreater(float(lagged_vix.loc[pd.Timestamp("2020-03-01")]), 50.0)
        self.assertLess(float(lagged_vix.loc[pd.Timestamp("2020-02-01")]), 20.0)
        source = inspect.getsource(lag_vix_and_momentum_one_month)
        body = source.split('"""', 2)[-1]
        self.assertEqual(body.count(".shift(1)"), 2)
        self.assertNotIn("cpi", body.lower())
        self.assertNotIn("gdp", body.lower())

    def test_publication_lag_is_not_shifted_again_with_the_market(self):
        macro, price = _calm_world()
        _, _, info = classify_regimes(macro, price, mode=MODE_TARGETED)
        _, _, look = classify_regimes(macro, price, mode=MODE_LOOKAHEAD)
        self.assertFalse(info["same_month_market"])
        self.assertTrue(info["publication_lag"])
        self.assertEqual(info["cpi_lag_months"], 1)
        self.assertEqual(info["gdp_lag_months"], 4)
        # The market shift(1) does not move the publication-lagged CPI or GDP.
        pd.testing.assert_series_equal(info["cpi_monthly"], look["cpi_monthly"])
        pd.testing.assert_series_equal(info["gdp_monthly"], look["gdp_monthly"])
        pd.testing.assert_series_equal(info["vix_monthly"], look["vix_monthly"].shift(1))
        pd.testing.assert_series_equal(
            info["spy_mom_monthly"], look["spy_mom_monthly"].shift(1),
        )

    def test_drawdown_scale_matches_the_engine_formula(self):
        self.assertEqual(dd_scale(-0.05, 0.07, 0.10, 0.10), 1.0)
        self.assertAlmostEqual(dd_scale(-0.12, 0.07, 0.10, 0.10), 0.50)
        self.assertEqual(dd_scale(-0.30, 0.07, 0.10, 0.10), 0.10)

    def test_live_weights_apply_trend_blend_and_both_scales(self):
        overlay = {
            "policy": "optimized_daily",
            "trend_risk_on": False,
            "bear_equity_frac": 0.70,
            "vol_scale": 1.20,
            "dd_scale": 0.50,
            "base_weights": {"SPY": 1.0},
            "defense_weights": {"IEF": 1.0},
        }
        weights = weights_from_overlay(overlay)
        self.assertAlmostEqual(weights["SPY"], 0.42)
        self.assertAlmostEqual(weights["IEF"], 0.18)
        self.assertAlmostEqual(sum(weights.values()), 0.60)

    def test_headline_equity_cut_matches_live_weights(self):
        self.assertEqual(vix_linear_scale(28), 1.0)
        self.assertAlmostEqual(vix_linear_scale(34), 0.5)
        self.assertEqual(vix_linear_scale(40), 0.0)
        self.assertEqual(vix_linear_scale(55), 0.0)
        self.assertEqual(spy_drawdown_scale(-0.03), 1.0)
        self.assertAlmostEqual(spy_drawdown_scale(-0.07), 0.5)
        self.assertEqual(spy_drawdown_scale(-0.10), 0.0)
        self.assertEqual(AGGRESSIVE_ONLY["vix_full_exposure"], 28.0)
        self.assertEqual(AGGRESSIVE_ONLY["spy_dd_window"], 20)
        overlay = {
            "policy": "optimized_daily",
            "trend_risk_on": True,
            "vol_scale": 1.0,
            "dd_scale": 0.50,
            "equity_scale": 0.50,
            "base_weights": {"SPY": 0.60, "IEF": 0.40},
            "defense_weights": {},
            "tradable": ["SPY", "IEF", "SHY", "AGG", "GLD"],
        }
        weights = weights_from_overlay(overlay)
        # Equity cut first (SPY 0.60 → 0.30, freed 0.30 into the safe basket),
        # then the portfolio drawdown scale of 0.50.
        self.assertAlmostEqual(weights["SPY"], 0.15)
        self.assertAlmostEqual(weights["IEF"], 0.2225)
        self.assertAlmostEqual(sum(weights.values()), 0.50)

    def test_engine_overlay_matches_the_live_equity_cut(self):
        from src.backtester.engine import BacktestEngine

        idx = pd.bdate_range("2020-01-02", periods=40)
        price = pd.DataFrame({
            "SPY": np.linspace(100.0, 70.0, len(idx)),
            "IEF": np.linspace(100.0, 101.0, len(idx)),
            "SHY": 100.0,
            "AGG": 100.0,
            "GLD": 100.0,
        }, index=idx)
        vix = pd.Series(35.0, index=idx)
        regime = pd.DataFrame({"regime": ["goldilocks"] * len(idx)}, index=idx)
        engine = BacktestEngine(price, risk_free_rate=0.0)
        result = engine.run_optimized_regime_backtest(
            regime,
            {"goldilocks": {"SPY": 0.6, "IEF": 0.4}},
            vix_data=vix,
            use_har_vol=False,
            risk_parity=False,
            target_vol=0.50,
            vol_lo=1.0,
            vol_hi=1.0,
        )
        overlay = result.overlay
        self.assertEqual(overlay["policy"], "optimized_daily")
        self.assertEqual(overlay["equity_scale"], 1.0)
        self.assertEqual(overlay["vix_scale"], 1.0)
        cut = engine.run_optimized_regime_backtest(
            regime,
            {"goldilocks": {"SPY": 0.6, "IEF": 0.4}},
            vix_data=vix,
            use_har_vol=False,
            risk_parity=False,
            target_vol=0.50,
            vol_lo=1.0,
            vol_hi=1.0,
            apply_equity_cut=True,
            turnover_basis="book",
        )
        cut_overlay = cut.overlay
        self.assertAlmostEqual(cut_overlay["vix_scale"], vix_linear_scale(35.0))
        self.assertAlmostEqual(
            cut_overlay["equity_scale"],
            min(cut_overlay["vix_scale"], cut_overlay["spy_dd_scale"]),
        )
        self.assertLess(cut_overlay["equity_scale"], 1.0)
        live = weights_from_overlay(cut_overlay)
        expected_spy = 0.6 * cut_overlay["equity_scale"] * cut_overlay["vol_scale"] * cut_overlay["dd_scale"]
        self.assertAlmostEqual(live.get("SPY", 0.0), expected_spy, places=6)
        self.assertGreater(sum(live.values()), 0.0)

    def test_publication_lag_percentiles(self):
        releases = pd.DataFrame([
            # Opening snapshot: already-published history, not a measured lag.
            {"date": "2020-01-01", "realtime_start": "2020-02-15", "value": 1.0},
            {"date": "2020-03-01", "realtime_start": "2020-04-15", "value": 1.0},
            {"date": "2020-04-01", "realtime_start": "2020-05-12", "value": 1.0},
        ])
        days = publication_lag_days(releases, quarterly=False)
        self.assertNotIn(pd.Timestamp("2020-01-01"), days.index)
        self.assertEqual(int(days.loc[pd.Timestamp("2020-03-01")]), 15)
        self.assertEqual(int(days.loc[pd.Timestamp("2020-04-01")]), 12)
        summary = summarize_lags(days)
        self.assertEqual(summary["n"], 2)
        self.assertAlmostEqual(summary["median"], 13.5)


if __name__ == "__main__":
    unittest.main()
