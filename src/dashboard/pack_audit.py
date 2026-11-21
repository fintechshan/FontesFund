"""Book checks for every strategy pack the dashboard shows.

One checker, used by the QQQ Vegas auditor and by the Saturday snapshot.
It does not change sleeve rules. A pack fails when its own session clocks
disagree, when a rebalance history does not match position changes, or when
the refresh script that extends the book does not write that history.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

VEGAS_REFRESH = ROOT / 'scripts' / 'refresh_qqq_vegas_signal.py'
US_REFRESH = ROOT / 'run_backtest.py'
CDN_REFRESH = ROOT / 'scripts' / 'run_cdn_backtest.py'

# CDN ``as_of`` is the day the refresh ran. A Friday session stamped on
# Saturday or Sunday is the same book. A stamp older than the curve is not.
CDN_STAMP_LAG_DAYS = 4


def _day(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date()


def _read_json(path: Path):
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _series_end(path: Path):
    if not path.is_file():
        return None
    try:
        frame = pd.read_csv(path)
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError):
        return None
    if frame.empty:
        return None
    column = 'Date' if 'Date' in frame.columns else ('date' if 'date' in frame.columns else frame.columns[0])
    dates = pd.to_datetime(frame[column], errors='coerce').dropna()
    if dates.empty:
        return None
    return pd.Timestamp(dates.max()).date()


def _indexed_signal(signal) -> pd.DataFrame:
    if signal is None or not isinstance(signal, pd.DataFrame) or signal.empty:
        return pd.DataFrame()
    frame = signal.copy()
    if 'date' in frame.columns and not isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.set_index('date')
    frame.index = pd.to_datetime(frame.index, errors='coerce')
    frame = frame[frame.index.notna()].sort_index()
    return frame


def _rebalance_frame(rebalances) -> pd.DataFrame:
    if rebalances is None or not isinstance(rebalances, pd.DataFrame):
        return pd.DataFrame()
    return rebalances.copy()


def history_problems(signal, rebalances, last_rebalance=None, strategy_date=None, strategy_action=None):
    """FAIL when the history table or last_rebalance disagrees with ``pos`` changes."""
    from scripts.refresh_qqq_vegas_signal import pos_flips

    problems = []
    frame = _indexed_signal(signal)
    if frame.empty or 'pos' not in frame.columns:
        return [('FAIL', 'The daily signal has no pos column, so rebalance history cannot be checked.')]
    flips = pos_flips(frame)
    rows = _rebalance_frame(rebalances)
    if rows.empty and flips:
        first = flips[0]
        problems.append((
            'FAIL',
            f"rebalances.csv has no rows; pos changes imply {len(flips)}, "
            f"starting with {first['action']} exec {first['exec'].date()} "
            f"signal_date {first['signal'].date()}.",
        ))
    elif len(rows) != len(flips):
        problems.append((
            'FAIL',
            f'rebalances.csv has {len(rows)} rows; pos changes imply {len(flips)}.',
        ))
        if len(flips) > len(rows):
            missing = flips[len(rows)]
            problems.append((
                'FAIL',
                f"missing {missing['action']} exec {missing['exec'].date()} "
                f"signal_date {missing['signal'].date()}.",
            ))
        elif len(rows) and 'exec_date' in rows.columns:
            extra = rows.iloc[len(flips)]
            problems.append((
                'FAIL',
                f"extra rebalance {extra.get('action')} exec {extra.get('exec_date')} "
                'has no pos change in the daily signal.',
            ))
    comparable = min(len(rows), len(flips))
    for i in range(comparable):
        flip = flips[i]
        row = rows.iloc[i]
        exec_day = _day(row.get('exec_date', row.get('date')))
        signal_day = _day(row.get('signal_date'))
        action = str(row.get('action') or '')
        if exec_day != flip['exec'].date() or action != flip['action']:
            problems.append((
                'FAIL',
                f"rebalance row {i + 1} is {action} exec {exec_day}; "
                f"pos changes to {flip['action']} on {flip['exec'].date()}.",
            ))
            break
        if signal_day != flip['signal'].date():
            problems.append((
                'FAIL',
                f"rebalance {flip['exec'].date()} signal_date is {signal_day}; "
                f"the confirm close is {flip['signal'].date()}.",
            ))
            break
        from_state = str(row.get('from_state') or '')
        to_state = str(row.get('to_state') or '')
        if from_state and from_state != flip['from_state']:
            problems.append((
                'FAIL',
                f"rebalance {flip['exec'].date()} from_state is {from_state}, not {flip['from_state']}.",
            ))
            break
        if to_state and to_state != flip['to_state']:
            problems.append((
                'FAIL',
                f"rebalance {flip['exec'].date()} to_state is {to_state}, not {flip['to_state']}.",
            ))
            break
    if flips:
        last = flips[-1]
        expect_date = last['exec'].strftime('%Y-%m-%d')
        recorded = last_rebalance if isinstance(last_rebalance, dict) else {}
        recorded_date = str(recorded.get('date') or '')[:10]
        recorded_action = str(recorded.get('action') or '')
        if recorded_date != expect_date or recorded_action != last['action']:
            problems.append((
                'FAIL',
                f"last_rebalance is {recorded_date or 'missing'} {recorded_action or ''}; "
                f"the last pos change is {expect_date} {last['action']}.",
            ))
        if recorded.get('from_state') and recorded.get('from_state') != last['from_state']:
            problems.append((
                'FAIL',
                f"last_rebalance from_state is {recorded.get('from_state')}, not {last['from_state']}.",
            ))
        if recorded.get('to_state') and recorded.get('to_state') != last['to_state']:
            problems.append((
                'FAIL',
                f"last_rebalance to_state is {recorded.get('to_state')}, not {last['to_state']}.",
            ))
        strat_date = str(strategy_date or '')[:10]
        if strategy_date is not None and strat_date != expect_date:
            problems.append((
                'FAIL',
                f"strategy last_rebalance_date is {strat_date or 'missing'}; "
                f"the last pos change is {expect_date}.",
            ))
        if strategy_action is not None and str(strategy_action) != last['action']:
            problems.append((
                'FAIL',
                f"strategy last_rebalance_action is {strategy_action}; "
                f"the last pos change is {last['action']}.",
            ))
    elif isinstance(last_rebalance, dict) and last_rebalance.get('date'):
        problems.append(('FAIL', 'last_rebalance is set but the daily signal has no pos change.'))
    return problems


def refresh_path_problems(source: str, markers, *, label: str):
    """FAIL when a refresh script does not mention the artifacts it must rewrite."""
    missing = [marker for marker in markers if marker not in (source or '')]
    if not missing:
        return []
    joined = ', '.join(missing)
    return [(
        'FAIL',
        f'{label} updates the book without writing {joined}.',
    )]


def _check(name, problems, *, threshold, location, remedy, pack):
    levels = [level for level, _message in problems if level in {'FAIL', 'WARNING', 'PASS'}]
    if 'FAIL' in levels:
        status = 'FAIL'
    elif 'WARNING' in levels:
        status = 'WARNING'
    else:
        status = 'PASS'
    detail = ' '.join(message for _level, message in problems if message)
    if not detail:
        detail = 'No evidence.'
    value = detail if len(detail) <= 180 else detail[:177] + '...'
    return {
        'check': name,
        'pack': pack,
        'status': status,
        'value': value,
        'threshold': threshold,
        'location': location,
        'remedy': remedy,
        'desc': detail,
    }


def _vegas_pack(root: Path):
    directory = root / 'data' / 'qqq_vegas'
    signal = _indexed_signal(pd.read_csv(directory / 'daily_signal.csv') if (directory / 'daily_signal.csv').is_file() else pd.DataFrame())
    rebalances = pd.read_csv(directory / 'rebalances.csv') if (directory / 'rebalances.csv').is_file() else pd.DataFrame()
    current = _read_json(directory / 'signal_current.json')
    summary = _read_json(directory / 'summary.json')
    strategy = _read_json(directory / 'strategy.json')
    equity_end = _series_end(directory / 'equity_curve.csv')
    signal_end = None
    if not signal.empty:
        signal_end = pd.Timestamp(signal.index.max()).date()
    clocks = {
        'signal as_of': _day(current.get('as_of')),
        'summary as_of': _day(summary.get('as_of') or summary.get('end_date')),
        'strategy asof': _day(strategy.get('asof') or strategy.get('as_of')),
        'daily_signal end': signal_end,
        'equity end': equity_end,
    }
    problems = []
    present = {name: day for name, day in clocks.items() if day is not None}
    if len(set(present.values())) > 1:
        shown = ', '.join(f'{name} {day.isoformat()}' for name, day in present.items())
        problems.append(('FAIL', f'Session dates disagree: {shown}.'))
    elif not present:
        problems.append(('FAIL', 'QQQ Vegas has no session date.'))
    problems.extend(history_problems(
        signal,
        rebalances,
        last_rebalance=current.get('last_rebalance'),
        strategy_date=strategy.get('last_rebalance_date'),
        strategy_action=strategy.get('last_rebalance_action'),
    ))
    try:
        source = (root / 'scripts' / 'refresh_qqq_vegas_signal.py').read_text(encoding='utf-8')
    except OSError:
        source = ''
    problems.extend(refresh_path_problems(
        source,
        ('_sync_rebalances(', 'last_rebalance'),
        label='scripts/refresh_qqq_vegas_signal.py',
    ))
    if not any(level == 'FAIL' for level, _message in problems):
        session = next(iter(present.values())).isoformat() if present else 'n/a'
        last = current.get('last_rebalance') if isinstance(current.get('last_rebalance'), dict) else {}
        problems.append((
            'PASS',
            f"QQQ Vegas book is one session ({session}); "
            f"last_rebalance {last.get('date')} {last.get('action')}.",
        ))
    return _check(
        'QQQ Vegas book',
        problems,
        threshold='as_of, daily_signal, equity, and summary are one session; rebalances match pos changes; refresh writes both',
        location='data/qqq_vegas',
        remedy='Run scripts/refresh_qqq_vegas_signal.py. It extends the sleeve and rewrites rebalances.csv and last_rebalance from pos.',
        pack='qqq_vegas',
    )


def _ends_agree(label, ends):
    present = {name: day for name, day in ends.items() if day is not None}
    missing = [name for name, day in ends.items() if day is None]
    problems = []
    if missing:
        problems.append(('FAIL', f'{label} is missing {", ".join(missing)}.'))
    if len(set(present.values())) > 1:
        shown = ', '.join(f'{name} {day.isoformat()}' for name, day in present.items())
        problems.append(('FAIL', f'{label} session dates disagree: {shown}.'))
    return problems, present


def _us_pack(root: Path):
    ends = {
        'all_equity_curves': _series_end(root / 'data' / 'backtest_results' / 'all_equity_curves.csv'),
        'aggressive_equity_curve': _series_end(root / 'data' / 'backtest_results' / 'aggressive_equity_curve.csv'),
    }
    problems, present = _ends_agree('US regime book', ends)
    honesty_path = root / 'data' / 'backtest_results' / 'lag_honesty.csv'
    honesty_end = None
    if honesty_path.is_file():
        try:
            honesty = pd.read_csv(honesty_path)
            row = honesty.loc[honesty['mode'] == 'B_targeted']
            if len(row):
                honesty_end = _day(row.iloc[0].get('end'))
        except (OSError, ValueError, KeyError, pd.errors.ParserError):
            honesty_end = None
    if honesty_end is None:
        problems.append(('FAIL', 'US regime book is missing lag_honesty.csv B_targeted end.'))
    elif present and honesty_end not in set(present.values()):
        problems.append((
            'FAIL',
            f'lag_honesty B_targeted ends {honesty_end.isoformat()}, '
            f'not the equity session {next(iter(present.values())).isoformat()}.',
        ))
    try:
        source = (root / 'run_backtest.py').read_text(encoding='utf-8')
    except OSError:
        source = ''
    problems.extend(refresh_path_problems(
        source,
        ('all_equity_curves.csv', 'aggressive_equity_curve.csv', 'aggressive_monthly_returns.csv', '20yr_comparison.csv'),
        label='run_backtest.py',
    ))
    if not any(level == 'FAIL' for level, _message in problems):
        session = next(iter(present.values())).isoformat()
        problems.append((
            'PASS',
            f'US regime book ends {session}. run_backtest.py rewrites the equity curve, '
            'the monthly file, and the comparison together. There is no separate rebalance table.',
        ))
    return _check(
        'US regime book',
        problems,
        threshold='Equity curves and B_targeted end are one session; run_backtest.py rewrites that book together',
        location='data/backtest_results',
        remedy='Run run_backtest.py. Do not refresh one equity file and leave the comparison or the other curve behind.',
        pack='us_regime',
    )


def _cdn_pack(root: Path):
    equity_end = _series_end(root / 'data' / 'backtest_results' / 'cdn_equity_curve.csv')
    config = _read_json(root / 'data' / 'backtest_results' / 'cdn_strategy_config.json')
    as_of = _day(config.get('as_of'))
    problems = []
    if equity_end is None:
        problems.append(('FAIL', 'CDN equity curve is missing.'))
    if as_of is None:
        problems.append(('FAIL', 'CDN strategy config has no as_of.'))
    if equity_end is not None and as_of is not None:
        gap = (as_of - equity_end).days
        if gap < 0:
            problems.append((
                'FAIL',
                f'CDN config as_of {as_of.isoformat()} lags the equity session {equity_end.isoformat()}.',
            ))
        elif gap > CDN_STAMP_LAG_DAYS:
            problems.append((
                'FAIL',
                f'CDN config as_of {as_of.isoformat()} is {gap} days after the equity session {equity_end.isoformat()}.',
            ))
    try:
        source = (root / 'scripts' / 'run_cdn_backtest.py').read_text(encoding='utf-8')
    except OSError:
        source = ''
    problems.extend(refresh_path_problems(
        source,
        ('cdn_equity_curve.csv', 'cdn_monthly_returns.csv', 'cdn_strategy_config.json'),
        label='scripts/run_cdn_backtest.py',
    ))
    if not any(level == 'FAIL' for level, _message in problems):
        problems.append((
            'PASS',
            f'CDN regime book equity ends {equity_end.isoformat()} and config as_of is {as_of.isoformat()}. '
            'run_cdn_backtest.py rewrites the curve, the monthly file, and the config together. '
            'There is no separate rebalance table.',
        ))
    return _check(
        'CDN regime book',
        problems,
        threshold='Config as_of is the equity session or the refresh stamp within 4 days after it; one script writes the book',
        location='data/backtest_results/cdn_equity_curve.csv, cdn_strategy_config.json',
        remedy='Run scripts/run_cdn_backtest.py. Do not stamp as_of ahead of a curve that was left behind.',
        pack='cdn_regime',
    )


def audit_strategy_packs(root=None):
    """One row per strategy pack. FAIL when that pack's book is internally inconsistent."""
    root = Path(root) if root is not None else ROOT
    return [_vegas_pack(root), _us_pack(root), _cdn_pack(root)]


def worst_status(rows):
    statuses = [row.get('status') for row in rows]
    if 'FAIL' in statuses:
        return 'FAIL'
    if 'WARNING' in statuses:
        return 'WARNING'
    return 'PASS'
