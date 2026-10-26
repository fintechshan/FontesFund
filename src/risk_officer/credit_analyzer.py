"""E_credit. ICE BofA US HY OAS from the public FRED graph. Notify only.

FRED series BAMLH0A0HYM2 is quoted in percent. 4.50 means 450 bps.
The published flag is the prior observation, matching the tactical lag.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from src.risk_flags import RULES

FRED_SERIES = 'BAMLH0A0HYM2'
FRED_CSV_URL = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={FRED_SERIES}'
ON_BPS = 450.0
OFF_BPS = 380.0
ON_Z = 2.0
OFF_Z = 1.0
Z_MIN_PERIODS = 252


def to_bps(series: pd.Series) -> pd.Series:
    """Percent → bps. A median above 50 is already in bps and is left alone."""
    values = pd.to_numeric(series, errors='coerce').dropna()
    values = values.sort_index()
    values = values[~values.index.duplicated(keep='last')]
    if values.empty:
        return values
    if float(values.median()) > 50:
        return values.astype(float)
    return (values * 100.0).astype(float)


def expanding_z(bps: pd.Series, min_periods: int = Z_MIN_PERIODS) -> pd.Series:
    mean = bps.expanding(min_periods=min_periods).mean()
    std = bps.expanding(min_periods=min_periods).std(ddof=1)
    return (bps - mean) / std.replace(0, pd.NA)


def credit_raw_on(bps: pd.Series, z: pd.Series) -> pd.Series:
    """Hysteresis. Missing z does not release and does not trigger the z leg."""
    aligned_z = z.reindex(bps.index)
    b_ok = bps.notna()
    z_ok = aligned_z.notna()
    trigger = b_ok & ((bps >= ON_BPS) | (z_ok & (aligned_z >= ON_Z)))
    release = b_ok & (bps < OFF_BPS) & z_ok & (aligned_z < OFF_Z)
    state = False
    out = []
    for trig, rel in zip(trigger.tolist(), release.tolist()):
        if state:
            if rel:
                state = False
        elif trig:
            state = True
        out.append(state)
    return pd.Series(out, index=bps.index, dtype=bool)


def credit_frame(spread: pd.Series) -> pd.DataFrame:
    bps = to_bps(spread)
    z = expanding_z(bps).reindex(bps.index)
    raw = credit_raw_on(bps, z)
    published = raw.astype(float).shift(1)
    return pd.DataFrame({'bps': bps, 'z': z, 'raw_on': raw.astype(float), 'on': published})


def _flag(on: bool, status: str, mode: str, detail: str, **extra) -> dict:
    payload = {
        'name': 'E_credit',
        'on': bool(on) and status == 'on',
        'status': status,
        'mode': mode,
        'tier': 'structural',
        'rule_en': RULES['E_credit']['rule_en'],
        'rule_zh': RULES['E_credit']['rule_zh'],
        'detail': detail,
    }
    payload.update(extra)
    return payload


def _date(value) -> str:
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return 'n/a'


def evaluate_credit_series(spread: pd.Series) -> dict:
    frame = credit_frame(spread)
    if frame.empty or frame['on'].dropna().empty:
        return _flag(
            False, 'skipped', 'insufficient',
            '信用利差历史不足，无法滞后 1 期。保留上一份。',
            inherit_previous=True,
        )
    published = frame['on'].iloc[-1]
    if pd.isna(published):
        return _flag(
            False, 'skipped', 'insufficient',
            '信用利差只有一期，滞后后无公布值。保留上一份。',
            inherit_previous=True,
        )
    on = bool(published)
    signal = frame.iloc[-2] if len(frame) >= 2 else frame.iloc[-1]
    bps = signal.get('bps')
    z = signal.get('z')
    bps_txt = 'n/a' if pd.isna(bps) else f'{float(bps):.0f}bp'
    z_txt = 'n/a' if pd.isna(z) else f'{float(z):.2f}'
    detail = (
        f'OAS {bps_txt} · Z {z_txt} · 滞后 1 期 · '
        f'ON≥{ON_BPS:.0f}bp 或 Z≥{ON_Z:.1f}；OFF 需 <{OFF_BPS:.0f}bp 且 Z<{OFF_Z:.1f}'
    )
    return _flag(
        on, 'on' if on else 'off', 'hysteresis', detail,
        metrics={
            'as_of': _date(frame.index[-1]),
            'signal_date': _date(frame.index[-2]) if len(frame) >= 2 else None,
            'bps': None if pd.isna(bps) else round(float(bps), 2),
            'z': None if pd.isna(z) else round(float(z), 3),
        },
    )


def parse_fred_csv(text: str) -> pd.Series:
    frame = pd.read_csv(io.StringIO(text))
    columns = {str(col).strip(): col for col in frame.columns}
    date_col = columns.get('DATE') or columns.get('date')
    value_col = columns.get(FRED_SERIES) or columns.get(FRED_SERIES.lower())
    if date_col is None or value_col is None:
        raise ValueError('FRED CSV is missing DATE or the OAS column')
    values = frame[value_col].replace('.', pd.NA)
    series = pd.to_numeric(values, errors='coerce')
    series.index = pd.to_datetime(frame[date_col], errors='coerce')
    series = series[series.index.notna()].dropna().sort_index()
    series = series[~series.index.duplicated(keep='last')]
    series.name = FRED_SERIES
    return series


def fetch_hy_oas(opener=None) -> pd.Series:
    import urllib.request

    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(FRED_CSV_URL, headers={'User-Agent': 'FontesFund risk-officer research'})
    with opener(req, timeout=20) as resp:
        raw = resp.read()
    if isinstance(raw, str):
        text = raw
    else:
        text = raw.decode('utf-8', errors='replace')
    return parse_fred_csv(text)


def _write_spread(path: Path, series: pd.Series) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({'spread_percent': series.astype(float)})
    frame.index.name = 'date'
    frame.to_csv(path)


def _read_spread(path: Path) -> pd.Series:
    frame = pd.read_csv(path, parse_dates=['date'])
    series = pd.to_numeric(frame['spread_percent'], errors='coerce')
    series.index = pd.to_datetime(frame['date'])
    return series.dropna().sort_index()


def load_spread(cache_path, fetch: bool = False, fetcher=None):
    target = Path(cache_path)
    error = None
    if fetch:
        try:
            series = (fetcher or fetch_hy_oas)()
            if series is not None and not series.dropna().empty:
                _write_spread(target, series)
                return series, None
            error = 'empty OAS series'
        except Exception as exc:  # noqa: BLE001 — keep the cache or the previous flag
            error = exc.__class__.__name__
    if target.is_file():
        try:
            return _read_spread(target), None
        except Exception as exc:  # noqa: BLE001
            error = exc.__class__.__name__
    return None, error or 'missing OAS series'


def evaluate_credit_source(cache_path, fetch: bool = False, fetcher=None) -> dict:
    series, error = load_spread(cache_path, fetch=fetch, fetcher=fetcher)
    if series is None or series.dropna().empty:
        return _flag(
            False, 'skipped', 'missing',
            f'没有高收益债 OAS（{error}）。保留上一份 E_credit。',
            inherit_previous=True,
        )
    return evaluate_credit_series(series)
