"""The v9 signal refresh extends the locked gate. It does not replace it."""
from __future__ import annotations

import unittest
from pathlib import Path

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
    compute_indicators,
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


if __name__ == '__main__':
    unittest.main()
