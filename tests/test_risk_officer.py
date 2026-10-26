"""Structural flags D/E/F. Fixtures only — no EDGAR, no FRED, no orders."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from src.risk_flags import (  # noqa: E402
    FLAG_IDS,
    STRUCTURAL_FLAG_IDS,
    attach_structural,
    bubble_pressure_score,
    compute_snapshot,
    to_notify_block,
)
from src.risk_officer.capex_analyzer import (  # noqa: E402
    PUBLIC_NAMES,
    TEMPLATE_NAME,
    align_quarterly_musd,
    build_official_table,
    capex_signal_from_totals,
    evaluate_capex_sources,
    evaluate_capex_table,
    load_capex_csv,
    nearest_calendar_quarter,
    quarterly_from_facts,
)
from src.risk_officer.concentration_analyzer import (  # noqa: E402
    concentration_on,
    concentration_path,
    evaluate_concentration_series,
    holdings_table_from_raw,
    weight_from_holdings_frame,
)
from src.risk_officer.credit_analyzer import (  # noqa: E402
    credit_raw_on,
    evaluate_credit_series,
    parse_fred_csv,
    to_bps,
)

SPACEX_NOTE = 'SpaceX excluded: private company, cell left blank, no official SpaceX figure.'


def _quarters(n=7, start='2019Q1'):
    return [str(period) for period in pd.period_range(start, periods=n, freq='Q-DEC')]


def _table(values, status='OFFICIAL', notes=SPACEX_NOTE, spacex='', extra=None):
    rows = []
    for quarter, total in zip(_quarters(len(values)), values):
        share = float(total) / 6.0
        row = {
            'calendar_q': quarter,
            'status': status,
            'source_notes': notes,
            'spacex_musd': spacex,
            'total_musd': total,
        }
        for name in PUBLIC_NAMES:
            row[f'{name}_musd'] = share
        rows.append(row)
    if extra:
        rows.append(extra)
    return pd.DataFrame(rows)


def _blank_pending(quarter):
    row = {
        'calendar_q': quarter,
        'status': 'PENDING_EARNINGS',
        'source_notes': 'blank placeholder. SpaceX is private.',
        'spacex_musd': '',
        'total_musd': '',
    }
    for name in PUBLIC_NAMES:
        row[f'{name}_musd'] = ''
    return row


class CapexFormulaTests(unittest.TestCase):
    def test_steep_drop_two_quarter_and_boundaries(self):
        steep = pd.Series(
            [100, 100, 100, 100, 140, 140, 110],
            index=pd.period_range('2019Q1', periods=7, freq='Q-DEC'),
        )
        steep_sig = capex_signal_from_totals(steep)
        self.assertTrue(steep_sig['on'])
        self.assertEqual(steep_sig['reason'], 'steep_drop')
        self.assertLess(steep_sig['yoy'], 15)
        self.assertLessEqual(steep_sig['delta'], -5)

        two = pd.Series(
            [100, 100, 100, 100, 126, 123, 121],
            index=steep.index,
        )
        two_sig = capex_signal_from_totals(two)
        self.assertTrue(two_sig['on'])
        self.assertEqual(two_sig['reason'], 'two_quarter')
        self.assertGreaterEqual(two_sig['yoy'], 15)

        exact = pd.Series(
            [100, 100, 100, 100, 130, 128, 126],
            index=steep.index,
        )
        exact_sig = capex_signal_from_totals(exact)
        self.assertTrue(exact_sig['on'])
        self.assertEqual(exact_sig['reason'], 'two_quarter')
        self.assertAlmostEqual(exact_sig['delta'] + exact_sig['prev_delta'], -4.0)

        shy = pd.Series(
            [100, 100, 100, 100, 130, 129, 127],
            index=steep.index,
        )
        self.assertFalse(capex_signal_from_totals(shy)['on'])

        flat = pd.Series([100, 100, 100, 100, 120, 120, 120], index=steep.index)
        self.assertFalse(capex_signal_from_totals(flat)['on'])

        boundary = pd.Series(
            [100, 100, 100, 100, 120, 120, 115],
            index=steep.index,
        )
        boundary_sig = capex_signal_from_totals(boundary)
        self.assertAlmostEqual(boundary_sig['yoy'], 15.0)
        self.assertAlmostEqual(boundary_sig['delta'], -5.0)
        self.assertFalse(boundary_sig['on'])

    def test_pending_inherits_and_does_not_front_run(self):
        values = [100, 100, 100, 100, 140, 140, 110]
        pending = {
            'calendar_q': '2020Q4',
            'status': 'PENDING_EARNINGS',
            'source_notes': 'partial print before the filing is complete',
            'msft_musd': 999,
            'spacex_musd': '',
        }
        table = _table(values, extra=pending)
        stayed = evaluate_capex_table(table, {'name': 'D_capex', 'on': False, 'status': 'off'})
        self.assertFalse(stayed['on'])
        self.assertEqual(stayed['status'], 'off')
        self.assertEqual(stayed['mode'], 'pending_inherit')
        self.assertIn('PENDING_EARNINGS', stayed['pending_notice'])
        self.assertIn('不抢跑', stayed['pending_notice'])

        kept = evaluate_capex_table(table, {'name': 'D_capex', 'on': True, 'status': 'on'})
        self.assertTrue(kept['on'])
        self.assertEqual(kept['status'], 'on')
        self.assertEqual(kept['mode'], 'pending_inherit')

    def test_blank_pending_does_not_block_official_history(self):
        values = [100, 100, 100, 100, 140, 140, 110]
        table = _table(values, extra=_blank_pending('2020Q4'))
        flag = evaluate_capex_table(table, {'name': 'D_capex', 'on': False, 'status': 'off'})
        self.assertTrue(flag['on'])
        self.assertEqual(flag['mode'], 'official')

    def test_example_rows_are_not_live(self):
        values = [100, 100, 100, 100, 140, 140, 110]
        flagged = evaluate_capex_table(
            _table(values, status='EXAMPLE', notes='EXAMPLE fake capex, not SEC'),
            None,
        )
        self.assertFalse(flagged['on'])
        self.assertNotEqual(flagged['status'], 'on')
        self.assertEqual(flagged['mode'], 'example_ignored')

        labeled = _table(values, status='OFFICIAL', notes='EXAMPLE pretending to be a filing. SpaceX excluded.')
        rejected = evaluate_capex_table(labeled, None)
        self.assertFalse(rejected['on'])
        self.assertNotEqual(rejected['status'], 'on')

    def test_official_spacex_number_is_rejected(self):
        table = _table([100, 100, 100, 100, 140, 140, 110], spacex=50)
        flag = evaluate_capex_table(table, None)
        self.assertFalse(flag['on'])
        self.assertNotEqual(flag['status'], 'on')
        self.assertIn('SpaceX', flag['detail'])

    def test_shipped_template_has_no_official_rows(self):
        path = ROOT / 'data' / 'risk_flags' / TEMPLATE_NAME
        frame = load_capex_csv(path)
        self.assertFalse((frame['status'] == 'OFFICIAL').any())
        self.assertTrue((frame['status'] == 'EXAMPLE').any())
        examples = frame[frame['status'] == 'EXAMPLE']
        self.assertTrue(examples['source_notes'].str.contains('EXAMPLE').all())
        self.assertTrue(frame['source_notes'].str.contains('SpaceX').any())
        flag = evaluate_capex_table(frame, None)
        self.assertFalse(flag['on'])
        self.assertNotEqual(flag['status'], 'on')
        text = path.read_text(encoding='utf-8')
        self.assertNotIn(',OFFICIAL,', text)

    def test_official_cache_is_not_blocked_by_the_template_placeholder(self):
        values = [100, 100, 100, 100, 140, 140, 110]
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cache = tmp / 'capex_official.csv'
            _table(values).to_csv(cache, index=False)
            template = tmp / 'template.csv'
            pd.DataFrame([_blank_pending('2099Q4')]).to_csv(template, index=False)
            flag = evaluate_capex_sources(template, cache, previous_flag=None, fetch=False)
            self.assertTrue(flag['on'])
            self.assertEqual(flag['metrics'].get('table'), 'official_cache')


class CapexSourceTests(unittest.TestCase):
    def test_nearest_quarter_and_six_name_join(self):
        self.assertEqual(str(nearest_calendar_quarter('2024-03-31')), '2024Q1')
        self.assertEqual(str(nearest_calendar_quarter('2024-04-26')), '2024Q1')
        self.assertEqual(str(nearest_calendar_quarter('2024-05-20')), '2024Q2')
        self.assertIsNone(nearest_calendar_quarter('2024-05-20', tolerance_days=20))

        ends = pd.to_datetime(['2024-03-31', '2024-04-20'])
        frame = pd.DataFrame({'end': ends, 'val': [10e6, 99e6]})
        aligned = align_quarterly_musd(frame)
        self.assertEqual(list(aligned.index.astype(str)), ['2024Q1'])
        self.assertAlmostEqual(float(aligned.iloc[0]), 10.0)

        series = {
            name: pd.Series([10.0], index=pd.PeriodIndex(['2024Q1'], freq='Q-DEC'))
            for name in PUBLIC_NAMES
        }
        table = build_official_table(series)
        self.assertEqual(len(table), 1)
        self.assertEqual(table.iloc[0]['status'], 'OFFICIAL')
        self.assertAlmostEqual(float(table.iloc[0]['total_musd']), 60.0)
        self.assertTrue(pd.isna(table.iloc[0]['spacex_musd']) or table.iloc[0]['spacex_musd'] == '')
        self.assertIn('SpaceX', table.iloc[0]['source_notes'])
        self.assertIn('private', table.iloc[0]['source_notes'].lower())
        partial = dict(series)
        partial.pop('tsm')
        self.assertTrue(build_official_table(partial).empty)

    def test_quarterly_fact_filter_drops_year_to_date(self):
        records = []
        start = pd.Timestamp('2023-01-01')
        for i in range(4):
            begin = start + pd.DateOffset(months=3 * i)
            records.append({
                'start': begin.date().isoformat(),
                'end': (begin + pd.Timedelta(days=90)).date().isoformat(),
                'val': 1e9 * (i + 1),
            })
        records.append({
            'start': '2023-01-01',
            'end': '2023-12-31',
            'val': 9e9,
        })
        quarterly = quarterly_from_facts(records)
        self.assertIsNotNone(quarterly)
        self.assertEqual(len(quarterly), 4)
        self.assertLess(float(quarterly['val'].max()), 9e9)


class CreditTests(unittest.TestCase):
    def test_hysteresis_and_units(self):
        percent = pd.Series([3.2, 4.5, 7.0])
        bps = to_bps(percent)
        self.assertAlmostEqual(float(bps.iloc[0]), 320.0)
        self.assertAlmostEqual(float(bps.iloc[1]), 450.0)
        already = to_bps(pd.Series([320.0, 450.0, 700.0]))
        self.assertAlmostEqual(float(already.iloc[1]), 450.0)

        idx = pd.bdate_range('2024-01-02', periods=6)
        calm_z = pd.Series(0.0, index=idx)
        level = pd.Series([300, 440, 450, 400, 370, 200], index=idx, dtype=float)
        raw = credit_raw_on(level, calm_z)
        self.assertEqual(list(raw.astype(int)), [0, 0, 1, 1, 0, 0])

        z_on = pd.Series([0.0, 2.0], index=idx[:2])
        self.assertTrue(bool(credit_raw_on(pd.Series([400, 400], index=idx[:2]), z_on).iloc[-1]))
        hold = credit_raw_on(
            pd.Series([500, 370], index=idx[:2]),
            pd.Series([0.0, 1.0], index=idx[:2]),
        )
        self.assertTrue(bool(hold.iloc[-1]))
        release = credit_raw_on(
            pd.Series([500, 379], index=idx[:2]),
            pd.Series([0.0, 0.99], index=idx[:2]),
        )
        self.assertFalse(bool(release.iloc[-1]))

        lagged = credit_raw_on(
            pd.Series([300, 300, 500, 500, 300], index=idx[:5]),
            pd.Series(0.0, index=idx[:5]),
        )
        published = lagged.astype(float).shift(1)
        self.assertFalse(bool(lagged.iloc[-1]))
        self.assertTrue(bool(published.iloc[-1]))

    def test_published_flag_uses_the_prior_observation(self):
        idx = pd.bdate_range('2016-01-04', periods=260)
        calm = pd.Series(3.0, index=idx)
        self.assertFalse(evaluate_credit_series(calm)['on'])
        hot = calm.copy()
        hot.iloc[-2:] = 6.0
        flag = evaluate_credit_series(hot)
        self.assertTrue(flag['on'])
        self.assertEqual(flag['status'], 'on')
        today_only = calm.copy()
        today_only.iloc[-1] = 6.0
        self.assertFalse(evaluate_credit_series(today_only)['on'])

    def test_fred_csv_parser_ignores_dots(self):
        text = 'DATE,BAMLH0A0HYM2\n2024-01-02,3.25\n2024-01-03,.\n2024-01-04,4.50\n'
        series = parse_fred_csv(text)
        self.assertEqual(len(series), 2)
        self.assertAlmostEqual(float(series.iloc[-1]), 4.50)


class ConcentrationTests(unittest.TestCase):
    def test_hysteresis_band(self):
        self.assertFalse(concentration_on(0.319, False))
        self.assertTrue(concentration_on(0.32, False))
        self.assertTrue(concentration_on(32, False))
        self.assertTrue(concentration_on(0.30, True))
        self.assertTrue(concentration_on(0.291, True))
        self.assertFalse(concentration_on(0.29, True))
        self.assertFalse(concentration_on(29, True))
        path = concentration_path(pd.Series([0.31, 0.32, 0.30, 0.29]))
        self.assertEqual(list(path.astype(int)), [0, 1, 1, 0])
        flag = evaluate_concentration_series(pd.Series(
            [0.31, 0.33],
            index=pd.to_datetime(['2026-10-22', '2026-10-23']),
        ))
        self.assertTrue(flag['on'])
        self.assertIn('SPY', flag['detail'])
        self.assertIn('GOOG', flag['detail'])

    def test_holdings_parser_requires_the_full_basket(self):
        raw = pd.DataFrame([
            ['SPDR S&P 500', None],
            ['As of 2026-10-23', None],
            ['Name', 'Ticker', 'Weight'],
            ['Apple', 'AAPL', 7],
            ['Microsoft', 'MSFT', 6],
            ['Amazon', 'AMZN', 4],
            ['Nvidia', 'NVDA', 6],
            ['Meta', 'META', 3],
            ['Tesla', 'TSLA', 2],
            ['Alphabet A', 'GOOGL', 2],
            ['Alphabet C', 'GOOG', 2],
            ['Other', 'BRK.B', 1],
        ])
        table, as_of = holdings_table_from_raw(raw)
        self.assertEqual(pd.Timestamp(as_of), pd.Timestamp('2026-10-23'))
        weight, note = weight_from_holdings_frame(table)
        self.assertAlmostEqual(weight, 0.32)
        self.assertIn('SPY', note)
        self.assertTrue(concentration_on(weight, False))
        partial = table[table['Ticker'] != 'GOOG']
        missing, why = weight_from_holdings_frame(partial)
        self.assertIsNone(missing)
        self.assertIn('GOOG', why)

        fractions = table.copy()
        fractions['Weight'] = pd.to_numeric(fractions['Weight']) / 100.0
        fraction_weight, _note = weight_from_holdings_frame(fractions)
        self.assertAlmostEqual(fraction_weight, 0.32)


class ScoreAndNotifyTests(unittest.TestCase):
    def test_bubble_score_is_hard_on_off(self):
        self.assertEqual(bubble_pressure_score({}), 0.0)
        both = {
            'D_capex': {'on': True, 'status': 'on'},
            'E_credit': {'on': True, 'status': 'on'},
            'F_conc': {'on': False, 'status': 'off'},
        }
        self.assertEqual(bubble_pressure_score(both), 0.75)
        self.assertEqual(bubble_pressure_score({
            'D_capex': {'on': True, 'status': 'on'},
            'E_credit': {'on': True, 'status': 'on'},
            'F_conc': {'on': True, 'status': 'on'},
        }), 1.0)
        pending = {'D_capex': {'on': True, 'status': 'pending'}}
        self.assertEqual(bubble_pressure_score(pending), 0.0)

    def test_failed_source_keeps_the_previous_flag(self):
        previous = {'flags': {'E_credit': {
            'name': 'E_credit', 'on': True, 'status': 'on', 'detail': 'kept',
        }}}
        snap = {'flags': {}, 'as_of': '2026-10-23'}
        out = attach_structural(
            snap,
            {'E_credit': {'name': 'E_credit', 'on': False, 'status': 'skipped', 'inherit_previous': True}},
            previous=previous,
        )
        self.assertTrue(out['flags']['E_credit']['on'])
        self.assertEqual(out['bubble_pressure_score'], 0.35)
        self.assertFalse(out['orders'])
        self.assertFalse(out['weights'])
        self.assertIn('不改仓', out['hard_constraint_notice']['zh'])
        self.assertIn('NOTIFY-ONLY', out['hard_constraint_notice']['en'])
        for key in FLAG_IDS:
            self.assertIn(key, out['flags'])

    def test_notify_block_alias_carries_structural_flags(self):
        idx = pd.bdate_range('2024-01-02', periods=5)
        snap = compute_snapshot(
            pd.Series(range(100, 105), index=idx, dtype=float),
            pd.Series(16.0, index=idx),
            today=idx[-1],
        )
        block = to_notify_block(snap)
        self.assertIsNotNone(block)
        for key in STRUCTURAL_FLAG_IDS:
            self.assertIn(key, block)
            self.assertFalse(block[key])
        self.assertIn('NOTIFY-ONLY', block['hard_constraint_notice']['en'])

    def test_structural_rising_edge_is_notify_only(self):
        import notify_regime as nr
        from src.risk_flags import rising_flag_ids

        prev_flags = {
            'as_of': '2026-10-16',
            'A_vol': False, 'B_crowd': False, 'C_put': False,
            'D_capex': False, 'E_credit': False, 'F_conc': False,
            'status': {key: 'off' for key in FLAG_IDS},
            'mode': {key: 'official' for key in FLAG_IDS},
            'detail': {key: '' for key in FLAG_IDS},
            'rule_zh': {key: key for key in FLAG_IDS},
            'hard_constraint_notice': {'zh': '不改仓', 'en': 'NOTIFY-ONLY'},
            'bubble_pressure_score': 0.0,
        }
        base = {
            'schema': 1,
            'regime': 'reflation',
            'vix_band': '0-20',
            'vix_band_name': '正常',
            'vix': 16.0,
            'price_asof': '2026-10-16',
            'checked_at': '2026-10-16 23:00 UTC',
            'risk_flags': prev_flags,
        }
        unseen = dict(base)
        unseen['risk_flags'] = {
            'as_of': '2026-10-16',
            'A_vol': False, 'B_crowd': False, 'C_put': False,
            'D_capex': True,
            'status': {'A_vol': 'off', 'B_crowd': 'off', 'C_put': 'off', 'D_capex': 'on'},
        }
        # Previous block in this pair has no D key: first sight is a baseline.
        no_d = dict(base)
        no_d['risk_flags'] = {
            'as_of': '2026-10-15',
            'A_vol': False, 'B_crowd': False, 'C_put': False,
            'status': {'A_vol': 'off', 'B_crowd': 'off', 'C_put': 'off'},
        }
        self.assertEqual(rising_flag_ids(no_d['risk_flags'], unseen['risk_flags']), [])
        action, reasons = nr.classify_change(no_d, unseen, force=False)
        self.assertEqual(action, 'silent')
        self.assertNotIn('risk_flags', reasons)

        cur = dict(base)
        cur['price_asof'] = '2026-10-17'
        cur['risk_flags'] = dict(prev_flags)
        cur['risk_flags']['as_of'] = '2026-10-17'
        cur['risk_flags']['D_capex'] = True
        cur['risk_flags']['E_credit'] = True
        cur['risk_flags']['status'] = dict(prev_flags['status'], D_capex='on', E_credit='on')
        action, reasons = nr.classify_change(base, cur, force=False)
        self.assertEqual(action, 'notify')
        self.assertEqual(reasons['risk_flags'], 'D_capex+E_credit')
        title, body = nr.build_message(base, cur, reasons)
        self.assertTrue(title.startswith('[风险旗]'))
        self.assertIn('D_capex', title)
        self.assertIn('E_credit', title)
        self.assertIn('不改仓', body)
        self.assertIn('NOTIFY-ONLY', body)
        self.assertIn('卖 Put', body)
        self.assertNotIn('减持 ', body)
        self.assertNotIn('--execute', body)
        self.assertNotIn('| 标的 |', body)

        sticky, sticky_reasons = nr.classify_change(cur, cur, force=False)
        self.assertEqual(sticky, 'silent')
        self.assertEqual(sticky_reasons, {})

    def test_refresh_writes_structural_fields_without_network(self):
        import tempfile
        import refresh_risk_flags as refresh_mod

        def fake_download():
            idx = pd.bdate_range('2024-01-02', periods=5)
            soxx = pd.Series([100, 101, 102, 103, 104], index=idx, name='SOXX')
            vix = pd.Series(16.0, index=idx, name='VIX')
            return {'SOXX': soxx, 'VIX': vix}, []

        with tempfile.TemporaryDirectory() as tmp:
            ok = refresh_mod.refresh(Path(tmp), fetch_structural=False, downloader=fake_download)
            self.assertTrue(ok)
            data = json.loads((Path(tmp) / 'flags.json').read_text(encoding='utf-8'))
        self.assertFalse(data['orders'])
        self.assertFalse(data['weights'])
        self.assertEqual(data['purpose'], 'notify_only')
        self.assertIn('不改仓', data['hard_constraint_notice']['zh'])
        self.assertIn('NOTIFY-ONLY', data['hard_constraint_notice']['en'])
        self.assertEqual(data['bubble_pressure_score'], 0.0)
        for key in STRUCTURAL_FLAG_IDS:
            self.assertIn(key, data['flags'])
            self.assertNotEqual(data['flags'][key]['status'], 'on')
        self.assertNotEqual(data['flags']['D_capex']['mode'], 'official')


class DashboardAndIsolationTests(unittest.TestCase):
    def test_section_6_is_outside_sleeve_stress(self):
        from src.dashboard.app import build_auditor_tab
        from tests.test_backtest_default import _find_id, _fixture, _texts

        tab = build_auditor_tab(_fixture())
        panel = _find_id(tab, 'auditor-panel-5')
        section = _find_id(tab, 'auditor-section-6')
        self.assertIsNotNone(panel)
        self.assertIsNotNone(section)
        self.assertIsNone(_find_id(panel, 'auditor-section-6'))
        panel_text = '\n'.join(_texts(panel))
        section_text = '\n'.join(_texts(section))
        self.assertIn('Risk Assessment', panel_text)
        self.assertNotIn('D_capex', panel_text)
        self.assertNotIn('Risk Officer', panel_text)
        self.assertIn('6. Risk Officer', section_text)
        self.assertIn('结构旗', section_text)
        for key in STRUCTURAL_FLAG_IDS:
            self.assertIn(key, section_text)
        self.assertIn('不改仓', section_text)
        self.assertIn('NOTIFY-ONLY', section_text)
        self.assertIn('0.40', section_text)
        self.assertIn('A_vol', section_text)
        self.assertIn('EXAMPLE', section_text)

    def test_trading_paths_do_not_import_the_risk_officer(self):
        banned = [
            'src/backtester/engine.py',
            'src/backtester/daily_overlay.py',
            'src/execution/broker.py',
            'src/execution/order_manager.py',
            'src/execution/risk_manager.py',
            'scripts/ibkr_rebalance.py',
            'scripts/refresh_qqq_vegas_signal.py',
            'config/regime_rules.py',
            'config/cdn_regime_rules.py',
        ]
        tokens = ('risk_officer', 'D_capex', 'E_credit', 'F_conc', 'raw_capex_hyperscalers')
        for rel in banned:
            text = (ROOT / rel).read_text(encoding='utf-8')
            for token in tokens:
                self.assertNotIn(token, text, rel)
        package = ROOT / 'src' / 'risk_officer'
        for path in package.glob('*.py'):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('from config.regime_rules', text, path.name)
            self.assertNotIn('ibkr_rebalance', text, path.name)
            self.assertNotIn('placeOrder', text, path.name)
            self.assertNotIn('run_optimized_regime_backtest', text, path.name)


if __name__ == '__main__':
    unittest.main()
