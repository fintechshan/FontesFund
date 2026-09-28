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
        raw = json.dumps({'title': title, 'body': body}, ensure_ascii=False).encode('utf-8')
        self.assertIn('调仓'.encode('utf-8'), raw)
        restored = json.loads(raw.decode('utf-8'))
        self.assertEqual(restored['title'], title)
        self.assertIn('→', restored['title'])

    def test_source_file_is_utf8(self):
        text = (ROOT / 'scripts' / 'notify_regime.py').read_text(encoding='utf-8')
        self.assertIn('调仓', text)
        self.assertIn('DateOffset(months=1)', (ROOT / 'run_dashboard.py').read_text(encoding='utf-8'))


class ClassifierLagTests(unittest.TestCase):
    def test_compute_state_uses_publication_lag(self):
        macro, price = _spiked_inputs()
        state = nr.compute_state(macro, price)
        self.assertEqual(state['regime'], 'goldilocks')
        self.assertEqual(state['vix_band'], '0-20')
        fn = nr.load_classifier()
        _hist, unlagged, _derived = fn(macro, price, apply_lag=False)
        self.assertEqual(unlagged['regime'], 'reflation')
        sig_default = fn.__defaults__
        self.assertEqual(sig_default, (True,))


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._old_state = os.environ.get('NOTIFY_STATE_PATH')
        os.environ['NOTIFY_STATE_PATH'] = str(self.tmp / 'notify_state.json')

    def tearDown(self):
        if self._old_state is None:
            os.environ.pop('NOTIFY_STATE_PATH', None)
        else:
            os.environ['NOTIFY_STATE_PATH'] = self._old_state
        self._tmp.cleanup()

    def test_parse_args(self):
        args = nr.parse_args(['--dry-run', '--force', '--github-issue', '--refresh'])
        self.assertTrue(args.dry_run and args.force and args.github_issue and args.refresh)

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
        # dry-run must not clobber the baseline
        self.assertEqual(json.loads(nr.state_path().read_text(encoding='utf-8'))['regime'], 'goldilocks')

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


if __name__ == '__main__':
    unittest.main()
