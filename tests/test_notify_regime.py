"""Offline smoke tests for the regime notifier. No FRED, no GitHub."""
from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import notify_regime as nr  # noqa: E402

from config.cdn_regime_rules import CDN_REGIME_WEIGHTS  # noqa: E402
from config.regime_rules import REGIME_WEIGHTS  # noqa: E402


def _state(regime, band, name, vix, **extra):
    base = {
        'schema': 1,
        'regime': regime,
        'vix_band': band,
        'vix_band_name': name,
        'vix': vix,
        'cpi_yoy': 2.4,
        'gdp': 2.1,
        'spy_momentum': 0.12,
        'price_asof': '2026-09-15',
        'checked_at': '2026-09-15 21:00 UTC',
    }
    base.update(extra)
    return base


def _spiked_inputs():
    """CPI spike dated on the last classification month.

    With CPI+1 the spike sits one month past the sample and the lagged regime
    stays goldilocks. Without the lag the same spike is reflation.
    """
    cpi_idx = pd.date_range('2003-01-01', '2026-09-01', freq='MS')
    level = 100.0 * (1.02 ** (np.arange(len(cpi_idx)) / 12.0))
    cpi = pd.Series(level, index=cpi_idx)
    cpi.iloc[-1] = float(cpi.iloc[-13]) * 1.08
    gdp_idx = pd.date_range('2003-01-01', '2026-07-01', freq='QS')
    gdp = pd.Series(2.5, index=gdp_idx)
    days = pd.bdate_range('2005-01-03', '2026-09-15')
    vix = pd.Series(15.0, index=days)
    spy = pd.Series(np.linspace(100.0, 400.0, len(days)), index=days, name='SPY')
    macro = {
        'vix': vix,
        'gdp': gdp,
        'cpi': cpi,
        't10y': pd.Series(4.0, index=days),
        't2y': pd.Series(3.5, index=days),
    }
    return macro, spy.to_frame('SPY')


class BandAndDedupeTests(unittest.TestCase):
    def test_band_edges(self):
        expect = {
            0: '0-20',
            19.9: '0-20',
            20: '20-28',
            27.9: '20-28',
            28: '28-30',
            29.9: '28-30',
            30: '30-40',
            39.9: '30-40',
            40: '40+',
            55: '40+',
        }
        for value, key in expect.items():
            got, _name = nr.vix_band(value)
            self.assertEqual(got, key, value)

    def test_inside_band_wiggle_is_silent(self):
        self.assertEqual(nr.vix_band(21.2)[0], nr.vix_band(27.4)[0])
        prev = _state('goldilocks', '20-28', '偏高', 21.2)
        cur = _state('goldilocks', '20-28', '偏高', 27.4)
        action, reasons = nr.classify_change(prev, cur, force=False)
        self.assertEqual(action, 'silent')
        self.assertEqual(reasons, {})

    def test_band_cross_notifies_without_regime_change(self):
        prev = _state('goldilocks', '20-28', '偏高', 26.0)
        cur = _state('goldilocks', '28-30', '开始降敞口', 28.4)
        action, reasons = nr.classify_change(prev, cur, force=False)
        self.assertEqual(action, 'notify')
        self.assertIn('vix', reasons)
        self.assertNotIn('regime', reasons)
        title, body = nr.build_message(prev, cur, reasons)
        self.assertIn('风险档位', title)
        self.assertIn('28-30', body)
        self.assertNotIn('| 标的 |', body)
        self.assertIn('目标权重不变', body)
        self.assertIn('需要调仓：否', body)
        self.assertIn('防御姿态：应收紧', body)
        self.assertIn('月中再平衡：不建议', body)
        self.assertIn('观察为主', body)
        self.assertIn('scripts/ibkr_rebalance.py', body)
        self.assertIn('scripts/moomoo_rebalance.py', body)
        self.assertIn('不要为了这一档加上 `--execute`', body)
        self.assertNotIn('减持 QQQ', body)

    def test_unchanged_regime_and_band_silent(self):
        prev = _state('reflation', '0-20', '正常', 14.0)
        cur = _state('reflation', '0-20', '正常', 15.2)
        self.assertEqual(nr.classify_change(prev, cur, force=False)[0], 'silent')

    def test_first_run_is_baseline_unless_forced(self):
        cur = _state('goldilocks', '0-20', '正常', 15.0)
        self.assertEqual(nr.classify_change(None, cur, force=False)[0], 'baseline')
        action, reasons = nr.classify_change(None, cur, force=True)
        self.assertEqual(action, 'notify')
        self.assertIn('init', reasons)
        title, _body = nr.build_message(None, cur, reasons)
        self.assertTrue(title.startswith('[测试]'))


