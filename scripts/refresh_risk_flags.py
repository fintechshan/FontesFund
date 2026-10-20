#!/usr/bin/env python3
"""Refresh the notify-only risk scorecard from Yahoo Finance.

Writes, only after at least one series downloads:

* ``data/risk_flags/flags.json`` — lagged A_vol / B_crowd / C_put scorecard
* ``data/risk_flags/prices.csv`` — the closes used to build it (gitignored)

Does not place orders, change weights, or read the QQQ Vegas v9 sleeve.
A failed download leaves the previous ``flags.json`` in place.

    python scripts/refresh_risk_flags.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.risk_flags import compute_snapshot, write_snapshot  # noqa: E402

DEFAULT_DIR = ROOT / 'data' / 'risk_flags'
PRICE_NAME = 'prices.csv'
START = '2005-01-01'
# SOXX close plus high/low for the 10-day range. VIX and VXN are closes.
SERIES = (
    ('SOXX', 'SOXX', 'close'),
    ('SOXX_HIGH', 'SOXX', 'high'),
    ('SOXX_LOW', 'SOXX', 'low'),
    ('VIX', '^VIX', 'close'),
    ('VXN', '^VXN', 'close'),
)


def _column(df: pd.DataFrame, field: str) -> pd.Series:
    wanted = 'High' if field == 'high' else 'Low' if field == 'low' else 'Close'
    frame = df
    if isinstance(frame.columns, pd.MultiIndex):
        level0 = frame.columns.get_level_values(0)
        level_last = frame.columns.get_level_values(-1)
        if wanted in level0:
            picked = frame[wanted]
        elif wanted in level_last:
            picked = frame.xs(wanted, axis=1, level=-1)
        else:
            picked = frame.iloc[:, [0]]
        if isinstance(picked, pd.DataFrame):
            picked = picked.iloc[:, 0]
    elif wanted in frame.columns:
        picked = frame[wanted]
    else:
        picked = frame.iloc[:, 0]
    series = pd.to_numeric(pd.Series(picked), errors='coerce').dropna()
    series.index = pd.to_datetime(series.index)
    if getattr(series.index, 'tz', None) is not None:
        series.index = series.index.tz_localize(None)
    series = series.sort_index()
    series = series[~series.index.duplicated(keep='last')]
    return series


def _download_one(ticker: str):
    import yfinance as yf

    last_err = None
    for attempt in range(3):
        try:
            df = yf.download(
                ticker, start=START, auto_adjust=True, progress=False, threads=False,
            )
            if df is not None and not getattr(df, 'empty', True):
                return df
        except Exception as exc:  # noqa: BLE001 — keep the previous scorecard
            last_err = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'{ticker}: {last_err}')


def download_series():
    """Best-effort Yahoo download. Missing names are omitted, not fatal."""
    frames = {}
    errors = []
    fetched = {}
    for name, ticker, field in SERIES:
        if ticker not in fetched:
            try:
                fetched[ticker] = _download_one(ticker)
            except Exception as exc:  # noqa: BLE001
                fetched[ticker] = None
                errors.append(str(exc))
        raw = fetched.get(ticker)
        if raw is None:
            continue
        try:
            series = _column(raw, field)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'{name}: {exc}')
            continue
        if series.empty:
            errors.append(f'{name}: empty')
            continue
        series.name = name
        frames[name] = series
    return frames, errors


def _frame_to_csv(frames: dict, path: Path) -> None:
    if not frames:
        return
    table = pd.DataFrame(frames)
    table.index.name = 'date'
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path)


def refresh(directory: Path | None = None) -> bool:
    dest = Path(directory) if directory is not None else DEFAULT_DIR
    frames, errors = download_series()
    if not frames:
        print('风险旗：行情下载失败，保留上一份 flags.json。' + ' '.join(errors), file=sys.stderr)
        return False
    snap = compute_snapshot(
        frames.get('SOXX'),
        frames.get('VIX'),
        frames.get('VXN'),
        soxx_high=frames.get('SOXX_HIGH'),
        soxx_low=frames.get('SOXX_LOW'),
    )
    snap['source'] = 'yahoo'
    if errors:
        snap['download_notes'] = errors
    write_snapshot(snap, dest / 'flags.json')
    _frame_to_csv(frames, dest / PRICE_NAME)
    flags = snap.get('flags') or {}
    summary = ' '.join(
        f"{key}={((flags.get(key) or {}).get('status'))}" for key in ('A_vol', 'B_crowd', 'C_put')
    )
    print(f"风险旗已写入 {dest / 'flags.json'} as_of {snap.get('as_of')} {summary}")
    if errors:
        print('部分行情缺失：' + '; '.join(errors), file=sys.stderr)
    return True


def main(argv=None) -> None:
    ok = refresh()
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
