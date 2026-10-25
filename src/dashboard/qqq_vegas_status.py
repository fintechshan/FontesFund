"""QQQ Vegas clocks and the three Auditor checks.

Stamps come from the artifact fields (``fetched_at``, ``generated_at``,
session ``as_of``). They do not use the file modification time and they do
not use the page clock. A session date is the 16:00 America/New_York cash
close, also printed in UTC and Asia/Shanghai. A calendar date that has no
clock stays a calendar date.

The checks read the locked v9 sleeve. They do not change it, and they do
not read Merrill ``REGIME_WEIGHTS``.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
VEGAS_DIR = ROOT / 'data' / 'qqq_vegas'
APP_PATH = ROOT / 'src' / 'dashboard' / 'app.py'

NY = ZoneInfo('America/New_York')
SHANGHAI = ZoneInfo('Asia/Shanghai')

STRATEGY_ID = 'qqq_vegas_rv20_q80'
VERSION_TAG = 'v9'
QQQ_WEIGHT = 0.7
QLD_WEIGHT = 0.3
Q80_QUANTILE = 0.80
Q80_LEVEL = 0.31
Q80_LEVEL_LO = 0.25
Q80_LEVEL_HI = 0.40
HISTORY_START_MAX = date(1999, 12, 31)
MIN_HISTORY_ROWS = 2000
FRESH_WARN_DAYS = 4
FRESH_FAIL_DAYS = 10
SESSION_CLOSE_HOUR = 16

CHECK_ACCURACY = 'QQQ Vegas information accuracy'
CHECK_FRESHNESS = 'QQQ Vegas time freshness'
CHECK_CONSISTENCY = 'QQQ Vegas v9 strategy consistency'
CHECK_NAMES = (CHECK_ACCURACY, CHECK_FRESHNESS, CHECK_CONSISTENCY)

_BLANK = {'', 'none', 'nan', 'nat', 'null', '—', '-'}


def _blank(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in _BLANK


def parse_date(value):
    """Calendar date. A longer timestamp contributes its date prefix only."""
    if _blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) >= 10:
        try:
            return datetime.strptime(text[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
    return None


def parse_instant(value):
    """Aware datetime, or None when the text is missing, date-only, or naive.

    Date-only values are session or calendar dates, not fetch instants.
    """
    if _blank(value) or isinstance(value, date) and not isinstance(value, datetime):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return None
    if text.endswith(' UTC'):
        body = text[:-4].strip()
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                return datetime.strptime(body, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None
    iso = text[:-1] + '+00:00' if text.endswith('Z') else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _has_clock(value):
    if _blank(value):
        return False
    text = str(value).strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return False
    return parse_instant(value) is not None or _naive_clock(value) is not None


def _naive_clock(value):
    if _blank(value) or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith('Z') or text.endswith('UTC') or '+' in text[10:]:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return None
    return parsed


def format_instant(value):
    """UTC plus Asia/Shanghai. Date-only and missing clocks stay unlabeled as times."""
    instant = parse_instant(value)
    if instant is not None:
        shanghai = instant.astimezone(SHANGHAI)
        return f'{instant:%Y-%m-%d %H:%M} UTC · {shanghai:%Y-%m-%d %H:%M} Asia/Shanghai'
    naive = _naive_clock(value) if isinstance(value, str) else None
    if naive is not None:
        return f'{naive:%Y-%m-%d %H:%M} (no timezone in source)'
    day = parse_date(value)
    if day is not None and not _has_clock(value):
        return f'{day.isoformat()} (calendar date, no clock in source)'
    if _blank(value):
        return '— (no fetch clock in source)'
    return f'— (unreadable timestamp {value})'


def format_calendar(value):
    instant = parse_instant(value)
    if instant is not None:
        return format_instant(value)
    day = parse_date(value)
    if day is None:
        if _blank(value):
            return '— (no calendar date in source)'
        return f'— (unreadable date {value})'
    return f'{day.isoformat()} (calendar date, no clock in source)'


def format_session_close(value):
    """Cash close for a session date, labeled in New York, UTC, and Shanghai."""
    day = parse_date(value)
    if day is None:
        if _blank(value):
            return '— (no session date in source)'
        return f'— (unreadable session date {value})'
    local = datetime(day.year, day.month, day.day, SESSION_CLOSE_HOUR, 0, tzinfo=NY)
    utc = local.astimezone(timezone.utc)
    shanghai = local.astimezone(SHANGHAI)
    return (
        f'{local:%Y-%m-%d %H:%M} America/New_York (session close) · '
        f'{utc:%Y-%m-%d %H:%M} UTC · '
        f'{shanghai:%Y-%m-%d %H:%M} Asia/Shanghai'
    )


def _frame(value):
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _dict(value):
    return value if isinstance(value, dict) else {}


def _date_max(frame):
    frame = _frame(frame)
    if frame.empty or 'date' not in frame.columns:
        return None
    dates = pd.to_datetime(frame['date'], errors='coerce').dropna()
    if dates.empty:
        return None
    return pd.Timestamp(dates.max()).date()


def _date_min(frame):
    frame = _frame(frame)
    if frame.empty or 'date' not in frame.columns:
        return None
    dates = pd.to_datetime(frame['date'], errors='coerce').dropna()
    if dates.empty:
        return None
    return pd.Timestamp(dates.min()).date()


def _read_json(path):
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_csv(path):
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError):
        return pd.DataFrame()


def load_bundle(directory=None):
    """Read the sleeve files the tab reads. Missing files stay empty."""
    base = Path(directory) if directory is not None else VEGAS_DIR
    missing = []

    def take_json(name):
        path = base / name
        if not path.is_file():
            missing.append(name)
            return {}
        payload = _read_json(path)
        if not payload:
            missing.append(name)
        return payload

    def take_csv(name):
        path = base / name
        if not path.is_file():
            missing.append(name)
            return pd.DataFrame()
        frame = _read_csv(path)
        if frame.empty:
            missing.append(name)
        return frame

    return {
        'directory': base,
        'signal': take_json('signal_current.json'),
        'summary': take_json('summary.json'),
        'strategy': take_json('strategy.json'),
        'live': take_json('live_snapshot.json'),
        'market_snapshot': take_json('market_snapshot.json'),
        'equity': take_csv('equity_curve.csv'),
        'rebalances': take_csv('rebalances.csv'),
        'monthly': take_csv('monthly_returns.csv'),
        'market_prices': take_csv('market_prices.csv'),
        'missing': missing,
    }


def _flags_snapshot(flags):
    if isinstance(flags, dict):
        return flags
    try:
        from src.risk_flags import load_snapshot
        loaded = load_snapshot()
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _monthly_through(monthly):
    frame = _frame(monthly)
    if frame.empty or 'year' not in frame.columns:
        return None
    years = pd.to_numeric(frame['year'], errors='coerce')
    if years.notna().sum() == 0:
        return None
    last_i = years.idxmax()
    year = int(years.loc[last_i])
    row = frame.loc[last_i]
    last_month = None
    for month in range(12, 0, -1):
        column = f'M{month:02d}'
        if column in frame.columns and not _blank(row.get(column)):
            last_month = month
            break
    if last_month is None:
        return f'{year} (year only, no month cell)'
    return f'{year}-{last_month:02d}'


def collect_clocks(bundle, flags=None):
    bundle = _dict(bundle)
    signal = _dict(bundle.get('signal'))
    summary = _dict(bundle.get('summary'))
    strategy = _dict(bundle.get('strategy'))
    live = _dict(bundle.get('live'))
    market = _dict(bundle.get('market_snapshot'))
    flags = _flags_snapshot(flags)
    equity_end = _date_max(bundle.get('equity'))
    price_end = _date_max(bundle.get('market_prices'))
    rebalance_end = _date_max(bundle.get('rebalances'))
    signal_day = (
        parse_date(signal.get('as_of'))
        or parse_date(summary.get('as_of'))
        or parse_date(summary.get('end_date'))
        or equity_end
    )
    pack_raw = summary.get('generated_at') or strategy.get('generated_at')
    return {
        'signal_day': signal_day,
        'signal_session': format_session_close(signal_day),
        'pack_raw': pack_raw,
        'pack_generated': format_calendar(pack_raw) if not _blank(pack_raw) else None,
        'market_fetched_raw': market.get('fetched_at'),
        'market_fetched': format_instant(market.get('fetched_at')),
        'market_day': parse_date(market.get('as_of')) or price_end,
        'market_session': format_session_close(market.get('as_of') or price_end),
        'equity_day': equity_end,
        'equity_session': format_session_close(equity_end),
        'rebalance_day': rebalance_end,
        'rebalance_session': format_session_close(rebalance_end),
        'monthly_through': _monthly_through(bundle.get('monthly')),
        'flags_generated_raw': flags.get('generated_at'),
        'flags_generated': format_instant(flags.get('generated_at')),
        'flags_day': parse_date(flags.get('as_of')),
        'flags_session': format_session_close(flags.get('as_of')),
        'flags_signal': format_session_close(flags.get('signal_date')),
        'flags_lag': flags.get('lag_trading_days', 1),
        'live_as_of': live.get('as_of'),
        'live_signal': format_session_close(live.get('signal_as_of') or signal_day),
        'live_match': bool(live.get('match')),
    }


def _pack_updated(clocks):
    if not _blank(clocks.get('pack_raw')):
        return f"{format_calendar(clocks.get('pack_raw'))} · summary.json generated_at"
    if clocks.get('signal_day'):
        return f"{clocks['signal_session']} (no generated_at; using the session close)"
    return '— (no generated_at and no session date in the sleeve pack)'


def section_stamps(bundle, flags=None):
    """One visible last-updated line per QQQ Vegas section."""
    clocks = collect_clocks(bundle, flags)
    pack = _pack_updated(clocks)
    signal_line = f"Last updated {pack} · data as of {clocks['signal_session']}"
    market_line = (
        f"Last updated {clocks['market_fetched']} · "
        f"data as of {clocks['market_session']} · source yfinance"
    )
    if clocks.get('market_fetched_raw') in (None, '') and clocks.get('market_day') is None:
        market_line += (
            ' · No market pack yet. python scripts/refresh_qqq_vegas_market.py '
            'writes data/qqq_vegas/market_prices.csv and market_snapshot.json. '
            'The page does not call Yahoo.'
        )
    equity_line = signal_line
    if clocks.get('equity_day') and clocks.get('equity_day') != clocks.get('signal_day'):
        equity_line = f"{signal_line} · equity curve ends {clocks['equity_session']}"
    elif clocks.get('equity_day'):
        equity_line = f"{signal_line} · equity curve ends {clocks['equity_day'].isoformat()}"
    through = clocks.get('monthly_through') or '— (no monthly_returns.csv year)'
    heat_line = (
        f"{signal_line} · heatmap through {through} "
        f"(month cells have no clock; the series as-of is the session close above)"
    )
    yearly_line = (
        f"{signal_line} · yearly_returns.csv has no clock; it uses the sleeve pack as-of"
    )
    newest = clocks['rebalance_session'] if clocks.get('rebalance_day') else '— (no rebalance row)'
    rebalance_line = f"{signal_line} · newest rebalance row {newest}"
    if _blank(clocks.get('live_as_of')):
        broker = (
            '— (live_snapshot.json as_of is empty; broker not connected; '
            'this is not a page clock)'
        )
    else:
        broker = format_instant(clocks.get('live_as_of'))
        if parse_instant(clocks.get('live_as_of')) is None:
            broker = format_session_close(clocks.get('live_as_of'))
    live_line = f"Last updated {broker} · signal as of {clocks['live_signal']}"
    flags_line = (
        f"Last updated {clocks['flags_generated']} · "
        f"data as of {clocks['flags_session']} · "
        f"signal date {clocks['flags_signal']} · "
        f"lag {clocks['flags_lag']} trading day"
    )
    tab_line = (
        f"Last updated · Signal as of {clocks['signal_session']} · "
        f"pack generated {clocks['pack_generated'] or '— (no generated_at)'} · "
        f"Prices fetched {clocks['market_fetched']} · "
        f"price bar {clocks['market_session']} · "
        f"Risk flags generated {clocks['flags_generated']}"
    )
    return {
        'tab': tab_line,
        'rules': signal_line,
        'disclaimer': signal_line,
        'market': market_line,
        'signal': signal_line,
        'equity': equity_line,
        'heatmap': heat_line,
        'yearly': yearly_line,
        'rebalances': rebalance_line,
        'live': live_line,
        'flags': flags_line,
        'as_of_signal': clocks['signal_session'],
        'as_of_market': f"{clocks['market_fetched']} · data as of {clocks['market_session']}",
        'as_of_equity': clocks['equity_session'],
        'as_of_heatmap': clocks['signal_session'],
        'as_of_rebalances': clocks['signal_session'],
        'as_of_live': clocks['live_signal'],
        'as_of_flags': clocks['flags_generated'],
    }


def tab_stamp_text(bundle, flags=None):
    return section_stamps(bundle, flags)['tab']


def audit_today(today=None):
    if today is None:
        return datetime.now(NY).date()
    parsed = parse_date(today)
    if parsed is None:
        raise ValueError(f'unreadable audit date {today}')
    return parsed


def session_age_days(day, today):
    """Calendar days from a session date to the last weekday on or before ``today``.

    A Friday bar is current on Saturday and Sunday. A fetch clock is not a
    session: compare that with ``calendar_age_days`` so a weekend refresh is
    not treated as future data.
    """
    if day is None:
        return None
    anchor = today
    while anchor.weekday() >= 5:
        anchor -= timedelta(days=1)
    return (anchor - day).days


def calendar_age_days(day, today):
    """Calendar days from ``day`` to ``today``. Negative means ``day`` is later."""
    if day is None:
        return None
    return (today - day).days


def _worst(levels):
    if 'FAIL' in levels:
        return 'FAIL'
    if 'WARNING' in levels:
        return 'WARNING'
    return 'PASS'


def _float(value):
    if _blank(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _near(left, right, tol=1e-4):
    if left is None or right is None:
        return False
    return abs(left - right) <= tol


def _problems_accuracy(bundle):
    problems = []
    signal = _dict(bundle.get('signal'))
    summary = _dict(bundle.get('summary'))
    strategy = _dict(bundle.get('strategy'))
    market = _dict(bundle.get('market_snapshot'))
    equity = _frame(bundle.get('equity'))
    prices = _frame(bundle.get('market_prices'))
    if not signal:
        problems.append(('FAIL', 'signal_current.json is missing or empty.'))
        return problems
    as_of = parse_date(signal.get('as_of'))
    signal_date = parse_date(signal.get('signal_date'))
    summary_end = parse_date(summary.get('end_date') or summary.get('as_of'))
    strategy_asof = parse_date(strategy.get('asof') or strategy.get('as_of'))
    equity_end = _date_max(equity)
    stamps = {
        'signal as_of': as_of,
        'signal_date': signal_date,
        'summary end': summary_end,
        'strategy asof': strategy_asof,
        'equity end': equity_end,
    }
    present = {name: day for name, day in stamps.items() if day is not None}
    if as_of is None:
        problems.append(('FAIL', 'signal as_of is missing, so the card has no session date.'))
    elif len(set(present.values())) > 1:
        shown = ', '.join(f'{name} {day.isoformat()}' for name, day in present.items())
        problems.append(('FAIL', f'Session dates disagree: {shown}.'))
    state = str(signal.get('state') or '')
    vegas = signal.get('vegas')
    rv_ok = signal.get('rv_ok')
    risk_on = state == 'RISK_ON'
    if risk_on and not (vegas == 1 and rv_ok == 1):
        problems.append(('FAIL', f'state is RISK_ON but vegas={vegas} rv_ok={rv_ok}.'))
    if state in {'CASH', 'RISK_OFF'} and vegas == 1 and rv_ok == 1:
        problems.append(('FAIL', f'state is {state} while vegas and rv_ok are both on.'))
    weights = _dict(signal.get('weights'))
    qqq_w = _float(weights.get('QQQ', signal.get('qqq_w')))
    qld_w = _float(weights.get('QLD', signal.get('qld_w')))
    cash_w = _float(weights.get('cash', signal.get('cash_w')))
    if None in (qqq_w, qld_w, cash_w):
        problems.append(('FAIL', 'Signal weights are missing.'))
    elif abs((qqq_w + qld_w + cash_w) - 1.0) > 1e-6:
        problems.append(('FAIL', f'Weights sum to {qqq_w + qld_w + cash_w:.4f}, not 1.'))
    elif risk_on and not (_near(qqq_w, QQQ_WEIGHT, 1e-6) and _near(qld_w, QLD_WEIGHT, 1e-6)):
        problems.append(('FAIL', f'RISK_ON weights are QQQ {qqq_w} / QLD {qld_w}, not 70/30.'))
    rv20 = _float(signal.get('rv20'))
    q80 = _float(signal.get('rv20_q80'))
    reason = str(signal.get('reason') or '')
    for label, reported in (('rv20', rv20), ('q80', q80)):
        match = re.search(rf'{label}\s*=\s*([0-9.]+)', reason)
        if reported is None:
            problems.append(('FAIL', f'signal {label} is missing.'))
        elif match and not _near(float(match.group(1)), reported, 5e-4):
            problems.append((
                'FAIL',
                f'reason {label}={match.group(1)} disagrees with the field {reported}.',
            ))
    if equity.empty or 'date' not in equity.columns:
        problems.append(('FAIL', 'equity_curve.csv is missing, so the card cannot be checked against the series.'))
    else:
        last = equity.iloc[-1]
        for column, reported in (
            ('rv20', rv20), ('rv20_q80', q80), ('vegas', vegas), ('rv_ok', rv_ok),
        ):
            if column not in equity.columns:
                problems.append(('FAIL', f'equity_curve.csv has no {column} column.'))
                continue
            series_value = _float(last.get(column))
            if reported is None or series_value is None:
                continue
            tol = 1e-6 if column in {'vegas', 'rv_ok'} else 5e-4
            if not _near(series_value, float(reported), tol):
                problems.append((
                    'FAIL',
                    f'Last equity {column} {series_value} disagrees with signal {reported}.',
                ))
        if 'signal' in equity.columns:
            last_signal = _float(last.get('signal'))
            if risk_on and last_signal != 1:
                problems.append(('FAIL', 'Card is RISK_ON but the last equity signal is not 1.'))
            if not risk_on and last_signal == 1 and state in {'CASH', 'RISK_OFF'}:
                problems.append(('FAIL', 'Card is cash but the last equity signal is 1.'))
    full = _dict(_dict(signal.get('metrics')).get('full'))
    full_start = parse_date(full.get('start'))
    full_end = parse_date(full.get('end'))
    if full_start is None or full_start.year > 1999:
        problems.append(('FAIL', f'metrics.full start is {full_start}, not the 1999 sample.'))
    if as_of and full_end and full_end != as_of:
        problems.append(('FAIL', f'metrics.full end {full_end} is not signal as_of {as_of}.'))
    if market or not prices.empty:
        market_day = parse_date(market.get('as_of'))
        price_day = _date_max(prices)
        if market_day and price_day and market_day != price_day:
            problems.append((
                'FAIL',
                f'market_snapshot as_of {market_day} is not the last price bar {price_day}.',
            ))
        tickers = _dict(market.get('tickers'))
        for ticker in ('QQQ', 'QLD'):
            last_px = _float(_dict(tickers.get(ticker)).get('last'))
            if tickers and (last_px is None or last_px <= 0):
                problems.append(('WARNING', f'{ticker} last price is missing or not positive.'))
    if not problems:
        problems.append(('PASS', 'Signal, equity, and market dates describe the same sleeve.'))
    return problems


def _age_problem(label, day, today, *, fail_missing=True, session=True):
    if day is None:
        level = 'FAIL' if fail_missing else 'WARNING'
        kind = 'session date' if session else 'clock date'
        return level, f'{label} has no {kind}.'
    age = session_age_days(day, today) if session else calendar_age_days(day, today)
    if age < 0:
        return 'FAIL', f'{label} {day.isoformat()} is after the audit date {today.isoformat()}.'
    basis = 'the last weekday' if session else 'the audit date'
    if age > FRESH_FAIL_DAYS:
        return 'FAIL', f'{label} {day.isoformat()} is {age} days behind {basis} ({today.isoformat()}).'
    if age > FRESH_WARN_DAYS:
        return 'WARNING', f'{label} {day.isoformat()} is {age} days behind {basis} ({today.isoformat()}).'
    return 'PASS', f'{label} {day.isoformat()} is {age} days behind {basis}.'


def _problems_freshness(bundle, flags, today, now=None):
    problems = []
    clocks = collect_clocks(bundle, flags)
    signal = _dict(bundle.get('signal'))
    market = _dict(bundle.get('market_snapshot'))
    live = _dict(bundle.get('live'))
    problems.append(_age_problem('Signal session', clocks.get('signal_day'), today))
    problems.append(_age_problem('Price bar', clocks.get('market_day'), today, fail_missing=not _frame(bundle.get('market_prices')).empty or bool(market)))
    fetched_raw = market.get('fetched_at')
    fetched = parse_instant(fetched_raw)
    if market or not _frame(bundle.get('market_prices')).empty:
        if _blank(fetched_raw):
            problems.append(('FAIL', 'market_snapshot.json has no fetched_at, so the price stamp would not be a real fetch time.'))
        elif fetched is None:
            problems.append(('FAIL', f'fetched_at {fetched_raw!r} is not a timezone-aware clock.'))
        else:
            fetch_day = fetched.astimezone(NY).date()
            moment = now or datetime.now(timezone.utc)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            if fetched > moment.astimezone(timezone.utc) + timedelta(days=1):
                problems.append(('FAIL', f'fetched_at {fetched:%Y-%m-%d %H:%M} UTC is in the future.'))
            else:
                problems.append(_age_problem('Price fetch', fetch_day, today, session=False))
    pack_raw = clocks.get('pack_raw')
    pack_day = parse_date(pack_raw)
    if pack_day and pack_day > today:
        problems.append(('FAIL', f'generated_at {pack_day.isoformat()} is after the audit date.'))
    elif pack_raw and parse_instant(pack_raw) is None and pack_day is not None:
        problems.append(('PASS', f'Pack generated_at is a calendar date ({pack_day.isoformat()}), not a fetch clock. The stamp says so.'))
    flags = _flags_snapshot(flags) if not isinstance(flags, dict) else flags
    if flags:
        generated = parse_instant(flags.get('generated_at'))
        if flags.get('unavailable'):
            problems.append(('WARNING', 'Risk-flag snapshot is unavailable, so that card has no fetch clock.'))
        elif generated is None:
            problems.append(('WARNING', 'Risk flags have no timezone-aware generated_at.'))
        else:
            problems.append(_age_problem(
                'Risk-flag fetch', generated.astimezone(NY).date(), today,
                fail_missing=False, session=False,
            ))
            problems.append(_age_problem('Risk-flag session', parse_date(flags.get('as_of')), today, fail_missing=False))
    if live.get('match') and _blank(live.get('as_of')):
        problems.append(('WARNING', 'live match is true but as_of is empty.'))
    elif _blank(live.get('as_of')):
        problems.append(('PASS', 'Broker as_of is empty because the book is not connected. The stamp does not invent a clock.'))
    problems.append((
        'PASS',
        f"Clocks: signal {clocks['signal_session']}; prices {clocks['market_fetched']}; "
        f"risk flags {clocks['flags_generated']}.",
    ))
    return problems


def _rule_blob(summary, strategy):
    chunks = []
    for source in (summary, strategy):
        rules = _dict(_dict(source).get('rules'))
        for key in ('en', 'zh'):
            lines = rules.get(key) or []
            if isinstance(lines, list):
                chunks.extend(str(line) for line in lines)
    return '\n'.join(chunks)


def _problems_consistency(bundle):
    problems = []
    signal = _dict(bundle.get('signal'))
    summary = _dict(bundle.get('summary'))
    strategy = _dict(bundle.get('strategy'))
    equity = _frame(bundle.get('equity'))
    rebalances = _frame(bundle.get('rebalances'))
    strategy_id = signal.get('strategy_id') or summary.get('strategy_id') or strategy.get('id')
    if strategy_id != STRATEGY_ID:
        problems.append(('FAIL', f'strategy id is {strategy_id!r}, not {STRATEGY_ID}.'))
    version = ' '.join(str(part) for part in (
        signal.get('backtest_tag'), summary.get('backtest_tag'), strategy.get('version'),
    ) if part)
    if VERSION_TAG not in version:
        problems.append(('FAIL', f'backtest tag/version {version!r} does not carry {VERSION_TAG}.'))
    risk_on = _dict(strategy.get('weights_risk_on'))
    if risk_on:
        if not _near(_float(risk_on.get('QQQ')), QQQ_WEIGHT, 1e-6) or not _near(_float(risk_on.get('QLD')), QLD_WEIGHT, 1e-6):
            problems.append(('FAIL', f'weights_risk_on is {risk_on}, not 70/30 QQQ+QLD.'))
    risk_off = _dict(strategy.get('weights_risk_off'))
    if risk_off:
        off_sum = sum(_float(risk_off.get(key)) or 0.0 for key in risk_off)
        qqq_off = _float(risk_off.get('QQQ')) or 0.0
        qld_off = _float(risk_off.get('QLD')) or 0.0
        if qqq_off > 1e-6 or qld_off > 1e-6 or abs(off_sum - 1.0) > 1e-6:
            problems.append(('FAIL', f'weights_risk_off is {risk_off}, not 100% cash.'))
    rules = _rule_blob(summary, strategy)
    required = (
        ('70' in rules or '0.7' in rules, 'rules do not state the 70/30 sleeve'),
        ('Q80' in rules or '80' in rules or '0.80' in rules, 'rules do not state the Q80 gate'),
        ('252' in rules, 'rules do not state min_periods=252'),
        ('shift(1)' in rules or '次日' in rules or 'next' in rules.lower(), 'rules do not state close-to-next-open'),
    )
    for ok, message in required:
        if rules and not ok:
            problems.append(('FAIL', message + '.'))
    if not rules:
        problems.append(('FAIL', 'strategy.json and summary.json have no rules text.'))
    try:
        app_source = APP_PATH.read_text(encoding='utf-8')
    except OSError:
        app_source = ''
    if app_source:
        for snippet in ('70% QQQ + 30% QLD', 'expanding 80th percentile', 'min_periods=252', 'Close confirm'):
            if snippet not in app_source:
                problems.append(('FAIL', f'Vegas fallback copy in app.py dropped {snippet!r}.'))
    start = _date_min(equity)
    if start is None:
        problems.append(('FAIL', 'equity_curve.csv has no dates, so the 1999 history cannot be verified.'))
    elif start > HISTORY_START_MAX:
        problems.append(('FAIL', f'Equity starts {start.isoformat()}. A short history that drops the 1999 gate is forbidden.'))
    if len(equity) < MIN_HISTORY_ROWS:
        problems.append(('FAIL', f'Equity has {len(equity)} rows. The locked sleeve keeps the full 1999–present series.'))
    if 'rv20_q80' not in equity.columns:
        problems.append(('FAIL', 'equity_curve.csv has no rv20_q80 column, so the gate is not on the series.'))
    else:
        q80 = pd.to_numeric(equity['rv20_q80'], errors='coerce')
        missing_share = float(q80.isna().mean()) if len(q80) else 1.0
        if missing_share > 0.05:
            problems.append(('FAIL', f'{missing_share:.0%} of rv20_q80 is empty. The gate is not on the full series.'))
        first = q80.dropna()
        if first.empty:
            problems.append(('FAIL', 'rv20_q80 is empty.'))
        else:
            first_value = float(first.iloc[0])
            unique = int(first.round(6).nunique())
            if not (Q80_LEVEL_LO <= first_value <= Q80_LEVEL_HI):
                problems.append((
                    'FAIL',
                    f'First Q80 is {first_value:.4f}, not the ~{Q80_LEVEL:.2f} full-sample threshold.',
                ))
            if unique < 2 and start is not None and start <= HISTORY_START_MAX:
                if Q80_LEVEL_LO <= first_value <= Q80_LEVEL_HI:
                    problems.append(('PASS', f'Q80 is a constant {first_value:.4f} on a 1999 start (preheated replica).'))
                else:
                    problems.append(('FAIL', 'Q80 is constant and is not the ~0.31 replica.'))
            elif unique < 2:
                problems.append(('FAIL', 'Q80 does not expand and the history is not the 1999 replica.'))
        if 'rv20' in equity.columns:
            rv20 = pd.to_numeric(equity['rv20'], errors='coerce')
            binds = (rv20 > q80).fillna(False).sum()
            if int(binds) == 0:
                problems.append(('FAIL', 'RV20 never exceeds Q80, so the gate does not bind.'))
    if 'signal' in equity.columns and 'pos' in equity.columns and len(equity) > 2:
        signal_col = pd.to_numeric(equity['signal'], errors='coerce')
        pos = pd.to_numeric(equity['pos'], errors='coerce')
        lagged = signal_col.shift(1)
        comparable = lagged.notna() & pos.notna()
        mismatches = int((pos[comparable] != lagged[comparable]).sum())
        if mismatches:
            problems.append(('FAIL', f'{mismatches} rows have pos different from the prior close signal.'))
    if rebalances.empty:
        problems.append(('FAIL', 'rebalances.csv is missing, so next-open execution cannot be checked.'))
    else:
        actions = set(str(value) for value in rebalances.get('action', []))
        if not actions or not actions <= {'ENTER', 'EXIT'}:
            problems.append(('FAIL', f'Rebalance actions are {sorted(actions)}. Mid-hold rebalance is not the v9 sleeve.'))
        if 'from_state' in rebalances.columns and 'to_state' in rebalances.columns:
            same = rebalances['from_state'].astype(str) == rebalances['to_state'].astype(str)
            if int(same.sum()):
                problems.append(('FAIL', f'{int(same.sum())} rebalance rows keep the same state.'))
        if {'signal_date', 'exec_date'} <= set(rebalances.columns):
            signal_dates = pd.to_datetime(rebalances['signal_date'], errors='coerce')
            exec_dates = pd.to_datetime(rebalances['exec_date'], errors='coerce')
            not_next = exec_dates <= signal_dates
            if int(not_next.fillna(True).sum()):
                problems.append(('FAIL', 'At least one rebalance executes on the signal close instead of the next session.'))
        if 'action' in rebalances.columns:
            enter = rebalances['action'].astype(str) == 'ENTER'
            exit_ = rebalances['action'].astype(str) == 'EXIT'
            if 'qqq_w' in rebalances.columns and enter.any():
                qqq = pd.to_numeric(rebalances.loc[enter, 'qqq_w'], errors='coerce')
                qld = pd.to_numeric(rebalances.loc[enter, 'qld_w'], errors='coerce') if 'qld_w' in rebalances.columns else None
                if not (qqq.sub(QQQ_WEIGHT).abs() <= 1e-6).all() or qld is None or not (qld.sub(QLD_WEIGHT).abs() <= 1e-6).all():
                    problems.append(('FAIL', 'An ENTER row is not 70% QQQ + 30% QLD.'))
            if exit_.any() and 'qqq_w' in rebalances.columns:
                qqq = pd.to_numeric(rebalances.loc[exit_, 'qqq_w'], errors='coerce').fillna(0)
                if 'qld_w' in rebalances.columns:
                    qld = pd.to_numeric(rebalances.loc[exit_, 'qld_w'], errors='coerce').fillna(0)
                else:
                    qld = pd.Series(0.0, index=qqq.index)
                if float(qqq.abs().max()) > 1e-6 or float(qld.abs().max()) > 1e-6:
                    problems.append(('FAIL', 'An EXIT row still holds QQQ or QLD.'))
    if not any(level == 'FAIL' for level, _message in problems):
        problems.append(('PASS', 'Sleeve matches locked v9: Vegas and expanding Q80, 70/30, close then next open, 1999 history.'))
    return problems


def _check(name, problems, *, threshold, location, remedy):
    levels = [level for level, _message in problems if level in {'FAIL', 'WARNING', 'PASS'}]
    status = _worst(levels)
    detail = ' '.join(message for _level, message in problems if message)
    if not detail:
        detail = 'No evidence.'
    value = detail if len(detail) <= 180 else detail[:177] + '...'
    return {
        'check': name,
        'status': status,
        'value': value,
        'threshold': threshold,
        'location': location,
        'remedy': remedy,
        'desc': detail,
    }


def audit_qqq_vegas(directory=None, bundle=None, flags=None, today=None, now=None):
    """Three checks: accuracy, freshness, and locked v9 consistency.

    ``today`` is the audit date in the New York session calendar. Display
    stamps do not use it.
    """
    if bundle is None:
        bundle = load_bundle(directory)
    today = audit_today(today)
    accuracy = _problems_accuracy(bundle)
    freshness = _problems_freshness(bundle, flags, today, now=now)
    consistency = _problems_consistency(bundle)
    return [
        _check(
            CHECK_ACCURACY,
            accuracy,
            threshold='Signal, last equity row, and market bar describe one session; RISK_ON is 70/30',
            location='data/qqq_vegas/signal_current.json, equity_curve.csv, market_snapshot.json',
            remedy='Regenerate the v9 pack from the full series. Do not hand-edit the card ahead of equity_curve.csv.',
        ),
        _check(
            CHECK_FRESHNESS,
            freshness,
            threshold=f'Session or fetch age ≤{FRESH_WARN_DAYS}d vs the last weekday; >{FRESH_FAIL_DAYS}d fails; fetch clocks must carry a timezone',
            location='data/qqq_vegas/signal_current.json, market_snapshot.json, data/risk_flags/flags.json',
            remedy=(
                'POST /tasks/refresh runs scripts/refresh_qqq_vegas_market.py and writes fetched_at. '
                'That path does not recompute the v9 sleeve. Refresh the 1999–present pack to move '
                'the signal session. Do not substitute a short history that drops Q80. '
                'Weekends use the prior weekday; exchange holidays are not a separate calendar.'
            ),
        ),
        _check(
            CHECK_CONSISTENCY,
            consistency,
            threshold='v9 Vegas ∧ expanding Q80 (~0.31, min_periods 252), 70/30, no mid-hold rebalance, close then next open, history from 1999',
            location='data/qqq_vegas/strategy.json, equity_curve.csv, rebalances.csv',
            remedy=(
                'Keep the locked sleeve: full OHLCV since 1999 or a preheated constant Q80 replica, '
                '70% QQQ + 30% QLD, signal at the close and the fill at the next open. '
                'This check does not change Merrill weights, the CPI+1/GDP+4 clock, or the GS switch.'
            ),
        ),
    ]
