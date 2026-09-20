#!/usr/bin/env python3
"""
verify_portfolio.py -- settle backtest accuracy questions before trusting a number.

Runs three checks that have each caught a real error in this project:

  1. BACKFILL  -- does every ticker exist at the backtest start date?
                  (Universe D's 11.22% and Portfolio B's 14.62% both came
                  substantially from pre-inception history.)
  2. HEDGING   -- is a CAD-hedged ETF being fed an unhedged return series?
                  ZQQ.TO is HEDGED to CAD. If its series tracks USDCAD, it is
                  wrong and inflates returns. Unhedged Nasdaq in CAD = ZNQ/HXQ.
  3. METRICS   -- recompute CAGR / Sharpe / MaxDD on the CLEAN common window
                  and compare against the claimed figures.

Usage:
    python verify_portfolio.py --prices data/cache/cdn_price_data.csv \
        --tickers ZQQ.TO VFV.TO ZEB.TO XBB.TO CGL-C.TO XGD.TO \
        --claimed-cagr 14.62 --claimed-sharpe 1.16 --claimed-dd 15.53
"""
import argparse
import sys

import numpy as np
import pandas as pd

# ETFs that hedge USD exposure to CAD. If the loaded series correlates with
# USDCAD moves, the data is the UNHEDGED cousin and returns are overstated.
CAD_HEDGED = {
    'ZQQ.TO': 'BMO NASDAQ 100 Equity HEDGED to CAD (unhedged = ZNQ.TO / HXQ.TO)',
    'XQQ.TO': 'iShares NASDAQ 100 CAD-HEDGED (unhedged = XQQU.TO)',
    'XSP.TO': 'iShares Core S&P 500 CAD-HEDGED (unhedged = XUS.TO / VFV.TO)',
    'ZUE.TO': 'BMO S&P 500 HEDGED to CAD (unhedged = ZSP.TO)',
    'CGL.TO': 'iShares Gold Bullion CAD-HEDGED (unhedged = CGL-C.TO)',
}


def stats(r, rf):
    r = r.dropna()
    if len(r) < 2:
        return 0.0, 0.0, 0.0, 0.0
    ny = len(r) / 252
    cagr = (1 + r).prod() ** (1 / ny) - 1
    vol = r.std() * np.sqrt(252)
    eq = (1 + r).cumprod()
    dd = ((eq - eq.expanding().max()) / eq.expanding().max()).min()
    return cagr, (cagr - rf) / vol if vol else 0.0, abs(dd), vol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prices', required=True)
    ap.add_argument('--tickers', nargs='+', required=True)
    ap.add_argument('--fx', default=None,
                    help="CSV with a USDCAD=X column, for the hedging check")
    ap.add_argument('--rf', type=float, default=0.02)
    ap.add_argument('--claimed-cagr', type=float, default=None)
    ap.add_argument('--claimed-sharpe', type=float, default=None)
    ap.add_argument('--claimed-dd', type=float, default=None)
    a = ap.parse_args()

    px = pd.read_csv(a.prices, index_col=0, parse_dates=True)
    px = px[~px.index.duplicated(keep='last')].sort_index()

    missing = [t for t in a.tickers if t not in px.columns]
    if missing:
        print(f"!! ABSENT from {a.prices}: {missing}")
        print("   The backtest cannot have used this file for those tickers.")
        sys.exit(1)

    px = px[a.tickers]
    start, end = px.index[0], px.index[-1]
    total = max((end - start).days, 1)

    print("=" * 74)
    print(f"1. BACKFILL CHECK   window {start.date()} -> {end.date()}")
    print("=" * 74)
    common, bad = start, []
    for t in a.tickers:
        s = px[t].dropna()
        first = s.index[0]
        pct = 100.0 * max((first - start).days, 0) / total
        common = max(common, first)
        flag = '' if pct <= 5 else f'  <-- MISSING {pct:.1f}% OF WINDOW'
        if pct > 5:
            bad.append(t)
        print(f"  {t:12s} first={first.date()}  n={len(s):5d}{flag}")
    if bad:
        print(f"\n  FAIL: {len(bad)} ticker(s) backfilled. Results before "
              f"{common.date()} describe a DIFFERENT portfolio.")
        print(f"  -> Re-run the backtest starting {common.date()}.")
    else:
        print("\n  PASS: every ticker exists at the window start.")

    print("\n" + "=" * 74)
    print("2. HEDGING CHECK (CAD-hedged ETFs must NOT track USDCAD)")
    print("=" * 74)
    fx = None
    if a.fx:
        f = pd.read_csv(a.fx, index_col=0, parse_dates=True)
        f = f[~f.index.duplicated(keep='last')].sort_index()
        col = next((c for c in f.columns if 'USDCAD' in c.upper()), None)
        if col:
            fx = f[col].dropna()
    hedged = [t for t in a.tickers if t in CAD_HEDGED]
    if not hedged:
        print("  No CAD-hedged tickers in this universe. Nothing to check.")
    elif fx is None:
        for t in hedged:
            print(f"  {t:12s} {CAD_HEDGED[t]}")
        print("\n  Pass --fx <file with USDCAD=X> to test this automatically.")
    else:
        idx = px.index
        fxr = fx.reindex(fx.index.union(idx)).ffill().reindex(idx).pct_change()
        for t in hedged:
            c = px[t].pct_change().corr(fxr)
            verdict = 'SUSPECT - looks UNHEDGED' if abs(c) > 0.15 else 'OK - hedged'
            print(f"  {t:12s} corr(returns, USDCAD) = {c:+.3f}   {verdict}")
            print(f"               {CAD_HEDGED[t]}")

    print("\n" + "=" * 74)
    print("3. METRICS on the CLEAN common window (equal-weight, monthly rebal)")
    print("=" * 74)
    clean = px.loc[common:].ffill()
    r = clean.pct_change().dropna().mean(axis=1)
    cagr, sh, dd, vol = stats(r, a.rf)
    print(f"  from {common.date()}:  CAGR {cagr:.2%} | Sharpe {sh:.2f} | "
          f"MaxDD {dd:.2%} | Vol {vol:.2%}")
    print("  (equal-weight buy & hold -- the benchmark any strategy must beat)")

    if a.claimed_cagr is not None:
        print("\n  CLAIMED vs CLEAN-WINDOW BENCHMARK:")
        print(f"    CAGR   claimed {a.claimed_cagr:6.2f}%   benchmark {cagr * 100:6.2f}%")
        if a.claimed_sharpe is not None:
            print(f"    Sharpe claimed {a.claimed_sharpe:6.2f}    benchmark {sh:6.2f}")
        if a.claimed_dd is not None:
            print(f"    MaxDD  claimed {a.claimed_dd:6.2f}%   benchmark {dd * 100:6.2f}%")
        print("\n  A strategy CAGR far above the clean benchmark, when MaxDD and Vol")
        print("  match closely, points at the RETURN SERIES (backfill or hedging),")
        print("  not at the strategy logic.")


if __name__ == '__main__':
    main()
