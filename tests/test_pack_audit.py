"""Strategy-pack book checks. No network."""
from __future__ import annotations

import unittest

import pandas as pd

from src.dashboard.pack_audit import (
    audit_strategy_packs,
    history_problems,
    refresh_path_problems,
)


class HistoryProblemsTests(unittest.TestCase):
    def test_missing_exit_and_stale_last_rebalance_fail(self):
        rebalances = pd.DataFrame({
            'date': ['2026-07-08'],
            'signal_date': ['2026-07-07'],
            'exec_date': ['2026-07-08'],
            'action': ['ENTER'],
            'from_state': ['CASH'],
            'to_state': ['RISK_ON'],
        })
        full_dates = pd.to_datetime(['2026-07-07', '2026-07-08', '2026-10-30', '2026-11-02'])
        full = pd.DataFrame({
            'date': full_dates,
            'signal': [1, 1, 0, 0],
            'pos': [0, 1, 1, 0],
        })
        problems = history_problems(
            full,
            rebalances,
            last_rebalance={'date': '2026-07-08', 'action': 'ENTER', 'from_state': 'CASH', 'to_state': 'RISK_ON'},
            strategy_date='2026-07-08',
            strategy_action='ENTER',
        )
        text = ' '.join(message for _level, message in problems)
        self.assertIn('2026-11-02', text)
        self.assertIn('EXIT', text)
        self.assertIn('2026-10-30', text)
        self.assertTrue(any(level == 'FAIL' for level, _message in problems))

    def test_refresh_path_without_history_fails(self):
        problems = refresh_path_problems(
            'def refresh_signal():\n    write daily_signal.csv\n',
            ('_sync_rebalances(', 'last_rebalance'),
            label='scripts/refresh_qqq_vegas_signal.py',
        )
        self.assertEqual(problems[0][0], 'FAIL')
        self.assertIn('last_rebalance', problems[0][1])
        self.assertIn('_sync_rebalances(', problems[0][1])


class StrategyPackTests(unittest.TestCase):
    def test_every_pack_is_audited(self):
        rows = audit_strategy_packs()
        packs = [row['pack'] for row in rows]
        self.assertEqual(packs, ['qqq_vegas', 'us_regime', 'cdn_regime'])
        for row in rows:
            self.assertIn(row['status'], {'PASS', 'WARNING', 'FAIL'})
            self.assertTrue(row['desc'])
        # The committed books agree with themselves. A missing flip fails above.
        self.assertTrue(all(row['status'] == 'PASS' for row in rows), [row['desc'] for row in rows])


if __name__ == '__main__':
    unittest.main()
