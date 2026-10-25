"""QQQ Vegas stamps use artifact clocks. The auditor checks accuracy, freshness, and v9."""
from __future__ import annotations

import inspect
import json
import unittest
from datetime import datetime, timezone

import pandas as pd

from src.dashboard.app import (
    build_auditor_tab,
    build_qqq_vegas_audit_panel,
    build_qqq_vegas_tab,
    create_app,
)
from src.dashboard.auditor import run_independent_audit
from src.dashboard.qqq_vegas_status import (
    CHECK_ACCURACY,
    CHECK_CONSISTENCY,
    CHECK_FRESHNESS,
    VEGAS_DIR,
    audit_qqq_vegas,
    format_instant,
    format_session_close,
    load_bundle,
    parse_instant,
    section_stamps,
)
from tests.test_backtest_default import _fixture
from tests.test_qqq_vegas_tab import _find_id, _texts

STAMP_IDS = (
    'qqq-vegas-updated',
    'qqq-vegas-stamp-rules',
    'qqq-vegas-stamp-disclaimer',
    'qqq-vegas-stamp-signal',
    'qqq-vegas-stamp-equity',
    'qqq-vegas-stamp-heatmap',
    'qqq-vegas-stamp-yearly',
    'qqq-vegas-stamp-rebalances',
    'qqq-vegas-stamp-live',
    'qqq-vegas-market-meta',
    'qqq-vegas-stamp-flags',
)


def _by_name(checks):
    return {row['check']: row for row in checks}


def _fresh_bundle(day='2026-10-23'):
    return {
        'signal': {'as_of': day, 'signal_date': day, 'state': 'RISK_ON', 'vegas': 1, 'rv_ok': 1},
        'summary': {'generated_at': day, 'end_date': day, 'as_of': day},
        'strategy': {'asof': day},
        'market_snapshot': {
            'as_of': day,
            'fetched_at': f'{day}T20:05:00Z',
            'source': 'yfinance',
            'tickers': {
                'QQQ': {'last': 100.0},
                'QLD': {'last': 40.0},
            },
        },
        'market_prices': pd.DataFrame({'date': [day], 'QQQ': [100.0], 'QLD': [40.0]}),
        'live': {'match': False, 'as_of': None, 'signal_as_of': day},
        'equity': pd.DataFrame(),
        'rebalances': pd.DataFrame(),
    }


def _flags(day='2026-10-23'):
    return {
        'generated_at': f'{day} 21:00 UTC',
        'as_of': day,
        'signal_date': day,
        'lag_trading_days': 1,
        'unavailable': False,
        'flags': {},
    }


class StampFormatTests(unittest.TestCase):
    def test_fetch_clock_is_utc_and_shanghai(self):
        text = format_instant('2026-10-19T07:28:16Z')
        self.assertEqual(text, '2026-10-19 07:28 UTC · 2026-10-19 15:28 Asia/Shanghai')

    def test_session_close_uses_new_york_not_a_page_clock(self):
        text = format_session_close('2026-10-16')
        self.assertEqual(
            text,
            '2026-10-16 16:00 America/New_York (session close) · '
            '2026-10-16 20:00 UTC · '
            '2026-10-17 04:00 Asia/Shanghai',
        )

    def test_date_only_fetch_is_not_labeled_as_a_clock(self):
        self.assertIn('no clock in source', format_instant('2026-10-19'))
        self.assertIsNone(parse_instant('2026-10-19'))

    def test_display_helpers_do_not_read_mtime_or_now(self):
        from src.dashboard import qqq_vegas_status as status
        source = (
            inspect.getsource(status.section_stamps)
            + inspect.getsource(status.format_instant)
            + inspect.getsource(status.format_session_close)
            + inspect.getsource(status.format_calendar)
        )
        self.assertNotIn('st_mtime', source)
        self.assertNotIn('now(', source)

    def test_market_stamp_uses_fetched_at(self):
        stamps = section_stamps({
            'market_snapshot': {'as_of': '2026-10-16', 'fetched_at': '2026-10-19T07:28:16Z'},
        }, flags=_flags('2026-10-20'))
        self.assertIn('Last updated 2026-10-19 07:28 UTC · 2026-10-19 15:28 Asia/Shanghai', stamps['market'])
        self.assertIn('2026-10-16 16:00 America/New_York', stamps['market'])
        self.assertNotIn('16:03', stamps['market'])


