"""Canadian classifier uses the targeted month-end clock, not a tenth copy."""
from __future__ import annotations

import unittest

import pandas as pd

from config.cdn_regime_rules import CDN_UNIVERSE
from scripts.run_cdn_backtest import classify_regimes
from src.backtester.regime_clock import (
    _classify_one,
    market_signals,
    publication_lagged_macro,
)
from config.regime_rules import REGIME_VIX_DEFENSIVE


def _book(index):
    frame = pd.DataFrame(
        {ticker: 100.0 + pd.Series(range(len(index)), index=index) for ticker in CDN_UNIVERSE},
        index=index,
    )
    return frame


class CdnClockTests(unittest.TestCase):
    def test_vix_spike_is_visible_the_next_month_only(self):
        index = pd.bdate_range("2012-01-02", "2012-04-30")
        prices = _book(index)
        vix = pd.Series(12.0, index=index)
        vix.loc["2012-01-03":"2012-01-31"] = 80.0
        cpi = pd.Series(100.0, index=pd.date_range("2010-01-01", "2012-04-01", freq="MS"))
        gdp = pd.Series(2.5, index=pd.date_range("2010-01-01", "2012-04-01", freq="QS"))
        macro = {"vix": vix, "cpi": cpi, "gdp": gdp}

        history = classify_regimes(macro, prices, momentum_ticker="VFV.TO")
        by_month = dict(zip(history["date"], history["regime"]))
        january = pd.Timestamp("2012-02-01")
        # date_range from the first price day (2012-01-02) starts at February.
        self.assertIn(january, by_month)
        self.assertEqual(by_month[january], "deflation")
        march = pd.Timestamp("2012-03-01")
        self.assertNotEqual(by_month[march], "deflation")

    def test_matches_shared_clock_and_not_same_month_vix(self):
        index = pd.bdate_range("2013-01-02", "2014-06-30")
        prices = _book(index)
        vix = pd.Series(14.0, index=index)
        vix.loc["2013-06-03":"2013-06-28"] = 45.0
        cpi = pd.Series(
            [100 * (1.002 ** i) for i in range(48)],
            index=pd.date_range("2011-01-01", periods=48, freq="MS"),
        )
        gdp = pd.Series(2.2, index=pd.date_range("2011-01-01", "2014-06-01", freq="QS"))
        macro = {"vix": vix, "cpi": cpi, "gdp": gdp}

        history = classify_regimes(macro, prices)
        _cpi, _gdp, cpi_mo, gdp_mo = publication_lagged_macro(cpi, gdp, apply_lag=True)
        vix_me, mom_me = market_signals(vix, prices["VFV.TO"], same_month=False)
        vix_ms, mom_ms = market_signals(vix, prices["VFV.TO"], same_month=True)

        targeted = []
        lookahead = []
        for date in history["date"]:
            targeted.append(_classify_one(
                date, gdp_mo, mom_me, cpi_mo, vix_me, REGIME_VIX_DEFENSIVE,
            ))
            lookahead.append(_classify_one(
                date, gdp_mo, mom_ms, cpi_mo, vix_ms, REGIME_VIX_DEFENSIVE,
            ))
        self.assertEqual(list(history["regime"]), targeted)
        self.assertNotEqual(targeted, lookahead)


if __name__ == "__main__":
    unittest.main()