class MessageTests(unittest.TestCase):
    def test_regime_change_has_us_and_cdn_deltas(self):
        prev = _state('goldilocks', '0-20', '正常', 15.0)
        cur = _state('deflation', '0-20', '正常', 16.0)
        action, reasons = nr.classify_change(prev, cur, force=False)
        self.assertEqual(action, 'notify')
        title, body = nr.build_message(prev, cur, reasons)
        self.assertIn('调仓', title)
        self.assertIn('goldilocks → deflation', title)
        self.assertIn('US 目标权重', body)
        self.assertIn('CDN 目标权重', body)
        qqq_old = REGIME_WEIGHTS['goldilocks']['QQQ']
        qqq_new = REGIME_WEIGHTS['deflation']['QQQ']
        self.assertIn(
            f'| QQQ | {nr.format_pct(qqq_old)} | {nr.format_pct(qqq_new)} | '
            f'{nr.format_pct(qqq_new - qqq_old, signed=True)} |',
            body,
        )
        zqq_old = CDN_REGIME_WEIGHTS['goldilocks']['ZQQ.TO']
        zqq_new = CDN_REGIME_WEIGHTS['deflation']['ZQQ.TO']
        self.assertIn(
            f'| ZQQ.TO | {nr.format_pct(zqq_old)} | {nr.format_pct(zqq_new)} | '
            f'{nr.format_pct(zqq_new - zqq_old, signed=True)} |',
            body,
        )
        self.assertLess(body.index('| IEF |'), body.index('| AIPO |'))
        self.assertLess(body.index('### 组合变化'), body.index('US 目标权重'))
        self.assertLess(body.index('US 目标权重'), body.index('### 建议操作'))
        self.assertLess(body.index('### 建议操作'), body.index('### 判定依据'))
        self.assertIn('**需要调仓：是**', body)
        self.assertIn(nr.posture_line('US', REGIME_WEIGHTS['goldilocks'], REGIME_WEIGHTS['deflation']), body)
        self.assertIn(nr.posture_line('CDN', CDN_REGIME_WEIGHTS['goldilocks'], CDN_REGIME_WEIGHTS['deflation']), body)
        self.assertIn('QQQ+SOXX+SPY+AIPO', body)
        self.assertIn('IEF+GLD+DBMF', body)
        self.assertIn(
            '- ' + nr.trade_line('QQQ', qqq_old, qqq_new),
            body,
        )
        self.assertIn(
            '- ' + nr.trade_line('ZQQ.TO', zqq_old, zqq_new),
            body,
        )
        self.assertLess(body.index('减持 QQQ'), body.index('增持 IEF'))
        self.assertIn('scripts/ibkr_rebalance.py', body)
        self.assertIn('scripts/moomoo_rebalance.py', body)
        self.assertIn('SIMULATE', body)
        self.assertIn('dry-run', body)
        self.assertIn('不是已成交', body)
        self.assertIn('Regime Monitor', body)
        prev_hot = _state('goldilocks', '0-20', '正常', 18.0)
        cur_hot = _state('deflation', '20-28', '偏高', 22.4, price_asof='2026-09-25')
        _action_hot, reasons_hot = nr.classify_change(prev_hot, cur_hot, force=False)
        self.assertIn('vix', reasons_hot)
        _title_hot, body_hot = nr.build_message(prev_hot, cur_hot, reasons_hot)
        self.assertIn('同日 VIX 升档：日频 overlay 另应收紧。目标权重仍按新象限调整。', body_hot)
        raw = json.dumps({'title': title, 'body': body}, ensure_ascii=False).encode('utf-8')
        self.assertIn('调仓'.encode('utf-8'), raw)
        restored = json.loads(raw.decode('utf-8'))
        self.assertEqual(restored['title'], title)
        self.assertIn('→', restored['title'])

    def test_epsilon_and_vix_ease(self):
        self.assertFalse(nr.needs_rebalance({'QQQ': 0.30}, {'QQQ': 0.305}))
        self.assertTrue(nr.needs_rebalance({'QQQ': 0.30}, {'QQQ': 0.29}))
        self.assertEqual(nr.vix_direction('30-40', '20-28'), 'ease')
        self.assertEqual(nr.vix_direction('0-20', '28-30'), 'tighten')
        prev = _state('goldilocks', '30-40', '大幅降敞口 / 象限转 deflation', 32.0)
        cur = _state('goldilocks', '0-20', '正常', 16.0)
        _action, reasons = nr.classify_change(prev, cur, force=False)
        _title, body = nr.build_message(prev, cur, reasons)
        self.assertIn('防御姿态：可放松', body)
        self.assertIn('需要调仓：否', body)
        self.assertIn('观察为主，不改目标权重', body)
        self.assertNotIn('减持 ', body)

    def test_force_is_not_a_rebalance(self):
        cur = _state('goldilocks', '0-20', '正常', 15.0)
        _action, reasons = nr.classify_change(None, cur, force=True)
        _title, body = nr.build_message(None, cur, reasons)
        self.assertIn('需要调仓：否', body)
        self.assertNotIn('减持 QQQ', body)

    def test_source_file_is_utf8_and_imports_clock(self):
        text = (ROOT / 'scripts' / 'notify_regime.py').read_text(encoding='utf-8')
        self.assertIn('调仓', text)
        self.assertIn('src.backtester.regime_clock', text)
        self.assertIn('MODE_TARGETED', text)
        self.assertNotIn('get_source_segment', text)
        clock = (ROOT / 'src' / 'backtester' / 'regime_clock.py').read_text(encoding='utf-8')
        self.assertIn('CPI_RELEASE_LAG_M = 1', clock)
        self.assertIn('GDP_RELEASE_LAG_M = 4', clock)