class VegasTabStampTests(unittest.TestCase):
    def test_every_section_shows_a_real_clock(self):
        tab = build_qqq_vegas_tab()
        for component_id in STAMP_IDS:
            node = _find_id(tab, component_id)
            self.assertIsNotNone(node, component_id)
            text = node.children if isinstance(node.children, str) else '\n'.join(_texts(node))
            self.assertIn('Last updated', text, component_id)
            self.assertTrue(
                any(zone in text for zone in ('UTC', 'America/New_York', 'Asia/Shanghai')),
                component_id,
            )
            self.assertNotIn('16:03:41', text, component_id)
        market = _find_id(tab, 'qqq-vegas-market-meta').children
        snapshot = json.loads((VEGAS_DIR / 'market_snapshot.json').read_text(encoding='utf-8'))
        fetched = format_instant(snapshot['fetched_at'])
        self.assertIn(fetched, market)
        self.assertIn('Asia/Shanghai', fetched)
        self.assertIn(format_session_close(snapshot['as_of']), market)
        live = _find_id(tab, 'qqq-vegas-stamp-live').children
        self.assertIn('as_of is empty', live)
        signal = json.loads((VEGAS_DIR / 'signal_current.json').read_text(encoding='utf-8'))
        self.assertIn(format_session_close(signal['as_of']), live)
        flags_file = json.loads((VEGAS_DIR.parent / 'risk_flags' / 'flags.json').read_text(encoding='utf-8'))
        flags = _find_id(tab, 'qqq-vegas-stamp-flags').children
        self.assertIn(format_instant(flags_file['generated_at']), flags)

    def test_refresh_callback_rewrites_stamps_from_files(self):
        source = inspect.getsource(create_app)
        for component_id in (
            'qqq-vegas-updated',
            'qqq-vegas-stamp-rules',
            'qqq-vegas-stamp-signal',
            'qqq-vegas-stamp-equity',
            'qqq-vegas-stamp-heatmap',
            'qqq-vegas-stamp-rebalances',
            'qqq-vegas-stamp-live',
            'qqq-vegas-market-meta',
        ):
            self.assertIn(component_id, source)
        self.assertIn('section_stamps', source)
        self.assertIn('_pull_vegas_market_cache', source)
        panel = inspect.getsource(create_app)
        start = panel.index('def refresh_qqq_vegas_market_panel')
        body = panel[start:start + 900]
        self.assertNotIn('datetime.now', body)


