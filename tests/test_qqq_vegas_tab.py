"""QQQ Vegas is a read-only tab over data/qqq_vegas. It is not the Merrill sleeve."""
from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

import pandas as pd

from src.dashboard.app import (
    QQQ_VEGAS_DIR,
    _build_qqq_vegas_body,
    _vegas_heatmap_figure,
    _vegas_monthly_returns,
    build_qqq_vegas_tab,
    create_app,
    load_qqq_vegas,
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

        self.assertIn(signal['state'], blob)
        self.assertIn(signal['next_action'], blob)
        self.assertIn(signal['reason'], blob)
        self.assertIn(signal['disclaimer'], blob)
        self.assertIn('Not investment advice', blob)
        self.assertIn('不构成投资建议', blob)
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
        self.assertEqual(names, ['QQQ Vegas', 'Buy & hold QQQ'])
        self.assertAlmostEqual(float(equity.figure.data[0].y.iloc[0]
                                      if hasattr(equity.figure.data[0].y, 'iloc')
                                      else equity.figure.data[0].y[0]),
                               float(bundle['equity']['equity'].iloc[0]), places=6)
        drawdown = _find_id(tab, 'qqq-vegas-drawdown')
        dd_y = drawdown.figure.data[0].y
        dd_value = float(dd_y.iloc[1] if hasattr(dd_y, 'iloc') else dd_y[1])
        self.assertAlmostEqual(dd_value, float(bundle['equity']['drawdown'].iloc[1]) * 100, places=4)

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
        self.assertIn('equity_curve.csv (equity)', blob)

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
        self.assertEqual(list(trace.x), ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', '  ', 'Year'])
        self.assertEqual(heat.figure.layout.title.text, reference.layout.title.text)
        self.assertEqual(heat.figure.layout.yaxis.autorange, 'reversed')

        equity = bundle['equity'].copy()
        equity['date'] = pd.to_datetime(equity['date'])
        indexed = equity.set_index('date')['equity'].astype(float).sort_index()
        jan = _month_end(indexed, 2011, 1)
        dec = _month_end(indexed, 2010, 12)
        expected_jan = (jan / dec - 1) * 100
        yi, xi = _heat_index(trace, 2011, 'Jan')
        self.assertAlmostEqual(float(trace.z[yi][xi]), expected_jan, places=6)
        self.assertEqual(trace.text[yi][xi], f'{expected_jan:.1f}')

        end_2011 = _month_end(indexed, 2011, 12)
        expected_year = (end_2011 / dec - 1) * 100
        _yi, year_i = _heat_index(trace, 2011, 'Year')
        self.assertAlmostEqual(float(trace.z[yi][year_i]), expected_year, places=6)
        self.assertEqual(trace.text[yi][year_i], f'{expected_year:+.1f}%')

        bh = equity.set_index('date')['qqq_bh'].astype(float).sort_index()
        bh_jan = (_month_end(bh, 2011, 1) / _month_end(bh, 2010, 12) - 1) * 100
        self.assertNotAlmostEqual(expected_jan, bh_jan, places=1)

        y2010, jan_i = _heat_index(trace, 2010, 'Jan')
        oct_i = list(trace.x).index('Oct')
        self.assertEqual(trace.text[y2010][jan_i], '')
        self.assertNotEqual(trace.text[y2010][oct_i], '')

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
