"""
scripts/run_cdn_backtest.py
===========================
Canadian ETF Regime Strategy (6-ETF Portfolio B) Backtest Engine.

Canadian Portfolio B (6 ETFs). The published numbers live in
``data/backtest_results/cdn_comparison.csv`` after this script runs. Do not
copy a CAGR into this file.

The curve starts when every sleeve exists (about 2012-11), not 20 years.
ZQQ.TO is CAD-hedged Nasdaq-100; VFV.TO is unhedged. The book does not hold ZNQ.TO.

Regime clock matches the US targeted fix: CPI +1 month and GDP +4 months,
applied once. VIX monthly mean and 12-month momentum are labeled on month-end
(the same information as ``shift(1)`` on a month-start stamp). Momentum is
VFV.TO, not SPY.

Outputs:
  data/backtest_results/cdn_equity_curve.csv
  data/backtest_results/cdn_monthly_returns.csv
  data/backtest_results/cdn_comparison.csv
  data/backtest_results/cdn_strategy_config.json
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import json
import pickle
import numpy as np
import pandas as pd
import yfinance as yf

from src.backtester.engine import BacktestEngine
from src.backtester.regime_clock import (
    _classify_one,
    market_signals,
    publication_lagged_macro,
)
from config.regime_rules import STRATEGY_PARAMS, REGIME_VIX_DEFENSIVE
from config.cdn_regime_rules import CDN_REGIME_WEIGHTS, CDN_UNIVERSE, CDN_VERSION


def load_data():
    """Load Canadian ETF prices and macro data."""
    cdn_cache = ROOT / 'data' / 'cache' / 'cdn_price_data.csv'
    macro_cache = ROOT / 'data' / 'cache' / 'macro_data.pkl'

    if not cdn_cache.exists():
        print("Downloading Canadian ETF prices...")
        raw = yf.download(CDN_UNIVERSE, start='2012-01-01', auto_adjust=True, progress=False)
        cdn_px = raw['Close'] if isinstance(raw.columns, pd.MultiIndex) else raw
        cdn_px.columns = [str(c) for c in cdn_px.columns]
        cdn_px.to_csv(cdn_cache)
    else:
        cdn_px = pd.read_csv(cdn_cache, index_col=0, parse_dates=True)

    cdn_px = cdn_px.ffill()

    if macro_cache.exists():
        with open(macro_cache, 'rb') as f:
            macro = pickle.load(f)
    else:
        raise FileNotFoundError(f"Macro data cache not found at {macro_cache}")

    return cdn_px, macro


def classify_regimes(macro, price_data, momentum_ticker='VFV.TO'):
    """Canadian regimes on the US targeted clock.

    CPI +1 and GDP +4 are applied once in ``publication_lagged_macro``.
    VIX monthly mean and 12-month momentum use month-end labels
    (``market_signals(..., same_month=False)``), which is the same information
    as shifting a month-start stamp by one month. Momentum is
    ``momentum_ticker`` (VFV.TO). CPI and GDP are not shifted a second time.
    """
    vix = macro.get('vix', pd.Series(dtype=float))
    gdp = macro.get('gdp', pd.Series(dtype=float))
    cpi = macro.get('cpi', pd.Series(dtype=float))
    _cpi_yoy, _gdp, cpi_mo, gdp_mo = publication_lagged_macro(cpi, gdp, apply_lag=True)

    if isinstance(price_data, pd.DataFrame) and momentum_ticker in price_data.columns:
        mom_px = price_data[momentum_ticker]
    else:
        mom_px = pd.Series(dtype=float)
    vix_mo, mom_mo = market_signals(vix, mom_px, same_month=False)

    ready = price_data[CDN_UNIVERSE].dropna()
    if len(ready) == 0:
        return pd.DataFrame(columns=['date', 'regime'])
    end = price_data.index.max()
    dates = pd.date_range(start=ready.index[0], end=end, freq='MS')

    records = []
    for date in dates:
        records.append({
            'date': date,
            'regime': _classify_one(
                date, gdp_mo, mom_mo, cpi_mo, vix_mo, REGIME_VIX_DEFENSIVE,
            ),
        })
    return pd.DataFrame(records)


def run_cdn_backtest():
    cdn_px, macro = load_data()
    regime_history = classify_regimes(macro, cdn_px, momentum_ticker='VFV.TO')

    print(f"Canadian Backtest Period: {cdn_px.index[0].date()} to {cdn_px.index[-1].date()}")
    print("Regime Distribution:")
    for r, cnt in regime_history['regime'].value_counts().items():
        print(f"  {r:<12}: {cnt} months ({cnt / len(regime_history):.1%})")

    engine = BacktestEngine(cdn_px[CDN_UNIVERSE], initial_capital=100_000, risk_free_rate=0.02)
    params = dict(STRATEGY_PARAMS)

    result = engine.run_optimized_regime_backtest(
        regime_history=regime_history,
        regime_weights=CDN_REGIME_WEIGHTS,
        name='Portfolio B (High-Growth 14.6%)',
        vix_data=macro.get('vix'),
        **params,
    )

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
        'Strategy': 'Portfolio B (High-Growth 14.6%)',
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
        'name': 'Portfolio B (High-Growth 14.6%)',
        'as_of': pd.Timestamp.now().strftime('%Y-%m-%d'),
        'tickers': CDN_UNIVERSE,
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


if __name__ == '__main__':
    run_cdn_backtest()
