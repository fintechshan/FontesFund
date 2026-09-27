"""Backtest tab opens on the targeted fix. Other clocks stay labeled radios."""
from __future__ import annotations

import unittest

import pandas as pd

from src.dashboard.app import (
    AUDITOR_SERIES_LABEL,
    BACKTEST_PATH_AUDITOR,
    BACKTEST_PATH_LOOKAHEAD,
    BACKTEST_PATH_TARGETED,
    BACKTEST_PATH_UNLAGGED,
    LOOKAHEAD_SERIES_LABEL,
    TARGETED_SERIES_LABEL,
    build_backtest_path_body,
    build_backtest_tab,
    build_cdn_portfolio_tab,
    monthly_for_path,
    portfolio_backtest_headline,
    us_backtest_comparison,
)


def _fixture():
    cdn_idx = pd.to_datetime(['2012-11-27', '2012-11-28'])
    comparison = pd.DataFrame(
        [
            {
                'Annual Return': '14.85%',
                'Volatility': '12.60%',
                'Sharpe Ratio': '1.03',
                'Sortino Ratio': '1.39',
                'Max Drawdown': '13.90%',
                'Calmar Ratio': '1.07',
                'Win Rate': '54.5%',
                'Total Return': '1909.27%',
            },
            {
                'Annual Return': '10.97%',
                'Volatility': '18.89%',
                'Sharpe Ratio': '0.48',
                'Sortino Ratio': '0.59',
                'Max Drawdown': '55.19%',
                'Calmar Ratio': '0.20',
                'Win Rate': '55.0%',
                'Total Return': '855.25%',
            },
        ],
        index=['Optimized Regime Strategy', 'S&P 500'],
    )
    targeted = {
        'annual_return': '13.43%',
        'sharpe': '0.93',
        'max_dd': '14.13%',
        'total_return': '1438.39%',
        'sortino': '1.25',
        'calmar': '0.95',
        'volatility': '12.41%',
        'win_rate': '54.2%',
    }
    lookahead = {
        'annual_return': '14.81%',
        'sharpe': '1.03',
        'max_dd': '13.90%',
        'total_return': '1901.15%',
        'sortino': '1.38',
        'calmar': '1.07',
        'volatility': '12.60%',
        'win_rate': '54.5%',
    }
    auditor = {
        'annual_return': '12.17%',
        'sharpe': '0.83',
        'max_dd': '14.10%',
        'total_return': '1108.46%',
        'sortino': '1.11',
        'calmar': '0.86',
        'volatility': '12.40%',
        'win_rate': '54.1%',
    }
    unlagged = {
        'annual_return': '15.70%',
        'sharpe': '1.11',
        'max_dd': '14.58%',
        'total_return': '2266.07%',
        'sortino': '1.47',
        'calmar': '1.08',
        'volatility': '12.52%',
        'win_rate': '54.6%',
    }
    curve = pd.Series([1.0, 1.02], index=pd.to_datetime(['2005-01-31', '2005-02-28']))
    lookahead_curve = pd.Series([1.0, 1.15], index=curve.index)
    auditor_curve = pd.Series([1.0, 1.008], index=curve.index)
    # Stale production file and a poisoned packed monthly. The heatmap must
    # follow the selected equity curve, not either of these.
    production_monthly = pd.Series([0.15], index=pd.to_datetime(['2005-01-31']))
    return {
        'backtest_results': comparison,
        'equity_curve': curve,
        'all_equity_curves': pd.DataFrame({
            'Optimized Regime Strategy': pd.Series(9.0, index=curve.index),
            'S&P 500': curve * 0.9,
        }),
        'monthly_returns': production_monthly,
        'audit': {
            'lagged_metrics': {
                'targeted': targeted,
                'standard': targeted,
                'lookahead': lookahead,
                'lagged': auditor,
                'unlagged': unlagged,
                'targeted_curve': curve,
                'standard_curve': curve,
                'lookahead_curve': lookahead_curve,
                'lagged_curve': auditor_curve,
                'unlagged_curve': curve * 1.08,
                'targeted_monthly': production_monthly,
                'standard_monthly': production_monthly,
                'lookahead_monthly': production_monthly,
                'lagged_monthly': production_monthly,
                'unlagged_monthly': production_monthly,
            }
        },
        'timestamps': {},
        'current_regime': 'goldilocks',
        'cdn_current_weights': {'ZQQ.TO': 0.6, 'VFV.TO': 0.4},
        'cdn_all_weights': {},
        'cdn_backtest_meta': {
            'name': 'Portfolio B',
            'metrics': {
                'CAGR': '14.62%',
                'MaxDD': '15.53%',
                'Sharpe': '1.16',
                'Volatility': '10.90%',
                'WinRate': '56.4%',
                'TotalReturn': '552.90%',
                'Calmar': '0.94',
            },
        },
        'cdn_equity_curve': pd.Series([1.0, 1.01], index=cdn_idx),
        'cdn_monthly_returns': pd.Series(dtype=float),
        'regime_history': pd.DataFrame(),
        'gsblbr_data': pd.DataFrame(),
        'cdn_regime_changes': [],
    }


