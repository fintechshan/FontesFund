"""Extend the locked QQQ Vegas v9 sleeve. Do not replace the gate.

The published book is ``qqq_vegas_rv20_q80`` / ``v9_rv20_q80``:

* Vegas tunnel on the QQQ close: Mom189 > 0, close > SMA150, close >= min(EMA144, EMA169)
* RV gate: rv20 = std(close-to-close, 20, ddof=1) * sqrt(252);
  q80 = expanding 80% quantile of rv20.shift(1), min_periods=252; rv_ok = rv20 <= q80
* risk_on = Vegas AND rv_ok
* Position is that signal shifted one session (confirm at the close, fill the next open)
* Risk-on is 70% QQQ + 30% QLD. Risk-off is 100% cash. No mid-hold rebalance
* 4 bps on the QQQ + 2x leg when that position changes
* QLD is synthetic ``2*QQQ - cash - 0.95%/yr`` before 2006-06-21, the listed fund after
* Cash is IRX/100/252 before 2010-01-04, BIL after

The published series starts 1999-01-04. The expanding Q80 on that first bar is already
the ~0.31 full-sample threshold, so the quantile is preheated: Nasdaq-100 closes from
1996-12-31, scaled onto the first published QQQ close, then the stored splice. A short
history that starts in 1999 and drops that preheat is a different gate (it disagrees
with the committed rv_ok path). This script recomputes the gate on that preheated
series, refuses to write when the overlap disagrees with ``daily_signal.csv``, and
appends only new sessions.

Prices are Yahoo Finance adjusted closes via yfinance. The market-price cache is not
an input. A failed download or a gate mismatch leaves the previous files in place.

    python scripts/refresh_qqq_vegas_signal.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / 'data' / 'qqq_vegas'

PREHEAT_START = pd.Timestamp('1996-12-31')
QLD_LISTED = pd.Timestamp('2006-06-21')
BIL_START = pd.Timestamp('2010-01-04')
W_QQQ = 0.7
W_QLD = 0.3
COST = 4.0 / 10000.0
QLD_FEE = 0.0095 / 252.0
Q80_Q = 0.80
Q80_MIN_PERIODS = 252
HISTORY_START_MAX = pd.Timestamp('1999-12-31')
MIN_HISTORY_ROWS = 2000

SIGNAL_FILES = (
    'daily_signal.csv',
    'equity_curve.csv',
    'rebalances.csv',
    'monthly_returns.csv',
    'yearly_returns.csv',
    'signal_current.json',
    'summary.json',
    'strategy.json',
    'live_snapshot.json',
)


def _download_close(ticker, start):
    """Adjusted close. Retries a few times; the caller keeps the previous pack."""
    import time
    import yfinance as yf

    last_err = None
    for attempt in range(3):
        try:
            frame = yf.download(
                ticker, start=start, auto_adjust=True, progress=False, threads=False,
            )
            if frame is None or getattr(frame, 'empty', True):
                raise ValueError(f'{ticker}: empty download')
            if isinstance(frame.columns, pd.MultiIndex):
                close = frame['Close']
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
            else:
                close = frame['Close'] if 'Close' in frame.columns else frame.iloc[:, 0]
            series = pd.to_numeric(pd.Series(close), errors='coerce').dropna()
            series.index = pd.to_datetime(series.index)
            if getattr(series.index, 'tz', None) is not None:
                series.index = series.index.tz_localize(None)
            series = series.sort_index()
            series = series[~series.index.duplicated(keep='last')]
            if series.empty:
                raise ValueError(f'{ticker}: no closes')
            series.name = ticker
            return series
        except Exception as exc:  # noqa: BLE001 — leave the pack unchanged
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'{ticker}: {last_err}')


def download_market():
    """NDX preheat plus the listed legs the sleeve actually trades."""
    return {
        'ndx': _download_close('^NDX', '1996-12-01'),
        'qqq': _download_close('QQQ', '1999-03-01'),
        'qld': _download_close('QLD', '2006-06-01'),
        'bil': _download_close('BIL', '2007-05-01'),
        'irx': _download_close('^IRX', '1996-01-01'),
    }


def compute_indicators(close):
    """Locked v9 indicators on one close series. ``pos`` is not included.

    ``pos`` is ``signal.shift(1)`` on the published calendar only. Shifting on a
    series that still contains the preheat would fill the first 1999 bar from a
    1998 signal.
    """
    close = pd.to_numeric(pd.Series(close), errors='coerce').astype(float).sort_index()
    ret = close.pct_change()
    rv20 = ret.rolling(20).std(ddof=1) * np.sqrt(252)
    q80 = rv20.shift(1).expanding(min_periods=Q80_MIN_PERIODS).quantile(Q80_Q)
    mom = close / close.shift(189) - 1.0
    sma = close.rolling(150).mean()
    ema144 = close.ewm(span=144, adjust=False).mean()
    ema169 = close.ewm(span=169, adjust=False).mean()
    vegas_low = np.minimum(ema144, ema169)
    vegas = ((mom > 0) & (close > sma) & (close >= vegas_low)).astype(int)
    rv_ok = (rv20 <= q80).astype(int)
    signal = ((vegas == 1) & (rv_ok == 1)).astype(int)
    return pd.DataFrame({
        'close': close,
        'rv20': rv20,
        'rv20_q80': q80,
        'mom189': mom,
        'sma150': sma,
        'vegas_low': vegas_low,
        'vegas': vegas,
        'rv_ok': rv_ok,
        'signal': signal,
    })


def _published_pos(signal):
    pos = signal.shift(1)
    if len(pos):
        pos.iloc[0] = 0
    return pos.fillna(0).astype(int)


def _irx_daily(irx, index):
    series = pd.to_numeric(irx, errors='coerce').sort_index()
    daily = (series / 100.0) / 252.0
    return daily.reindex(index).ffill()


def _leg_return(level, index):
    series = pd.to_numeric(level, errors='coerce').sort_index()
    return series.pct_change().reindex(index)


def sleeve_return(index, qqq_ret, qld_level, bil_level, irx, pos):
    """Close-to-close sleeve return. Cost hits only when ``pos`` changes."""
    qqq_ret = pd.Series(qqq_ret, index=index).astype(float)
    cash_daily = _irx_daily(irx, index)
    qld_ret = _leg_return(qld_level, index)
    bil_ret = _leg_return(bil_level, index)
    prev = pos.shift(1)
    out = []
    for stamp, held in pos.items():
        qret = float(qqq_ret.loc[stamp]) if pd.notna(qqq_ret.loc[stamp]) else np.nan
        cash = float(cash_daily.loc[stamp]) if pd.notna(cash_daily.loc[stamp]) else np.nan
        qld = qld_ret.loc[stamp]
        bil = bil_ret.loc[stamp]
        if stamp >= QLD_LISTED and pd.notna(qld):
            two = float(qld)
        else:
            two = 2.0 * qret - cash - QLD_FEE
        if int(held) == 1:
            gross = W_QQQ * qret + W_QLD * two
        elif stamp >= BIL_START and pd.notna(bil):
            gross = float(bil)
        else:
            gross = cash
        previous = prev.loc[stamp]
        if pd.notna(previous) and int(previous) != int(held):
            gross -= COST
        out.append(gross)
    return pd.Series(out, index=index, dtype=float)


def _trim(value, digits):
    text = f'{float(value):.{digits}f}'
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    if text in {'', '-', '-0'}:
        return '0'
    return text


def _fmt_pct(value):
    return _trim(round(float(value) + 0.0, 2), 2)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def _read_signal(directory: Path) -> pd.DataFrame:
    path = directory / 'daily_signal.csv'
    frame = pd.read_csv(path, parse_dates=['date']).set_index('date').sort_index()
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame


def _read_equity(directory: Path) -> pd.DataFrame:
    path = directory / 'equity_curve.csv'
    frame = pd.read_csv(path, parse_dates=['date']).set_index('date').sort_index()
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame


def _extend_close(stored_close, qqq):
    """Chain Yahoo QQQ returns onto the stored splice. History is not rescaled."""
    anchor = stored_close.index.max()
    yahoo = pd.to_numeric(qqq, errors='coerce').sort_index()
    yahoo.index = pd.to_datetime(yahoo.index).tz_localize(None)
    if anchor not in yahoo.index:
        raise RuntimeError(f'QQQ download has no close on the stored session {anchor.date()}')
    new_index = yahoo.index[yahoo.index > anchor]
    if len(new_index) == 0:
        return stored_close.copy(), new_index
    scale = float(stored_close.loc[anchor]) / float(yahoo.loc[anchor])
    extended = pd.concat([
        stored_close,
        yahoo.loc[new_index] * scale,
    ])
    extended = extended[~extended.index.duplicated(keep='last')].sort_index()
    return extended, new_index


def _preheat(stored_close, ndx):
    anchor = stored_close.index.min()
    level = pd.to_numeric(ndx, errors='coerce').sort_index()
    level.index = pd.to_datetime(level.index).tz_localize(None)
    if anchor not in level.index:
        raise RuntimeError(f'NDX download has no close on {anchor.date()}')
    scaled = level / float(level.loc[anchor]) * float(stored_close.loc[anchor])
    pre = scaled.loc[(scaled.index >= PREHEAT_START) & (scaled.index < anchor)]
    if pre.empty or pre.index.min() != PREHEAT_START:
        raise RuntimeError(
            f'NDX preheat does not start on {PREHEAT_START.date()} '
            f'(got {None if pre.empty else pre.index.min().date()})'
        )
    return pre


def _guard(stored, recomputed):
    """Refuse a write when the recomputed gate is not the committed series."""
    overlap = recomputed.reindex(stored.index)
    problems = []
    for column in ('signal', 'pos', 'vegas', 'rv_ok'):
        left = overlap[column].astype(int)
        right = stored[column].astype(int)
        mismatches = int((left != right).sum())
        if mismatches:
            problems.append(f'{column} mismatches {mismatches}')
    for column, limit in (('rv20', 1e-4), ('rv20_q80', 1e-4)):
        delta = (overlap[column] - stored[column]).abs()
        worst = float(delta.max())
        if worst > limit:
            problems.append(f'{column} max abs error {worst:.6g} > {limit}')
    if problems:
        raise RuntimeError('refusing to write; gate disagrees with daily_signal.csv: ' + '; '.join(problems))


def _window_stats(nav, ret, start, end):
    """Calendar-day CAGR from the bar before ``start``, Sharpe on the window returns."""
    nav = pd.to_numeric(nav, errors='coerce').dropna().sort_index()
    ret = pd.to_numeric(ret, errors='coerce').reindex(nav.index)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    window_nav = nav.loc[(nav.index >= start_ts) & (nav.index <= end_ts)]
    if window_nav.empty:
        raise RuntimeError(f'no equity between {start} and {end}')
    prior = nav.loc[nav.index < window_nav.index[0]]
    base = float(prior.iloc[-1]) if len(prior) else float(window_nav.iloc[0])
    last = float(window_nav.iloc[-1])
    final = last / base
    days = int((window_nav.index[-1] - window_nav.index[0]).days)
    cagr = final ** (365.25 / days) - 1.0 if days > 0 else 0.0
    window_ret = ret.loc[window_nav.index].dropna()
    sharpe = float(window_ret.mean() / window_ret.std(ddof=1) * np.sqrt(252))
    vol = float(window_ret.std(ddof=1) * np.sqrt(252))
    drawdown = window_nav / window_nav.cummax() - 1.0
    maxdd = float(drawdown.min())
    cagr_r = round(float(cagr), 6)
    maxdd_r = round(maxdd, 6)
    calmar = round(cagr_r / abs(maxdd_r), 4) if maxdd_r else None
    return {
        'CAGR': cagr_r,
        'CAGR_pct': round(cagr_r * 100, 2),
        'MaxDD': maxdd_r,
        'MaxDD_pct': round(maxdd_r * 100, 2),
        'MaxDD_Date': pd.Timestamp(drawdown.idxmin()).strftime('%Y-%m-%d'),
        'Sharpe': round(sharpe, 4),
        'Calmar': calmar,
        'Vol_pct': round(vol * 100, 2),
        'start': pd.Timestamp(window_nav.index[0]).strftime('%Y-%m-%d'),
        'end': pd.Timestamp(window_nav.index[-1]).strftime('%Y-%m-%d'),
        'n_days': int(len(window_nav)),
        'final_nav': round(final, 4),
    }


def _signal_metrics(stats):
    return {
        'cagr': stats['CAGR'],
        'max_dd': stats['MaxDD'],
        'sharpe': stats['Sharpe'],
        'cagr_pct': stats['CAGR_pct'],
        'max_dd_pct': stats['MaxDD_pct'],
        'max_dd_date': stats['MaxDD_Date'],
        'calmar': stats['Calmar'],
        'start': stats['start'],
        'end': stats['end'],
    }


def _apply_summary_block(block, stats):
    for key, value in stats.items():
        if key in block:
            block[key] = value


def _month_returns(nav):
    """Percent month returns. January 1999 uses the first bar as the base."""
    nav = pd.to_numeric(nav, errors='coerce').dropna().sort_index()
    month_end = nav.resample('ME').last().dropna()
    out = {}
    prev = None
    first_year = int(nav.index[0].year)
    for stamp, value in month_end.items():
        if prev is None:
            base = float(nav.iloc[0]) if int(stamp.year) == first_year else float(value)
        else:
            base = prev
        out[(int(stamp.year), int(stamp.month))] = (float(value) / base - 1.0) * 100.0
        prev = float(value)
    return out


def _year_returns(nav):
    nav = pd.to_numeric(nav, errors='coerce').dropna().sort_index()
    out = {}
    first_year = int(nav.index.min().year)
    for year, group in nav.groupby(nav.index.year):
        year = int(year)
        if year == first_year:
            base = float(nav.iloc[0])
        else:
            prev = nav.loc[nav.index.year == year - 1]
            if prev.empty:
                continue
            base = float(prev.iloc[-1])
        out[year] = (float(group.iloc[-1]) / base - 1.0) * 100.0
    return out


def _patch_monthly(path: Path, nav) -> None:
    """Replace only the in-progress month. Earlier cells stay as committed."""
    rets = _month_returns(nav)
    stamp = nav.index.max()
    key = (int(stamp.year), int(stamp.month))
    lines = path.read_text(encoding='utf-8').splitlines()
    updated = []
    found = False
    for line in lines:
        parts = line.split(',')
        if parts and parts[0].isdigit() and int(parts[0]) == key[0]:
            while len(parts) < 13:
                parts.append('')
            parts[key[1]] = _fmt_pct(rets[key])
            line = ','.join(parts[:13])
            found = True
        updated.append(line)
    if not found:
        raise RuntimeError(f'monthly_returns.csv has no {key[0]} row')
    _atomic_text(path, '\n'.join(updated) + '\n')


def _patch_yearly(path: Path, equity, vegas, qqq) -> None:
    """Replace only the latest calendar year. Earlier years stay as committed."""
    year = int(equity.index.max().year)
    strat = _year_returns(equity)[year]
    prior = _year_returns(vegas)[year]
    hold = _year_returns(qqq)[year]
    lines = path.read_text(encoding='utf-8').splitlines()
    updated = []
    found = False
    row = f'{year},{_fmt_pct(strat)},{_fmt_pct(prior)},{_fmt_pct(hold)}'
    for line in lines:
        if line.startswith(f'{year},'):
            line = row
            found = True
        updated.append(line)
    if not found:
        updated.append(row)
    _atomic_text(path, '\n'.join(updated) + '\n')


def _append_csv(path: Path, frame: pd.DataFrame) -> None:
    text = path.read_text(encoding='utf-8')
    if not text.endswith('\n'):
        text += '\n'
    body = frame.to_csv(index=False, header=False)
    _atomic_text(path, text + body)


def _reason(row):
    def mark(flag):
        return 'OK' if flag else 'OFF'

    state = 'RISK_ON' if int(row['signal']) == 1 else 'CASH'
    return (
        f"Mom189={mark(row['mom189'] > 0)} ({row['mom189']:.4f}); "
        f"Close>SMA150={mark(row['close'] > row['sma150'])}; "
        f"Close>=VegasLow={mark(row['close'] >= row['vegas_low'])}; "
        f"RV20<=Q80={mark(row['rv20'] <= row['rv20_q80'])} "
        f"(rv20={row['rv20']:.4f}, q80={row['rv20_q80']:.4f}) → {state}"
    )


def _next_action(signal, pos):
    if int(signal) == int(pos):
        return 'HOLD'
    return 'ENTER' if int(signal) == 1 else 'EXIT'


def _state(pos):
    return 'RISK_ON' if int(pos) == 1 else 'CASH'


def _weights(pos):
    if int(pos) == 1:
        return W_QQQ, W_QLD, 0.0, None
    return 0.0, 0.0, 1.0, 'BIL'


def _dump_json(path: Path, payload) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + '\n')


def _load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def refresh_signal(directory=None, market=None, now=None):
    """Append new sessions when the recomputed gate matches the stored series.

    Returns a before/after record. Writes nothing when ``market`` has no session
    after the stored pack, and writes nothing when the overlap disagrees.
    """
    directory = Path(directory) if directory is not None else DEFAULT_DIR
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    generated_at = moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    stored = _read_signal(directory)
    equity = _read_equity(directory)
    if stored.empty or equity.empty:
        raise RuntimeError('signal pack is empty')
    if stored.index.min() > HISTORY_START_MAX or len(stored) < MIN_HISTORY_ROWS:
        raise RuntimeError('stored history is shorter than the 1999 sleeve; refusing')
    if not stored.index.equals(equity.index):
        raise RuntimeError('daily_signal.csv and equity_curve.csv dates disagree')

    market = market if market is not None else download_market()
    published_close, new_index = _extend_close(stored['qqq_close'], market['qqq'])
    before = _snapshot(stored, equity)
    if len(new_index) == 0:
        before['changed'] = False
        before['after'] = before['before']
        return before

    pre = _preheat(published_close, market['ndx'])
    long_close = pd.concat([pre, published_close]).sort_index()
    long_close = long_close[~long_close.index.duplicated(keep='last')]
    indicators = compute_indicators(long_close).reindex(published_close.index)
    indicators['pos'] = _published_pos(indicators['signal'])
    _guard(stored, indicators)

    new = indicators.loc[new_index]
    if new[['signal', 'vegas', 'rv_ok', 'rv20', 'rv20_q80', 'mom189', 'sma150', 'vegas_low', 'close']].isna().any().any():
        raise RuntimeError('a new session is missing a Vegas or Q80 input')

    qqq_ret = published_close.pct_change()
    pos = indicators['pos']
    qld_ret = _leg_return(market['qld'], published_close.index)
    bil_ret = _leg_return(market['bil'], published_close.index)
    for stamp in new_index:
        held = int(pos.loc[stamp])
        if pd.isna(qqq_ret.loc[stamp]):
            raise RuntimeError(f'{stamp.date()} has no QQQ return')
        if stamp >= QLD_LISTED and held == 1 and pd.isna(qld_ret.loc[stamp]):
            raise RuntimeError(f'{stamp.date()} is risk-on without a QLD return')
        if held == 0 and stamp >= BIL_START and pd.isna(bil_ret.loc[stamp]):
            raise RuntimeError(f'{stamp.date()} is risk-off without a BIL return')
    strat_ret = sleeve_return(
        published_close.index, qqq_ret, market['qld'], market['bil'], market['irx'], pos,
    )
    vegas_pos = _published_pos(indicators['vegas'])
    vegas_ret = sleeve_return(
        published_close.index, qqq_ret, market['qld'], market['bil'], market['irx'], vegas_pos,
    )

    nav = float(equity['equity'].iloc[-1])
    vegas_nav = float(equity['vegas_only_equity'].iloc[-1])
    bh_nav = float(equity['qqq_bh'].iloc[-1])
    peak = float(equity['equity'].max())
    vegas_peak = float(equity['vegas_only_equity'].max())
    rows = []
    for stamp in new_index:
        nav = round(nav * (1.0 + float(strat_ret.loc[stamp])), 3)
        vegas_nav = round(vegas_nav * (1.0 + float(vegas_ret.loc[stamp])), 3)
        bh_nav = round(bh_nav * (1.0 + float(qqq_ret.loc[stamp])), 3)
        peak = max(peak, nav)
        vegas_peak = max(vegas_peak, vegas_nav)
        held = int(pos.loc[stamp])
        qqq_w, qld_w, cash_w = (W_QQQ, W_QLD, 0.0) if held == 1 else (0.0, 0.0, 1.0)
        rows.append({
            'date': stamp,
            'equity': nav,
            'qqq_bh': bh_nav,
            'drawdown': nav / peak - 1.0,
            'vegas_only_equity': vegas_nav,
            'vegas_only_drawdown': vegas_nav / vegas_peak - 1.0,
            'strat_ret': float(strat_ret.loc[stamp]),
            'signal': int(new.loc[stamp, 'signal']),
            'pos': held,
            'vegas': int(new.loc[stamp, 'vegas']),
            'rv_ok': int(new.loc[stamp, 'rv_ok']),
            'rv20': float(new.loc[stamp, 'rv20']),
            'rv20_q80': float(new.loc[stamp, 'rv20_q80']),
            'qqq_w': qqq_w,
            'qld_w': qld_w,
            'cash_w': cash_w,
            'mom189': float(new.loc[stamp, 'mom189']),
            'sma150': float(new.loc[stamp, 'sma150']),
            'vegas_low': float(new.loc[stamp, 'vegas_low']),
            'close': float(new.loc[stamp, 'close']),
        })
    added = pd.DataFrame(rows).set_index('date')

    signal_lines = pd.DataFrame({
        'date': [stamp.strftime('%Y-%m-%d') for stamp in added.index],
        'signal': added['signal'].astype(int),
        'pos': added['pos'].astype(int),
        'vegas': added['vegas'].astype(int),
        'rv_ok': added['rv_ok'].astype(int),
        'rv20': added['rv20'].map(lambda v: _trim(v, 6)),
        'rv20_q80': added['rv20_q80'].map(lambda v: _trim(v, 6)),
        'mom189': added['mom189'].map(lambda v: _trim(v, 6)),
        'sma150': added['sma150'].map(lambda v: _trim(v, 6)),
        'vegas_low': added['vegas_low'].map(lambda v: _trim(v, 6)),
        'qqq_close': added['close'].map(lambda v: _trim(v, 6)),
        'w_qqq': added['qqq_w'].map(lambda v: f'{float(v):.1f}'),
        'w_qld': added['qld_w'].map(lambda v: f'{float(v):.1f}'),
        'w_bil': added['cash_w'].map(lambda v: f'{float(v):.1f}'),
    })
    equity_lines = pd.DataFrame({
        'date': signal_lines['date'],
        'equity': added['equity'].map(lambda v: _trim(v, 3)),
        'qqq_bh': added['qqq_bh'].map(lambda v: _trim(v, 3)),
        'drawdown': added['drawdown'].map(lambda v: _trim(v, 8)),
        'vegas_only_equity': added['vegas_only_equity'].map(lambda v: _trim(v, 3)),
        'vegas_only_drawdown': added['vegas_only_drawdown'].map(lambda v: _trim(v, 8)),
        'strat_ret': added['strat_ret'].map(lambda v: _trim(v, 8)),
        'signal': added['signal'].astype(int),
        'pos': added['pos'].astype(int),
        'vegas': added['vegas'].astype(int),
        'rv_ok': added['rv_ok'].astype(int),
        'rv20': signal_lines['rv20'],
        'rv20_q80': signal_lines['rv20_q80'],
    })
    _append_csv(directory / 'daily_signal.csv', signal_lines)
    _append_csv(directory / 'equity_curve.csv', equity_lines)

    full_equity = _read_equity(directory)
    _patch_monthly(directory / 'monthly_returns.csv', full_equity['equity'])
    _patch_yearly(
        directory / 'yearly_returns.csv',
        full_equity['equity'], full_equity['vegas_only_equity'], full_equity['qqq_bh'],
    )
    _rewrite_json(directory, full_equity, added.iloc[-1], generated_at)
    after_signal = _read_signal(directory)
    report = _snapshot(stored, equity)
    report['after'] = _snapshot(after_signal, full_equity)['before']
    report['changed'] = True
    report['sessions_added'] = [stamp.strftime('%Y-%m-%d') for stamp in added.index]
    report['generated_at'] = generated_at
    return report


def _rewrite_json(directory, equity, last, generated_at):
    as_of = pd.Timestamp(equity.index.max()).strftime('%Y-%m-%d')
    old_signal = _load_json(directory / 'signal_current.json')
    old_as_of = str(old_signal.get('as_of') or '')[:10]
    nav = equity['equity']
    bh = equity['qqq_bh']
    bh_ret = bh.pct_change()
    vegas_nav = equity['vegas_only_equity']
    vegas_ret = vegas_nav.pct_change()

    equity = equity.copy()
    equity['bh_ret'] = bh_ret
    equity['vegas_ret'] = vegas_ret
    summary = _load_json(directory / 'summary.json')
    strategy = _load_json(directory / 'strategy.json')
    signal = old_signal
    live = _load_json(directory / 'live_snapshot.json')

    def refresh_named(block, nav_name, ret_name):
        if not isinstance(block, dict) or str(block.get('end') or '')[:10] != old_as_of:
            return None
        return _window_stats(equity[nav_name], equity[ret_name], block.get('start'), as_of)

    primary = summary.get('configs', {}).get('vegas_rv20_q80', {})
    prior = summary.get('configs', {}).get('vegas_1_3x_same_engine', {})
    for name, block in primary.items():
        if name in {'name', 'w_qld', 'use_cash_yield', 'cost_bps'}:
            continue
        refreshed = refresh_named(block, 'equity', 'strat_ret')
        if refreshed:
            _apply_summary_block(block, refreshed)
    for name, block in prior.items():
        if name in {'name', 'w_qld'}:
            continue
        refreshed = refresh_named(block, 'vegas_only_equity', 'vegas_ret')
        if refreshed:
            _apply_summary_block(block, refreshed)
    hold = summary.get('buy_hold_qqq', {}).get('full')
    refreshed = refresh_named(hold, 'qqq_bh', 'bh_ret')
    if refreshed:
        _apply_summary_block(hold, refreshed)

    compare = summary.get('compare_to_prior_vegas', {})
    new_full = primary.get('full') if isinstance(primary, dict) else None
    prior_full = prior.get('full') if isinstance(prior, dict) else None
    if isinstance(new_full, dict) and isinstance(prior_full, dict):
        compare['new_full'] = json.loads(json.dumps(new_full))
        compare['prior_full'] = json.loads(json.dumps(prior_full))
        delta = compare.get('delta_full') if isinstance(compare.get('delta_full'), dict) else {}
        delta['dCAGR_pp'] = round(new_full['CAGR_pct'] - prior_full['CAGR_pct'], 2)
        delta['dMaxDD_pp'] = round(new_full['MaxDD_pct'] - prior_full['MaxDD_pct'], 2)
        delta['dSharpe'] = round(new_full['Sharpe'] - prior_full['Sharpe'], 4)
        delta['dCalmar'] = round(new_full['Calmar'] - prior_full['Calmar'], 4)
        compare['delta_full'] = delta

    summary['as_of'] = as_of
    summary['end_date'] = as_of
    summary['generated_at'] = generated_at

    full_stats = _window_stats(equity['equity'], equity['strat_ret'], signal.get('metrics', {}).get('full', {}).get('start', '1999-01-05'), as_of)
    oos_start = signal.get('metrics', {}).get('oos', {}).get('start', '2021-01-04')
    oos_stats = _window_stats(equity['equity'], equity['strat_ret'], oos_start, as_of)
    p2010_start = primary.get('p2010_2026', {}).get('start', '2010-01-04') if isinstance(primary, dict) else '2010-01-04'
    p2010_stats = _window_stats(equity['equity'], equity['strat_ret'], p2010_start, as_of)
    metrics = signal.get('metrics') if isinstance(signal.get('metrics'), dict) else {}
    metrics['full'] = _signal_metrics(full_stats)
    metrics['oos'] = _signal_metrics(oos_stats)
    window = metrics.get('p2010_2026') if isinstance(metrics.get('p2010_2026'), dict) else {}
    window.update({
        'cagr_pct': p2010_stats['CAGR_pct'],
        'max_dd_pct': p2010_stats['MaxDD_pct'],
        'sharpe': p2010_stats['Sharpe'],
        'calmar': p2010_stats['Calmar'],
    })
    metrics['p2010_2026'] = window
    signal['metrics'] = metrics

    qqq_w, qld_w, cash_w, cash_ticker = _weights(last['pos'])
    signal.update({
        'as_of': as_of,
        'signal_date': as_of,
        'exec_date': as_of,
        'state': _state(last['pos']),
        'weights': {'QQQ': qqq_w, 'QLD': qld_w, 'cash': cash_w},
        'cash_ticker': cash_ticker,
        'qqq_w': qqq_w,
        'qld_w': qld_w,
        'cash_w': cash_w,
        'current_signal': int(last['signal']),
        'current_pos': int(last['pos']),
        'vegas': int(last['vegas']),
        'rv_ok': int(last['rv_ok']),
        'rv20': round(float(last['rv20']), 6),
        'rv20_q80': round(float(last['rv20_q80']), 6),
        'mom189': round(float(last['mom189']), 6),
        'qqq_close': round(float(last['close']), 4),
        'sma150': round(float(last['sma150']), 4),
        'vegas_low': round(float(last['vegas_low']), 4),
        'next_action': _next_action(last['signal'], last['pos']),
        'reason': _reason(last),
    })

    strategy['asof'] = as_of
    strategy['generated_at'] = generated_at
    strategy['current_signal'] = int(last['signal'])
    strategy['current_pos'] = int(last['pos'])
    strategy['vegas'] = int(last['vegas'])
    strategy['rv_ok'] = int(last['rv_ok'])
    strategy['rv20'] = round(float(last['rv20']), 6)
    strategy['rv20_q80'] = round(float(last['rv20_q80']), 6)
    strategy['current_weights'] = {'QQQ': qqq_w, 'QLD': qld_w, 'BIL': cash_w}
    strategy['last_signal_date'] = as_of
    strat_metrics = strategy.get('metrics') if isinstance(strategy.get('metrics'), dict) else {}
    if isinstance(strat_metrics.get('full'), dict):
        _apply_summary_block(strat_metrics['full'], full_stats)
    if isinstance(strat_metrics.get('oos'), dict):
        _apply_summary_block(strat_metrics['oos'], oos_stats)
    if isinstance(strat_metrics.get('p2010_2026'), dict):
        strat_metrics['p2010_2026'].update({
            'CAGR_pct': p2010_stats['CAGR_pct'],
            'MaxDD_pct': p2010_stats['MaxDD_pct'],
            'Sharpe': p2010_stats['Sharpe'],
            'Calmar': p2010_stats['Calmar'],
        })
    strategy['metrics'] = strat_metrics

    target = live.get('target') if isinstance(live.get('target'), dict) else {}
    target.update({'state': _state(last['pos']), 'QQQ': qqq_w, 'QLD': qld_w, 'cash_ticker': cash_ticker, 'cash_w': cash_w})
    live['target'] = target
    live['signal_as_of'] = as_of
    live['strategy_id'] = signal.get('strategy_id', 'qqq_vegas_rv20_q80')

    _dump_json(directory / 'summary.json', summary)
    _dump_json(directory / 'strategy.json', strategy)
    _dump_json(directory / 'signal_current.json', signal)
    _dump_json(directory / 'live_snapshot.json', live)


def _snapshot(signal, equity):
    last_s = signal.iloc[-1]
    last_e = equity.iloc[-1]
    qqq_w = float(last_s['w_qqq'])
    qld_w = float(last_s['w_qld'])
    state = _state(last_s['pos'])
    return {
        'before': {
            'session': pd.Timestamp(signal.index[-1]).strftime('%Y-%m-%d'),
            'signal': int(last_s['signal']),
            'pos': int(last_s['pos']),
            'state': state,
            'vegas': int(last_s['vegas']),
            'rv_ok': int(last_s['rv_ok']),
            'weights': {'QQQ': qqq_w, 'QLD': qld_w, 'cash': float(last_s['w_bil'])},
            'rv20': float(last_s['rv20']),
            'rv20_q80': float(last_s['rv20_q80']),
            'equity': float(last_e['equity']),
            'rows': int(len(signal)),
        }
    }


def _print_report(report):
    before = report['before']
    after = report.get('after') or before

    def line(label, row):
        weights = row['weights']
        print(
            f"{label} session {row['session']} signal {row['signal']} "
            f"pos {row['pos']} state {row['state']} "
            f"vegas {row['vegas']} rv_ok {row['rv_ok']} "
            f"weights QQQ {weights['QQQ']} QLD {weights['QLD']} cash {weights['cash']} "
            f"rv20 {row['rv20']:.6f} q80 {row['rv20_q80']:.6f} "
            f"equity {row['equity']:.3f}"
        )

    line('before', before)
    line('after', after)
    same_signal = (
        before['signal'] == after['signal']
        and before['state'] == after['state']
        and before['weights'] == after['weights']
    )
    verdict = 'UNCHANGED' if same_signal else 'CHANGED'
    print(
        f"verdict {verdict} signal/state/weights; "
        f"sessions {before['session']} -> {after['session']}"
    )
    if report.get('sessions_added'):
        print('added ' + ','.join(report['sessions_added']))


def main(argv=None):
    del argv
    try:
        report = refresh_signal()
    except Exception as exc:  # noqa: BLE001 — caller keeps the previous pack
        print(f'QQQ Vegas signal pack unchanged: {exc}', file=sys.stderr)
        return 1
    _print_report(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
