"""
scripts/run_cdn_backtest.py
===========================
Canadian ETF Regime Strategy (6-ETF Portfolio B) Backtest Engine.

Canadian Portfolio B (6 ETFs). The published numbers live in
``data/backtest_results/cdn_comparison.csv`` after this script runs. Do not
copy a CAGR into this file.

ZQQ.TO is CAD-hedged Nasdaq-100; VFV.TO is unhedged. The book does not hold ZNQ.TO.
Names that have not listed yet are dropped and the sleeve is renormalized.

Regime clock matches the US targeted fix: CPI +1 month and GDP +4 months,
applied once. VIX monthly mean and 12-month momentum then take
``lag_vix_and_momentum_one_month`` (``shift(1)`` on those two series only).
Momentum is VFV.TO, not SPY. The extra month is stored for the auditor only.

The published curve is path B (targeted). Path A, path C, the unlagged
diagnostic, and the extra month are written to ``cdn_lag_honesty.csv`` for
the auditor. They are not the CDN cards.

Outputs:
  data/backtest_results/cdn_equity_curve.csv
  data/backtest_results/cdn_monthly_returns.csv
  data/backtest_results/cdn_comparison.csv
  data/backtest_results/cdn_strategy_config.json
  data/backtest_results/cdn_lag_honesty.csv
  data/backtest_results/cdn_benchmark_xiu.csv
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import json
import pickle
import pandas as pd

from src.backtester.cdn_clock import (
    CDN_BENCHMARK,
    CDN_BENCHMARK_TICKER,
    CDN_HONESTY,
    classify_cdn_regimes,
    honesty_frame,
    run_cdn_honesty_paths,
)
from src.backtester.regime_clock import MODE_TARGETED
from config.cdn_regime_rules import CDN_AB_WINNER, CDN_REGIME_WEIGHTS, CDN_UNIVERSE, CDN_VERSION


def cdn_prices_need_refresh(path, today=None, force=None) -> bool:
    """True when the TSX cache is missing or its last print is before ``today``.

    ``FORCE_REFRESH=1`` (the Cloud Scheduler path) always re-downloads. A GCS
    pull stamps a fresh mtime on a file whose last row can still be weeks old,
    so the decision uses the last index date inside the CSV, not the mtime.
    """
    if force is None:
        force = bool(os.getenv('FORCE_REFRESH'))
    if force:
        return True
    file = Path(path)
    if not file.exists():
        return True
    try:
        frame = pd.read_csv(file, index_col=0, parse_dates=True)
    except Exception:
        return True
    if frame.empty:
        return True
    last = pd.Timestamp(frame.index.max())
    if getattr(last, 'tzinfo', None) is not None:
        last = last.tz_localize(None)
    last = last.normalize()
    anchor = pd.Timestamp(today or pd.Timestamp.now())
    if getattr(anchor, 'tzinfo', None) is not None:
        anchor = anchor.tz_localize(None)
    anchor = anchor.normalize()
    return last < anchor


def _coerce_cdn_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, 'tz', None) is not None:
        out.index = out.index.tz_localize(None)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep='last')]
    out.columns = [str(col) for col in out.columns]
    return out


def _read_cdn_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return _coerce_cdn_prices(pd.read_csv(path, index_col=0, parse_dates=True))
    except Exception as exc:
        print(f'CDN price cache unreadable ({exc}).')
        return pd.DataFrame()


def _download_cdn_prices() -> pd.DataFrame:
    import yfinance as yf
    raw = yf.download(
        list(CDN_UNIVERSE), start='2012-01-01', auto_adjust=True, progress=False, threads=False,
    )
    if raw is None or getattr(raw, 'empty', True):
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        levels = raw.columns.get_level_values(0)
        px = raw['Close'] if 'Close' in levels else raw.iloc[:, 0]
    else:
        px = raw['Close'] if 'Close' in raw.columns else raw
    if isinstance(px, pd.Series):
        px = px.to_frame()
    return _coerce_cdn_prices(px)


def load_cdn_price_frame(cache_path=None, today=None, force=None) -> pd.DataFrame:
    """Return TSX closes, refreshing when the cache stops before ``today``.

    A failed or shorter download keeps the previous file. Names that Yahoo
    omits stay on the previous column via ``combine_first``.
    """
    cdn_cache = Path(cache_path) if cache_path is not None else ROOT / 'data' / 'cache' / 'cdn_price_data.csv'
    existing = _read_cdn_cache(cdn_cache)
    if not cdn_prices_need_refresh(cdn_cache, today=today, force=force):
        if not existing.empty:
            print(f"CDN prices {existing.index.min().date()} → {existing.index.max().date()} (cache)")
        return existing
    print("Downloading Canadian ETF prices...")
    try:
        fresh = _download_cdn_prices()
    except Exception as exc:
        print(f'CDN price refresh failed ({exc}); keeping the previous cache.')
        fresh = pd.DataFrame()
    if fresh.empty:
        if existing.empty:
            raise RuntimeError(f'CDN price download failed and {cdn_cache} is empty.')
        print('CDN download was empty; keeping the previous cache.')
        return existing
    merged = fresh if existing.empty else fresh.combine_first(existing)
    merged = _coerce_cdn_prices(merged)
    if len(merged) < 100:
        print(f'CDN download returned {len(merged)} rows; keeping the previous cache.')
        if existing.empty:
            raise RuntimeError('CDN price download is too short and there is no previous cache.')
        return existing
    if not existing.empty and merged.index.max() < existing.index.max():
        print(
            f'CDN download ends {merged.index.max().date()}, '
            f'behind the cache {existing.index.max().date()}; keeping the cache.'
        )
        return existing
    cdn_cache.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(cdn_cache)
    print(f"CDN prices {merged.index.min().date()} → {merged.index.max().date()} (refreshed)")
    return merged


def load_data():
    """Load Canadian ETF prices and macro data."""
    macro_cache = ROOT / 'data' / 'cache' / 'macro_data.pkl'
    cdn_px = load_cdn_price_frame()
    if cdn_px.empty:
        raise FileNotFoundError('CDN price cache is empty.')

    cdn_px = cdn_px.ffill()

    if macro_cache.exists():
        with open(macro_cache, 'rb') as f:
            macro = pickle.load(f)
    else:
        raise FileNotFoundError(f"Macro data cache not found at {macro_cache}")

    return cdn_px, macro


def classify_regimes(macro, price_data, momentum_ticker='VFV.TO', mode=MODE_TARGETED):
    """Canadian regimes on the shared clock.

    The default mode is targeted: CPI +1 and GDP +4 once, then
    ``lag_vix_and_momentum_one_month`` on VIX and ``momentum_ticker``
    (VFV.TO). ``lookahead`` keeps the publication lag but stamps VIX and
    momentum in the same month. That path is not the published book.
    """
    history, _current, _info = classify_cdn_regimes(
        macro, price_data, momentum_ticker=momentum_ticker, mode=mode,
    )
    return history


def refresh_xiu_benchmark():
    """Adjusted close of XIU.TO, the S&P/TSX 60 proxy. Not a sleeve holding."""
    dest = CDN_BENCHMARK
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yfinance as yf
        raw = yf.download(CDN_BENCHMARK_TICKER, start='2011-12-01', auto_adjust=True, progress=False)
        px = raw['Close'] if isinstance(raw.columns, pd.MultiIndex) else raw
        if isinstance(px, pd.DataFrame):
            px = px.iloc[:, 0]
        px = px.dropna()
        px.index = pd.to_datetime(px.index)
        if getattr(px.index, 'tz', None) is not None:
            px.index = px.index.tz_convert(None)
        if len(px) < 100:
            raise RuntimeError(f'XIU.TO download returned {len(px)} rows')
        px.to_csv(dest, header=[CDN_BENCHMARK_TICKER])
        print(f'Saved: {dest} ({px.index.min().date()} → {px.index.max().date()})')
    except Exception as exc:
        print(f'XIU benchmark unchanged ({exc}).')
    return dest


def run_cdn_backtest():
    cdn_px, macro = load_data()
    refresh_xiu_benchmark()
    regime_history = classify_regimes(macro, cdn_px, momentum_ticker='VFV.TO')

    print(f"Canadian Backtest Period: {cdn_px.index[0].date()} to {cdn_px.index[-1].date()}")
    print("Regime Distribution:")
    for r, cnt in regime_history['regime'].value_counts().items():
        print(f"  {r:<12}: {cnt} months ({cnt / len(regime_history):.1%})")

    paths = run_cdn_honesty_paths(cdn_px, macro)
    result = paths.get(MODE_TARGETED)
    if result is None:
        raise RuntimeError('CDN targeted path did not run.')
    honesty = honesty_frame(paths)
    honesty.to_csv(CDN_HONESTY)
    print(f'Saved: {CDN_HONESTY}')
    print(honesty[['cagr', 'max_dd', 'sharpe']].to_string())

    print("\n" + "=" * 60)
    print(f"CANADIAN REGIME STRATEGY RESULTS ({CDN_VERSION})")
    print("=" * 60)
    print(f"  CAGR:          {result.annual_return:.2%}")
    print(f"  Volatility:    {result.volatility:.2%}")
    print(f"  Sharpe Ratio:  {result.sharpe_ratio:.2f}")
    print(f"  Sortino Ratio: {result.sortino_ratio:.2f}")
    print(f"  Max Drawdown:  {result.max_drawdown:.2%}")
    print(f"  Calmar Ratio:  {result.calmar_ratio:.2f}")
    print(f"  Win Rate:      {result.win_rate:.1%}")
    print(f"  Total Return:  {result.total_return:.2%}")

    # Save artifacts
    out_dir = ROOT / 'data' / 'backtest_results'
    out_dir.mkdir(parents=True, exist_ok=True)

    result.equity_curve.to_csv(out_dir / 'cdn_equity_curve.csv', header=['CDN Regime Strategy'])
    print(f"Saved: {out_dir / 'cdn_equity_curve.csv'}")

    if hasattr(result, 'monthly_returns') and len(result.monthly_returns) > 0:
        result.monthly_returns.to_csv(out_dir / 'cdn_monthly_returns.csv', header=['CDN Regime Strategy'])
        print(f"Saved: {out_dir / 'cdn_monthly_returns.csv'}")

    comp_df = pd.DataFrame([{
        'Strategy': CDN_AB_WINNER,
        'Annual Return': f'{result.annual_return:.2%}',
        'Volatility': f'{result.volatility:.2%}',
        'Sharpe Ratio': f'{result.sharpe_ratio:.2f}',
        'Sortino Ratio': f'{result.sortino_ratio:.2f}',
        'Max Drawdown': f'{result.max_drawdown:.2%}',
        'Calmar Ratio': f'{result.calmar_ratio:.2f}',
        'Win Rate': f'{result.win_rate:.1%}',
        'Total Return': f'{result.total_return:.2%}',
        'Winner': 'YES',
    }]).set_index('Strategy')
    comp_df.to_csv(out_dir / 'cdn_comparison.csv')
    print(f"Saved: {out_dir / 'cdn_comparison.csv'}")

    cfg_out = {
        'name': CDN_AB_WINNER,
        'as_of': pd.Timestamp.now().strftime('%Y-%m-%d'),
        'tickers': CDN_UNIVERSE,
        'clock': {
            'mode': 'targeted',
            'cpi_lag_months': 1,
            'gdp_lag_months': 4,
            'momentum': 'VFV.TO',
            'same_month_market': False,
            'publication_lag': True,
        },
        'weights': CDN_REGIME_WEIGHTS,
        'metrics': {
            'CAGR': f'{result.annual_return:.2%}',
            'MaxDD': f'{result.max_drawdown:.2%}',
            'Sharpe': f'{result.sharpe_ratio:.2f}',
            'Volatility': f'{result.volatility:.2%}',
            'Calmar': f'{result.calmar_ratio:.2f}',
            'WinRate': f'{result.win_rate:.1%}',
            'TotalReturn': f'{result.total_return:.2%}',
        },
    }
    with open(out_dir / 'cdn_strategy_config.json', 'w') as f:
        json.dump(cfg_out, f, indent=2)
    print(f"Saved: {out_dir / 'cdn_strategy_config.json'}")

    from src.backtester.consistency import verify_series
    report = verify_series(
        result.annual_return,
        result.total_return,
        result.max_drawdown,
        result.equity_curve,
        result.monthly_returns,
    )
    print("\n" + report.text())
    if not report.ok:
        print('Consistency check failed. This CDN run is not publishable.')
        sys.exit(3)


if __name__ == '__main__':
    run_cdn_backtest()