def _walk(node, acc):
    if node is None or node is False:
        return
    if isinstance(node, str):
        acc.append(node)
        return
    if isinstance(node, dict):
        for key in ('label', 'children', 'title'):
            if key in node:
                _walk(node[key], acc)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _walk(item, acc)
        return
    _walk(getattr(node, 'children', None), acc)
    _walk(getattr(node, 'options', None), acc)


def _texts(node):
    acc = []
    _walk(node, acc)
    return acc


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


def _tables(node, acc=None):
    acc = [] if acc is None else acc
    if node is None or isinstance(node, (str, dict)):
        return acc
    if isinstance(node, (list, tuple)):
        for item in node:
            _tables(item, acc)
        return acc
    if node.__class__.__name__ == 'DataTable':
        acc.append(node)
    children = getattr(node, 'children', None)
    if isinstance(children, (list, tuple)):
        for child in children:
            _tables(child, acc)
    elif children is not None:
        _tables(children, acc)
    return acc


def _trace_named(body, name):
    graphs = []

    def walk(node):
        if node is None or isinstance(node, (str, dict)):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if node.__class__.__name__ == 'Graph':
            graphs.append(node)
        children = getattr(node, 'children', None)
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        elif children is not None:
            walk(children)

    walk(body)
    for graph in graphs:
        for trace in getattr(graph.figure, 'data', []):
            if getattr(trace, 'name', None) == name:
                return trace
    return None


def _heatmap_text(body):
    graphs = []

    def walk(node):
        if node is None or isinstance(node, (str, dict)):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if node.__class__.__name__ == 'Graph':
            graphs.append(node)
        children = getattr(node, 'children', None)
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        elif children is not None:
            walk(children)

    walk(body)
    chunks = []
    for graph in graphs:
        fig = graph.figure
        for trace in getattr(fig, 'data', []):
            text = getattr(trace, 'text', None)
            if text is None:
                continue
            if isinstance(text, str):
                chunks.append(text)
            else:
                for row in text:
                    chunks.extend(str(cell) for cell in row)
    return ' '.join(chunks)


def _card_after(texts, title):
    return texts[texts.index(title) + 1]


