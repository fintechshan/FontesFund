"""Backtest heatmap: strategy year beside the S&P 500 year, same compound."""
from __future__ import annotations

import unittest

import pandas as pd

from src.dashboard.app import (
    BACKTEST_PATH_AUDITOR,
    BACKTEST_PATH_LOOKAHEAD,
    BACKTEST_PATH_TARGETED,
    BACKTEST_SPX_COLUMN,
    BACKTEST_YEAR_COLUMN,
    backtest_monthly_heatmap,
    backtest_spx_year_returns,
    build_backtest_path_body,
    compounded_year_returns,
    make_monthly_heatmap,
    monthly_for_path,
    spx_calendar_year_returns,
)
from tests.test_backtest_default import _fixture, _texts


def _heatmap(node):
    found = []

    def walk(item):
        if item is None or isinstance(item, (str, dict)):
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                walk(child)
            return
        if item.__class__.__name__ == 'Graph' and getattr(item, 'figure', None) is not None:
            data = getattr(item.figure, 'data', None) or []
            if data and getattr(data[0], 'type', None) == 'heatmap':
                found.append(item.figure)
        walk(getattr(item, 'children', None))

    walk(node)
    return found


def _cell(trace, year, label):
    years = [int(value) for value in trace.y]
    yi = years.index(year)
    xi = list(trace.x).index(label)
    return float(trace.z[yi][xi]), trace.text[yi][xi]


class CompoundedYearTests(unittest.TestCase):
    def test_full_year_is_the_product_of_its_months(self):
        monthly = pd.Series(
            [0.10, -0.05, 0.02],
            index=pd.to_datetime(['2019-01-31', '2019-06-30', '2019-12-31']),
        )
        got = compounded_year_returns(monthly)
        expected = ((1.10 * 0.95 * 1.02) - 1.0) * 100.0
        self.assertAlmostEqual(float(got.loc[2019]), expected, places=8)

    def test_partial_year_compounds_only_the_months_present(self):
        # Same rule as the strategy Year cell: two months, not an annualized rate.
        monthly = pd.Series(
            [0.10, 0.10],
            index=pd.to_datetime(['2026-01-30', '2026-02-27']),
        )
        got = float(compounded_year_returns(monthly).loc[2026])
        self.assertAlmostEqual(got, 21.0, places=8)
        annualized = ((1.21 ** (12 / 2)) - 1.0) * 100.0
        self.assertGreater(abs(got - annualized), 1.0)

    def test_years_stay_separate(self):
        monthly = pd.Series(
            [0.10, -0.20],
            index=pd.to_datetime(['2008-12-31', '2009-12-31']),
        )
        got = compounded_year_returns(monthly)
        self.assertAlmostEqual(float(got.loc[2008]), 10.0, places=8)
        self.assertAlmostEqual(float(got.loc[2009]), -20.0, places=8)


class SpxCalendarYearTests(unittest.TestCase):
    def test_adj_close_full_and_partial_years_match_price_ratios(self):
        prices = pd.Series(
            [100.0, 80.0, 88.0],
            index=pd.to_datetime(['2007-12-31', '2008-12-31', '2009-06-30']),
        )
        got = spx_calendar_year_returns(prices, equity_curve=False)
        # 2008 is a full calendar year. 2009 stops in June: 88/80 - 1, not annualized.
        self.assertAlmostEqual(float(got.loc[2008]), -20.0, places=6)
        self.assertAlmostEqual(float(got.loc[2009]), 10.0, places=6)
        self.assertNotIn(2007, list(got.index))
        annualized_2009 = ((1.10 ** (12 / 6)) - 1.0) * 100.0
        self.assertGreater(abs(float(got.loc[2009]) - annualized_2009), 1.0)

    def test_equity_curve_is_not_differenced_again(self):
        # Growth index already. 2008 = 0.80/1 - 1 because the curve starts at the
        # first return; 2009 = 1.50/0.80 - 1 = last/prior year-end.
        equity = pd.Series(
            [0.80, 1.50],
            index=pd.to_datetime(['2008-12-31', '2009-12-31']),
        )
        got = spx_calendar_year_returns(equity, equity_curve=True)
        self.assertAlmostEqual(float(got.loc[2008]), -20.0, places=6)
        self.assertAlmostEqual(float(got.loc[2009]), 87.5, places=6)

    def test_backtest_prefers_the_spx_equity_curve_over_spy_prices(self):
        idx = pd.to_datetime(['2008-12-31', '2009-12-31'])
        data = {
            'all_equity_curves': pd.DataFrame({'S&P 500': [0.80, 1.50]}, index=idx),
            'price_data': pd.DataFrame({'SPY': [100.0, 200.0, 400.0]}, index=pd.to_datetime(
                ['2007-12-31', '2008-12-31', '2009-12-31'])),
        }
        got = backtest_spx_year_returns(data)
        self.assertAlmostEqual(float(got.loc[2008]), -20.0, places=6)
        self.assertAlmostEqual(float(got.loc[2009]), 87.5, places=6)

    def test_spy_prices_are_the_fallback(self):
        data = {
            'all_equity_curves': pd.DataFrame({'Nasdaq 100 (QQQ)': [1.0, 1.2]}),
            'price_data': pd.DataFrame(
                {'SPY': [100.0, 80.0, 88.0]},
                index=pd.to_datetime(['2007-12-31', '2008-12-31', '2009-06-30']),
            ),
        }
        got = backtest_spx_year_returns(data)
        self.assertAlmostEqual(float(got.loc[2008]), -20.0, places=6)
        self.assertAlmostEqual(float(got.loc[2009]), 10.0, places=6)

    def test_missing_spx_is_an_empty_series(self):
        self.assertEqual(len(backtest_spx_year_returns({})), 0)
        self.assertEqual(len(backtest_spx_year_returns(None)), 0)


