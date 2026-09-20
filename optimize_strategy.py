"""
optimize_strategy.py
====================
Fast experimentation harness for the ETF regime strategy.

Builds the regime daily-weight matrix ONCE (matching run_backtest.py's logic),
then tests overlay designs vectorized so a full 20yr backtest runs in <1s.

Goal: get closer to 16% CAGR / 14.8% MaxDD / Sharpe 1.2 and find what is
actually achievable (vs. the current 13.18% / 19.58% / 0.75).
"""
import sys, os, pickle, logging
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
logging.disable(logging.CRITICAL)

from config.regime_rules import REGIME_WEIGHTS

# ──────────────────────────────────────────────────────────────────────
# 1. LOAD DATA (from existing caches — same source as production)
# ──────────────────────────────────────────────────────────────────────
price = pd.read_csv('data/cache/price_data.csv', index_col=0, parse_dates=True).ffill()
with open('data/cache/macro_data.pkl', 'rb') as f:
    macro = pickle.load(f)
vix   = macro['vix'];   vix.index   = pd.to_datetime(vix.index)
gdp   = macro['gdp'];   gdp.index   = pd.to_datetime(gdp.index)
cpi   = macro['cpi'];   cpi.index   = pd.to_datetime(cpi.index)
ff    = macro['ff_rate']
AVG_RF = ff.mean()/100 if len(ff) else 0.02

# ──────────────────────────────────────────────────────────────────────
# 2. REGIME HISTORY  (identical rules to run_backtest.py)
# ──────────────────────────────────────────────────────────────────────
monthly_dates = price.resample('MS').first().index
cpi_yoy = cpi.pct_change(12)*100
cpi_m   = cpi_yoy.resample('MS').last().ffill()
gdp_m   = gdp.resample('MS').last().ffill()
spy_m   = price['SPY'].resample('MS').last()
spy_mom = spy_m.pct_change(12)
vix_m   = vix.resample('MS').mean()

def classify(date):
    g = gdp_m.asof(date); s = spy_mom.asof(date)
    growth = (g > 1.5) or (s > 0.05)
    c  = cpi_m.asof(date); c3 = cpi_m.asof(date - pd.DateOffset(months=3))
    infl = (c > 3.0) and (c > c3)
    if vix_m.asof(date) > 30: return 'deflation'
    if growth and not infl: return 'goldilocks'
    if growth and infl:     return 'reflation'
    if not growth and infl: return 'stagflation'
    return 'deflation'

regime_hist = pd.Series(
    {d: classify(d) for d in monthly_dates if d >= pd.Timestamp('2005-06-01')}
)

# ──────────────────────────────────────────────────────────────────────
# 3. DAILY BASE-WEIGHT MATRIX  (monthly rebalance, per-date availability)
# ──────────────────────────────────────────────────────────────────────
R = price.pct_change().dropna(how='all')
tickers = list(price.columns)
avail_mask = price.notna()  # True where the ETF has real data

def build_weight_matrix(regime_weights, defense=None):
    """Return daily weight DataFrame from a regime->weights dict.
    Monthly rebalance; renormalise to tickers that have data on the prior day."""
    W = pd.DataFrame(0.0, index=R.index, columns=tickers)
    last_month = (-1, -1); cur = {}
    for i, date in enumerate(R.index):
        m = (date.year, date.month)
        if m != last_month or not cur:
            last_month = m
            reg = regime_hist.loc[regime_hist.index <= date]
            if len(reg):
                raw = regime_weights.get(reg.iloc[-1], {})
                avail = {t: w for t, w in raw.items()
                         if t in tickers and avail_mask.iloc[i-1].get(t, False)}
                tot = sum(avail.values())
                cur = {t: w/tot for t, w in avail.items()} if tot > 0 else {}
        for t, w in cur.items():
            W.iat[i, W.columns.get_loc(t)] = w
    return W