class BacktestDefaultTests(unittest.TestCase):
    def test_fresh_backtest_tab_shows_targeted_fix(self):
        tab = build_backtest_tab(_fixture())
        radio = _find_id(tab, 'backtest-path-select')
        self.assertIsNotNone(radio)
        self.assertEqual(radio.value, BACKTEST_PATH_TARGETED)
        values = [opt['value'] for opt in radio.options]
        labels = [opt['label'] for opt in radio.options]
        self.assertEqual(values[0], BACKTEST_PATH_TARGETED)
        self.assertIn(BACKTEST_PATH_LOOKAHEAD, values)
        self.assertIn(BACKTEST_PATH_UNLAGGED, values)
        self.assertIn(BACKTEST_PATH_AUDITOR, values)
        self.assertTrue(any('Targeted fix' in label and '13.43%' in label for label in labels))
        self.assertTrue(any('month-end look-ahead' in label and '14.81%' in label for label in labels))
        self.assertTrue(any('overly conservative' in label and '12.17%' in label for label in labels))
        blob = ' '.join(_texts(tab))
        self.assertIn('no month-end look-ahead', blob)
        self.assertIn('overly conservative', blob.lower() + blob)

        body = _find_id(tab, 'backtest-path-body')
        texts = _texts(body)
        self.assertEqual(_card_after(texts, 'Annual Return'), '13.43%')
        self.assertEqual(_card_after(texts, 'Sharpe Ratio'), '0.93')
        self.assertEqual(_card_after(texts, 'Max Drawdown'), '14.13%')
        self.assertIn('Daily peak-to-trough', texts)
        self.assertIn('252-day year count', texts)
        self.assertIn('month-end snapshot', ' '.join(texts))
        table = _tables(body)[0]
        self.assertEqual(table.data[0]['Strategy'], TARGETED_SERIES_LABEL)
        self.assertEqual(table.data[0]['Annual Return'], '13.43%')

    def test_heatmap_matches_selected_path_not_the_stale_file(self):
        data = _fixture()
        self.assertAlmostEqual(float(monthly_for_path(data, BACKTEST_PATH_TARGETED).iloc[-1]), 0.02)
        self.assertAlmostEqual(float(monthly_for_path(data, BACKTEST_PATH_LOOKAHEAD).iloc[-1]), 0.15)
        self.assertAlmostEqual(float(monthly_for_path(data, BACKTEST_PATH_AUDITOR).iloc[-1]), 0.008)
        targeted_body = build_backtest_path_body(data, BACKTEST_PATH_TARGETED)
        targeted_heat = _heatmap_text(targeted_body)
        self.assertIn('2.0', targeted_heat)
        self.assertNotIn('15.0', targeted_heat)
        old_body = build_backtest_path_body(data, BACKTEST_PATH_LOOKAHEAD)
        old_heat = _heatmap_text(old_body)
        self.assertIn('15.0', old_heat)
        self.assertEqual(_card_after(_texts(old_body), 'Annual Return'), '14.81%')

    def test_radio_switches_cards_curve_and_heatmap_together(self):
        data = _fixture()
        targeted = build_backtest_path_body(data, BACKTEST_PATH_TARGETED)
        auditor = build_backtest_path_body(data, BACKTEST_PATH_AUDITOR)
        self.assertEqual(_card_after(_texts(targeted), 'Annual Return'), '13.43%')
        self.assertEqual(_card_after(_texts(auditor), 'Annual Return'), '12.17%')
        self.assertIn('2.0', _heatmap_text(targeted))
        self.assertNotIn('15.0', _heatmap_text(targeted))
        auditor_heat = _heatmap_text(auditor)
        self.assertIn('0.8', auditor_heat)
        self.assertNotIn('15.0', auditor_heat)
        targeted_trace = _trace_named(targeted, TARGETED_SERIES_LABEL)
        auditor_trace = _trace_named(auditor, AUDITOR_SERIES_LABEL)
        self.assertIsNotNone(targeted_trace)
        self.assertIsNotNone(auditor_trace)
        self.assertAlmostEqual(float(list(targeted_trace.y)[-1]), 102_000.0)
        self.assertAlmostEqual(float(list(auditor_trace.y)[-1]), 100_800.0)
        self.assertIsNone(_trace_named(targeted, 'Optimized Regime Strategy'))
        self.assertIsNone(_trace_named(auditor, 'Optimized Regime Strategy'))

    def test_lookahead_radio_is_labeled_and_not_the_default(self):
        body = build_backtest_path_body(_fixture(), BACKTEST_PATH_LOOKAHEAD)
        texts = _texts(body)
        self.assertEqual(_card_after(texts, 'Annual Return'), '14.81%')
        self.assertEqual(_card_after(texts, 'Max Drawdown'), '13.90%')
        self.assertIn('month-end look-ahead', ' '.join(texts))
        table = _tables(body)[0]
        self.assertEqual(table.data[0]['Strategy'], LOOKAHEAD_SERIES_LABEL)
        self.assertEqual(table.data[0]['Annual Return'], '14.81%')

    def test_missing_auditor_run_does_not_silently_show_targeted_cards(self):
        data = _fixture()
        data['audit']['lagged_metrics'].pop('lagged')
        body = build_backtest_path_body(data, BACKTEST_PATH_AUDITOR)
        texts = _texts(body)
        self.assertEqual(_card_after(texts, 'Annual Return'), '—')
        self.assertIn('not loaded', ' '.join(texts))
        table = _tables(body)[0]
        self.assertEqual(table.data[0]['Annual Return'], '—')
        self.assertEqual(table.data[0]['Strategy'], AUDITOR_SERIES_LABEL)

    def test_portfolio_headline_matches_backtest_default(self):
        title, cagr, subtitle = portfolio_backtest_headline(_fixture())
        self.assertEqual(title, 'Targeted-fix CAGR')
        self.assertEqual(cagr, '13.43%')
        self.assertIn('14.81%', subtitle)
        self.assertIn('no month-end look-ahead', subtitle)

    def test_cdn_us_column_follows_targeted_fix(self):
        cmp = us_backtest_comparison(_fixture())
        self.assertTrue(cmp['uses_targeted_fix'])
        self.assertFalse(cmp['uses_auditor_lag'])
        self.assertEqual(cmp['cagr'], '13.43%')
        tab = build_cdn_portfolio_tab(_fixture())
        blob = ' '.join(_texts(tab))
        self.assertIn('TSX production', blob)
        self.assertIn('targeted fix', blob)
        us_table = next(
            t for t in _tables(tab)
            if any(c.get('id') == 'US targeted fix (no month-end look-ahead)' for c in (t.columns or []))
        )
        cagr = next(row for row in us_table.data if row['Metric'] == 'CAGR')
        self.assertEqual(cagr['US targeted fix (no month-end look-ahead)'], '13.43%')
        self.assertEqual(cagr['CDN Portfolio (CAD)'], '14.62%')


if __name__ == '__main__':
    unittest.main()