class BacktestHeatmapSpxTests(unittest.TestCase):
    def test_strategy_year_matches_the_year_only_heatmap(self):
        monthly = pd.Series(
            [0.01, 0.02, -0.03, 0.04],
            index=pd.to_datetime(['2011-01-31', '2011-02-28', '2012-01-31', '2012-03-30']),
        )
        prices = pd.Series(
            [100.0, 110.0, 90.0],
            index=pd.to_datetime(['2010-12-31', '2011-12-30', '2012-03-30']),
        )
        data = {'price_data': pd.DataFrame({'SPY': prices})}
        plain = make_monthly_heatmap(monthly)
        paired = backtest_monthly_heatmap(monthly, data)
        plain_trace = plain.data[0]
        paired_trace = paired.data[0]
        self.assertEqual(list(plain_trace.x)[-1], 'Year')
        self.assertEqual(list(paired_trace.x)[-2:], [BACKTEST_YEAR_COLUMN, BACKTEST_SPX_COLUMN])
        self.assertEqual(paired.layout.title.text,
                         'Monthly Returns Heatmap (%) — Strategy vs S&P500')
        for year in (2011, 2012):
            plain_z, plain_text = _cell(plain_trace, year, 'Year')
            strat_z, strat_text = _cell(paired_trace, year, BACKTEST_YEAR_COLUMN)
            self.assertAlmostEqual(strat_z, plain_z, places=8)
            self.assertEqual(strat_text, plain_text)
            expected = float(compounded_year_returns(monthly).loc[year])
            self.assertAlmostEqual(strat_z, expected, places=8)
            spx_z, spx_text = _cell(paired_trace, year, BACKTEST_SPX_COLUMN)
            self.assertAlmostEqual(spx_z, float(spx_calendar_year_returns(prices).loc[year]), places=6)
            self.assertEqual(spx_text, f'{spx_z:+.1f}%')

    def test_tab_shows_strategy_and_spx_on_every_path(self):
        data = _fixture()
        targeted = build_backtest_path_body(data, BACKTEST_PATH_TARGETED)
        auditor = build_backtest_path_body(data, BACKTEST_PATH_AUDITOR)
        lookahead = build_backtest_path_body(data, BACKTEST_PATH_LOOKAHEAD)
        for body, strat_text in (
            (targeted, '+2.0%'),
            (auditor, '+0.8%'),
            (lookahead, '+15.0%'),
        ):
            fig = _heatmap(body)[0]
            trace = fig.data[0]
            self.assertEqual(list(trace.x)[-2:], ['Strategy', 'S&P500'])
            _z, text = _cell(trace, 2005, 'Strategy')
            self.assertEqual(text, strat_text)
            spx_z, spx_text = _cell(trace, 2005, 'S&P500')
            self.assertAlmostEqual(spx_z, -8.2, places=4)
            self.assertEqual(spx_text, '-8.2%')
            blob = ' '.join(_texts(body))
            self.assertIn('S&P500', blob)
            self.assertIn('SPY', blob)
        # Month cells stay the strategy series. Targeted February is +2%, not the S&P year.
        targeted_trace = _heatmap(targeted)[0].data[0]
        feb_z, feb_text = _cell(targeted_trace, 2005, 'Feb')
        self.assertAlmostEqual(feb_z, 2.0, places=4)
        self.assertEqual(feb_text, '2.0')

    def test_missing_spx_keeps_the_year_column_only(self):
        data = _fixture()
        data['all_equity_curves'] = data['all_equity_curves'].drop(columns=['S&P 500'])
        monthly = monthly_for_path(data, BACKTEST_PATH_TARGETED)
        fig = backtest_monthly_heatmap(monthly, data)
        self.assertEqual(list(fig.data[0].x)[-1], 'Year')
        self.assertNotIn('S&P500', list(fig.data[0].x))
        self.assertEqual(fig.layout.title.text,
                         'Monthly Returns Heatmap (%) — with compounded annual return')
        body = build_backtest_path_body(data, BACKTEST_PATH_TARGETED)
        self.assertNotIn('S&P500 is the S&P 500', ' '.join(_texts(body)))

    def test_no_overlap_does_not_add_a_blank_column(self):
        monthly = pd.Series([0.01], index=pd.to_datetime(['2010-01-29']))
        data = {
            'all_equity_curves': pd.DataFrame(
                {'S&P 500': [1.0, 1.1]},
                index=pd.to_datetime(['2005-06-30', '2005-12-30']),
            ),
        }
        fig = backtest_monthly_heatmap(monthly, data)
        self.assertEqual(list(fig.data[0].x)[-1], 'Year')


if __name__ == '__main__':
    unittest.main()