def _august_vix_spike():
    """Calm September print, hot August. Targeted September sees August."""
    cpi_idx = pd.date_range('2003-01-01', '2026-09-01', freq='MS')
    level = 100.0 * (1.02 ** (np.arange(len(cpi_idx)) / 12.0))
    cpi = pd.Series(level, index=cpi_idx)
    gdp = pd.Series(2.5, index=pd.date_range('2003-01-01', '2026-07-01', freq='QS'))
    days = pd.bdate_range('2005-01-03', '2026-09-15')
    vix = pd.Series(15.0, index=days)
    vix.loc[(days.year == 2026) & (days.month == 8)] = 45.0
    spy = pd.Series(np.linspace(100.0, 400.0, len(days)), index=days, name='SPY')
    macro = {
        'vix': vix,
        'gdp': gdp,
        'cpi': cpi,
        't10y': pd.Series(4.0, index=days),
        't2y': pd.Series(3.5, index=days),
    }
    return macro, spy.to_frame('SPY')


class ClassifierLagTests(unittest.TestCase):
    def test_compute_state_uses_targeted_clock(self):
        from src.backtester.regime_clock import (
            MODE_LOOKAHEAD,
            MODE_TARGETED,
            MODE_UNLAGGED,
            classify_regimes,
        )

        macro, price = _spiked_inputs()
        state = nr.compute_state(macro, price)
        self.assertEqual(state['regime'], 'goldilocks')
        self.assertEqual(state['clock'], MODE_TARGETED)
        self.assertEqual(state['vix_band'], '0-20')
        _hist, unlagged, _info = classify_regimes(macro, price, mode=MODE_UNLAGGED)
        self.assertEqual(unlagged['regime'], 'reflation')
        _hist, targeted, info = classify_regimes(macro, price, mode=MODE_TARGETED)
        self.assertEqual(targeted['regime'], 'goldilocks')
        self.assertTrue(info['publication_lag'])
        self.assertFalse(info['same_month_market'])
        _hist, lookahead, _la = classify_regimes(macro, price, mode=MODE_LOOKAHEAD)
        self.assertEqual(lookahead['regime'], 'goldilocks')

    def test_targeted_sees_prior_month_vix(self):
        from src.backtester.regime_clock import MODE_LOOKAHEAD, classify_regimes

        macro, price = _august_vix_spike()
        state = nr.compute_state(macro, price)
        self.assertEqual(state['regime'], 'deflation')
        self.assertEqual(state['vix_band'], '0-20')
        _hist, lookahead, _info = classify_regimes(macro, price, mode=MODE_LOOKAHEAD)
        self.assertEqual(lookahead['regime'], 'goldilocks')


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._old_state = os.environ.get('NOTIFY_STATE_PATH')
        self._old_audit = os.environ.get('NOTIFY_AUDIT_PATH')
        os.environ['NOTIFY_STATE_PATH'] = str(self.tmp / 'notify_state.json')
        os.environ['NOTIFY_AUDIT_PATH'] = str(self.tmp / 'notify_audit.json')

    def tearDown(self):
        if self._old_state is None:
            os.environ.pop('NOTIFY_STATE_PATH', None)
        else:
            os.environ['NOTIFY_STATE_PATH'] = self._old_state
        if self._old_audit is None:
            os.environ.pop('NOTIFY_AUDIT_PATH', None)
        else:
            os.environ['NOTIFY_AUDIT_PATH'] = self._old_audit
        self._tmp.cleanup()

    def test_parse_args(self):
        args = nr.parse_args(['--dry-run', '--force', '--github-issue', '--refresh', '--audit'])
        self.assertTrue(
            args.dry_run and args.force and args.github_issue and args.refresh and args.audit
        )

    def test_silent_execute_does_not_open_or_rewrite_state(self):
        cur = _state('stagflation', '30-40', '大幅降敞口 / 象限转 deflation', 32.0)
        nr.write_state(cur)
        original = nr.state_path().read_text(encoding='utf-8')
        calls = []
        real = nr.current_state
        nr.current_state = lambda: dict(cur, checked_at='2026-09-28 02:00 UTC', vix=33.5)
        try:
            action = nr.execute(
                nr.parse_args([]),
                opener=lambda title, body: calls.append((title, body)),
            )
        finally:
            nr.current_state = real
        self.assertEqual(action, 'silent')
        self.assertEqual(calls, [])
        self.assertEqual(nr.state_path().read_text(encoding='utf-8'), original)

    def test_baseline_dry_run_skips_state(self):
        real = nr.current_state
        nr.current_state = lambda: _state('goldilocks', '0-20', '正常', 15.0)
        try:
            action = nr.execute(nr.parse_args(['--dry-run']))
        finally:
            nr.current_state = real
        self.assertEqual(action, 'baseline')
        self.assertFalse(nr.state_path().exists())

    def test_force_dry_run_prints_chinese_title(self):
        prev = _state('goldilocks', '0-20', '正常', 15.0)
        nr.write_state(prev)
        real = nr.current_state
        nr.current_state = lambda: dict(prev)
        try:
            action = nr.execute(nr.parse_args(['--dry-run', '--force']))
        finally:
            nr.current_state = real
        self.assertEqual(action, 'notify')
        # dry-run must not clobber the baseline or a previous audit log
        self.assertEqual(json.loads(nr.state_path().read_text(encoding='utf-8'))['regime'], 'goldilocks')
        self.assertFalse(nr.audit_path().exists())

    def test_refresh_without_key_exits(self):
        old = os.environ.pop('FRED_API_KEY', None)
        env_path = ROOT / '.env'
        self.assertFalse(env_path.exists())
        try:
            with self.assertRaises(SystemExit) as ctx:
                nr.refresh_caches()
        finally:
            if old is not None:
                os.environ['FRED_API_KEY'] = old
        self.assertEqual(ctx.exception.code, 1)