# Base regime weights (production REGIME_WEIGHTS) and a defense basket
DEFENSE = {"SHY": 0.35, "AGG": 0.20, "GLD": 0.25, "TLT": 0.20}
W_base = build_weight_matrix(REGIME_WEIGHTS)
W_def  = build_weight_matrix({r: DEFENSE for r in REGIME_WEIGHTS})

Rf = R.fillna(0.0)
r_base = (W_base * Rf).sum(axis=1)
r_def  = (W_def  * Rf).sum(axis=1)

# ──────────────────────────────────────────────────────────────────────
# 4. SIGNALS (all lagged 1 day — no look-ahead)
# ──────────────────────────────────────────────────────────────────────
spy = price['SPY']
spy_200 = spy.rolling(200).mean()
spy_100 = spy.rolling(100).mean()
trend_ok_200 = (spy.shift(1) >= spy_200.shift(1)).reindex(R.index).fillna(True)
trend_ok_100 = (spy.shift(1) >= spy_100.shift(1)).reindex(R.index).fillna(True)
vix_lag = vix.reindex(R.index, method='ffill').shift(1)

def metrics(r, name=""):
    r = r.dropna()
    tot = (1+r).prod() - 1
    yrs = len(r)/252
    cagr = (1+tot)**(1/yrs) - 1
    vol = r.std()*np.sqrt(252)
    sharpe = (cagr - AVG_RF)/vol if vol > 0 else 0
    eq = (1+r).cumprod()
    dd = (eq/eq.expanding().max() - 1).min()
    down = r[r < 0].std()*np.sqrt(252)
    sortino = (cagr-AVG_RF)/down if down > 0 else 0
    calmar = cagr/abs(dd) if dd < 0 else 0
    return dict(name=name, cagr=cagr, vol=vol, sharpe=sharpe,
               maxdd=dd, sortino=sortino, calmar=calmar)

def show(m):
    print(f"  {m['name']:42s} CAGR {m['cagr']:6.2%} | Vol {m['vol']:6.2%} | "
          f"Sharpe {m['sharpe']:5.2f} | MaxDD {m['maxdd']:7.2%} | "
          f"Sortino {m['sortino']:4.2f} | Calmar {m['calmar']:.2f}")

# ──────────────────────────────────────────────────────────────────────
# 5. OVERLAY BUILDING BLOCKS  (compose on the daily return series)
# ──────────────────────────────────────────────────────────────────────
def trend_overlay(r_risk, r_defense, trend_ok, bear_frac=0.0):
    """When trend is broken, hold bear_frac risk + (1-bear_frac) defense."""
    on = trend_ok.astype(float)
    return on*r_risk + (1-on)*(bear_frac*r_risk + (1-bear_frac)*r_defense)

def vol_target(r, target=0.12, lookback=21, lo=0.5, hi=1.3, borrow=0.0):
    """Portfolio-level vol targeting using the strategy's OWN realised vol."""
    rv = r.rolling(lookback).std()*np.sqrt(252)
    scale = (target/rv).clip(lo, hi).shift(1).fillna(1.0)
    cost = (scale-1).clip(lower=0)*(borrow/252)   # financing cost on leverage
    return r*scale - cost

def dd_breaker(r, trigger=0.12, floor=0.10, span=0.10):
    """Path-dependent: cut exposure linearly once drawdown exceeds trigger."""
    arr = r.values.copy(); out = np.empty_like(arr)
    eq = 1.0; peak = 1.0
    for i in range(len(arr)):
        dd = eq/peak - 1
        if dd < -trigger:
            sc = max(floor, 1.0 - (abs(dd)-trigger)/span)
        else:
            sc = 1.0
        out[i] = arr[i]*sc
        eq *= (1+out[i]); peak = max(peak, eq)
    return pd.Series(out, index=r.index)

def tx_drag(W, bps=5.0):
    """Approx monthly turnover cost from the base weight matrix."""
    turn = W.diff().abs().sum(axis=1)/2
    return turn*(bps/10000)

