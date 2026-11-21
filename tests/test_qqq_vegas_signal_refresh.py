"""The v9 signal refresh extends the locked gate. It does not replace it."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.refresh_qqq_vegas_signal import (
    BIL_START,
    COST,
    PREHEAT_START,
    Q80_MIN_PERIODS,
    Q80_Q,
    QLD_LISTED,
    W_QLD,
    W_QQQ,
    _assert_feed_current,
    apply_official_session,
    compute_indicators,
    pos_flips,
    refresh_signal,
)
from src.dashboard.gcs_sync import SYNC_FILES, VEGAS_SIGNAL_FILES
from src.dashboard.qqq_vegas_status import VEGAS_DIR

ROOT = Path(__file__).resolve().parents[1]


class VegasSignalRefreshTests(unittest.TestCase):
    def test_locked_gate_constants(self):
        self.assertEqual(W_QQQ, 0.7)
        self.assertEqual(W_QLD, 0.3)
        self.assertEqual(COST, 0.0004)
        self.assertEqual(Q80_Q, 0.80)
        self.assertEqual(Q80_MIN_PERIODS, 252)
        self.assertEqual(str(PREHEAT_START.date()), '1996-12-31')
        self.assertEqual(str(QLD_LISTED.date()), '2006-06-21')
        self.assertEqual(str(BIL_START.date()), '2010-01-04')

    def test_published_close_reproduces_vegas(self):
        """SMA, EMA, and Mom189 on the stored splice match the committed vegas column.

        The expanding Q80 also needs the 1996-12-31 Nasdaq-100 preheat. That check
        runs inside the refresh script and refuses a write on a mismatch.
        """
        stored = pd.read_csv(VEGAS_DIR / 'daily_signal.csv', parse_dates=['date']).set_index('date')
        indicators = compute_indicators(stored['qqq_close'])
        ready = indicators['mom189'].notna() & indicators['sma150'].notna()
        self.assertGreater(int(ready.sum()), 2000)
        self.assertTrue((indicators.loc[ready, 'vegas'].astype(int) == stored.loc[ready, 'vegas'].astype(int)).all())
        signal = stored['signal'].astype(int)
        pos = stored['pos'].astype(int)
        self.assertEqual(int(pos.iloc[0]), 0)
        self.assertTrue((pos.iloc[1:].to_numpy() == signal.iloc[:-1].to_numpy()).all())

    def test_daily_path_refreshes_the_signal_pack(self):
        dashboard = (ROOT / 'run_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('scripts/refresh_qqq_vegas_signal.py', dashboard)
        self.assertIn('def refresh_qqq_vegas_signal_cache', dashboard)
        script = (ROOT / 'scripts/refresh_qqq_vegas_signal.py').read_text(encoding='utf-8')
        for banned in ('REGIME_WEIGHTS', 'STRATEGY_PARAMS', 'run_optimized_regime_backtest'):
            self.assertNotIn(banned, script)
        self.assertIn('1996-12-31', script)
        for rel in VEGAS_SIGNAL_FILES:
            self.assertIn(rel, SYNC_FILES)
        self.assertIn('data/qqq_vegas/signal_current.json', VEGAS_SIGNAL_FILES)
        self.assertNotIn('data/qqq_vegas/signal_current.json', [
            'data/qqq_vegas/market_prices.csv',
            'data/qqq_vegas/market_snapshot.json',
        ])
        self.assertIn('_sync_rebalances(', script)
        self.assertIn('last_rebalance', script)

    def test_committed_rebalances_match_pos_changes(self):
        signal = pd.read_csv(VEGAS_DIR / 'daily_signal.csv', parse_dates=['date']).set_index('date')
        flips = pos_flips(signal)
        stored = pd.read_csv(VEGAS_DIR / 'rebalances.csv')
        self.assertEqual(len(flips), len(stored))
        self.assertGreater(len(flips), 0)
        # Independent of pos_flips: a change in pos is exactly one history row.
        pos = signal['pos'].astype(int)
        changes = int((pos != pos.shift(1)).iloc[1:].sum())
        self.assertEqual(changes, len(stored))
        last = flips[-1]
        self.assertEqual(stored.iloc[-1]['exec_date'][:10], last['exec'].strftime('%Y-%m-%d'))
        self.assertEqual(stored.iloc[-1]['signal_date'][:10], last['signal'].strftime('%Y-%m-%d'))
        self.assertEqual(stored.iloc[-1]['action'], last['action'])

    def test_official_session_chains_the_published_return(self):
        prev = pd.Timestamp('2026-11-19')
        stamp = pd.Timestamp('2026-11-20')
        market = {
            'qqq': pd.Series({prev: 600.0}),
            'qld': pd.Series({prev: 70.0}),
            'bil': pd.Series({prev: 90.0}),
        }
        filled = apply_official_session(market)
        self.assertAlmostEqual(float(filled['qqq'].loc[stamp]), 608.45, places=2)
        self.assertAlmostEqual(float(filled['qld'].loc[stamp]), 70.0 * (63.52 / 71.26), places=4)
        self.assertAlmostEqual(float(filled['bil'].loc[stamp]), 90.0 * (91.59 / 91.57), places=4)
        again = apply_official_session(filled)
        self.assertEqual(len(again['qqq']), 2)

    def test_stale_feed_fails_instead_of_leaving_the_book(self):
        now = datetime(2026, 11, 21, 23, tzinfo=timezone.utc)
        with self.assertRaises(RuntimeError) as raised:
            _assert_feed_current(pd.Timestamp('2026-11-06'), now)
        self.assertIn('Refusing to leave the book stale', str(raised.exception))
        _assert_feed_current(pd.Timestamp('2026-11-20'), now)

    def test_refresh_crossing_exit_writes_history(self):
        """A refresh that crosses 2026-10-30 / 2026-11-02 writes the EXIT row."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in (
                'daily_signal.csv', 'equity_curve.csv', 'rebalances.csv',
                'monthly_returns.csv', 'yearly_returns.csv',
                'signal_current.json', 'summary.json', 'strategy.json', 'live_snapshot.json',
            ):
                shutil.copy(VEGAS_DIR / name, directory / name)
            signal = pd.read_csv(directory / 'daily_signal.csv', parse_dates=['date'])
            signal = signal.loc[signal['date'] <= '2026-10-23'].copy()
            signal.to_csv(directory / 'daily_signal.csv', index=False)
            equity = pd.read_csv(directory / 'equity_curve.csv', parse_dates=['date'])
            equity = equity.loc[equity['date'] <= '2026-10-23'].copy()
            equity.to_csv(directory / 'equity_curve.csv', index=False)
            rebalances = pd.read_csv(directory / 'rebalances.csv', parse_dates=['exec_date'])
            rebalances = rebalances.loc[rebalances['exec_date'] <= '2026-10-23'].copy()
            rebalances.to_csv(directory / 'rebalances.csv', index=False)
            current = json.loads((directory / 'signal_current.json').read_text(encoding='utf-8'))
            current['last_rebalance'] = {
                'date': '2026-07-08', 'action': 'ENTER',
                'from_state': 'CASH', 'to_state': 'RISK_ON',
            }
            (directory / 'signal_current.json').write_text(
                json.dumps(current, indent=2) + '\n', encoding='utf-8',
            )
            strategy = json.loads((directory / 'strategy.json').read_text(encoding='utf-8'))
            strategy['last_rebalance_date'] = '2026-07-08'
            strategy['last_rebalance_action'] = 'ENTER'
            (directory / 'strategy.json').write_text(
                json.dumps(strategy, indent=2) + '\n', encoding='utf-8',
            )

            stored = signal.set_index('date').sort_index()
            new_days = pd.bdate_range('2026-10-26', '2026-11-20')
            new_days = new_days[new_days != pd.Timestamp('2026-11-11')]
            crafted = stored.copy()
            extra = []
            last_close = float(stored['qqq_close'].iloc[-1])
            for i, day in enumerate(new_days, start=1):
                turned_off = day >= pd.Timestamp('2026-10-30')
                extra.append({
                    'date': day,
                    'signal': 0 if turned_off else 1,
                    'pos': 0,
                    'vegas': 0 if turned_off else 1,
                    'rv_ok': 1,
                    'rv20': 0.20,
                    'rv20_q80': 0.31,
                    'mom189': -0.01 if turned_off else 0.10,
                    'sma150': last_close,
                    'vegas_low': last_close,
                    'qqq_close': last_close * (1.0 + 0.001 * i),
                    'w_qqq': 0.0 if turned_off else 0.7,
                    'w_qld': 0.0 if turned_off else 0.3,
                    'w_bil': 1.0 if turned_off else 0.0,
                })
            crafted = pd.concat([crafted, pd.DataFrame(extra).set_index('date')]).sort_index()
            qqq = crafted['qqq_close'].astype(float).copy()
            qqq.name = 'QQQ'
            level = pd.Series(100.0, index=qqq.index)
            market = {
                'qqq': qqq,
                'qld': level * 1.01,
                'bil': level * 0.99,
                'irx': pd.Series(1.0, index=qqq.index),
                'ndx': pd.Series(1.0, index=pd.DatetimeIndex([pd.Timestamp('1996-12-31')])),
            }

            def fake_indicators(close):
                frame = crafted.reindex(pd.to_datetime(close.index))
                return pd.DataFrame({
                    'close': qqq.reindex(frame.index),
                    'rv20': frame['rv20'].astype(float),
                    'rv20_q80': frame['rv20_q80'].astype(float),
                    'mom189': frame['mom189'].astype(float),
                    'sma150': frame['sma150'].astype(float),
                    'vegas_low': frame['vegas_low'].astype(float),
                    'vegas': frame['vegas'].astype(float),
                    'rv_ok': frame['rv_ok'].astype(float),
                    'signal': frame['signal'].astype(float),
                })

            preheat = pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp('1996-12-31')]))
            now = datetime(2026, 11, 20, 22, tzinfo=timezone.utc)
            with patch('scripts.refresh_qqq_vegas_signal._preheat', return_value=preheat), \
                    patch('scripts.refresh_qqq_vegas_signal.compute_indicators', side_effect=fake_indicators):
                report = refresh_signal(directory=directory, market=market, now=now)
            self.assertTrue(report['changed'])
            written = pd.read_csv(directory / 'rebalances.csv')
            last = written.iloc[-1]
            self.assertEqual(last['action'], 'EXIT')
            self.assertEqual(str(last['exec_date'])[:10], '2026-11-02')
            self.assertEqual(str(last['signal_date'])[:10], '2026-10-30')
            self.assertEqual(last['from_state'], 'RISK_ON')
            self.assertEqual(last['to_state'], 'CASH')
            later = written.loc[pd.to_datetime(written['exec_date']) > '2026-11-02']
            self.assertTrue(later.empty)
            current = json.loads((directory / 'signal_current.json').read_text(encoding='utf-8'))
            self.assertEqual(current['last_rebalance']['date'], '2026-11-02')
            self.assertEqual(current['last_rebalance']['action'], 'EXIT')
            self.assertEqual(current['state'], 'CASH')
            self.assertEqual(current['next_action'], 'HOLD')
            self.assertEqual(current['as_of'], '2026-11-20')
            strategy = json.loads((directory / 'strategy.json').read_text(encoding='utf-8'))
            self.assertEqual(strategy['last_rebalance_date'], '2026-11-02')
            self.assertEqual(strategy['last_rebalance_action'], 'EXIT')
            rows_after = len(written)
            with patch('scripts.refresh_qqq_vegas_signal._preheat', return_value=preheat), \
                    patch('scripts.refresh_qqq_vegas_signal.compute_indicators', side_effect=fake_indicators):
                again = refresh_signal(directory=directory, market=market, now=now)
            self.assertFalse(again['changed'])
            self.assertEqual(len(pd.read_csv(directory / 'rebalances.csv')), rows_after)


if __name__ == '__main__':
    unittest.main()
