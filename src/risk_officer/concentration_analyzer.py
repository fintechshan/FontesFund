"""F_conc. Mag7 weight inside SPY. Notify only.

Seven companies, eight tickers: Alphabet is GOOGL + GOOG. A basket that is
missing any of those lines is skipped rather than treated as a low weight.
Hysteresis walks the stored history. The latest published holdings file is
the last point; there is no extra one-day lag on top of the file's as-of date.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.risk_flags import RULES

ON_WEIGHT = 0.32
OFF_WEIGHT = 0.29
MAG7_TICKERS = ('AAPL', 'MSFT', 'AMZN', 'NVDA', 'META', 'TSLA', 'GOOGL', 'GOOG')
HOLDINGS_URLS = (
    'https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx',
    'https://www.ssga.com/us/en/individual/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx',
)


def normalize_weight(value):
    """Fractions stay fractions. Numbers above 1.5 are percent (32 → 0.32)."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return None
    if weight != weight:
        return None
    if weight > 1.5:
        weight = weight / 100.0
    return weight


def concentration_on(weight, was_on: bool):
    """None when the weight is missing. Exactly 32% turns on. Exactly 29% turns off."""
    value = normalize_weight(weight)
    if value is None:
        return None
    if was_on:
        return value > OFF_WEIGHT
    return value >= ON_WEIGHT


def concentration_path(weights: pd.Series, initial: bool = False) -> pd.Series:
    state = bool(initial)
    out = []
    index = []
    for stamp, weight in weights.items():
        nxt = concentration_on(weight, state)
        if nxt is not None:
            state = bool(nxt)
        out.append(state)
        index.append(stamp)
    return pd.Series(out, index=pd.Index(index), dtype=bool)


def _flag(on: bool, status: str, mode: str, detail: str, **extra) -> dict:
    payload = {
        'name': 'F_conc',
        'on': bool(on) and status == 'on',
        'status': status,
        'mode': mode,
        'tier': 'structural',
        'rule_en': RULES['F_conc']['rule_en'],
        'rule_zh': RULES['F_conc']['rule_zh'],
        'detail': detail,
    }
    payload.update(extra)
    return payload


def evaluate_concentration_series(weights: pd.Series) -> dict:
    clean = pd.to_numeric(weights, errors='coerce').dropna()
    if clean.empty:
        return _flag(False, 'skipped', 'missing', '没有 SPY Mag7 权重。', inherit_previous=True)
    path = concentration_path(clean, initial=False)
    on = bool(path.iloc[-1])
    last = normalize_weight(clean.iloc[-1])
    try:
        as_of = pd.Timestamp(clean.index[-1]).date().isoformat()
    except (TypeError, ValueError):
        as_of = str(clean.index[-1])
    detail = (
        f'Mag7 {last:.1%} of SPY · as of {as_of} · '
        f'ON≥{ON_WEIGHT:.0%} OFF≤{OFF_WEIGHT:.0%} · 含 GOOG+GOOGL · 最新公布持仓'
    )
    return _flag(
        on, 'on' if on else 'off', 'holdings', detail,
        metrics={'as_of': as_of, 'mag7_weight': None if last is None else round(float(last), 6)},
    )


def _ticker_token(value) -> str:
    text = str(value or '').upper().strip()
    if not text or text == 'NAN':
        return ''
    return text.split()[0].replace('.', '')


def weight_from_holdings_frame(frame: pd.DataFrame):
    """Sum Mag7 weights. Returns (fraction or None, note)."""
    if frame is None or frame.empty:
        return None, 'empty holdings'
    columns = {str(col).strip().lower(): col for col in frame.columns}
    ticker_col = columns.get('ticker') or columns.get('symbol')
    weight_col = None
    for key, original in columns.items():
        if key == 'weight' or key.startswith('weight'):
            weight_col = original
            break
    if ticker_col is None or weight_col is None:
        return None, 'holdings table has no ticker/weight columns'
    tickers = frame[ticker_col].map(_ticker_token)
    weights = pd.to_numeric(frame[weight_col], errors='coerce')
    basket = {}
    for ticker, weight in zip(tickers.tolist(), weights.tolist()):
        if ticker in MAG7_TICKERS and weight == weight:
            basket[ticker] = float(weight)
    missing = [ticker for ticker in MAG7_TICKERS if ticker not in basket]
    if missing:
        return None, 'SPY holdings missing ' + ','.join(missing)
    total = float(sum(basket.values()))
    if total > 1.5:
        total = total / 100.0
    note = (
        'SSGA SPY holdings. Mag7 = AAPL MSFT AMZN NVDA META TSLA GOOGL GOOG. '
        'SpaceX is not in SPY.'
    )
    return total, note


