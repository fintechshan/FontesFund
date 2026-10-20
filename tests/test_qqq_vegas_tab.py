"""QQQ Vegas is a read-only tab over data/qqq_vegas. It is not the Merrill sleeve."""
from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

import pandas as pd

from src.dashboard.app import (
    QQQ_VEGAS_DIR,
    VEGAS_INITIAL_CAPITAL,
    _build_qqq_vegas_body,
    _vegas_equity_figure,
    _vegas_equity_series,
    _vegas_heatmap_figure,
    _vegas_monthly_returns,
    _vegas_nav_to_dollars,
    _vegas_qqq_calendar_returns,
    _vegas_qqq_level,
    build_qqq_vegas_tab,
    create_app,
    load_qqq_vegas,
    make_equity_curves,
    make_monthly_heatmap,
)

ROOT = Path(__file__).resolve().parents[1]


def _walk(node, acc):
    if node is None or isinstance(node, dict):
        return
    if isinstance(node, str):
        acc.append(node)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _walk(item, acc)
        return
    _walk(getattr(node, 'children', None), acc)


def _texts(node):
    acc = []
    _walk(node, acc)
    return acc


def _month_end(series, year, month):
    window = series[(series.index.year == year) & (series.index.month == month)]
    return float(window.iloc[-1])


def _hold_from_year_start(level, year):
    """Last close of the year over the prior year-end close, in percent.

    The first year in the series uses its first print as the entry.
    """
    level = level.dropna().sort_index()
    this = level[level.index.year == year]
    prev = level[level.index.year == year - 1]
    entry = float(prev.iloc[-1]) if len(prev) else float(this.iloc[0])
    return (float(this.iloc[-1]) / entry - 1.0) * 100.0


def _heat_index(trace, year, label):
    years = [int(value) for value in trace.y]
    return years.index(year), list(trace.x).index(label)


def _find_id(node, component_id):
    if getattr(node, 'id', None) == component_id:
        return node
    children = getattr(node, 'children', None)
    if isinstance(children, (list, tuple)):
        for child in children:
            hit = _find_id(child, component_id)
            if hit is not None:
                return hit
    elif children is not None and not isinstance(children, (str, dict)):
        return _find_id(children, component_id)
    return None


