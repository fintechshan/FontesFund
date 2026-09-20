"""
ab_etf_swap.py — A/B test ETF substitutions in the regime book.

Reuses the production engine logic via optimize_strategy's vectorized harness
(risk-parity sleeve book -> 200MA trend hedge -> portfolio vol target -> DD breaker),
so the DELTA between baseline and a swap is apples-to-apples. Absolute numbers are
the research-harness figures (realised-vol target, not HAR) and run slightly hotter
than the 14.68% production headline; only the baseline-vs-variant DELTA is the signal.

Tests:
  1) URA -> XLY (full history)         "does consumer-disc beat the uranium/AI-power leg?"
  2) URA vs AIPO vs XLY (since AIPO)    forward-outlook proxy (AIPO has no long history)
  3) XEI.TO / ZWB.TO as diversifier sleeves (CAD; FX-naive local returns)
"""
import copy
import numpy as np
import pandas as pd
import optimize_strategy as O

EXTRA = pd.read_csv('data/cache/ab_extra_prices.csv', index_col=0, parse_dates=True)
EXTRA.index = pd.to_datetime(EXTRA.index).normalize()  # strip time-of-day so it aligns to cache dates
RW = O.REGIME_WEIGHTS

# Merge extra tickers onto the production cache, aligned to the cache trading days.
price = O.price.copy()
for t in EXTRA.columns:
    price[t] = EXTRA[t].reindex(price.index).ffill()

R = price.pct_change()
Rf = R.fillna(0.0)
tickers = list(price.columns)
avail = price.notna()

# Shared production overlays (SPY/defense only -> reuse the harness objects)
r_def = O.r_def
trend_ok = O.trend_ok_200
PROD = dict(bear=0.70, target=0.13, lo=0.50, hi=1.50, lb=21, trig=0.07, borrow=0.01, bps=5.0)


def rp_book(regime_weights):
    """Risk-parity (inverse-60d-vol) regime book on the merged universe."""
    vol = R.rolling(60).std() * np.sqrt(252)
    invvol = (1.0 / vol).shift(1)
    W = pd.DataFrame(0.0, index=R.index, columns=tickers)
    last_m = (-1, -1); cur = {}
    for i, date in enumerate(R.index):
        m = (date.year, date.month)
        if m != last_m or not cur:
            last_m = m
            reg = O.regime_hist.loc[O.regime_hist.index <= date]
            if len(reg):
                raw = regime_weights.get(reg.iloc[-1], {})
                iv = invvol.iloc[i] if i > 0 else invvol.iloc[0]
                a = {t: w * iv.get(t, np.nan) for t, w in raw.items()
                     if t in tickers and avail.iloc[i-1].get(t, False) and pd.notna(iv.get(t, np.nan))}
                tot = sum(a.values())
                cur = {t: w / tot for t, w in a.items()} if tot > 0 else {}
        for t, w in cur.items():
            W.iat[i, W.columns.get_loc(t)] = w
    return W


def run(regime_weights, start=None):
    W = rp_book(regime_weights)
    book = (W * Rf).sum(axis=1)
    tx = W.diff().abs().sum(axis=1) / 2 * (PROD['bps'] / 10000)
    r = O.trend_overlay(book - tx, r_def, trend_ok, PROD['bear'])
    r = O.vol_target(r, PROD['target'], PROD['lb'], PROD['lo'], PROD['hi'], borrow=PROD['borrow'])
    r = O.dd_breaker(r, PROD['trig'])
    if start:
        r = r[r.index >= start]
    return r


def swap(regime_weights, old, new):
    rw = copy.deepcopy(regime_weights)
    for reg, d in rw.items():
        if old in d:
            d[new] = d.pop(old)
    return rw


def line(m):
    print(f"  {m['name']:34s} CAGR {m['cagr']:6.2%} | Vol {m['vol']:6.2%} | "
          f"Sharpe {m['sharpe']:5.2f} | MaxDD {m['maxdd']:7.2%} | Calmar {m['calmar']:.2f}")


print("=" * 104)
print("TEST 1 — URA -> XLY swap (production engine: RP book + trend + vol-target + DD breaker)")
print("=" * 104)
for start, label in [(None, 'Full 2005-2026'), ('2011-01-01', 'URA-era 2011-2026')]:
    base = O.metrics(run(RW, start), f'[{label}] BASELINE (URA)')
    xly  = O.metrics(run(swap(RW, 'URA', 'XLY'), start), f'[{label}] URA->XLY')
    line(base); line(xly)
    print(f"    d CAGR {xly['cagr']-base['cagr']:+.2%} | d Sharpe {xly['sharpe']-base['sharpe']:+.2f} | "
          f"d MaxDD {xly['maxdd']-base['maxdd']:+.2%}\n")

print("=" * 104)
print("TEST 2 — URA vs AIPO vs XLY standalone, since AIPO inception (forward-outlook proxy)")
print("=" * 104)
s = '2025-07-25'
sub = price.loc[price.index >= s, ['URA', 'AIPO', 'XLY']].dropna()
rr = sub.pct_change().dropna()
book = run(RW)  # production book over same window for correlation
book = book[book.index >= rr.index.min()]
for t in ['URA', 'AIPO', 'XLY']:
    x = rr[t]
    tot = (1 + x).prod() - 1
    vol = x.std() * np.sqrt(252)
    corr = pd.concat([x, book], axis=1).dropna().corr().iloc[0, 1]
    print(f"  {t:6s} total {tot:+7.2%} | annvol {vol:6.2%} | corr-to-book {corr:+.2f}")
print(f"  (window {rr.index.min().date()} -> {rr.index.max().date()}, {len(rr)} days)")

print("\n" + "=" * 104)
print("TEST 3 — Canadian diversifiers XEI.TO / ZWB.TO (CAD, FX-naive local total return)")
print("=" * 104)
book_full = run(RW)
for t in ['XEI.TO', 'ZWB.TO']:
    px = EXTRA[t].dropna()
    x = px.pct_change().dropna()
    yrs = len(x) / 252
    tot = (1 + x).prod() - 1
    cagr = (1 + tot) ** (1 / yrs) - 1
    vol = x.std() * np.sqrt(252)
    sh = (cagr - O.AVG_RF) / vol if vol > 0 else 0
    bk = book_full[book_full.index >= x.index.min()]
    corr = pd.concat([x, bk], axis=1).dropna().corr().iloc[0, 1]
    # 10% sleeve blend with the existing book (rest scaled to 90%)
    j = pd.concat([bk, x.reindex(bk.index)], axis=1).dropna()
    blend = 0.90 * j.iloc[:, 0] + 0.10 * j.iloc[:, 1]
    bm = O.metrics(blend, f'book+10% {t}')
    base_same = O.metrics(bk[bk.index.isin(j.index)], 'book (same window)')
    print(f"  {t:7s} CAGR {cagr:6.2%} | Vol {vol:6.2%} | Sharpe {sh:4.2f} | corr-to-book {corr:+.2f}")
    print(f"          90/10 blend Sharpe {bm['sharpe']:.2f} vs book {base_same['sharpe']:.2f} "
          f"(dSharpe {bm['sharpe']-base_same['sharpe']:+.2f}, dMaxDD {bm['maxdd']-base_same['maxdd']:+.2%})")
