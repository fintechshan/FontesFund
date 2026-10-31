"""Auditor section 7 and the Saturday snapshot writer. No network."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _texts(node):
    acc = []

    def _walk(item):
        if item is None or isinstance(item, (int, float, bool)):
            return
        if isinstance(item, str):
            acc.append(item)
            return
        if isinstance(item, dict):
            for value in item.values():
                _walk(value)
            return
        if isinstance(item, (list, tuple)):
            for value in item:
                _walk(value)
            return
        _walk(getattr(item, 'children', None))

    _walk(node)
    return acc


def _find_id(node, component_id):
    if getattr(node, 'id', None) == component_id:
        return node
    children = getattr(node, 'children', None)
    if isinstance(children, (list, tuple)):
        for child in children:
            hit = _find_id(child, component_id)
            if hit is not None:
                return hit
    elif children is not None and not isinstance(children, (str, dict)):
        return _find_id(children, component_id)
    return None


def _load_script():
    path = ROOT / 'scripts' / 'weekly_audit_snapshot.py'
    spec = importlib.util.spec_from_file_location('weekly_audit_snapshot', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(path: Path, header, rows):
    lines = [','.join(header)]
    for row in rows:
        lines.append(','.join('' if cell is None else str(cell) for cell in row))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


class Section7RenderTests(unittest.TestCase):
    def test_source_has_no_mid_file_future_import(self):
        text = (ROOT / 'src' / 'dashboard' / 'auditor.py').read_text(encoding='utf-8')
        self.assertNotIn('from __future__', text)
        self.assertIn('def build_weekly_audit_section', text)
        self.assertEqual(text.count('def build_risk_officer_section('), 1)
        self.assertEqual(text.count('def _build_risk_officer_section('), 1)

    def test_empty_snapshot_renders_section_7(self):
        from src.dashboard.auditor import build_risk_officer_section

        wrapped = build_risk_officer_section(snapshot={}, weekly_snapshot={})
        section6 = _find_id(wrapped, 'auditor-section-6')
        section7 = _find_id(wrapped, 'auditor-section-7')
        self.assertIsNotNone(section6)
        self.assertIsNotNone(section7)
        self.assertIsNone(_find_id(section6, 'auditor-section-7'))
        section6_text = '\n'.join(_texts(section6))
        section7_text = '\n'.join(_texts(section7))
        self.assertIn('6. Risk Officer', section6_text)
        self.assertIn('D_capex', section6_text)
        self.assertIn('NOTIFY-ONLY', section6_text)
        self.assertIn('尚未生成', section7_text)
        self.assertNotIn('D_capex', section7_text)

    def test_pass_snapshot_renders_without_crash(self):
        from src.dashboard.auditor import build_weekly_audit_section

        snap = {
            'overall_status': 'PASS',
            'generated_at': '2026-10-31 00:00 UTC',
            'freshness': {
                'status': 'PASS',
                'backtest_end': '2026-09-25',
                'notify_price_asof': '2026-09-25',
                'risk_flags_asof': '2026-09-25',
                'backtest_lag_calendar_days': 0,
            },
            'backtest_consistency': {
                'status': 'PASS',
                'reported_cagr': 0.1343,
                'cagr_diff_bps': 0.01,
                'reported_total_return': 0.10,
                'total_diff_bps': 0.1,
                'reported_max_dd': 0.1413,
                'benchmark_normalization_notes': ['day-1 base note'],
            },
            'live_market_check': {
                'latest_market_date': '2026-09-25',
                'tickers': {'SPY': {'close': 100.0, 'weekly_change_pct': 1.25}},
            },
        }
        section = build_weekly_audit_section(snap)
        self.assertEqual(getattr(section, 'id', None), 'auditor-section-7')
        blob = '\n'.join(_texts(section))
        self.assertIn('Overall Status: PASS', blob)
        self.assertIn('13.43%', blob)
        self.assertIn('14.13%', blob)
        self.assertIn('SPY 100.0 (+1.25% wk)', blob)
        self.assertIn('day-1 base note', blob)

    def test_repo_snapshot_renders(self):
        from src.dashboard.auditor import build_weekly_audit_section, load_weekly_audit_snapshot

        loaded = load_weekly_audit_snapshot()
        self.assertEqual(loaded.get('schema'), 1)
        self.assertEqual(loaded.get('backtest_consistency', {}).get('status'), 'PASS')
        section = build_weekly_audit_section(loaded)
        blob = '\n'.join(_texts(section))
        self.assertIn('7. Weekly Data', blob)
        self.assertIn(loaded['overall_status'], blob)


class SnapshotScriptTests(unittest.TestCase):
    def test_blank_day1_base_is_skipped_and_matching_book_passes(self):
        module = _load_script()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            series = [1.0, 0.95] + [1.0] * 249 + [1.10]
            rows = []
            for i, value in enumerate(series):
                weather = '' if i == 0 else '1.20'
                spy = '0.9900' if i == 0 else '1.5000'
                rows.append([f'2020-01-{i+1:02d}' if i < 28 else f'2020-02-{i:02d}', f'{value:.4f}', weather, spy])
            _write_csv(
                root / 'equity.csv',
                ['Date', 'Optimized Regime Strategy', 'All Weather', 'S&P 500'],
                rows,
            )
            _write_csv(
                root / 'comparison.csv',
                ['Strategy', 'Annual Return', 'Max Drawdown', 'Total Return'],
                [
                    ['Optimized Regime Strategy', '10.00%', '5.00%', '10.00%'],
                    ['All Weather', '1.00%', '1.00%', '1.00%'],
                    ['S&P 500', '8.00%', '2.00%', '50.00%'],
                ],
            )
            _write_csv(root / 'monthly.csv', ['Date', '0'], [['2020-12-31', '0.10']])
            _write_csv(
                root / 'lag.csv',
                ['mode', 'cagr', 'max_dd', 'sharpe', 'end'],
                [['B_targeted', '0.10', '0.05', '1.0', '2020-12-31']],
            )
            saved = (
                module.COMPARISON_CSV,
                module.ALL_EQUITY_CSV,
                module.MONTHLY_CSV,
                module.LAG_HONESTY_CSV,
            )
            module.COMPARISON_CSV = root / 'comparison.csv'
            module.ALL_EQUITY_CSV = root / 'equity.csv'
            module.MONTHLY_CSV = root / 'monthly.csv'
            module.LAG_HONESTY_CSV = root / 'lag.csv'
            try:
                report = module.check_backtest_consistency()
            finally:
                (
                    module.COMPARISON_CSV,
                    module.ALL_EQUITY_CSV,
                    module.MONTHLY_CSV,
                    module.LAG_HONESTY_CSV,
                ) = saved
        self.assertEqual(report['status'], 'PASS')
        notes = '\n'.join(report['benchmark_normalization_notes'])
        self.assertNotIn('All Weather', notes)
        self.assertIn('S&P 500', notes)
        self.assertEqual(report['lag_paths']['B_targeted']['cagr'], 0.10)

    def test_main_exit_code_follows_overall_status(self):
        module = _load_script()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'snap.json'

            def _run(status):
                original = module.build_snapshot
                module.build_snapshot = lambda refresh=False: {'overall_status': status}
                argv = sys.argv
                sys.argv = ['weekly_audit_snapshot.py', '--output', str(out)]
                try:
                    return module.main()
                finally:
                    module.build_snapshot = original
                    sys.argv = argv

            self.assertEqual(_run('WARNING'), 0)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['overall_status'], 'WARNING')
            self.assertEqual(_run('FAIL'), 3)
            self.assertEqual(_run('PASS'), 0)


class NotifyWorkflowTests(unittest.TestCase):
    def test_saturday_cron_keeps_weekday_notify_path(self):
        text = (ROOT / '.github' / 'workflows' / 'notify.yml').read_text(encoding='utf-8')
        self.assertIn("cron: '0 23 * * 1-5'", text)
        self.assertIn("cron: '0 1 * * 6'", text)
        self.assertIn('FRED_API_KEY', text)
        self.assertIn('SERVERCHAN_SENDKEY', text)
        self.assertIn('python scripts/notify_regime.py --audit', text)
        self.assertIn('confirmed_miss', text)
        self.assertIn('NOTIFY_PUSH_TOKEN', text)
        self.assertIn('[skip ci]', text)
        self.assertIn('weekly_audit_snapshot.py --refresh', text)
        self.assertIn('git add -- data/notify_state.json', text)
        self.assertIn('git add -- data/weekly_audit_snapshot.json', text)
        self.assertNotIn('git diff --cached --quiet -- data/notify_state.json', text)
        self.assertIn('git diff --cached --quiet', text)


if __name__ == '__main__':
    unittest.main()
