"""Title and legend occupy separate bands on multi-series growth charts."""
from __future__ import annotations

import unittest

import pandas as pd

from src.dashboard.app import (
    AUDITOR_SERIES_LABEL,
    TARGETED_SERIES_LABEL,
    build_backtest_path_body,
    build_cdn_portfolio_tab,
    make_auditor_curves,
    make_equity_curves,
    make_regime_timeline,
)
from tests.test_backtest_default import _fixture, _texts


def _graphs(node, acc=None):
    acc = [] if acc is None else acc
    if node is None or isinstance(node, (str, dict)):
        return acc
    if isinstance(node, (list, tuple)):
        for item in node:
            _graphs(item, acc)
        return acc
    if node.__class__.__name__ == 'Graph':
        acc.append(node)
    children = getattr(node, 'children', None)
    if isinstance(children, (list, tuple)):
        for child in children:
            _graphs(child, acc)
    elif children is not None:
        _graphs(children, acc)
    return acc


def _assert_legend_below_title(test, fig, *, titled):
    legend = fig.layout.legend
    title = fig.layout.title
    test.assertEqual(legend.orientation, 'h')
    test.assertEqual(legend.yref, 'container')
    test.assertEqual(legend.yanchor, 'bottom')
    test.assertLess(float(legend.y), 0.2)
    test.assertGreaterEqual(float(fig.layout.margin.b), 80)
    test.assertEqual(title.yref, 'container')
    test.assertEqual(title.yanchor, 'top')
    test.assertGreater(float(title.y), 0.9)
    if titled:
        test.assertTrue((title.text or '').strip())
        test.assertGreaterEqual(float(fig.layout.margin.t), 48)
    else:
        test.assertFalse((title.text or '').strip())


class ChartLegendLayoutTests(unittest.TestCase):
    def test_equity_curve_title_sits_above_the_legend(self):
        idx = pd.bdate_range('2005-01-03', periods=40)
        frame = pd.DataFrame({
            'Basic Regime (upper bound)': 1.0,
            '60/40 Benchmark': 1.1,
            'S&P 500': 1.2,
            'Nasdaq 100 (QQQ)': 1.3,
            'All Weather': 0.9,
            AUDITOR_SERIES_LABEL: 1.4,
        }, index=idx)
        curve = pd.Series(1.4, index=idx)
        title = f'Equity Curve — {AUDITOR_SERIES_LABEL} vs benchmarks ($100K)'
        fig = make_equity_curves(frame, curve, title=title, main_name=AUDITOR_SERIES_LABEL)
        _assert_legend_below_title(self, fig, titled=True)
        self.assertEqual(fig.layout.title.text, title)
        main = next(t for t in fig.data if t.name == AUDITOR_SERIES_LABEL)
        bench = next(t for t in fig.data if t.name == 'Nasdaq 100 (QQQ)')
        self.assertEqual(main.line.color, '#00d97e')
        self.assertEqual(bench.line.color, '#00e5ff')
        self.assertEqual(main.line.width, 2.5)
        self.assertEqual(bench.line.width, 1.2)

    def test_backtest_body_uses_the_separated_equity_layout(self):
        body = build_backtest_path_body(_fixture(), 'targeted')
        titled = [
            g.figure for g in _graphs(body)
            if (g.figure.layout.title.text or '').startswith('Equity Curve')
        ]
        self.assertEqual(len(titled), 1)
        _assert_legend_below_title(self, titled[0], titled=True)
        self.assertIn(TARGETED_SERIES_LABEL, titled[0].layout.title.text)

    def test_auditor_overlay_keeps_its_title_off_the_legend(self):
        idx = pd.bdate_range('2010-01-04', periods=30)
        fig = make_auditor_curves(
            pd.Series(1.2, index=idx),
            pd.Series(1.05, index=idx),
            pd.Series(1.3, index=idx),
        )
        _assert_legend_below_title(self, fig, titled=True)
        colors = {t.name: t.line.color for t in fig.data}
        self.assertEqual(colors['Targeted fix'], '#00d97e')
        self.assertEqual(colors['Month-end look-ahead'], '#f5a623')
        self.assertEqual(colors['Auditor extra month'], '#b55fe6')

    def test_regime_timeline_legend_is_not_on_the_title(self):
        rh = pd.DataFrame({
            'date': pd.bdate_range('2005-01-31', periods=8, freq='ME'),
            'regime': ['goldilocks', 'reflation', 'stagflation', 'deflation'] * 2,
        })
        fig = make_regime_timeline(rh)
        _assert_legend_below_title(self, fig, titled=True)
        self.assertIn('Regime Timeline', fig.layout.title.text)
        self.assertEqual(
            {t.name: t.marker.color for t in fig.data},
            {
                'Goldilocks': '#00d97e',
                'Reflation': '#f5a623',
                'Stagflation': '#e74c3c',
                'Deflation': '#3498db',
            },
        )

    def test_cdn_growth_note_is_outside_the_plot(self):
        tab = build_cdn_portfolio_tab(_fixture())
        texts = _texts(tab)
        self.assertIn('Bold US line is the targeted fix.', texts)
        growth = []
        for graph in _graphs(tab):
            names = [getattr(t, 'name', '') or '' for t in graph.figure.data]
            if any(name.startswith('CDN Portfolio B') or name.startswith('US targeted') for name in names):
                growth.append(graph.figure)
        self.assertEqual(len(growth), 1)
        fig = growth[0]
        _assert_legend_below_title(self, fig, titled=False)
        self.assertNotIn('Bold US line', fig.layout.title.text or '')
        joined = ' '.join(getattr(t, 'name', '') or '' for t in fig.data)
        self.assertIn('US targeted fix (CPI+1 / GDP+4, no month-end look-ahead)', joined)
        self.assertIn('CDN Portfolio B (CAD — TSX production, no extra-month series)', joined)
        by_name = {t.name: t.line.color for t in fig.data}
        self.assertEqual(
            by_name['US targeted fix (CPI+1 / GDP+4, no month-end look-ahead)'],
            '#00d97e',
        )
        self.assertEqual(
            by_name['CDN Portfolio B (CAD — TSX production, no extra-month series)'],
            '#f5a623',
        )


if __name__ == '__main__':
    unittest.main()
