"""QQQ/QLD price pack is display-only. It does not feed the v9 signal."""
from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

import pandas as pd

from scripts.refresh_qqq_vegas_market import (
    build_snapshot,
    prices_frame,
    select_pe,
    write_market_pack,
)
from src.dashboard.app import (
    QQQ_VEGAS_DIR,
    _build_qqq_vegas_body,
    _vegas_market_cards,
    _vegas_price_figure,
    build_qqq_vegas_tab,
    load_qqq_vegas,
)
from src.dashboard.gcs_sync import SYNC_FILES, VEGAS_MARKET_FILES
from tests.test_qqq_vegas_tab import _find_id, _texts

ROOT = Path(__file__).resolve().parents[1]


def _frame(periods, end='2026-10-16'):
    dates = pd.bdate_range(end=end, periods=periods)
    return pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'QQQ': [100.0 + i for i in range(periods)],
        'QLD': [40.0 + i for i in range(periods)],
    })


class QqqVegasMarketPackTests(unittest.TestCase):
    def test_select_pe_prefers_trailing_and_does_not_invent(self):
        self.assertEqual(select_pe({'trailingPE': 32.4, 'forwardPE': 28.0}), (32.4, 'trailing'))
        self.assertEqual(select_pe({'forwardPE': 28}), (28.0, 'forward'))
        self.assertEqual(select_pe({}), (None, None))
        self.assertEqual(select_pe({'trailingPE': 0, 'forwardPE': None}), (None, None))
        self.assertEqual(select_pe({'trailingPE': 'n/a'}), (None, None))

    def test_prices_frame_keeps_gap_before_qld_lists(self):
        qqq = pd.Series([10.0, 11.0, 12.0], index=pd.to_datetime(['1999-03-10', '1999-03-11', '2006-06-21']))
        qld = pd.Series([20.0], index=pd.to_datetime(['2006-06-21']))
        frame = prices_frame({'QQQ': qqq, 'QLD': qld})
        self.assertEqual(list(frame.columns), ['date', 'QQQ', 'QLD'])
        self.assertTrue(pd.isna(frame.loc[frame['date'] == '1999-03-10', 'QLD']).all())
        self.assertEqual(float(frame.loc[frame['date'] == '2006-06-21', 'QLD'].iloc[0]), 20.0)

    def test_snapshot_uses_last_trade_and_leaves_qld_pe_null(self):
        frame = _frame(5)
        snapshot = build_snapshot(frame, {
            'QQQ': {
                'last': 610.5, 'previous_close': 600.0, 'volume': 45_200_000,
                'week52_high': 640.0, 'week52_low': 412.0, 'pe': 32.25, 'pe_kind': 'trailing',
                'price_basis': 'last_trade', 'week52_basis': 'yahoo', 'currency': 'USD',
            },
            'QLD': {
                'last': 148.2, 'previous_close': 145.0, 'volume': 8_100_000,
                'week52_high': 160.0, 'week52_low': 70.0, 'pe': None, 'pe_kind': None,
                'price_basis': 'last_trade', 'week52_basis': 'yahoo', 'currency': 'USD',
            },
        }, fetched_at='2026-10-19T12:00:00Z')
        self.assertEqual(snapshot['source'], 'yfinance')
        self.assertEqual(snapshot['tickers']['QQQ']['pe_kind'], 'trailing')
        self.assertIsNone(snapshot['tickers']['QLD']['pe'])
        self.assertIsNone(snapshot['tickers']['QLD']['pe_kind'])
        self.assertAlmostEqual(snapshot['tickers']['QQQ']['change_pct'], (610.5 / 600.0 - 1) * 100, places=4)

    def test_snapshot_falls_back_to_adjusted_close_without_inventing_pe(self):
        frame = _frame(5)
        snapshot = build_snapshot(frame, {'QQQ': {}, 'QLD': {}}, fetched_at='2026-10-19T12:00:00Z')
        qqq = snapshot['tickers']['QQQ']
        self.assertEqual(qqq['price_basis'], 'adjusted_close')
        self.assertEqual(qqq['change_basis'], 'adjusted_close')
        self.assertEqual(qqq['last'], 104.0)
        self.assertIsNone(qqq['pe'])
        self.assertEqual(qqq['week52_basis'], 'price_history')

    def test_short_or_stale_download_does_not_clobber(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            good = _frame(8)
            write_market_pack(
                directory, good,
                {'source': 'yfinance', 'tickers': {}},
                min_qqq_rows=4, min_qld_rows=4, max_age_days=10, today='2026-10-16',
            )
            original = (directory / 'market_prices.csv').read_text(encoding='utf-8')
            with self.assertRaises(ValueError):
                write_market_pack(
                    directory, _frame(6), {'source': 'yfinance'},
                    min_qqq_rows=4, min_qld_rows=4, max_age_days=10, today='2026-10-16',
                )
            with self.assertRaises(ValueError):
                write_market_pack(
                    directory, good, {'source': 'yfinance'},
                    min_qqq_rows=4, min_qld_rows=4, max_age_days=10, today='2026-11-20',
                )
            self.assertEqual((directory / 'market_prices.csv').read_text(encoding='utf-8'), original)
            self.assertTrue((directory / 'market_snapshot.json').is_file())

    def test_cards_and_dual_axis_curve(self):
        frame = _frame(6)
        snapshot = {
            'source': 'yfinance',
            'as_of': '2026-10-16',
            'fetched_at': '2026-10-19T12:00:00Z',
            'tickers': {
                'QQQ': {
                    'last': 610.5, 'previous_close': 600.0, 'change_pct': 1.75,
                    'pe': 32.4, 'pe_kind': 'trailing', 'volume': 45_200_000,
                    'week52_high': 640.0, 'week52_low': 412.0, 'week52_basis': 'yahoo',
                },
                'QLD': {
                    'last': 148.2, 'previous_close': 150.0, 'change_pct': -1.2,
                    'pe': None, 'pe_kind': None, 'volume': 8_100_000,
                    'week52_high': 160.0, 'week52_low': 70.0, 'week52_basis': 'yahoo',
                },
            },
        }
        figure = _vegas_price_figure(frame)
        self.assertEqual([trace.name for trace in figure.data], ['QQQ', 'QLD'])
        self.assertEqual(figure.data[1].yaxis, 'y2')
        self.assertIn('QQQ ($)', figure.layout.yaxis.title.text)
        self.assertIn('QLD ($)', figure.layout.yaxis2.title.text)
        tab = build_qqq_vegas_tab({
            'signal': {
                'strategy_id': 'qqq_vegas_rv20_q80',
                'state': 'RISK_ON',
                'disclaimer': 'Backtest only. Not investment advice. Not live trading.',
            },
            'summary': {},
            'live': {},
            'missing': [],
            'market_prices': frame,
            'market_snapshot': snapshot,
        })
        graph = _find_id(tab, 'qqq-vegas-prices')
        self.assertEqual([trace.name for trace in graph.figure.data], ['QQQ', 'QLD'])
        blob = '\n'.join(_texts(tab))
        self.assertIn('610.50', blob)
        self.assertIn('+1.75%', blob)
        self.assertIn('32.4x', blob)
        self.assertIn('trailing', blob)
        self.assertIn('148.20', blob)
        self.assertIn('-1.20%', blob)
        self.assertIn('N/A', blob)
        self.assertIn('not published', blob)
        self.assertIn('45.2M', blob)
        self.assertIn('market_prices.csv', blob)
        self.assertIn('/tasks/refresh', blob)
        cards = _vegas_market_cards(snapshot)
        card_blob = '\n'.join(_texts(cards))
        self.assertNotIn('forward', card_blob)

    def test_seed_pack_and_ascii_filenames(self):
        names = [path.name for path in QQQ_VEGAS_DIR.rglob('*') if path.is_file()]
        self.assertTrue(names)
        for name in names:
            self.assertTrue(name.isascii(), name)
            self.assertNotRegex(name, r'[\u4e00-\u9fff]')
        bundle = load_qqq_vegas()
        self.assertEqual(bundle['missing'], [])
        prices = bundle['market_prices']
        self.assertIn('QQQ', prices.columns)
        self.assertIn('QLD', prices.columns)
        self.assertGreater(prices['QQQ'].notna().sum(), 1000)
        self.assertGreater(prices['QLD'].notna().sum(), 500)
        snapshot = bundle['market_snapshot']
        self.assertEqual(snapshot['source'], 'yfinance')
        self.assertIn('QQQ', snapshot['tickers'])
        self.assertIn('QLD', snapshot['tickers'])
        tab = build_qqq_vegas_tab(bundle)
        graph = _find_id(tab, 'qqq-vegas-prices')
        self.assertEqual([trace.name for trace in graph.figure.data], ['QQQ', 'QLD'])
        self.assertEqual(graph.figure.data[1].yaxis, 'y2')
        equity = _find_id(tab, 'qqq-vegas-equity')
        self.assertEqual(
            [trace.name for trace in equity.figure.data],
            ['QQQ Vegas', 'Buy & hold QQQ', 'Vegas only'],
        )
        blob = '\n'.join(_texts(tab))
        qqq_pe = snapshot['tickers']['QQQ']
        qld_pe = snapshot['tickers']['QLD']
        if qqq_pe.get('pe') is None:
            self.assertIn('N/A', blob)
        else:
            self.assertEqual(qqq_pe['pe_kind'] in {'trailing', 'forward'}, True)
            self.assertIn(qqq_pe['pe_kind'], blob)
        if qld_pe.get('pe') is None:
            self.assertIn('N/A', blob)
        else:
            self.assertIn(qld_pe['pe_kind'], blob)

    def test_daily_refresh_is_cache_not_signal(self):
        dashboard = (ROOT / 'run_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('scripts/refresh_qqq_vegas_market.py', dashboard)
        self.assertIn('def refresh_qqq_vegas_market_cache', dashboard)
        self.assertEqual(
            VEGAS_MARKET_FILES,
            ['data/qqq_vegas/market_prices.csv', 'data/qqq_vegas/market_snapshot.json'],
        )
        for rel in VEGAS_MARKET_FILES:
            self.assertIn(rel, SYNC_FILES)
        script = (ROOT / 'scripts/refresh_qqq_vegas_market.py').read_text(encoding='utf-8')
        for banned in ('REGIME_WEIGHTS', 'STRATEGY_PARAMS', 'run_optimized_regime_backtest', 'signal_current'):
            self.assertNotIn(banned, script)
        view = inspect.getsource(_vegas_price_figure) + inspect.getsource(_vegas_market_cards)
        self.assertNotIn('REGIME_WEIGHTS', view)
        self.assertNotIn('STRATEGY_PARAMS', view)
        body = inspect.getsource(_build_qqq_vegas_body)
        self.assertIn('qqq-vegas-prices', body)
        self.assertIn('qqq-vegas-equity', body)
        rules = json.loads((QQQ_VEGAS_DIR / 'strategy.json').read_text(encoding='utf-8'))
        self.assertEqual(rules['version'], 'v9_rv20_q80')
        self.assertEqual(rules['weights_risk_on'], {'QQQ': 0.7, 'QLD': 0.3, 'BIL': 0.0})
        self.assertIn('expanding_quantile', rules['rules']['en'][1])


if __name__ == '__main__':
    unittest.main()
