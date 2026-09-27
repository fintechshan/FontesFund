"""Backtest tab opens on Auditor Lagged. Production stays a labeled alternate."""
from __future__ import annotations

import unittest

import pandas as pd

from src.dashboard.app import (
    AUDITOR_SERIES_LABEL,
    BACKTEST_PATH_AUDITOR,
    BACKTEST_PATH_PRODUCTION,
    PRODUCTION_SERIES_LABEL,
    build_backtest_path_body,
    build_backtest_tab,
    build_cdn_portfolio_tab,
    portfolio_backtest_headline,
    us_backtest_comparison,
)


def _fixture():
    idx = pd.to_datetime(['2005-01-04', '2005-01-05', '2005-01-06'])
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
    lag = {
        'annual_return': '12.21%',
        'sharpe': '0.83',
        'max_dd': '14.10%',
        'total_return': '1113.59%',
        'sortino': '1.10',
        'calmar': '0.87',
        'volatility': '12.40%',
        'win_rate': '54.1%',
    }
    std = {
        'annual_return': '14.85%',
        'sharpe': '1.03',
        'max_dd': '13.90%',
        'total_return': '1909.27%',
        'sortino': '1.39',
        'calmar': '1.07',
        'volatility': '12.60%',
        'win_rate': '54.5%',
    }
    curve = pd.Series([1.0, 1.01, 1.02], index=idx)
    return {
        'backtest_results': comparison,
        'equity_curve': curve,
        'all_equity_curves': pd.DataFrame({
            'Optimized Regime Strategy': curve,
            'S&P 500': curve * 0.9,
        }),
        'monthly_returns': pd.Series([0.01], index=pd.to_datetime(['2005-01-31'])),
        'audit': {
            'lagged_metrics': {
                'lagged': lag,
                'standard': std,
                'lagged_curve': curve * 0.95,
                'standard_curve': curve,
                'lagged_monthly': pd.Series([0.008], index=pd.to_datetime(['2005-01-31'])),
                'standard_monthly': pd.Series([0.01], index=pd.to_datetime(['2005-01-31'])),
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


def _card_after(texts, title):
    return texts[texts.index(title) + 1]


class BacktestDefaultTests(unittest.TestCase):
    def test_fresh_backtest_tab_shows_auditor_lagged(self):
        tab = build_backtest_tab(_fixture())
        radio = _find_id(tab, 'backtest-path-select')
        self.assertIsNotNone(radio)
        self.assertEqual(radio.value, BACKTEST_PATH_AUDITOR)
        labels = [opt['label'] for opt in radio.options]
        self.assertIn(BACKTEST_PATH_AUDITOR, [opt['value'] for opt in radio.options])
        self.assertIn(BACKTEST_PATH_PRODUCTION, [opt['value'] for opt in radio.options])
        self.assertTrue(any('Auditor Lagged' in label and '12.21%' in label for label in labels))
        self.assertTrue(any('Production' in label and '14.85%' in label for label in labels))
        self.assertIn('execution / timing sensitivity', ' '.join(_texts(tab)))

        body = _find_id(tab, 'backtest-path-body')
        texts = _texts(body)
        self.assertEqual(_card_after(texts, 'Annual Return'), '12.21%')
        self.assertEqual(_card_after(texts, 'Sharpe Ratio'), '0.83')
        self.assertEqual(_card_after(texts, 'Max Drawdown'), '14.10%')
        table = _tables(body)[0]
        self.assertEqual(table.data[0]['Strategy'], AUDITOR_SERIES_LABEL)
        self.assertEqual(table.data[0]['Annual Return'], '12.21%')
        self.assertEqual(table.data[1]['Strategy'], PRODUCTION_SERIES_LABEL)
        self.assertEqual(table.data[1]['Annual Return'], '14.85%')

    def test_production_control_restores_csv_headline(self):
        body = build_backtest_path_body(_fixture(), BACKTEST_PATH_PRODUCTION)
        texts = _texts(body)
        self.assertEqual(_card_after(texts, 'Annual Return'), '14.85%')
        self.assertEqual(_card_after(texts, 'Max Drawdown'), '13.90%')
        self.assertIn('live allocation', ' '.join(texts))
        table = _tables(body)[0]
        self.assertEqual(table.data[0]['Strategy'], PRODUCTION_SERIES_LABEL)
        self.assertEqual(table.data[0]['Annual Return'], '14.85%')
        self.assertEqual(table.data[1]['Annual Return'], '12.21%')

    def test_missing_auditor_run_does_not_silently_show_production_cards(self):
        data = _fixture()
        data['audit'] = {}
        body = build_backtest_path_body(data, BACKTEST_PATH_AUDITOR)
        texts = _texts(body)
        self.assertEqual(_card_after(texts, 'Annual Return'), '—')
        self.assertIn('not loaded', ' '.join(texts))
        # Production remains in the table, labeled, and is not the highlighted first row's CAGR.
        table = _tables(body)[0]
        self.assertEqual(table.data[0]['Annual Return'], '—')
        self.assertEqual(table.data[1]['Annual Return'], '14.85%')

    def test_portfolio_headline_matches_backtest_default(self):
        title, cagr, subtitle = portfolio_backtest_headline(_fixture())
        self.assertEqual(title, 'Auditor Lagged CAGR')
        self.assertEqual(cagr, '12.21%')
        self.assertIn('14.85%', subtitle)
        self.assertIn('Production', subtitle)
        self.assertIn('extra-month', subtitle)

    def test_cdn_us_column_follows_auditor_and_states_no_cdn_lag(self):
        cmp = us_backtest_comparison(_fixture())
        self.assertTrue(cmp['uses_auditor_lag'])
        self.assertEqual(cmp['cagr'], '12.21%')
        tab = build_cdn_portfolio_tab(_fixture())
        blob = ' '.join(_texts(tab))
        self.assertIn('no CDN extra-month', blob)
        self.assertIn('TSX production', blob)
        us_table = next(
            t for t in _tables(tab)
            if any(c.get('id') == 'US Auditor Lagged (extra month)' for c in (t.columns or []))
        )
        cagr = next(row for row in us_table.data if row['Metric'] == 'CAGR')
        self.assertEqual(cagr['US Auditor Lagged (extra month)'], '12.21%')
        self.assertEqual(cagr['CDN Portfolio (CAD)'], '14.62%')


if __name__ == '__main__':
    unittest.main()