class CliDryRunTests(unittest.TestCase):
    def test_cli_baseline_then_silent(self):
        macro, price = _spiked_inputs()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cache = tmp / 'cache'
            cache.mkdir()
            with open(cache / 'macro_data.pkl', 'wb') as fh:
                pickle.dump(macro, fh)
            price.to_csv(cache / 'price_data.csv')
            state = tmp / 'notify_state.json'
            env = os.environ.copy()
            env['NOTIFY_CACHE_DIR'] = str(cache)
            env['NOTIFY_STATE_PATH'] = str(state)
            env['NOTIFY_AUDIT_PATH'] = str(tmp / 'notify_audit.json')
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'
            env.pop('FRED_API_KEY', None)
            script = str(ROOT / 'scripts' / 'notify_regime.py')

            first = subprocess.run(
                [sys.executable, script, '--dry-run'],
                cwd=str(ROOT), env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('首次运行', first.stdout)
            self.assertNotIn('调仓', first.stdout)
            self.assertFalse(state.exists())

            nr_state = nr.compute_state(macro, price)
            state.write_text(json.dumps(nr_state, ensure_ascii=False), encoding='utf-8')
            second = subprocess.run(
                [sys.executable, script, '--dry-run'],
                cwd=str(ROOT), env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn('无变化', second.stdout)

            forced = subprocess.run(
                [sys.executable, script, '--dry-run', '--force'],
                cwd=str(ROOT), env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(forced.returncode, 0, forced.stderr)
            self.assertIn('[测试]', forced.stdout)
            self.assertIn('US 目标权重', forced.stdout)
            self.assertIn('CDN 目标权重', forced.stdout)
            saved = json.loads(state.read_text(encoding='utf-8'))
            self.assertEqual(saved['regime'], nr_state['regime'])


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_light_and_dedupes(self):
        text = (ROOT / '.github' / 'workflows' / 'notify.yml').read_text(encoding='utf-8')
        self.assertIn('FRED_API_KEY', text)
        self.assertIn('contents: write', text)
        self.assertIn('issues: write', text)
        self.assertIn('[skip ci]', text)
        self.assertIn('NOTIFY_PUSH_TOKEN', text)
        self.assertIn('git diff --cached', text)
        self.assertIn('--refresh', text)
        self.assertIn('--audit', text)
        self.assertIn('id: audit', text)
        self.assertIn('confirmed_miss', text)
        self.assertIn("steps.notify.outcome == 'failure'", text)
        self.assertNotIn('run_backtest.py', text.split('不跑 run_backtest.py')[-1])
        # The comment may mention run_backtest.py; the run steps must not call it.
        run_steps = '\n'.join(
            line for line in text.splitlines() if line.startswith('        run:') or 'python ' in line
        )
        self.assertNotIn('run_backtest.py', run_steps)

    def test_unit_ci_does_not_need_fred(self):
        text = (ROOT / '.github' / 'workflows' / 'test-notify.yml').read_text(encoding='utf-8')
        body = '\n'.join(line for line in text.splitlines() if not line.strip().startswith('#'))
        self.assertIn('tests.test_notify_regime', body)
        self.assertNotIn('FRED_API_KEY', body)
        self.assertNotIn('secrets.', body)

    def test_docs_describe_audit(self):
        text = (ROOT / 'docs' / 'notify.md').read_text(encoding='utf-8')
        self.assertIn('--audit', text)
        self.assertIn('notify-audit', text)
        self.assertIn('[审计]', text)
        self.assertIn('SMTP', text)
        self.assertIn('7 days', text)
        self.assertIn('last_delivery', text)


def _fake_issue(number, title, created_at='2026-09-28T05:00:00Z'):
    return {
        'number': number,
        'html_url': f'https://github.com/fintechshan/FontesFund/issues/{number}',
        'title': title,
        'labels': [{'name': 'rebalance'}],
        'created_at': created_at,
    }


class AuditDecisionTests(unittest.TestCase):
    def test_window_and_match_rules(self):
        anchor = '2026-09-28T00:00:00Z'
        self.assertTrue(nr.within_audit_window('2026-09-21T00:00:00Z', anchor))
        self.assertFalse(nr.within_audit_window('2026-09-20T23:59:59Z', anchor))
        record = {
            'title': '[调仓] goldilocks → deflation（2026-09-25）',
            'checked_at_iso': anchor,
            'issue_number': 4,
        }
        fresh = _fake_issue(4, record['title'], created_at='2020-01-01T00:00:00Z')
        self.assertTrue(nr.issue_satisfies(fresh, record, numbered=True))
        self.assertFalse(nr.issue_satisfies(fresh, record, numbered=False))
        inside = _fake_issue(8, record['title'], created_at='2026-09-27T12:00:00Z')
        self.assertFalse(nr.issue_satisfies(inside, record, numbered=True))
        self.assertTrue(nr.issue_satisfies(inside, {**record, 'issue_number': None}, numbered=False))
        retitled = dict(fresh, title='[测试] 改过标题', labels=[])
        self.assertTrue(nr.issue_satisfies(retitled, record, numbered=True))
        self.assertFalse(nr.issue_satisfies(retitled, record, numbered=False))
        pull = dict(fresh, pull_request={'url': 'x'})
        self.assertFalse(nr.issue_satisfies(pull, record, numbered=True))

    def test_quiet_when_nothing_should_fire(self):
        state = json.loads((ROOT / 'data' / 'notify_state.json').read_text(encoding='utf-8'))
        self.assertNotIn('last_delivery', state)
        self.assertIsNone(nr.expectation_to_verify(None, state))
        silent = {'should_fire': False, 'delivery': 'not_required', 'action': 'silent'}
        self.assertIsNone(nr.expectation_to_verify(silent, state))
        self.assertIsNone(nr.expectation_to_verify(
            {'should_fire': True, 'delivery': 'dry_run'},
            {'last_delivery': {'delivery': 'failed', 'should_fire': True}},
        ))

    def test_history_is_checked_only_when_a_send_was_recorded(self):
        last = {
            'should_fire': True,
            'delivery': 'created',
            'title': '[调仓] a → b（2026-09-25）',
            'issue_number': 3,
            'fingerprint': 'regime|a>b|0-20>0-20|2026-09-25',
        }
        silent = {'should_fire': False, 'delivery': 'not_required', 'action': 'silent'}
        self.assertEqual(nr.expectation_to_verify(silent, {'last_delivery': last}), last)
        failed = {
            'should_fire': True,
            'delivery': 'failed',
            'title': '[风险档位] VIX',
            'fingerprint': 'vix|goldilocks>goldilocks|0-20>20-28|2026-09-25',
        }
        self.assertEqual(nr.expectation_to_verify(failed, {'last_delivery': last})['delivery'], 'failed')

    def test_fingerprint_and_audit_title(self):
        prev = _state('goldilocks', '0-20', '正常', 15.0)
        cur = _state('deflation', '20-28', '偏高', 22.4, price_asof='2026-09-25')
        _action, reasons = nr.classify_change(prev, cur, force=False)
        self.assertEqual(nr.delivery_kind(reasons), 'regime+vix')
        self.assertEqual(
            nr.delivery_fingerprint(prev, cur, reasons),
            'regime+vix|goldilocks>deflation|0-20>20-28|2026-09-25',
        )
        record = {
            'kind': 'regime+vix',
            'price_asof': '2026-09-25',
            'title': '[调仓] goldilocks → deflation（2026-09-25）',
            'fingerprint': nr.delivery_fingerprint(prev, cur, reasons),
            'delivery': 'failed',
        }
        self.assertEqual(nr.audit_issue_title(record), '[审计] 未发出象限切换与 VIX 跨档提醒（2026-09-25）')
        body = nr.audit_issue_body(record, '缺少 Issue')
        self.assertIn('audit-fingerprint:', body)
        self.assertIn(record['fingerprint'], body)
        self.assertIn('不走 SMTP', body)
        self.assertIn('rebalance', body)
        forced = _state('goldilocks', '0-20', '正常', 15.0, checked_at='2026-09-28 23:00 UTC')
        _action_f, reasons_f = nr.classify_change(forced, forced, force=True)
        self.assertEqual(nr.delivery_kind(reasons_f), 'force')
        self.assertTrue(nr.delivery_fingerprint(forced, forced, reasons_f).startswith('force|'))


class AuditExecuteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._env = {
            'NOTIFY_STATE_PATH': os.environ.get('NOTIFY_STATE_PATH'),
            'NOTIFY_AUDIT_PATH': os.environ.get('NOTIFY_AUDIT_PATH'),
            'GITHUB_ACTIONS': os.environ.get('GITHUB_ACTIONS'),
            'GITHUB_OUTPUT': os.environ.get('GITHUB_OUTPUT'),
            'GITHUB_REPOSITORY': os.environ.get('GITHUB_REPOSITORY'),
            'GITHUB_TOKEN': os.environ.get('GITHUB_TOKEN'),
        }
        os.environ['NOTIFY_STATE_PATH'] = str(self.tmp / 'notify_state.json')
        os.environ['NOTIFY_AUDIT_PATH'] = str(self.tmp / 'notify_audit.json')
        os.environ['GITHUB_OUTPUT'] = str(self.tmp / 'github_output.txt')
        os.environ.pop('GITHUB_ACTIONS', None)
        os.environ.pop('GITHUB_REPOSITORY', None)
        os.environ.pop('GITHUB_TOKEN', None)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _swap_current(self, cur):
        real = nr.current_state
        nr.current_state = lambda: dict(cur)
        return real

    def _restore_current(self, real):
        nr.current_state = real

    def test_should_fire_records_issue_and_audit_passes(self):
        prev = _state('goldilocks', '0-20', '正常', 15.0)
        nr.write_state(prev)
        cur = _state('deflation', '0-20', '正常', 16.0, price_asof='2026-09-25')
        opened = []

        def opener(title, body):
            issue = _fake_issue(15, title)
            opened.append(issue)
            return issue

        real = self._swap_current(cur)
        try:
            action = nr.execute(nr.parse_args(['--github-issue']), opener=opener)
        finally:
            self._restore_current(real)
        self.assertEqual(action, 'notify')
        self.assertEqual(len(opened), 1)
        saved = json.loads(nr.state_path().read_text(encoding='utf-8'))
        self.assertEqual(saved['regime'], 'deflation')
        self.assertEqual(saved['last_delivery']['delivery'], 'created')
        self.assertEqual(saved['last_delivery']['issue_number'], 15)
        self.assertIn('/issues/15', saved['last_delivery']['issue_url'])
        self.assertTrue(saved['last_delivery']['should_fire'])
        run_log = nr.read_audit()
        self.assertEqual(run_log['delivery'], 'created')
        alerted = []

        def finder(record):
            self.assertEqual(record['issue_number'], 15)
            return _fake_issue(15, record['title'])

        result = nr.run_audit(
            finder=finder,
            alerter=lambda record, detail: alerted.append(detail),
            find_audit=lambda fp: None,
        )
        self.assertEqual(result, 'ok')
        self.assertEqual(alerted, [])
        self.assertIn('confirmed_miss=false', Path(os.environ['GITHUB_OUTPUT']).read_text(encoding='utf-8'))

    def test_should_fire_failure_does_not_advance_state_and_audit_alerts_once(self):
        prev = _state('goldilocks', '0-20', '正常', 15.0)
        nr.write_state(prev)
        original = nr.state_path().read_text(encoding='utf-8')
        cur = _state('deflation', '20-28', '偏高', 22.0, price_asof='2026-09-25')
        real = self._swap_current(cur)
        try:
            with self.assertRaises(SystemExit) as ctx:
                nr.execute(
                    nr.parse_args(['--github-issue']),
                    opener=lambda title, body: None,
                )
        finally:
            self._restore_current(real)
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(nr.state_path().read_text(encoding='utf-8'), original)
        run_log = nr.read_audit()
        self.assertTrue(run_log['should_fire'])
        self.assertEqual(run_log['delivery'], 'failed')
        self.assertEqual(run_log['kind'], 'regime+vix')
        alerted = []

        def alerter(record, detail):
            alerted.append(nr.audit_issue_title(record))
            self.assertIn('rebalance', nr.audit_issue_body(record, detail))
            return _fake_issue(90, alerted[-1])

        with self.assertRaises(SystemExit) as miss:
            nr.run_audit(finder=lambda record: None, alerter=alerter, find_audit=lambda fp: None)
        self.assertEqual(miss.exception.code, 1)
        self.assertEqual(alerted, ['[审计] 未发出象限切换与 VIX 跨档提醒（2026-09-25）'])
        self.assertIn('confirmed_miss=true', Path(os.environ['GITHUB_OUTPUT']).read_text(encoding='utf-8'))

        again = []
        result = nr.run_audit(
            finder=lambda record: None,
            alerter=lambda record, detail: again.append(record),
            find_audit=lambda fp: {'number': 90, 'html_url': 'https://github.com/fintechshan/FontesFund/issues/90'},
        )
        self.assertEqual(result, 'already_alerted')
        self.assertEqual(again, [])
        self.assertIn(
            'confirmed_miss=false',
            Path(os.environ['GITHUB_OUTPUT']).read_text(encoding='utf-8').splitlines()[-1],
        )

    def test_unverified_create_does_not_clear_confirmed_miss(self):
        record = {
            'schema': 1,
            'action': 'notify',
            'should_fire': True,
            'kind': 'vix',
            'title': '[风险档位] VIX 28.6 → 开始降敞口（2026-09-25）',
            'fingerprint': 'vix|goldilocks>goldilocks|0-20>28-30|2026-09-25',
            'delivery': 'created',
            'issue_number': 7,
            'issue_url': 'https://github.com/fintechshan/FontesFund/issues/7',
            'checked_at': '2026-09-25 23:05 UTC',
            'checked_at_iso': '2026-09-25T23:05:00Z',
            'price_asof': '2026-09-25',
            'error': None,
        }
        nr.write_audit(record)
        nr.write_state(_state('goldilocks', '28-30', '开始降敞口', 28.6))
        alerted = []
        result = nr.run_audit(
            finder=lambda rec: None,
            alerter=lambda rec, detail: alerted.append(rec),
            find_audit=lambda fp: {
                'number': 3,
                'html_url': 'https://github.com/fintechshan/FontesFund/issues/3',
            },
        )
        self.assertEqual(result, 'already_alerted')
        self.assertEqual(alerted, [])
        self.assertIn(
            'confirmed_miss=true',
            Path(os.environ['GITHUB_OUTPUT']).read_text(encoding='utf-8').splitlines()[-1],
        )

    def test_recovered_issue_is_not_a_miss(self):
        prev = _state('goldilocks', '0-20', '正常', 18.0)
        nr.write_state(prev)
        cur = _state('goldilocks', '28-30', '开始降敞口', 28.6, price_asof='2026-09-25')
        real = self._swap_current(cur)
        try:
            with self.assertRaises(SystemExit):
                nr.execute(nr.parse_args(['--github-issue']), opener=lambda title, body: {})
        finally:
            self._restore_current(real)
        alerted = []
        result = nr.run_audit(
            finder=lambda record: _fake_issue(4, record['title']),
            alerter=lambda record, detail: alerted.append(record),
            find_audit=lambda fp: None,
        )
        self.assertEqual(result, 'ok')
        self.assertEqual(alerted, [])

    def test_no_fire_audit_is_quiet(self):
        cur = _state('stagflation', '30-40', '大幅降敞口 / 象限转 deflation', 32.0)
        nr.write_state(cur)
        real = self._swap_current(dict(cur, checked_at='2026-09-28 23:10 UTC', vix=33.0))
        try:
            action = nr.execute(nr.parse_args([]))
        finally:
            self._restore_current(real)
        self.assertEqual(action, 'silent')
        self.assertFalse(nr.read_audit()['should_fire'])
        looked = []
        alerted = []
        result = nr.run_audit(
            finder=lambda record: looked.append(record),
            alerter=lambda record, detail: alerted.append(record),
            find_audit=lambda fp: alerted.append(fp),
        )
        self.assertEqual(result, 'ok')
        self.assertEqual(looked, [])
        self.assertEqual(alerted, [])

    def test_silent_day_still_fails_when_recorded_issue_is_gone(self):
        cur = _state('goldilocks', '0-20', '正常', 15.0)
        cur['last_delivery'] = {
            'schema': 1,
            'action': 'notify',
            'should_fire': True,
            'kind': 'regime',
            'title': '[调仓] reflation → goldilocks（2026-09-01）',
            'fingerprint': 'regime|reflation>goldilocks|0-20>0-20|2026-09-01',
            'delivery': 'created',
            'issue_number': 8,
            'issue_url': 'https://github.com/fintechshan/FontesFund/issues/8',
            'checked_at': cur['checked_at'],
            'checked_at_iso': '2026-09-01T23:00:00Z',
            'price_asof': '2026-09-01',
            'error': None,
        }
        nr.write_state(cur)
        nr.write_audit(nr.blank_audit('silent', cur))
        alerted = []

        def alerter(record, detail):
            alerted.append(nr.audit_issue_title(record))
            return {'number': 91, 'html_url': 'https://github.com/fintechshan/FontesFund/issues/91'}

        with self.assertRaises(SystemExit):
            nr.run_audit(finder=lambda record: None, alerter=alerter, find_audit=lambda fp: None)
        self.assertEqual(alerted, ['[审计] 未发出象限切换提醒（2026-09-01）'])

    def test_force_success_and_force_failure(self):
        prev = _state('goldilocks', '0-20', '正常', 15.0, checked_at='2026-09-28 23:00 UTC')
        nr.write_state(prev)
        real = self._swap_current(dict(prev))
        try:
            action = nr.execute(
                nr.parse_args(['--github-issue', '--force']),
                opener=lambda title, body: _fake_issue(21, title),
            )
        finally:
            self._restore_current(real)
        self.assertEqual(action, 'notify')
        saved = json.loads(nr.state_path().read_text(encoding='utf-8'))
        self.assertEqual(saved['regime'], 'goldilocks')
        self.assertEqual(saved['last_delivery']['kind'], 'force')
        self.assertTrue(saved['last_delivery']['title'].startswith('[测试]'))
        self.assertEqual(saved['last_delivery']['issue_number'], 21)
        result = nr.run_audit(
            finder=lambda record: _fake_issue(21, record['title']),
            alerter=lambda record, detail: self.fail('force delivery should pass'),
            find_audit=lambda fp: None,
        )
        self.assertEqual(result, 'ok')

        nr.write_state(prev)
        real = self._swap_current(dict(prev))
        try:
            with self.assertRaises(SystemExit):
                nr.execute(
                    nr.parse_args(['--github-issue', '--force']),
                    opener=lambda title, body: (_ for _ in ()).throw(RuntimeError('boom')),
                )
        finally:
            self._restore_current(real)
        self.assertNotIn('last_delivery', json.loads(nr.state_path().read_text(encoding='utf-8')))
        failed = nr.read_audit()
        self.assertEqual(failed['kind'], 'force')
        self.assertEqual(failed['delivery'], 'failed')
        self.assertTrue(failed['should_fire'])
        alerted = []
        with self.assertRaises(SystemExit):
            nr.run_audit(
                finder=lambda record: None,
                alerter=lambda record, detail: alerted.append(nr.audit_issue_title(record)) or {
                    'number': 92,
                    'html_url': 'https://github.com/fintechshan/FontesFund/issues/92',
                },
                find_audit=lambda fp: None,
            )
        self.assertEqual(alerted, ['[审计] 未发出强制测试提醒（2026-09-15）'])

    def test_actions_without_github_issue_does_not_advance_state(self):
        prev = _state('goldilocks', '0-20', '正常', 15.0)
        nr.write_state(prev)
        cur = _state('stagflation', '0-20', '正常', 16.0)
        os.environ['GITHUB_ACTIONS'] = 'true'
        real = self._swap_current(cur)
        try:
            with self.assertRaises(SystemExit) as ctx:
                nr.execute(nr.parse_args([]))
        finally:
            self._restore_current(real)
            os.environ.pop('GITHUB_ACTIONS', None)
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(json.loads(nr.state_path().read_text(encoding='utf-8'))['regime'], 'goldilocks')
        self.assertEqual(nr.read_audit()['delivery'], 'skipped')
        self.assertTrue(nr.read_audit()['should_fire'])

    def test_local_print_does_not_advance_state(self):
        prev = _state('goldilocks', '0-20', '正常', 15.0)
        nr.write_state(prev)
        cur = _state('reflation', '0-20', '正常', 16.0)
        real = self._swap_current(cur)
        try:
            action = nr.execute(nr.parse_args([]))
        finally:
            self._restore_current(real)
        self.assertEqual(action, 'notify')
        self.assertEqual(json.loads(nr.state_path().read_text(encoding='utf-8'))['regime'], 'goldilocks')
        self.assertEqual(nr.read_audit()['delivery'], 'printed_only')

    def test_numbered_lookup_ignores_window_and_404_can_search(self):
        os.environ['GITHUB_REPOSITORY'] = 'fintechshan/FontesFund'
        os.environ['GITHUB_TOKEN'] = 'test-token'
        record = {
            'title': '[调仓] goldilocks → deflation（2026-09-25）',
            'issue_number': 4,
            'checked_at_iso': '2020-01-02T00:00:00Z',
            'fingerprint': 'regime|goldilocks>deflation|0-20>0-20|2026-09-25',
        }
        issue = _fake_issue(4, record['title'], created_at='2020-01-01T00:00:00Z')
        calls = []
        real_github = nr._github
        real_sleep = nr.time.sleep

        def fake_github(method, url, token, payload=None):
            calls.append(url)
            self.assertEqual(token, 'test-token')
            if url.endswith('/issues/4'):
                return issue
            raise AssertionError(url)

        nr._github = fake_github
        nr.time.sleep = lambda _seconds: None
        try:
            found = nr.github_find_rebalance(record)
        finally:
            nr._github = real_github
            nr.time.sleep = real_sleep
        self.assertEqual(found['number'], 4)
        self.assertTrue(any(url.endswith('/issues/4') for url in calls))
        self.assertFalse(any('labels=rebalance' in url or 'labels=' in url for url in calls))

        calls.clear()

        def missing_then_search(method, url, token, payload=None):
            calls.append(url)
            if url.endswith('/issues/4'):
                raise nr.GitHubAPIError(404, 'missing')
            self.assertIn('labels=rebalance', url)
            stale = _fake_issue(1, record['title'], created_at='2019-01-01T00:00:00Z')
            return [stale]

        nr._github = missing_then_search
        nr.time.sleep = lambda _seconds: None
        try:
            found = nr.github_find_rebalance(record)
        finally:
            nr._github = real_github
            nr.time.sleep = real_sleep
        self.assertIsNone(found)
        self.assertGreaterEqual(sum(url.endswith('/issues/4') for url in calls), 3)


if __name__ == '__main__':
    unittest.main()
