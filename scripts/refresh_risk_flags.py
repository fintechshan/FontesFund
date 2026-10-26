#!/usr/bin/env python3
"""Refresh the notify-only risk scorecard.

Writes, only after at least one price series downloads:

* ``data/risk_flags/flags.json`` — A_vol / B_crowd / C_put plus D_capex / E_credit / F_conc
* ``data/risk_flags/prices.csv`` — the closes used for the tactical flags (gitignored)

Structural inputs (gitignored caches, filled when the source answers):

* ``capex_official.csv`` — SEC EDGAR for six public names. SpaceX stays blank.
* ``credit_oas.csv`` — FRED BAMLH0A0HYM2
* ``spy_mag7_weight.csv`` — Mag7 weight inside SPY

Does not place orders, change weights, or read the QQQ Vegas v9 sleeve.
A failed price download leaves the previous ``flags.json`` in place.
A failed structural source keeps that flag's previous on/off state.

    python scripts/refresh_risk_flags.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.risk_flags import (  # noqa: E402
    FLAG_IDS,
    STRUCTURAL_FLAG_IDS,
    _blank_flag,
    attach_structural,
    compute_snapshot,
    write_snapshot,
)

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


def _read_previous(path: Path):
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def refresh(directory: Path | None = None, *, fetch_structural: bool = True, downloader=None) -> bool:
    dest = Path(directory) if directory is not None else DEFAULT_DIR
    download = downloader or download_series
    frames, errors = download()
    if not frames:
        print('风险旗：行情下载失败，保留上一份 flags.json。' + ' '.join(errors), file=sys.stderr)
        return False
    previous = _read_previous(dest / 'flags.json')
    snap = compute_snapshot(
        frames.get('SOXX'),
        frames.get('VIX'),
        frames.get('VXN'),
        soxx_high=frames.get('SOXX_HIGH'),
        soxx_low=frames.get('SOXX_LOW'),
    )
    from src.risk_officer import build_structural_flags

    try:
        structural = build_structural_flags(previous, directory=dest, fetch=fetch_structural)
    except Exception as exc:  # noqa: BLE001 — tactical scorecard still writes
        structural = {'flags': {}, 'notes': [f'structural: {exc.__class__.__name__}']}
        for key in STRUCTURAL_FLAG_IDS:
            item = _blank_flag(key, '结构旗计算失败，保留上一份。')
            item['inherit_previous'] = True
            structural['flags'][key] = item
    snap = attach_structural(snap, structural.get('flags'), previous=previous)
    snap['source'] = 'yahoo'
    if errors:
        snap['download_notes'] = errors
    if structural.get('notes'):
        snap['structural_notes'] = structural['notes']
    write_snapshot(snap, dest / 'flags.json')
    _frame_to_csv(frames, dest / PRICE_NAME)
    flags = snap.get('flags') or {}
    summary = ' '.join(
        f"{key}={((flags.get(key) or {}).get('status'))}" for key in FLAG_IDS
    )
    score = snap.get('bubble_pressure_score')
    print(
        f"风险旗已写入 {dest / 'flags.json'} as_of {snap.get('as_of')} "
        f"bubble {score} {summary}"
    )
    if errors:
        print('部分行情缺失：' + '; '.join(errors), file=sys.stderr)
    return True


def main(argv=None) -> None:
    ok = refresh()
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
