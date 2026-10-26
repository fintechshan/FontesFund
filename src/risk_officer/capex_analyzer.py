"""D_capex. Notify only. EXAMPLE rows are never a live print.

The committed CSV is a template: EXAMPLE rows are fake, and the trailing
PENDING_EARNINGS row is blank. A refresh may write ``capex_official.csv``
from SEC EDGAR for the six public names. SpaceX stays blank.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from src.risk_flags import RULES

TEMPLATE_NAME = 'raw_capex_hyperscalers.csv'
PUBLIC_NAMES = ('msft', 'googl', 'amzn', 'meta', 'tsm', 'nvda')
NAME_COLUMNS = tuple(f'{name}_musd' for name in PUBLIC_NAMES)
SPACEX_COLUMN = 'spacex_musd'
TOTAL_COLUMN = 'total_musd'
CAPEX_COLUMNS = (
    'calendar_q', *NAME_COLUMNS, SPACEX_COLUMN, TOTAL_COLUMN, 'status', 'source_notes',
)
STATUS_OFFICIAL = 'OFFICIAL'
STATUS_PENDING = 'PENDING_EARNINGS'
STATUS_EXAMPLE = 'EXAMPLE'
QUARTER_TOLERANCE_DAYS = 50

# Same us-gaap concepts as src/strategist/edgar_capex.py, plus IFRS tags so
# TSMC can print. This module does not change the four-name dashboard pulse.
CONCEPTS = (
    ('us-gaap', 'PaymentsToAcquirePropertyPlantAndEquipment'),
    ('us-gaap', 'PaymentsToAcquireProductiveAssets'),
    ('ifrs-full', 'PaymentsToAcquirePropertyPlantAndEquipment'),
    ('ifrs-full', 'PurchaseOfPropertyPlantAndEquipment'),
)
CIKS = {
    'msft': '0000789019',
    'googl': '0001652044',
    'amzn': '0001018724',
    'meta': '0001326801',
    'nvda': '0001045810',
    'tsm': '0001046179',
}
EDGAR_UA = {
    'User-Agent': 'FontesFund risk-officer research (notify-only; contact via dashboard)',
}
OFFICIAL_NOTE = (
    'SEC EDGAR XBRL quarterly capex for MSFT GOOGL AMZN META TSM NVDA, '
    'mapped to the nearest calendar quarter within 50 days. '
    'SpaceX excluded: private company, no OFFICIAL figure, cell left blank.'
)


def empty_capex_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=list(CAPEX_COLUMNS))


def parse_calendar_quarter(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().upper().replace('_', '')
    if not text or text == 'NAN':
        return None
    cleaned = text.replace(' ', '')
    if len(cleaned) >= 6 and cleaned[4] in {'Q', '-'}:
        year = cleaned[:4]
        rest = cleaned[4:].replace('-', '')
        if year.isdigit() and rest.startswith('Q') and rest[1:2] in {'1', '2', '3', '4'}:
            return pd.Period(f'{year}Q{rest[1]}', freq='Q-DEC')
    ts = pd.to_datetime(text, errors='coerce')
    if pd.isna(ts):
        return None
    return pd.Period(ts, freq='Q-DEC')


def nearest_calendar_quarter(end, tolerance_days: int = QUARTER_TOLERANCE_DAYS):
    """Map a fiscal period-end onto a calendar quarter, or None if it is too far."""
    ts = pd.Timestamp(end)
    if pd.isna(ts):
        return None
    ts = ts.normalize()
    candidates = []
    for year in (ts.year - 1, ts.year, ts.year + 1):
        for month in (3, 6, 9, 12):
            candidates.append(pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0))
    nearest = min(candidates, key=lambda stamp: abs((ts - stamp).days))
    if abs((ts - nearest).days) > tolerance_days:
        return None
    return pd.Period(nearest, freq='Q-DEC')


def _number(value):
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def load_capex_csv(path) -> pd.DataFrame:
    target = Path(path)
    if not target.is_file():
        return empty_capex_frame()
    frame = pd.read_csv(target)
    frame.columns = [str(col).strip().lower() for col in frame.columns]
    for col in CAPEX_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA
    return normalize_capex_frame(frame)


def normalize_capex_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or len(frame) == 0:
        return empty_capex_frame()
    out = frame.copy()
    out.columns = [str(col).strip().lower() for col in out.columns]
    for col in CAPEX_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    out['calendar_q'] = out['calendar_q'].map(lambda value: '' if pd.isna(value) else str(value).strip())
    out['quarter_period'] = out['calendar_q'].map(parse_calendar_quarter)
    out = out[out['quarter_period'].notna()].copy()
    status = out['status'].map(lambda value: '' if pd.isna(value) else str(value).strip().upper())
    out['status'] = status
    notes = out['source_notes'].map(lambda value: '' if pd.isna(value) else str(value).strip())
    out['source_notes'] = notes
    out = out.sort_values('quarter_period')
    out = out.drop_duplicates('quarter_period', keep='last')
    return out.reset_index(drop=True)


def row_amounts_blank(row) -> bool:
    cols = NAME_COLUMNS + (SPACEX_COLUMN, TOTAL_COLUMN)
    return all(_number(row.get(col)) is None for col in cols)


def spacex_disclosed(notes: str) -> bool:
    text = (notes or '').lower()
    if 'spacex' not in text:
        return False
    tokens = (
        'exclud', 'private', 'blank', 'omit', 'not in', 'no official', 'not official',
        '私人', '不含', '空白', '未计入',
    )
    return any(token in text for token in tokens)


def live_official_total(row) -> tuple[float | None, str]:
    """Return the live total in millions of USD, or (None, reason).

    An OFFICIAL row with a SpaceX number is rejected. EXAMPLE text is rejected.
    The six public names must all be present.
    """
    status = str(row.get('status') or '').strip().upper()
    if status != STATUS_OFFICIAL:
        return None, 'not official'
    notes = str(row.get('source_notes') or '')
    if 'EXAMPLE' in notes.upper():
        return None, 'example note on an OFFICIAL row'
    if not spacex_disclosed(notes):
        return None, 'OFFICIAL row must say SpaceX is excluded or private'
    if _number(row.get(SPACEX_COLUMN)) is not None:
        return None, 'SpaceX cell must stay blank on an OFFICIAL row'
    parts = []
    for col in NAME_COLUMNS:
        value = _number(row.get(col))
        if value is None:
            return None, f'missing {col}'
        parts.append(value)
    summed = float(sum(parts))
    total = _number(row.get(TOTAL_COLUMN))
    if total is None:
        total = summed
    elif abs(total - summed) > max(1.0, 0.01 * abs(summed)):
        return None, 'total_musd does not match the six public names'
    if total <= 0:
        return None, 'non-positive total'
    return total, ''


def _flag(on: bool, status: str, mode: str, detail: str, **extra) -> dict:
    payload = {
        'name': 'D_capex',
        'on': bool(on) and status == 'on',
        'status': status,
        'mode': mode,
        'tier': 'structural',
        'rule_en': RULES['D_capex']['rule_en'],
        'rule_zh': RULES['D_capex']['rule_zh'],
        'detail': detail,
    }
    payload.update(extra)
    return payload


def inherit_capex_flag(previous, quarter, notice: str) -> dict:
    prev = previous if isinstance(previous, dict) else {}
    prev_status = prev.get('status')
    if prev_status == 'on' and prev.get('on'):
        status, on = 'on', True
    elif prev_status == 'off':
        status, on = 'off', False
    else:
        status, on = 'pending', False
    quarter_txt = 'n/a' if quarter is None else str(quarter)
    return _flag(
        on, status, 'pending_inherit',
        f'{notice} 季度 {quarter_txt}。',
        pending_notice=notice,
        metrics={'quarter': quarter_txt, 'inherited': True},
    )


def _fmt(value, digits: int = 1) -> str:
    number = _number(value)
    if number is None:
        return 'n/a'
    return f'{number:.{digits}f}'


def capex_signal_from_totals(totals: pd.Series) -> dict:
    """YoY and ΔYoY on a quarterly total series. Index is a PeriodIndex."""
    if totals is None or len(totals) == 0:
        return {'on': False, 'reason': 'insufficient', 'n': 0}
    series = pd.to_numeric(totals, errors='coerce').sort_index()
    series = series[~series.index.duplicated(keep='last')]
    full = pd.period_range(series.index.min(), series.index.max(), freq='Q-DEC')
    series = series.reindex(full).astype(float)
    yoy = (series / series.shift(4) - 1.0) * 100.0
    delta = yoy - yoy.shift(1)
    prev_delta = delta.shift(1)
    def _round(value):
        if pd.isna(value):
            return value
        # Six decimals kills binary noise (15.0 must not become 14.999999999).
        return round(float(value), 6)

    yoy_t = _round(yoy.iloc[-1])
    delta_t = _round(delta.iloc[-1])
    prev_t = _round(prev_delta.iloc[-1])
    quarter = str(series.index[-1])
    total = series.iloc[-1]
    base = {
        'quarter': quarter,
        'total': None if pd.isna(total) else float(total),
        'yoy': None if pd.isna(yoy_t) else float(yoy_t),
        'delta': None if pd.isna(delta_t) else float(delta_t),
        'prev_delta': None if pd.isna(prev_t) else float(prev_t),
        'n': int(series.notna().sum()),
    }
    if any(pd.isna(value) for value in (yoy_t, delta_t, prev_t)):
        base.update({'on': False, 'reason': 'insufficient'})
        return base
    steep = bool(delta_t <= -5 and yoy_t < 15)
    two = bool(delta_t < 0 and prev_t < 0 and (delta_t + prev_t) <= -4)
    if steep and two:
        reason = 'both'
    elif steep:
        reason = 'steep_drop'
    elif two:
        reason = 'two_quarter'
    else:
        reason = 'none'
    base.update({'on': bool(steep or two), 'reason': reason})
    return base


def _pairs_to_series(pairs) -> pd.Series:
    if not pairs:
        return pd.Series(dtype=float)
    periods, values = zip(*pairs)
    series = pd.Series(list(values), index=pd.PeriodIndex(list(periods), freq='Q-DEC'), dtype=float)
    series = series.sort_index()
    return series[~series.index.duplicated(keep='last')]


def _from_official(pairs, rejects) -> dict:
    signal = capex_signal_from_totals(_pairs_to_series(pairs))
    reason = signal.get('reason')
    if reason == 'insufficient':
        status, mode, on = 'skipped', 'insufficient', False
    elif signal.get('on'):
        status, mode, on = 'on', 'official', True
    else:
        status, mode, on = 'off', 'official', False
    detail = (
        f"{signal.get('quarter')} total {_fmt(signal.get('total'), 1)} · "
        f"YoY {_fmt(signal.get('yoy'), 1)}% · ΔYoY {_fmt(signal.get('delta'), 1)}pp · "
        f"上一季 Δ {_fmt(signal.get('prev_delta'), 1)}pp · {reason}"
    )
    if rejects:
        detail += ' · 丢弃 ' + '; '.join(rejects[:3])
    return _flag(on, status, mode, detail, metrics=signal)


def _live_pairs(frame: pd.DataFrame):
    pairs = []
    rejects = []
    if frame is None or frame.empty:
        return pairs, rejects
    for _, row in frame.iterrows():
        if str(row.get('status') or '') != STATUS_OFFICIAL:
            continue
        total, why = live_official_total(row)
        label = str(row.get('quarter_period'))
        if total is None:
            rejects.append(f'{label}: {why}')
            continue
        pairs.append((row.get('quarter_period'), total))
    return pairs, rejects


def evaluate_capex_table(frame, previous_flag=None) -> dict:
    """Score one CapEx table.

    EXAMPLE rows are dropped. A latest non-blank PENDING_EARNINGS row inherits
    ``previous_flag`` and does not recompute. A blank trailing PENDING row is a
    template placeholder: it inherits only when no live OFFICIAL rows remain.
    """
    table = frame if isinstance(frame, pd.DataFrame) else empty_capex_frame()
    if 'quarter_period' not in table.columns:
        table = normalize_capex_frame(table)
    if table.empty:
        return _flag(False, 'skipped', 'missing', '没有 CapEx 表。')
    usable = table[table['status'] != STATUS_EXAMPLE].copy()
    if usable.empty:
        return _flag(
            False, 'skipped', 'example_ignored',
            '只有 EXAMPLE 行。EXAMPLE 不是实盘，不计算 D_capex。',
        )
    latest = usable.iloc[-1]
    quarter = latest.get('quarter_period')
    if latest.get('status') == STATUS_PENDING and not row_amounts_blank(latest):
        notice = 'PENDING_EARNINGS：最新季度有未完成数字，继承上一份旗标，不抢跑。'
        return inherit_capex_flag(previous_flag, quarter, notice)
    if latest.get('status') == STATUS_PENDING and row_amounts_blank(latest):
        pairs, rejects = _live_pairs(usable.iloc[:-1])
        if not pairs:
            notice = 'PENDING_EARNINGS：最新季度为空，没有可用的 OFFICIAL，继承上一份旗标。'
            flag = inherit_capex_flag(previous_flag, quarter, notice)
            if rejects:
                flag['detail'] += ' 丢弃 ' + '; '.join(rejects[:3])
            return flag
        return _from_official(pairs, rejects)
    pairs, rejects = _live_pairs(usable)
    if not pairs:
        detail = '没有可用的 OFFICIAL 行。EXAMPLE 已忽略。'
        if rejects:
            detail += ' 丢弃 ' + '; '.join(rejects[:3])
        return _flag(False, 'skipped', 'no_live_official', detail)
    return _from_official(pairs, rejects)


def quarterly_from_facts(records) -> pd.DataFrame | None:
    """Keep ~90-day facts. Same window the EDGAR pulse uses (80 to 100 days)."""
    if not records:
        return None
    frame = pd.DataFrame(records)
    if not {'start', 'end', 'val'}.issubset(frame.columns):
        return None
    frame = frame.copy()
    frame['start'] = pd.to_datetime(frame['start'], errors='coerce')
    frame['end'] = pd.to_datetime(frame['end'], errors='coerce')
    frame['val'] = pd.to_numeric(frame['val'], errors='coerce')
    frame = frame.dropna(subset=['start', 'end', 'val'])
    if frame.empty:
        return None
    frame['days'] = (frame['end'] - frame['start']).dt.days
    quarterly = frame[(frame['days'] >= 80) & (frame['days'] <= 100)]
    quarterly = quarterly.drop_duplicates('end', keep='last').sort_values('end')
    if len(quarterly) < 4:
        return None
    return quarterly[['end', 'val']].reset_index(drop=True)


def align_quarterly_musd(frame: pd.DataFrame) -> pd.Series:
    """USD facts → millions, one value per calendar quarter (closest end wins)."""
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    best: dict = {}
    for _, row in frame.iterrows():
        period = nearest_calendar_quarter(row['end'])
        if period is None:
            continue
        quarter_end = pd.Timestamp(period.to_timestamp(how='end')).normalize()
        distance = abs((pd.Timestamp(row['end']).normalize() - quarter_end).days)
        musd = float(row['val']) / 1e6
        current = best.get(period)
        if current is None or distance < current[0]:
            best[period] = (distance, musd)
    if not best:
        return pd.Series(dtype=float)
    series = pd.Series({period: musd for period, (_dist, musd) in best.items()})
    series.index = pd.PeriodIndex(series.index, freq='Q-DEC')
    return series.sort_index()


def build_official_table(series_by_name: dict) -> pd.DataFrame:
    """Inner-join the six public names. SpaceX is blank. Empty if any name is missing."""
    parts = []
    for name in PUBLIC_NAMES:
        series = series_by_name.get(name)
        if series is None or len(series) == 0 or series.dropna().empty:
            return empty_capex_frame()
        part = pd.to_numeric(series, errors='coerce').dropna().astype(float)
        part.name = f'{name}_musd'
        parts.append(part)
    joined = pd.concat(parts, axis=1, join='inner').dropna()
    if joined.empty:
        return empty_capex_frame()
    rows = []
    for period, row in joined.sort_index().iterrows():
        record = {'calendar_q': str(period)}
        total = 0.0
        for name in PUBLIC_NAMES:
            value = round(float(row[f'{name}_musd']), 3)
            record[f'{name}_musd'] = value
            total += value
        record[SPACEX_COLUMN] = ''
        record[TOTAL_COLUMN] = round(total, 3)
        record['status'] = STATUS_OFFICIAL
        record['source_notes'] = OFFICIAL_NOTE
        rows.append(record)
    return pd.DataFrame(rows, columns=list(CAPEX_COLUMNS))


def fetch_company_frame(cik: str, getter, sleep: float = 0.2):
    """Best quarterly series for one CIK. ``getter`` is a requests-like callable."""
    best = None
    best_end = pd.Timestamp.min
    for taxonomy, concept in CONCEPTS:
        url = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json'
        try:
            response = getter(url, headers=EDGAR_UA, timeout=15)
        except Exception:
            continue
        if getattr(response, 'status_code', None) != 200:
            continue
        try:
            payload = response.json()
        except Exception:
            continue
        facts = []
        if isinstance(payload, dict):
            facts = (payload.get('units') or {}).get('USD') or []
        frame = quarterly_from_facts(facts)
        if frame is None or frame.empty:
            continue
        end = pd.Timestamp(frame['end'].iloc[-1])
        if end > best_end:
            best = frame
            best_end = end
        if sleep:
            time.sleep(sleep)
    return best


def fetch_official_table(getter=None, sleep: float = 0.2) -> pd.DataFrame:
    if getter is None:
        import requests

        getter = requests.get
    series = {}
    for name, cik in CIKS.items():
        frame = fetch_company_frame(cik, getter, sleep=sleep)
        if frame is None:
            return empty_capex_frame()
        series[name] = align_quarterly_musd(frame)
    return build_official_table(series)


def load_official_table(cache_path, fetch: bool = False, getter=None) -> pd.DataFrame:
    target = Path(cache_path)
    if fetch:
        try:
            table = fetch_official_table(getter=getter, sleep=0.0 if getter is not None else 0.2)
        except Exception:
            table = None
        if table is not None and not table.empty:
            target.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(target, index=False)
            return table
    if target.is_file():
        return load_capex_csv(target)
    return empty_capex_frame()


def evaluate_capex_sources(template_path, cache_path, previous_flag=None, fetch: bool = False, getter=None) -> dict:
    """Prefer a real official cache. The template's blank PENDING row does not block it."""
    template = load_capex_csv(template_path)
    official = load_official_table(cache_path, fetch=fetch, getter=getter)
    if not official.empty:
        flag = evaluate_capex_table(official, previous_flag)
        flag.setdefault('metrics', {})
        if isinstance(flag.get('metrics'), dict):
            flag['metrics']['table'] = 'official_cache'
        return flag
    flag = evaluate_capex_table(template, previous_flag)
    flag.setdefault('metrics', {})
    if isinstance(flag.get('metrics'), dict):
        flag['metrics']['table'] = 'template'
    return flag