def holdings_table_from_raw(raw: pd.DataFrame):
    """Find the Ticker/Weight header. ``raw`` has no header row of its own."""
    if raw is None or raw.empty:
        raise ValueError('empty workbook')
    header_idx = None
    limit = min(40, len(raw))
    for i in range(limit):
        cells = [str(value).strip().lower() for value in raw.iloc[i].tolist()]
        if 'ticker' in cells and any(cell == 'weight' or cell.startswith('weight') for cell in cells):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError('no ticker/weight header')
    header = []
    for value in raw.iloc[header_idx].tolist():
        text = '' if pd.isna(value) else str(value).strip()
        header.append(text or 'blank')
    table = raw.iloc[header_idx + 1:].copy()
    table.columns = header
    table = table.dropna(how='all')
    as_of = _find_asof(raw, header_idx)
    return table, as_of


def _find_asof(raw: pd.DataFrame, header_idx: int):
    for i in range(header_idx):
        for value in raw.iloc[i].tolist():
            text = '' if pd.isna(value) else str(value)
            lower = text.lower()
            if 'as of' not in lower and 'as-of' not in lower:
                continue
            tail = text.lower().split('of', 1)[-1]
            stamp = pd.to_datetime(tail, errors='coerce')
            if not pd.isna(stamp):
                return pd.Timestamp(stamp).normalize()
    return None


def read_holdings_file(path):
    raw = pd.read_excel(path, header=None)
    table, as_of = holdings_table_from_raw(raw)
    weight, note = weight_from_holdings_frame(table)
    return weight, note, as_of


def read_weight_history(path) -> pd.Series:
    target = Path(path)
    if not target.is_file():
        return pd.Series(dtype=float)
    frame = pd.read_csv(target)
    if 'date' not in frame.columns or 'mag7_weight' not in frame.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(frame['mag7_weight'], errors='coerce')
    series.index = pd.to_datetime(frame['date'], errors='coerce')
    series = series[series.index.notna()].dropna().sort_index()
    return series[~series.index.duplicated(keep='last')]


def upsert_weight(path, day, weight, notes: str) -> pd.Series:
    target = Path(path)
    history = read_weight_history(target)
    stamp = pd.Timestamp(day).normalize()
    history = history.copy()
    history.loc[stamp] = float(weight)
    history = history.sort_index()
    history = history[~history.index.duplicated(keep='last')]
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({
        'date': [pd.Timestamp(idx).date().isoformat() for idx in history.index],
        'mag7_weight': history.to_numpy(dtype=float),
        'source_notes': notes,
    })
    frame.to_csv(target, index=False)
    return history


def download_holdings(path, opener=None):
    import urllib.request

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    opener = opener or urllib.request.urlopen
    last = None
    for url in HOLDINGS_URLS:
        req = urllib.request.Request(url, headers={'User-Agent': 'FontesFund risk-officer research'})
        try:
            with opener(req, timeout=20) as resp:
                payload = resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
        if payload:
            target.write_bytes(payload)
            return target
    if last is not None:
        raise last
    raise RuntimeError('SPY holdings download returned an empty file')


def load_mag7_history(cache_path, holdings_path, fetch: bool = False, downloader=None):
    error = None
    if fetch:
        try:
            saved = (downloader or download_holdings)(holdings_path)
            weight, note, as_of = read_holdings_file(saved)
            if weight is None:
                error = note
            else:
                day = as_of or pd.Timestamp.utcnow().normalize()
                if as_of is None:
                    note = (note or '') + ' as-of date missing; stamped at download.'
                return upsert_weight(cache_path, day, weight, note), None
        except Exception as exc:  # noqa: BLE001
            error = exc.__class__.__name__
    history = read_weight_history(cache_path)
    if not history.empty:
        return history, None
    return None, error or 'missing SPY Mag7 weight'


def evaluate_concentration_source(cache_path, holdings_path, fetch: bool = False, downloader=None) -> dict:
    history, error = load_mag7_history(cache_path, holdings_path, fetch=fetch, downloader=downloader)
    if history is None or history.dropna().empty:
        return _flag(
            False, 'skipped', 'missing',
            f'没有 SPY Mag7 权重（{error}）。保留上一份 F_conc。',
            inherit_previous=True,
        )
    return evaluate_concentration_series(history)