class QqqVegasTabTests(unittest.TestCase):
    def test_artifacts_render_from_files(self):
        signal = json.loads((QQQ_VEGAS_DIR / 'signal_current.json').read_text(encoding='utf-8'))
        live = json.loads((QQQ_VEGAS_DIR / 'live_snapshot.json').read_text(encoding='utf-8'))
        bundle = load_qqq_vegas()
        self.assertEqual(bundle['missing'], [])
        tab = build_qqq_vegas_tab(bundle)
        blob = '\n'.join(_texts(tab))

        self.assertEqual(signal['strategy_id'], 'qqq_vegas_rv20_q80')
        self.assertIn(signal['strategy_id'], blob)
        self.assertIn(signal['state'], blob)
        self.assertIn(signal['next_action'], blob)
        self.assertIn(signal['reason'], blob)
        self.assertIn(signal['disclaimer'], blob)
        self.assertIn('Not investment advice', blob)
        self.assertIn('不构成投资建议', blob)
        self.assertIn('1999-01-04', blob)
        self.assertIn('2026-10-16', blob)
        self.assertIn('Mom189', blob)
        self.assertIn('rv20_q80', blob)
        for key in ('vegas', 'rv_ok', 'rv20'):
            self.assertIn(key, blob)
        self.assertIn('0.1856', blob)
        self.assertIn('0.3122', blob)
        self.assertIn('Full sample vs prior Vegas 1.3x', blob)
        self.assertEqual(str(pd.Timestamp(bundle['equity']['date'].iloc[0]).date()), '1999-01-04')
        for block in (signal['metrics']['full'], signal['metrics']['oos']):
            for key in ('cagr_pct', 'max_dd_pct', 'sharpe'):
                self.assertIn(str(block[key]), blob)
        last = signal['last_rebalance']
        self.assertIn(last['date'], blob)
        self.assertIn(last['action'], blob)
        self.assertIn('70%', blob)
        self.assertIn('30%', blob)

        equity = _find_id(tab, 'qqq-vegas-equity')
        names = [trace.name for trace in equity.figure.data]
        self.assertEqual(names, ['QQQ Vegas', 'Buy & hold QQQ', 'Vegas only'])
        for trace in equity.figure.data:
            y0 = trace.y.iloc[0] if hasattr(trace.y, 'iloc') else trace.y[0]
            self.assertAlmostEqual(float(y0), VEGAS_INITIAL_CAPITAL, places=2)
            self.assertIn('$%{y:,.0f}', trace.hovertemplate)
        self.assertAlmostEqual(float(equity.figure.data[0].y.iloc[0]
                                      if hasattr(equity.figure.data[0].y, 'iloc')
                                      else equity.figure.data[0].y[0]),
                               float(bundle['equity']['equity'].iloc[0]), places=6)
        self.assertIn('净值 (USD)', equity.figure.layout.yaxis.title.text)
        self.assertIn('100,000', equity.figure.layout.title.text)
        stored = pd.read_csv(QQQ_VEGAS_DIR / 'equity_curve.csv')
        self.assertAlmostEqual(float(stored['equity'].iloc[0]), VEGAS_INITIAL_CAPITAL, places=2)
        self.assertAlmostEqual(float(stored['qqq_bh'].iloc[0]), VEGAS_INITIAL_CAPITAL, places=2)
        self.assertAlmostEqual(float(stored['vegas_only_equity'].iloc[0]), VEGAS_INITIAL_CAPITAL, places=2)
        self.assertAlmostEqual(float(stored['equity'].iloc[1]), 103361.417, places=3)
        self.assertAlmostEqual(float(stored['drawdown'].iloc[6]), -0.03977506, places=8)
        self.assertAlmostEqual(float(stored['rv20'].iloc[0]), 0.307838, places=6)
        self.assertEqual(int(stored['signal'].iloc[0]), 1)
        self.assertEqual(int(stored['pos'].iloc[0]), 0)
        drawdown = _find_id(tab, 'qqq-vegas-drawdown')
        dd_y = drawdown.figure.data[0].y
        dd_value = float(dd_y.iloc[1] if hasattr(dd_y, 'iloc') else dd_y[1])
        self.assertAlmostEqual(dd_value, float(bundle['equity']['drawdown'].iloc[1]) * 100, places=4)

        compare = _find_id(tab, 'qqq-vegas-compare')
        self.assertIsNotNone(compare)
        compare_blob = '\n'.join(
            ' '.join(str(row.get(key, '')) for key in ('book', 'cagr', 'max_dd', 'sharpe', 'calmar'))
            for row in compare.data
        )
        self.assertIn('qqq_vegas_1_3x', compare_blob)
        self.assertIn('12.98%', compare_blob)
        self.assertIn('-63.56%', compare_blob)
        self.assertIn('14.9%', compare_blob)
        self.assertIn('-27.81%', compare_blob)
        self.assertIn('+1.92 pp', compare_blob)
        self.assertIn('+35.75 pp', compare_blob)

        table = _find_id(tab, 'qqq-vegas-rebalances')
        self.assertEqual(len(table.data), len(bundle['rebalances']))
        self.assertEqual(table.data[0]['date'], str(bundle['rebalances']['date'].iloc[0])[:10])
        self.assertEqual(table.data[-1]['date'], str(bundle['rebalances']['date'].iloc[-1])[:10])
        self.assertTrue(all(row['action'] in {'ENTER', 'EXIT'} for row in table.data))
        self.assertGreater(table.data[0]['date'], table.data[-1]['date'])

        live_table = _find_id(tab, 'qqq-vegas-live')
        by_ticker = {row['ticker']: row for row in live_table.data}
        self.assertEqual(by_ticker['QQQ']['target_w'], '70%')
        self.assertEqual(by_ticker['QLD']['target_w'], '30%')
        self.assertEqual(by_ticker['QQQ']['status'], 'unknown')
        self.assertEqual(by_ticker['cash_usd']['target_w'], '0%')
        self.assertIn(live['broker'], blob)
        self.assertIn(live['notes'], blob)
        self.assertIn('match = false', blob)
        self.assertIn('尚未接入实盘', blob)
        self.assertIn('月度收益热力图', blob)
        self.assertIn('monthly_returns.csv', blob)
        self.assertIn('yearly_returns.csv', blob)
        self.assertIn('QQQ B&H', blob)
        self.assertIn('买入持有', blob)
        self.assertIn('策略', blob)

        heat = _find_id(tab, 'qqq-vegas-heatmap')
        self.assertIsNotNone(heat)
        trace = heat.figure.data[0]
        reference = make_monthly_heatmap(pd.Series(
            [0.01], index=pd.to_datetime(['2020-01-31']),
        ))
        ref = reference.data[0]
        self.assertEqual(trace.type, 'heatmap')
        self.assertEqual(list(trace.colorscale), list(ref.colorscale))
        self.assertEqual(trace.zmid, 0)
        self.assertEqual(trace.zmin, -12)
        self.assertEqual(trace.zmax, 12)
        self.assertEqual(trace.hovertemplate, ref.hovertemplate)
        self.assertEqual(list(ref.x), ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', '  ', 'Year'])
        self.assertEqual(list(trace.x), list(ref.x) + ['QQQ B&H'])
        self.assertEqual(reference.layout.title.text,
                         'Monthly Returns Heatmap (%) — with compounded annual return')
        self.assertIn('Year (策略) vs QQQ B&H', heat.figure.layout.title.text)
        self.assertEqual(heat.figure.layout.yaxis.autorange, 'reversed')
        self.assertIn(1999, [int(value) for value in trace.y])

        monthly = pd.read_csv(QQQ_VEGAS_DIR / 'monthly_returns.csv')
        row_2011 = monthly.loc[monthly['year'] == 2011].iloc[0]
        expected_jan = float(row_2011['M01'])
        yi, xi = _heat_index(trace, 2011, 'Jan')
        self.assertAlmostEqual(float(trace.z[yi][xi]), expected_jan, places=4)
        self.assertEqual(trace.text[yi][xi], f'{expected_jan:.1f}')
        compound = 1.0
        for month in range(1, 13):
            raw = row_2011[f'M{month:02d}']
            if pd.notna(raw):
                compound *= 1 + float(raw) / 100
        expected_year = (compound - 1) * 100
        _yi, year_i = _heat_index(trace, 2011, 'Year')
        self.assertAlmostEqual(float(trace.z[yi][year_i]), expected_year, places=4)
        self.assertEqual(trace.text[yi][year_i], f'{expected_year:+.1f}%')

        level = _vegas_qqq_level(bundle['equity'], bundle['market_prices'])
        for year in (1999, 2000, 2011, 2022, 2026):
            expected_bh = _hold_from_year_start(level, year)
            _by, bh_i = _heat_index(trace, year, 'QQQ B&H')
            self.assertAlmostEqual(float(trace.z[_by][bh_i]), expected_bh, places=4)
            self.assertEqual(trace.text[_by][bh_i], f'{expected_bh:+.1f}%')
            self.assertAlmostEqual(
                float(_vegas_qqq_calendar_returns(level).loc[year]), expected_bh, places=6,
            )
        # 2000's within-year first close to last close is not the calendar hold.
        y2000 = level[level.index.year == 2000]
        within = (float(y2000.iloc[-1]) / float(y2000.iloc[0]) - 1.0) * 100.0
        self.assertGreater(abs(within - _hold_from_year_start(level, 2000)), 1.0)

        yearly = pd.read_csv(QQQ_VEGAS_DIR / 'yearly_returns.csv')
        published = dict(zip(yearly['year'].astype(int), yearly['qqq_bh_pct'].astype(float)))
        for year, published_pct in published.items():
            self.assertAlmostEqual(_hold_from_year_start(level, year), published_pct, places=2)

        equity = bundle['equity'].copy()
        equity['date'] = pd.to_datetime(equity['date'])
        bh = equity.set_index('date')['qqq_bh'].astype(float).sort_index()
        bh_jan = (_month_end(bh, 2011, 1) / _month_end(bh, 2010, 12) - 1) * 100
        self.assertNotAlmostEqual(expected_jan, bh_jan, places=1)

        y1999, jan_i = _heat_index(trace, 1999, 'Jan')
        self.assertNotEqual(trace.text[y1999][jan_i], '')
        y2026, nov_i = _heat_index(trace, 2026, 'Nov')
        dec_i = list(trace.x).index('Dec')
        self.assertEqual(trace.text[y2026][nov_i], '')
        self.assertEqual(trace.text[y2026][dec_i], '')

        yearly = _find_id(tab, 'qqq-vegas-yearly')
        self.assertIsNotNone(yearly)
        self.assertEqual([trace.name for trace in yearly.figure.data],
                         ['QQQ Vegas', 'Vegas only', 'Buy & hold QQQ'])
        self.assertEqual(str(yearly.figure.data[0].x[0]), '1999')
        self.assertAlmostEqual(float(yearly.figure.data[0].y[0]), 111.3, places=2)

    def test_nav_scale_matches_other_strategies_and_stays_idempotent(self):
        frame = pd.DataFrame({
            'date': pd.to_datetime(['1999-01-04', '1999-01-05']),
            'equity': [1.0, 1.03361417],
            'qqq_bh': [1.0, 1.02621346],
            'vegas_only_equity': [1.0, 1.03401417],
            'drawdown': [0.0, -0.03977506],
            'strat_ret': [0.0, 0.03361417],
            'rv20': [0.307838, 0.298347],
            'signal': [1, 1],
        })
        once = _vegas_nav_to_dollars(frame)
        twice = _vegas_nav_to_dollars(once)
        self.assertAlmostEqual(float(once['equity'].iloc[0]), 100_000.0, places=2)
        self.assertAlmostEqual(float(once['equity'].iloc[1]), 103361.417, places=3)
        self.assertAlmostEqual(float(once['qqq_bh'].iloc[1]), 102621.346, places=3)
        self.assertAlmostEqual(float(once['vegas_only_equity'].iloc[1]), 103401.417, places=3)
        self.assertAlmostEqual(float(twice['equity'].iloc[1]), float(once['equity'].iloc[1]), places=6)
        self.assertAlmostEqual(float(once['drawdown'].iloc[1]), -0.03977506, places=8)
        self.assertAlmostEqual(float(once['strat_ret'].iloc[1]), 0.03361417, places=8)
        self.assertAlmostEqual(float(once['rv20'].iloc[0]), 0.307838, places=6)
        self.assertEqual(int(once['signal'].iloc[0]), 1)
        self.assertAlmostEqual(float(frame['equity'].iloc[0]), 1.0, places=6)

        fig = _vegas_equity_figure(frame)
        for trace in fig.data:
            y0 = trace.y.iloc[0] if hasattr(trace.y, 'iloc') else trace.y[0]
            self.assertAlmostEqual(float(y0), 100_000.0, places=2)
        self.assertEqual(fig.layout.yaxis.tickformat, '$,.0f')

        idx = pd.to_datetime(['2005-01-04', '2005-01-05'])
        regime = pd.DataFrame({'Optimized Regime Strategy': [1.0, 1.01]}, index=idx)
        regime_fig = make_equity_curves(
            regime, pd.Series(dtype=float), main_name='Optimized Regime Strategy',
        )
        y0 = regime_fig.data[0].y
        self.assertAlmostEqual(float(y0.iloc[0] if hasattr(y0, 'iloc') else y0[0]), 100_000.0, places=2)

        bundle = load_qqq_vegas()
        nav = _vegas_equity_series(bundle['equity'])
        january = nav[(nav.index.year == 1999) & (nav.index.month == 1)]
        expected = float(january.iloc[-1]) / float(nav.iloc[0]) - 1.0
        got = float(_vegas_monthly_returns(bundle['equity']).iloc[0])
        self.assertAlmostEqual(got, expected, places=6)
        self.assertLess(abs(got), 2.0)

    def test_heatmap_falls_back_to_equity_curve(self):
        bundle = load_qqq_vegas()
        bare = dict(bundle)
        bare['monthly'] = pd.DataFrame()
        tab = build_qqq_vegas_tab(bare)
        heat = _find_id(tab, 'qqq-vegas-heatmap')
        reference = make_monthly_heatmap(_vegas_monthly_returns(bundle['equity']))
        self.assertEqual(len(heat.figure.data), len(reference.data))
        self.assertAlmostEqual(
            float(heat.figure.data[0].z[0][0]),
            float(reference.data[0].z[0][0]),
            places=6,
        )
        blob = '\n'.join(_texts(tab))
        self.assertIn('equity_curve.csv (equity)', blob)
        self.assertIn('QQQ B&H', blob)
        self.assertEqual(list(heat.figure.data[0].x)[-1], 'QQQ B&H')
        level = _vegas_qqq_level(bundle['equity'])
        yi, xi = _heat_index(heat.figure.data[0], 2011, 'QQQ B&H')
        self.assertAlmostEqual(
            float(heat.figure.data[0].z[yi][xi]), _hold_from_year_start(level, 2011), places=4,
        )

    def test_heatmap_buyhold_falls_back_to_market_qqq_prices(self):
        bundle = load_qqq_vegas()
        curve = bundle['equity'].drop(columns=['qqq_bh'])
        level = _vegas_qqq_level(curve, bundle['market_prices'])
        self.assertEqual(level.index.min().strftime('%Y-%m-%d'), '1999-03-10')
        fig = _vegas_heatmap_figure(curve, bundle['monthly'], bundle['market_prices'])
        trace = fig.data[0]
        self.assertEqual(list(trace.x)[-1], 'QQQ B&H')
        yi, xi = _heat_index(trace, 2011, 'QQQ B&H')
        self.assertAlmostEqual(float(trace.z[yi][xi]), _hold_from_year_start(level, 2011), places=4)
        # 1999 starts at the first QQQ print in the price file, not a prior close.
        y1999, bh_i = _heat_index(trace, 1999, 'QQQ B&H')
        self.assertAlmostEqual(float(trace.z[y1999][bh_i]), _hold_from_year_start(level, 1999), places=4)
        packed = _vegas_qqq_level(bundle['equity'])
        self.assertGreater(abs(_hold_from_year_start(packed, 1999) - float(trace.z[y1999][bh_i])), 1.0)

    def test_heatmap_without_qqq_level_keeps_the_year_column_only(self):
        bundle = load_qqq_vegas()
        curve = bundle['equity'].drop(columns=['qqq_bh'])
        fig = _vegas_heatmap_figure(curve, bundle['monthly'], prices=pd.DataFrame())
        reference = make_monthly_heatmap(_vegas_monthly_returns(bundle['equity']))
        self.assertEqual(list(fig.data[0].x), list(reference.data[0].x))
        self.assertEqual(fig.layout.title.text, reference.layout.title.text)

    def test_summary_config_supplies_full_and_oos_metrics(self):
        summary = json.loads((QQQ_VEGAS_DIR / 'summary.json').read_text(encoding='utf-8'))
        self.assertIn('vegas_rv20_q80', summary['configs'])
        self.assertIn('compare_to_prior_vegas', summary)
        tab = build_qqq_vegas_tab({
            'signal': {
                'strategy_id': 'qqq_vegas_rv20_q80',
                'state': 'RISK_ON',
                'disclaimer': 'Backtest only. Not investment advice. Not live trading.',
                'metrics': {},
            },
            'summary': summary,
            'live': {},
            'missing': [],
        })
        blob = '\n'.join(_texts(tab))
        self.assertIn('14.9%', blob)
        self.assertIn('18.63%', blob)
        self.assertIn('-27.81%', blob)
        self.assertIn('0.8389', blob)
        self.assertIn('-17.4%', blob)

    def test_missing_directory_still_renders(self):
        bundle = load_qqq_vegas(ROOT / 'data' / 'qqq_vegas_missing')
        self.assertIn('signal_current.json', bundle['missing'])
        tab = build_qqq_vegas_tab(bundle)
        blob = '\n'.join(_texts(tab))
        self.assertIn('Missing artifacts', blob)
        self.assertIn('Not investment advice', blob)
        heat = _find_id(tab, 'qqq-vegas-heatmap')
        self.assertIsNotNone(heat)
        self.assertEqual(len(heat.figure.data), 0)
        self.assertIn('No Data', heat.figure.layout.title.text)

    def test_bad_bundle_does_not_raise(self):
        tab = build_qqq_vegas_tab({'equity': 'not-a-frame'})
        blob = '\n'.join(_texts(tab))
        self.assertIn('QQQ Vegas', blob)
        self.assertIn('Not investment advice', blob)

    def test_tab_is_wired_without_touching_strategy_params(self):
        source = inspect.getsource(create_app)
        self.assertIn('build_qqq_vegas_tab()', source)
        self.assertIn('QQQ Vegas', source)
        vegas_source = inspect.getsource(load_qqq_vegas) + inspect.getsource(build_qqq_vegas_tab)
        self.assertNotIn('STRATEGY_PARAMS', vegas_source)
        self.assertNotIn('REGIME_WEIGHTS', vegas_source)
        heatmap_source = (
            inspect.getsource(_vegas_monthly_returns)
            + inspect.getsource(_vegas_heatmap_figure)
        )
        self.assertNotIn('STRATEGY_PARAMS', heatmap_source)
        self.assertNotIn('REGIME_WEIGHTS', heatmap_source)
        self.assertNotIn('run_optimized_regime_backtest', heatmap_source)
        self.assertIn('qqq-vegas-heatmap', inspect.getsource(_build_qqq_vegas_body))
        rules = (ROOT / 'config' / 'regime_rules.py').read_text(encoding='utf-8')
        self.assertIn('STRATEGY_PARAMS', rules)


if __name__ == '__main__':
    unittest.main()