class VegasAuditTests(unittest.TestCase):
    def test_committed_pack_matches_v9_and_flags_stale_sessions(self):
        checks = _by_name(audit_qqq_vegas(today='2026-10-25', now=datetime(2026, 10, 25, tzinfo=timezone.utc)))
        self.assertEqual(checks[CHECK_ACCURACY]['status'], 'PASS')
        self.assertEqual(checks[CHECK_CONSISTENCY]['status'], 'PASS')
        self.assertEqual(checks[CHECK_FRESHNESS]['status'], 'WARNING')
        snapshot = json.loads((VEGAS_DIR / 'market_snapshot.json').read_text(encoding='utf-8'))
        signal = json.loads((VEGAS_DIR / 'signal_current.json').read_text(encoding='utf-8'))
        self.assertIn(signal['as_of'], checks[CHECK_FRESHNESS]['desc'])
        self.assertIn(format_instant(snapshot['fetched_at']), checks[CHECK_FRESHNESS]['desc'])
        self.assertIn('70/30', checks[CHECK_CONSISTENCY]['threshold'])
        self.assertIn('1999', checks[CHECK_CONSISTENCY]['desc'])

    def test_fresh_clocks_pass(self):
        checks = _by_name(audit_qqq_vegas(
            bundle=_fresh_bundle(),
            flags=_flags(),
            today='2026-10-23',
            now=datetime(2026, 10, 23, 22, tzinfo=timezone.utc),
        ))
        self.assertEqual(checks[CHECK_FRESHNESS]['status'], 'PASS', checks[CHECK_FRESHNESS]['desc'])

    def test_date_only_fetch_and_future_clock_fail(self):
        stale = _fresh_bundle('2026-09-01')
        checks = _by_name(audit_qqq_vegas(
            bundle=stale, flags=_flags('2026-09-01'), today='2026-10-25',
            now=datetime(2026, 10, 25, tzinfo=timezone.utc),
        ))
        self.assertEqual(checks[CHECK_FRESHNESS]['status'], 'FAIL')

        placeholder = _fresh_bundle()
        placeholder['market_snapshot'] = dict(placeholder['market_snapshot'], fetched_at='2026-10-23')
        checks = _by_name(audit_qqq_vegas(
            bundle=placeholder, flags=_flags(), today='2026-10-23',
            now=datetime(2026, 10, 23, 22, tzinfo=timezone.utc),
        ))
        self.assertEqual(checks[CHECK_FRESHNESS]['status'], 'FAIL')
        self.assertIn('timezone-aware', checks[CHECK_FRESHNESS]['desc'])

        future = _fresh_bundle()
        future['market_snapshot'] = dict(future['market_snapshot'], fetched_at='2026-12-01T00:00:00Z')
        checks = _by_name(audit_qqq_vegas(
            bundle=future, flags=_flags(), today='2026-10-23',
            now=datetime(2026, 10, 23, 22, tzinfo=timezone.utc),
        ))
        self.assertEqual(checks[CHECK_FRESHNESS]['status'], 'FAIL')
        self.assertIn('future', checks[CHECK_FRESHNESS]['desc'])

    def test_wrong_weights_fail_accuracy(self):
        bundle = load_bundle()
        signal = dict(bundle['signal'])
        signal['weights'] = {'QQQ': 0.5, 'QLD': 0.5, 'cash': 0.0}
        signal['qqq_w'] = 0.5
        signal['qld_w'] = 0.5
        bundle = dict(bundle, signal=signal)
        checks = _by_name(audit_qqq_vegas(bundle=bundle, today='2026-10-25'))
        self.assertEqual(checks[CHECK_ACCURACY]['status'], 'FAIL')
        self.assertIn('70/30', checks[CHECK_ACCURACY]['desc'])

    def test_short_history_and_same_bar_fill_fail_consistency(self):
        rules = {
            'en': [
                '70% QQQ + 30% QLD',
                'expanding Q80 min_periods=252',
                'close confirm shift(1) next open',
            ],
        }
        equity = pd.DataFrame({
            'date': ['2024-01-02', '2024-01-03'],
            'signal': [1, 1],
            'pos': [1, 1],
            'vegas': [1, 1],
            'rv_ok': [1, 1],
            'rv20': [0.20, 0.20],
            'rv20_q80': [0.31, 0.31],
        })
        rebalances = pd.DataFrame({
            'date': ['2024-01-02'],
            'signal_date': ['2024-01-02'],
            'exec_date': ['2024-01-02'],
            'action': ['ENTER'],
            'from_state': ['CASH'],
            'to_state': ['RISK_ON'],
            'qqq_w': [0.7],
            'qld_w': [0.3],
        })
        bundle = {
            'signal': {
                'strategy_id': 'qqq_vegas_rv20_q80',
                'backtest_tag': 'v9_rv20_q80',
                'state': 'RISK_ON',
            },
            'summary': {
                'strategy_id': 'qqq_vegas_rv20_q80',
                'backtest_tag': 'v9_rv20_q80',
                'rules': rules,
            },
            'strategy': {
                'id': 'qqq_vegas_rv20_q80',
                'version': 'v9_rv20_q80',
                'weights_risk_on': {'QQQ': 0.7, 'QLD': 0.3, 'BIL': 0.0},
                'weights_risk_off': {'QQQ': 0.0, 'QLD': 0.0, 'BIL': 1.0},
                'rules': rules,
            },
            'equity': equity,
            'rebalances': rebalances,
            'live': {},
            'market_snapshot': {},
            'market_prices': pd.DataFrame(),
        }
        checks = _by_name(audit_qqq_vegas(bundle=bundle, flags=_flags(), today='2026-10-25'))
        self.assertEqual(checks[CHECK_CONSISTENCY]['status'], 'FAIL')
        text = checks[CHECK_CONSISTENCY]['desc']
        self.assertIn('2024-01-02', text)
        self.assertIn('next session', text)

    def test_auditor_page_lists_the_three_checks(self):
        panel = build_qqq_vegas_audit_panel(audit_qqq_vegas(
            today='2026-10-25', now=datetime(2026, 10, 25, tzinfo=timezone.utc),
        ))
        blob = '\n'.join(_texts(panel))
        table = _find_id(panel, 'qqq-vegas-audit-table')
        names = [row['Check'] for row in table.data]
        for name in (CHECK_ACCURACY, CHECK_FRESHNESS, CHECK_CONSISTENCY):
            self.assertIn(name, names)
        self.assertIn('70% QQQ + 30% QLD', blob)
        self.assertIn('next open', blob)
        self.assertIn('1999', blob)
        self.assertIn('Asia/Shanghai', blob)
        joined = '\n'.join(row['Description'] for row in table.data)
        snapshot = json.loads((VEGAS_DIR / 'market_snapshot.json').read_text(encoding='utf-8'))
        self.assertIn(format_instant(snapshot['fetched_at']), joined)
        data = _fixture()
        data['audit']['qqq_vegas_checks'] = audit_qqq_vegas(
            today='2026-10-25', now=datetime(2026, 10, 25, tzinfo=timezone.utc),
        )
        tab = build_auditor_tab(data)
        tab_blob = '\n'.join(_texts(tab))
        tab_table = _find_id(tab, 'qqq-vegas-audit-table')
        self.assertEqual([row['Check'] for row in tab_table.data], list(names))
        self.assertIn('QQQ Vegas · accuracy, freshness, v9 consistency', tab_blob)

    def test_independent_audit_includes_vegas_rows(self):
        audit = run_independent_audit(
            pd.DataFrame(), {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        )
        names = [row['check'] for row in audit['data_checks']]
        for name in (CHECK_ACCURACY, CHECK_FRESHNESS, CHECK_CONSISTENCY):
            self.assertIn(name, names)
        self.assertEqual(
            [row['check'] for row in audit['qqq_vegas_checks']],
            [CHECK_ACCURACY, CHECK_FRESHNESS, CHECK_CONSISTENCY],
        )


if __name__ == '__main__':
    unittest.main()
