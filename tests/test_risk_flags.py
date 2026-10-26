"""Risk-flag scorecard. Fixtures only — no Yahoo, no orders."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from src.risk_flags import (  # noqa: E402
    FLAG_IDS,
    TACTICAL_FLAG_IDS,
    compute_flag_frame,
    compute_snapshot,
    load_notify_block,
    rising_flag_ids,
    risk_flags_changed,
)


def _index(n, start='2018-01-02'):
    return pd.bdate_range(start, periods=n)


def _prices_from_returns(returns, start=100.0, start_date='2018-01-02'):
    rets = np.asarray(returns, dtype=float)
    level = start * np.cumprod(1.0 + rets)
    # cumprod applies to returns; the first price should exist before the first return.
    # Build close[0] = start, close[t] = close[t-1] * (1+ret[t]).
    close = np.empty(len(rets))
    close[0] = start
    for i in range(1, len(rets)):
        close[i] = close[i - 1] * (1.0 + rets[i])
    return pd.Series(close, index=_index(len(rets), start_date), name='SOXX')


def _calm(n=400, noise=0.0004):
    t = np.arange(n)
    rets = np.full(n, 0.0002) + noise * np.sin(t / 3.0)
    rets[0] = 0.0
    return _prices_from_returns(rets)


def _shock_soxx():
    px = _calm(400)
    # Explosive last 30 sessions so RV20 clears the expanding 80th percentile.
    rets = np.resize([0.045, -0.045], 30)
    close = px.to_numpy(dtype=float).copy()
    for i, ret in enumerate(rets):
        close[-30 + i] = close[-31 + i] * (1.0 + ret)
    return pd.Series(close, index=px.index, name='SOXX')


class LagAndLookaheadTests(unittest.TestCase):
    def test_published_flag_uses_prior_session(self):
        soxx = _shock_soxx()
        vix = pd.Series(16.0, index=soxx.index, name='VIX')
        frame, meta = compute_flag_frame(soxx, vix, vxn=None)
        self.assertEqual(meta['modes']['A_vol'], 'soxx_only')
        lagged = frame['A_vol']
        raw = frame['A_vol_raw']
        self.assertTrue(bool(raw.iloc[-1]) or bool(raw.iloc[-2]))
        compared = pd.Series(raw.shift(1).iloc[1:].to_numpy(), index=lagged.index[1:])
        pd.testing.assert_series_equal(
            lagged.iloc[1:].astype(float),
            compared.astype(float),
            check_names=False,
        )
        # The last print is yesterday's condition, not today's.
        self.assertEqual(float(lagged.iloc[-1]), float(raw.iloc[-2]))

    def test_last_bar_does_not_change_earlier_flags(self):
        soxx = _shock_soxx()
        vix = pd.Series(16.0, index=soxx.index)
        vxn = pd.Series(18.0, index=soxx.index)
        full, _meta = compute_flag_frame(soxx, vix, vxn)
        trunc, _meta_t = compute_flag_frame(soxx.iloc[:-1], vix.iloc[:-1], vxn.iloc[:-1])
        for key in TACTICAL_FLAG_IDS:
            pd.testing.assert_series_equal(
                full[key].iloc[:-1],
                trunc[key],
                check_names=False,
                check_freq=False,
            )
        spiked = soxx.copy()
        spiked.iloc[-1] = spiked.iloc[-1] * 1.8
        spiked_frame, _meta_s = compute_flag_frame(spiked, vix, vxn)
        for key in TACTICAL_FLAG_IDS:
            pd.testing.assert_series_equal(
                full[key].iloc[:-1],
                spiked_frame[key].iloc[:-1],
                check_names=False,
                check_freq=False,
            )

    def test_short_history_does_not_fire_q80(self):
        soxx = _shock_soxx().iloc[:80]
        vix = pd.Series(40.0, index=soxx.index)
        frame, meta = compute_flag_frame(soxx, vix, vxn=None)
        self.assertEqual(meta['modes']['A_vol'], 'soxx_only')
        self.assertFalse(bool(frame['A_vol_raw'].fillna(0).max()))


class RuleTests(unittest.TestCase):
    def test_a_vol_soxx_or_vxn(self):
        flat = _prices_from_returns(np.zeros(400))
        vix = pd.Series(15.0, index=flat.index)
        calm_frame, _meta = compute_flag_frame(flat, vix, vxn=pd.Series(18.0, index=flat.index))
        self.assertEqual(float(calm_frame['A_vol'].dropna().max()), 0.0)

        shocked = _shock_soxx()
        shock_frame, meta = compute_flag_frame(shocked, vix.reindex(shocked.index), vxn=None)
        self.assertEqual(meta['modes']['A_vol'], 'soxx_only')
        self.assertGreater(float(shock_frame['A_vol'].fillna(0).max()), 0.0)
        snap = compute_snapshot(shocked, vix.reindex(shocked.index), today=shocked.index[-1])
        self.assertEqual(snap['flags']['A_vol']['mode'], 'soxx_only')
        self.assertNotIn('降级', snap['flags']['A_vol']['rule_zh'])
        self.assertIn('未改用 VIX≥30', snap['flags']['A_vol']['detail'])

        vxn = pd.Series(18.0, index=flat.index)
        vxn.iloc[-5:] = 80.0
        vxn_frame, vxn_meta = compute_flag_frame(flat, vix, vxn)
        self.assertEqual(vxn_meta['modes']['A_vol'], 'full')
        self.assertGreater(float(vxn_frame['A_vol'].fillna(0).max()), 0.0)

    def test_b_crowd_needs_range_or_streak(self):
        # Wide historical range keeps the expanding median high, so a mild
        # 4-day slide is the streak leg and not the range leg.
        n = 80
        rets = np.resize([0.15, -0.15], n)
        rets[-25:] = 0.0
        rets[-5:] = -0.014
        soxx = _prices_from_returns(rets, start_date='2024-01-02')
        vix = pd.Series(14.0, index=soxx.index)
        frame, meta = compute_flag_frame(soxx, vix)
        self.assertEqual(meta['modes']['B_crowd'], 'full')
        self.assertEqual(float(frame['B_crowd'].iloc[-1]), 1.0)
        signal = frame.iloc[-2]
        self.assertGreaterEqual(float(signal['streak']), 4.0)
        self.assertLessEqual(float(signal['ret_5']), -0.05)
        self.assertGreater(float(signal['ret_5']), -0.08)
        self.assertFalse(bool(signal['range_ratio'] > signal['range_median']))

        # One gap day after a wild history: 5d ≤ −8%, but the 10d range is
        # still under the expanding median, and the streak is a single day.
        rets = np.resize([0.20, -0.20], 80)
        rets[-20:] = 0.0
        rets[-1] = -0.09
        gap = _prices_from_returns(rets, start_date='2024-06-03')
        gap_frame, _meta = compute_flag_frame(gap, pd.Series(14.0, index=gap.index))
        self.assertEqual(float(gap_frame['B_crowd_raw'].iloc[-1]), 0.0)
        self.assertLessEqual(float(gap_frame['ret_5'].iloc[-1]), -0.08)
        self.assertLess(float(gap_frame['streak'].iloc[-1]), 4.0)

        # Same drop, but the window's range is wide versus a quiet history.
        quiet = np.full(40, 0.0005)
        quiet[-5:] = -0.02
        wide = _prices_from_returns(quiet, start_date='2024-06-03')
        wide_frame, _meta = compute_flag_frame(wide, pd.Series(14.0, index=wide.index))
        self.assertEqual(float(wide_frame['B_crowd_raw'].iloc[-1]), 1.0)
        self.assertLessEqual(float(wide_frame['ret_5'].iloc[-1]), -0.08)
        self.assertGreater(
            float(wide_frame['range_ratio'].iloc[-1]),
            float(wide_frame['range_median'].iloc[-1]),
        )

    def test_c_put_is_the_conjunction(self):
        n = 80
        rets = np.zeros(n)
        rets[-12:] = -0.012
        soxx = _prices_from_returns(rets, start_date='2024-03-01')
        vix = pd.Series(18.0, index=soxx.index)
        vix.iloc[-8:] = [20, 21, 23, 26, 27, 28, 29, 31]
        frame, meta = compute_flag_frame(soxx, vix)
        self.assertEqual(meta['modes']['C_put'], 'full')
        self.assertEqual(float(frame['C_put_raw'].iloc[-2]), 1.0)
        self.assertEqual(float(frame['C_put'].iloc[-1]), 1.0)
        # Not rising: VIX high but flat over 5 sessions.
        flat_vix = pd.Series(30.0, index=soxx.index)
        flat_frame, _meta = compute_flag_frame(soxx, flat_vix)
        self.assertEqual(float(flat_frame['C_put_raw'].max()), 0.0)
        # Price still above the 50-day average: no flag.
        up = _prices_from_returns(np.full(n, 0.002), start_date='2024-03-01')
        up_vix = pd.Series(18.0, index=up.index)
        up_vix.iloc[-8:] = [20, 22, 24, 26, 28, 30, 32, 34]
        up_frame, _meta = compute_flag_frame(up, up_vix)
        self.assertEqual(float(up_frame['C_put_raw'].max()), 0.0)

    def test_degrade_when_soxx_and_vxn_missing(self):
        idx = _index(30, '2024-01-02')
        vix = pd.Series(18.0, index=idx)
        vix.iloc[-3:] = 31.0
        frame, meta = compute_flag_frame(None, vix, vxn=None)
        self.assertEqual(meta['modes']['A_vol'], 'vix30_fallback')
        self.assertEqual(meta['modes']['B_crowd'], 'skipped')
        self.assertEqual(meta['modes']['C_put'], 'skipped')
        self.assertEqual(float(frame['A_vol'].iloc[-1]), 1.0)
        snap = compute_snapshot(None, vix, today=idx[-1])
        self.assertTrue(snap['flags']['A_vol']['on'])
        self.assertIn('VIX ≥ 30', snap['flags']['A_vol']['rule_en'])
        self.assertIn('降级', snap['flags']['A_vol']['rule_zh'])
        self.assertEqual(snap['flags']['B_crowd']['status'], 'skipped')
        self.assertEqual(snap['flags']['C_put']['status'], 'skipped')
        self.assertFalse(snap['flags']['C_put']['on'])
        self.assertIn('卖 Put', snap['flags']['C_put']['rule_zh'])
        self.assertIn('不是高盛', snap['flags']['B_crowd']['rule_zh'])
        self.assertFalse(snap['orders'])
        self.assertFalse(snap['weights'])
        self.assertEqual(snap['banner_zh'], '通知 / 不改仓')

    def test_empty_inputs_skip(self):
        snap = compute_snapshot(None, None, None)
        self.assertTrue(snap['unavailable'])
        for key in FLAG_IDS:
            self.assertEqual(snap['flags'][key]['status'], 'skipped')
            self.assertFalse(snap['flags'][key]['on'])


class NotifyEdgeTests(unittest.TestCase):
    def test_rising_edge_only(self):
        off = {'A_vol': False, 'B_crowd': False, 'C_put': False, 'status': {}}
        on_a = dict(off, A_vol=True)
        self.assertEqual(rising_flag_ids(None, on_a), [])
        self.assertEqual(rising_flag_ids(off, on_a), ['A_vol'])
        self.assertEqual(rising_flag_ids(on_a, on_a), [])
        both = dict(on_a, B_crowd=True)
        self.assertEqual(rising_flag_ids(on_a, both), ['B_crowd'])
        self.assertTrue(risk_flags_changed(off, on_a))
        self.assertFalse(risk_flags_changed(on_a, dict(on_a, as_of='2026-10-16')))
        self.assertTrue(risk_flags_changed(None, off))

    def test_notify_hook_fires_on_edge_and_stays_quiet_while_on(self):
        import notify_regime as nr

        prev = {
            'schema': 1,
            'regime': 'reflation',
            'vix_band': '0-20',
            'vix_band_name': '正常',
            'vix': 16.0,
            'price_asof': '2026-10-15',
            'checked_at': '2026-10-15 23:00 UTC',
            'risk_flags': {
                'as_of': '2026-10-14',
                'A_vol': False,
                'B_crowd': False,
                'C_put': False,
                'status': {'A_vol': 'off', 'B_crowd': 'off', 'C_put': 'off'},
                'mode': {'A_vol': 'full', 'B_crowd': 'full', 'C_put': 'full'},
                'detail': {'A_vol': 'calm', 'B_crowd': 'calm', 'C_put': 'calm'},
                'rule_zh': {key: key for key in FLAG_IDS},
            },
        }
        cur = dict(prev)
        cur['price_asof'] = '2026-10-16'
        cur['checked_at'] = '2026-10-16 23:00 UTC'
        cur['risk_flags'] = dict(prev['risk_flags'])
        cur['risk_flags']['as_of'] = '2026-10-16'
        cur['risk_flags']['A_vol'] = True
        cur['risk_flags']['status'] = dict(prev['risk_flags']['status'], A_vol='on')
        action, reasons = nr.classify_change(prev, cur, force=False)
        self.assertEqual(action, 'notify')
        self.assertEqual(reasons['risk_flags'], 'A_vol')
        self.assertNotIn('regime', reasons)
        title, body = nr.build_message(prev, cur, reasons)
        self.assertTrue(title.startswith('[风险旗]'))
        self.assertIn('A_vol', title)
        self.assertIn('通知 / 不改仓', body)
        self.assertIn('不改仓', body)
        self.assertIn('卖 Put', body)
        self.assertNotIn('减持 ', body)
        self.assertNotIn('--execute', body)
        self.assertNotIn('| 标的 |', body)
        self.assertEqual(nr.delivery_kind(reasons), 'flags')

        sticky = dict(cur)
        sticky_action, sticky_reasons = nr.classify_change(cur, sticky, force=False)
        self.assertEqual(sticky_action, 'silent')
        self.assertEqual(sticky_reasons, {})

        cleared = dict(cur)
        cleared['risk_flags'] = dict(prev['risk_flags'], as_of='2026-10-17')
        off_action, off_reasons = nr.classify_change(cur, cleared, force=False)
        self.assertEqual(off_action, 'silent')
        self.assertTrue(nr.risk_flag_state_changed(cur, cleared))

    def test_first_sight_does_not_notify_and_regime_title_stays(self):
        import notify_regime as nr

        prev = {
            'schema': 1,
            'regime': 'goldilocks',
            'vix_band': '0-20',
            'vix_band_name': '正常',
            'vix': 15.0,
            'price_asof': '2026-10-15',
            'checked_at': '2026-10-15 23:00 UTC',
        }
        cur = dict(prev)
        cur['risk_flags'] = {
            'as_of': '2026-10-15',
            'A_vol': True,
            'B_crowd': False,
            'C_put': False,
            'status': {'A_vol': 'on', 'B_crowd': 'off', 'C_put': 'off'},
        }
        action, reasons = nr.classify_change(prev, cur, force=False)
        self.assertEqual(action, 'silent')
        self.assertNotIn('risk_flags', reasons)

        changed = dict(cur, regime='deflation', price_asof='2026-10-16')
        action_r, reasons_r = nr.classify_change(prev, changed, force=False)
        self.assertEqual(action_r, 'notify')
        self.assertIn('regime', reasons_r)
        self.assertNotIn('risk_flags', reasons_r)
        self.assertEqual(nr.delivery_kind(reasons_r), 'regime')
        title, _body = nr.build_message(prev, changed, reasons_r)
        self.assertIn('调仓', title)
        self.assertFalse(title.startswith('[风险旗]'))


class IsolationTests(unittest.TestCase):
    def test_trading_paths_do_not_reference_flags(self):
        banned_files = [
            'src/backtester/engine.py',
            'src/backtester/daily_overlay.py',
            'src/execution/order_manager.py',
            'src/execution/risk_manager.py',
            'scripts/ibkr_rebalance.py',
            'config/regime_rules.py',
            'config/cdn_regime_rules.py',
        ]
        module = (ROOT / 'src' / 'risk_flags.py').read_text(encoding='utf-8')
        self.assertNotIn('from config.regime_rules', module)
        self.assertNotIn('from config.cdn_regime_rules', module)
        self.assertNotIn('ibkr_rebalance', module)
        self.assertNotIn('run_optimized_regime_backtest', module)
        self.assertNotIn('placeOrder', module)
        for rel in banned_files:
            text = (ROOT / rel).read_text(encoding='utf-8')
            self.assertNotIn('risk_flags', text, rel)
            self.assertNotIn('A_vol', text, rel)
            self.assertNotIn('B_crowd', text, rel)
            self.assertNotIn('C_put', text, rel)

    def test_stale_or_missing_snapshot_is_not_a_notify_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'flags.json'
            self.assertIsNone(load_notify_block(missing))
            stale = compute_snapshot(_shock_soxx(), pd.Series(15.0, index=_shock_soxx().index), today='2030-01-01')
            path = Path(tmp) / 'stale.json'
            path.write_text(json.dumps(stale), encoding='utf-8')
            self.assertTrue(stale['stale'])
            self.assertIsNone(load_notify_block(path))


class NotifyDeliveryTests(unittest.TestCase):
    def test_missing_sendkey_does_not_call_network(self):
        import notify_regime as nr

        old = os.environ.pop('SERVERCHAN_SENDKEY', None)
        called = []
        real = nr.urllib.request.urlopen
        nr.urllib.request.urlopen = lambda *args, **kwargs: called.append(args)
        try:
            result = nr.push_serverchan('风险旗', '通知 / 不改仓')
            self.assertIsNone(nr.serverchan_endpoint(''))
            self.assertIsNone(nr.serverchan_endpoint('SCT bad'))
            endpoint = nr.serverchan_endpoint('SCT1234Tdemo')
        finally:
            nr.urllib.request.urlopen = real
            if old is None:
                os.environ.pop('SERVERCHAN_SENDKEY', None)
            else:
                os.environ['SERVERCHAN_SENDKEY'] = old
        self.assertEqual(result, {'status': 'skipped', 'reason': 'missing_sendkey'})
        self.assertEqual(called, [])
        self.assertEqual(endpoint, 'https://sctapi.ftqq.com/SCT1234Tdemo.send')
        self.assertLessEqual(len(nr.wechat_title('风险旗 ' + ('甲' * 80))), 40)

    def test_first_sight_persists_on_silent_and_does_not_open_issue(self):
        import notify_regime as nr

        old = {
            'NOTIFY_STATE_PATH': os.environ.get('NOTIFY_STATE_PATH'),
            'NOTIFY_AUDIT_PATH': os.environ.get('NOTIFY_AUDIT_PATH'),
            'RISK_FLAGS_PATH': os.environ.get('RISK_FLAGS_PATH'),
            'SERVERCHAN_SENDKEY': os.environ.get('SERVERCHAN_SENDKEY'),
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            os.environ['NOTIFY_STATE_PATH'] = str(tmp / 'state.json')
            os.environ['NOTIFY_AUDIT_PATH'] = str(tmp / 'audit.json')
            os.environ['RISK_FLAGS_PATH'] = str(tmp / 'missing.json')
            os.environ.pop('SERVERCHAN_SENDKEY', None)
            prev = {
                'schema': 1,
                'regime': 'reflation',
                'vix_band': '0-20',
                'vix_band_name': '正常',
                'vix': 16.0,
                'price_asof': '2026-10-15',
                'checked_at': '2026-10-15 23:00 UTC',
            }
            nr.write_state(prev)
            cur = dict(prev)
            cur['risk_flags'] = {
                'as_of': '2026-10-15',
                'A_vol': True,
                'B_crowd': False,
                'C_put': False,
                'status': {'A_vol': 'on', 'B_crowd': 'off', 'C_put': 'off'},
            }
            opened = []
            real = nr.current_state
            nr.current_state = lambda: dict(cur)
            try:
                action = nr.execute(nr.parse_args([]), opener=lambda title, body: opened.append(title))
            finally:
                nr.current_state = real
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            self.assertEqual(action, 'silent')
            self.assertEqual(opened, [])
            saved = json.loads((tmp / 'state.json').read_text(encoding='utf-8'))
            self.assertTrue(saved['risk_flags']['A_vol'])
            self.assertNotIn('last_delivery', saved)
            audit = json.loads((tmp / 'audit.json').read_text(encoding='utf-8'))
            self.assertFalse(audit['should_fire'])


class DashboardCardTests(unittest.TestCase):
    def test_vegas_tab_shows_notify_only_card(self):
        from src.dashboard.app import _risk_flags_panel_children, build_qqq_vegas_tab
        from src.risk_flags import unavailable_snapshot

        def _walk(node, acc):
            if node is None or isinstance(node, dict):
                return
            if isinstance(node, str):
                acc.append(node)
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    _walk(item, acc)
                return
            _walk(getattr(node, 'children', None), acc)

        snap = unavailable_snapshot('fixture')
        acc = []
        for child in _risk_flags_panel_children(snap):
            _walk(child, acc)
        blob = '\n'.join(acc)
        self.assertIn('通知 / 不改仓', blob)
        self.assertIn('A_vol', blob)
        self.assertIn('B_crowd', blob)
        self.assertIn('C_put', blob)
        self.assertIn('卖 Put', blob)
        self.assertIn('不是高盛', blob)
        self.assertIn('SKIP', blob)
        self.assertFalse(snap['orders'])
        tab = build_qqq_vegas_tab()
        found = []

        def _find(node):
            if getattr(node, 'id', None) == 'risk-flags-panel':
                found.append(node)
            children = getattr(node, 'children', None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    _find(child)
            elif children is not None and not isinstance(children, (str, dict)):
                _find(children)

        _find(tab)
        self.assertEqual(len(found), 1)
        tab_acc = []
        _walk(found[0], tab_acc)
        self.assertIn('通知 / 不改仓', '\n'.join(tab_acc))


if __name__ == '__main__':
    unittest.main()
