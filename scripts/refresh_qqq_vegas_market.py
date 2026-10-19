"""Refresh cached QQQ and QLD prices and a market snapshot for the QQQ Vegas tab.

Writes, only after a successful download (a failure leaves the previous files):

* ``data/qqq_vegas/market_prices.csv`` — daily adjusted close (``date``, ``QQQ``, ``QLD``)
* ``data/qqq_vegas/market_snapshot.json`` — last trade, day change, PE, volume, 52-week range

The v9 sleeve does not read these files. Yahoo Finance via yfinance is the source.
PE is ``trailingPE`` when Yahoo publishes it, otherwise ``forwardPE``. A missing
value stays null and the tab shows N/A.

Daily path: Cloud Scheduler POSTs ``/tasks/refresh``, which runs this script and
uploads both files with the other GCS caches. The dashboard reads the cache.

    python scripts/refresh_qqq_vegas_market.py
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / 'data' / 'qqq_vegas'
PRICE_NAME = 'market_prices.csv'
SNAPSHOT_NAME = 'market_snapshot.json'
TICKERS = ('QQQ', 'QLD')
PRICE_START = '1999-01-01'
MIN_QQQ_ROWS = 1000
MIN_QLD_ROWS = 500
MAX_STALE_DAYS = 10


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def select_pe(info):
    """Yahoo trailing PE, else forward PE. Neither present → (None, None)."""
    info = info if isinstance(info, dict) else {}
    trailing = _num(info.get('trailingPE'))
    if trailing is not None and trailing > 0:
        return trailing, 'trailing'
    forward = _num(info.get('forwardPE'))
    if forward is not None and forward > 0:
        return forward, 'forward'
    return None, None


def _fast_get(fast, key):
    if fast is None:
        return None
    if isinstance(fast, dict):
        return fast.get(key)
    try:
        return fast[key]
    except Exception:
        try:
            return getattr(fast, key)
        except Exception:
            return None


def _close_series(df, ticker):
    """One adjusted-close series from a yfinance download frame."""
    if df is None or getattr(df, 'empty', True):
        raise ValueError(f'{ticker}: empty download')
    frame = df
    if isinstance(frame.columns, pd.MultiIndex):
        level0 = frame.columns.get_level_values(0)
        level_last = frame.columns.get_level_values(-1)
        if 'Close' in level0:
            close = frame['Close']
        elif 'Close' in level_last:
            close = frame.xs('Close', axis=1, level=-1)
        else:
            close = frame.iloc[:, [0]]
        if isinstance(close, pd.DataFrame):
            if ticker in close.columns:
                close = close[ticker]
            else:
                close = close.iloc[:, 0]
    elif 'Close' in frame.columns:
        close = frame['Close']
    else:
        close = frame.iloc[:, 0]
    series = pd.to_numeric(pd.Series(close), errors='coerce').dropna()
    series.index = pd.to_datetime(series.index)
    if getattr(series.index, 'tz', None) is not None:
        series.index = series.index.tz_localize(None)
    series = series.sort_index()
    series = series[~series.index.duplicated(keep='last')]
    series.name = ticker
    if series.empty:
        raise ValueError(f'{ticker}: no close prices')
    return series


def download_closes(tickers=TICKERS, start=PRICE_START):
    """Adjusted closes, one ticker at a time (yfinance batch downloads flake)."""
    import yfinance as yf

    closes = {}
    errors = []
    for ticker in tickers:
        last_err = None
        series = None
        for attempt in range(3):
            try:
                df = yf.download(
                    ticker, start=start, auto_adjust=True, progress=False, threads=False,
                )
                series = _close_series(df, ticker)
                break
            except Exception as exc:  # noqa: BLE001 — keep the previous cache on any miss
                last_err = exc
                series = None
                time.sleep(2 * (attempt + 1))
        if series is None:
            errors.append(f'{ticker}: {last_err}')
        else:
            closes[ticker] = series
    if errors:
        raise RuntimeError('price download failed: ' + '; '.join(errors))
    return closes


def _info_dict(ticker_obj):
    try:
        info = ticker_obj.info
    except Exception:
        return {}
    return info if isinstance(info, dict) else {}


def _fast_info(ticker_obj):
    try:
        return ticker_obj.fast_info
    except Exception:
        return None


def _empty_quote():
    return {
        'last': None,
        'previous_close': None,
        'volume': None,
        'week52_high': None,
        'week52_low': None,
        'currency': 'USD',
        'pe': None,
        'pe_kind': None,
        'price_basis': 'last_trade',
        'week52_basis': 'yahoo',
    }


def download_quotes(tickers=TICKERS):
    """Last trade, previous close, volume, 52-week range, and PE.

    A quote miss does not drop the price curve. PE stays null when Yahoo has none.
    """
    import yfinance as yf

    quotes = {}
    for ticker in tickers:
        quote = _empty_quote()
        try:
            obj = yf.Ticker(ticker)
            fast = _fast_info(obj)
            info = _info_dict(obj)
            pe, pe_kind = select_pe(info)
            # fast_info.previous_close can disagree with the official previous close
            # (and with the adjusted-close history). Prefer the regular-market fields.
            quote.update({
                'last': _num(info.get('regularMarketPrice')) or _num(_fast_get(fast, 'last_price')),
                'previous_close': (
                    _num(info.get('regularMarketPreviousClose'))
                    or _num(info.get('previousClose'))
                    or _num(_fast_get(fast, 'previous_close'))
                ),
                'volume': (
                    _num(info.get('regularMarketVolume'))
                    or _num(info.get('volume'))
                    or _num(_fast_get(fast, 'last_volume'))
                ),
                'week52_high': _num(info.get('fiftyTwoWeekHigh')) or _num(_fast_get(fast, 'year_high')),
                'week52_low': _num(info.get('fiftyTwoWeekLow')) or _num(_fast_get(fast, 'year_low')),
                'currency': _fast_get(fast, 'currency') or info.get('currency') or 'USD',
                'pe': pe,
                'pe_kind': pe_kind,
            })
        except Exception:
            pass
        quotes[ticker] = quote
    return quotes


def prices_frame(closes):
    """Align ticker series on a daily index. Missing prints stay empty (not zero)."""
    columns = {}
    for ticker in TICKERS:
        series = closes.get(ticker)
        if series is None:
            continue
        values = pd.to_numeric(pd.Series(series), errors='coerce')
        idx = pd.to_datetime(values.index)
        if getattr(idx, 'tz', None) is not None:
            idx = idx.tz_localize(None)
        values.index = idx
        columns[ticker] = values.sort_index()
    if not columns:
        return pd.DataFrame(columns=['date', *TICKERS])
    frame = pd.concat(columns, axis=1).sort_index()
    frame = frame[~frame.index.duplicated(keep='last')]
    frame.index.name = 'date'
    out = frame.reset_index()
    out['date'] = pd.to_datetime(out['date']).dt.strftime('%Y-%m-%d')
    for ticker in TICKERS:
        if ticker not in out.columns:
            out[ticker] = pd.NA
    return out[['date', *TICKERS]]


def _non_null_count(frame, column):
    if column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors='coerce').notna().sum())


def _last_stamp(frame, column):
    if frame.empty or column not in frame.columns or 'date' not in frame.columns:
        return None
    dates = pd.to_datetime(frame['date'], errors='coerce')
    values = pd.to_numeric(frame[column], errors='coerce')
    ok = dates.notna() & values.notna()
    if not ok.any():
        return None
    return pd.Timestamp(dates[ok].max()).normalize()


def validate_prices(frame, *, directory, min_qqq_rows, min_qld_rows, max_age_days, today):
    """Return a list of reasons to keep the previous files."""
    problems = []
    qqq_n = _non_null_count(frame, 'QQQ')
    qld_n = _non_null_count(frame, 'QLD')
    if qqq_n < min_qqq_rows:
        problems.append(f'QQQ rows {qqq_n} < {min_qqq_rows}')
    if qld_n < min_qld_rows:
        problems.append(f'QLD rows {qld_n} < {min_qld_rows}')
    today = pd.Timestamp(today).normalize()
    for ticker in TICKERS:
        last = _last_stamp(frame, ticker)
        if last is None:
            problems.append(f'{ticker} has no dated close')
            continue
        age = (today - last).days
        if max_age_days is not None and age > max_age_days:
            problems.append(f'{ticker} last {last.date()} is {age} days old')
    existing = Path(directory) / PRICE_NAME
    if existing.is_file() and not problems:
        try:
            old = pd.read_csv(existing)
        except (OSError, ValueError, pd.errors.ParserError):
            old = None
        if old is not None:
            old_n = _non_null_count(old, 'QQQ')
            if old_n and qqq_n < int(0.9 * old_n):
                problems.append(f'refused short QQQ history {qqq_n} < 90% of {old_n}')
    return problems


def _week52_from_history(series):
    values = pd.to_numeric(pd.Series(series), errors='coerce').dropna()
    if values.empty:
        return None, None
    window = values.tail(252)
    return _num(window.max()), _num(window.min())


def _change_pct(last, previous):
    if last is None or previous is None or previous == 0:
        return None
    return (last - previous) / previous * 100.0


def build_snapshot(frame, quotes, *, fetched_at):
    """Card payload. Fills gaps from the price history and labels that fallback."""
    quotes = quotes if isinstance(quotes, dict) else {}
    tickers = {}
    as_of = None
    for ticker in TICKERS:
        quote = quotes.get(ticker) if isinstance(quotes.get(ticker), dict) else {}
        last = _num(quote.get('last'))
        previous = _num(quote.get('previous_close'))
        price_basis = quote.get('price_basis') or 'last_trade'
        series = pd.Series(dtype=float)
        if frame is not None and not frame.empty and ticker in frame.columns:
            series = pd.to_numeric(frame[ticker], errors='coerce')
            series.index = pd.to_datetime(frame['date'], errors='coerce')
            series = series[series.index.notna()].dropna().sort_index()
        if last is None and len(series):
            last = _num(series.iloc[-1])
            price_basis = 'adjusted_close'
        change_basis = 'previous_close'
        change = _change_pct(last, previous)
        if change is None and len(series) >= 2:
            change = _change_pct(_num(series.iloc[-1]), _num(series.iloc[-2]))
            change_basis = 'adjusted_close'
            if previous is None:
                previous = _num(series.iloc[-2])
        high = _num(quote.get('week52_high'))
        low = _num(quote.get('week52_low'))
        week_basis = quote.get('week52_basis') or 'yahoo'
        if high is None or low is None:
            hist_high, hist_low = _week52_from_history(series)
            high = high if high is not None else hist_high
            low = low if low is not None else hist_low
            if hist_high is not None or hist_low is not None:
                week_basis = 'price_history'
        pe = _num(quote.get('pe'))
        pe_kind = quote.get('pe_kind') if pe is not None else None
        if pe_kind not in {'trailing', 'forward'}:
            pe, pe_kind = None, None
        if len(series):
            stamp = pd.Timestamp(series.index.max()).strftime('%Y-%m-%d')
            as_of = stamp if as_of is None or stamp > as_of else as_of
        tickers[ticker] = {
            'last': last,
            'previous_close': previous,
            'change_pct': None if change is None else round(change, 4),
            'price_basis': price_basis,
            'change_basis': change_basis if change is not None else None,
            'pe': None if pe is None else round(pe, 4),
            'pe_kind': pe_kind,
            'volume': _num(quote.get('volume')),
            'week52_high': high,
            'week52_low': low,
            'week52_basis': week_basis if high is not None or low is not None else None,
            'currency': quote.get('currency') or 'USD',
        }
    return {
        'source': 'yfinance',
        'fetched_at': fetched_at,
        'as_of': as_of,
        'note': (
            'Adjusted close curve from Yahoo Finance. Card price is the last trade '
            'when Yahoo publishes one. PE is trailingPE, else forwardPE; null means '
            'Yahoo did not publish a PE. Not an input to the v9 Vegas signal.'
        ),
        'tickers': tickers,
    }


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def write_market_pack(directory, frame, snapshot, *, min_qqq_rows=MIN_QQQ_ROWS,
                       min_qld_rows=MIN_QLD_ROWS, max_age_days=MAX_STALE_DAYS, today=None):
    """Replace the cache, or raise and leave the previous files untouched."""
    directory = Path(directory)
    if today is None:
        today = pd.Timestamp.now().normalize()
    else:
        today = pd.Timestamp(today)
        if today.tzinfo is not None:
            today = today.tz_localize(None)
        today = today.normalize()
    problems = validate_prices(
        frame,
        directory=directory,
        min_qqq_rows=min_qqq_rows,
        min_qld_rows=min_qld_rows,
        max_age_days=max_age_days,
        today=today,
    )
    if problems:
        raise ValueError('market pack refused: ' + '; '.join(problems))
    csv_text = frame.to_csv(index=False)
    payload = json.dumps(snapshot, indent=2, ensure_ascii=True) + '\n'
    _atomic_text(directory / PRICE_NAME, csv_text)
    _atomic_text(directory / SNAPSHOT_NAME, payload)


def refresh_market(directory=None, *, fetch_closes=None, fetch_quotes=None, now=None,
                    min_qqq_rows=MIN_QQQ_ROWS, min_qld_rows=MIN_QLD_ROWS,
                    max_age_days=MAX_STALE_DAYS):
    directory = Path(directory) if directory is not None else DEFAULT_DIR
    fetch_closes = fetch_closes or download_closes
    fetch_quotes = fetch_quotes or (lambda _closes: download_quotes())
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    fetched_at = moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    closes = fetch_closes()
    frame = prices_frame(closes)
    quotes = fetch_quotes(closes)
    snapshot = build_snapshot(frame, quotes, fetched_at=fetched_at)
    write_market_pack(
        directory, frame, snapshot,
        min_qqq_rows=min_qqq_rows, min_qld_rows=min_qld_rows,
        max_age_days=max_age_days, today=moment,
    )
    return snapshot


def main(argv=None):
    del argv
    try:
        snapshot = refresh_market()
    except Exception as exc:  # noqa: BLE001 — caller keeps the previous cache
        print(f'QQQ/QLD market pack unchanged: {exc}', file=sys.stderr)
        return 1
    bits = []
    for ticker, quote in snapshot.get('tickers', {}).items():
        pe = quote.get('pe')
        kind = quote.get('pe_kind') or 'N/A'
        pe_text = f'{pe:.2f} {kind}' if pe is not None else 'N/A'
        bits.append(f"{ticker} {quote.get('last')} PE {pe_text}")
    print(f"QQQ/QLD market pack as of {snapshot.get('as_of')}: " + '; '.join(bits))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