# ──────────────────────────────────────────────────────────────────────
# 6. EXPERIMENTS
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tx = tx_drag(W_base, 5.0)
    print("="*120)
    print("REFERENCE")
    print("="*120)
    show(metrics(r_base, "Basic regime (no overlay, no tx)"))
    show(metrics(r_base - tx, "Basic regime + tx cost"))

    print("\n" + "="*120)
    print("SINGLE OVERLAYS (on basic regime + tx)")
    print("="*120)
    base = r_base - tx
    show(metrics(trend_overlay(base, r_def, trend_ok_200, 0.0), "+ 200MA trend->full defense"))
    show(metrics(trend_overlay(base, r_def, trend_ok_200, 0.5), "+ 200MA trend->50% defense"))
    show(metrics(trend_overlay(base, r_def, trend_ok_100, 0.0), "+ 100MA trend->full defense"))
    show(metrics(vol_target(base, 0.12, 21, 0.5, 1.3), "+ portvol target 12% [0.5,1.3]"))
    show(metrics(vol_target(base, 0.11, 21, 0.5, 1.2), "+ portvol target 11% [0.5,1.2]"))
    show(metrics(vol_target(base, 0.13, 42, 0.5, 1.3), "+ portvol target 13% 42d [0.5,1.3]"))
    show(metrics(dd_breaker(base, 0.12), "+ DD breaker -12%"))

    print("\n" + "="*120)
    print("COMBINED: trend filter -> portfolio vol target -> DD breaker")
    print("="*120)
    def combo(bear, target, lo, hi, lb, trig, tname):
        r = trend_overlay(base, r_def, trend_ok_200, bear)
        r = vol_target(r, target, lb, lo, hi)
        r = dd_breaker(r, trig)
        return metrics(r, tname)
    show(combo(0.0, 0.12, 0.5, 1.3, 21, 0.12, "trend0 / vt12 / dd12"))
    show(combo(0.5, 0.12, 0.5, 1.3, 21, 0.12, "trend50 / vt12 / dd12"))
    show(combo(0.5, 0.13, 0.6, 1.4, 21, 0.13, "trend50 / vt13 hi1.4 / dd13"))
    show(combo(0.0, 0.11, 0.5, 1.2, 21, 0.12, "trend0 / vt11 / dd12"))
    show(combo(0.5, 0.115,0.5, 1.25,21, 0.12, "trend50 / vt11.5 / dd12"))

    print("\n" + "="*120)
    print("GRID SEARCH (trend50 + portvol target + DD breaker)")
    print("="*120)
    best = []
    for target in [0.10, 0.11, 0.115, 0.12, 0.13]:
        for hi in [1.1, 1.2, 1.3, 1.4]:
            for lo in [0.4, 0.5]:
                for bear in [0.0, 0.4, 0.5]:
                    for trig in [0.10, 0.12, 0.14]:
                        r = trend_overlay(base, r_def, trend_ok_200, bear)
                        r = vol_target(r, target, 21, lo, hi)
                        r = dd_breaker(r, trig)
                        m = metrics(r, f"vt{target} hi{hi} lo{lo} bear{bear} dd{trig}")
                        best.append(m)
    # Rank by closeness to target: meet DD<14.8, maximise (cagr then sharpe)
    feasible = [m for m in best if m['maxdd'] > -0.148]
    feasible.sort(key=lambda m: (m['cagr'], m['sharpe']), reverse=True)
    print(f"\nConfigs meeting MaxDD < 14.8%: {len(feasible)} / {len(best)}")
    print("Top 8 by CAGR (among DD-feasible):")
    for m in feasible[:8]: show(m)
    print("\nTop 8 by Sharpe (all):")
    best.sort(key=lambda m: m['sharpe'], reverse=True)
    for m in best[:8]: show(m)
    print("\nTop 8 by Calmar (all):")
    best.sort(key=lambda m: m['calmar'], reverse=True)
    for m in best[:8]: show(m)
