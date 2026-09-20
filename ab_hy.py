"""
ab_hy.py — PLANNING ONLY. A/B: add a CAD-hedged US high-yield sleeve to the book.

Idea (Disnat article): ZHY.TO / CHB.TO / XHY.TO give US high-yield income WITHOUT
USD/CAD FX risk (currency-hedged). Because they're hedged, the CAD return ≈ the
underlying US-HY return, so a synthetic HY sleeve drops straight into the
currency-agnostic production engine. CHB.TO delisted 2023 -> use ZHY+XHY blend.

Caveats: HY data starts 2010, so the backtest MISSES the 2008 GFC (HY fell ~-33%)
=> it understates HY's crisis drawdown. HY is risk-ON credit (equity-correlated),
not a defensive asset. Engine setup = run_backtest.py (lagged macro, HAR, VIX gate).
"""
import copy, pickle
import numpy as np, pandas as pd
import logging; logging.disable(logging.CRITICAL)
from config.regime_rules import STRATEGY_PARAMS
from src.backtester.engine import BacktestEngine

price = pd.read_csv('data/cache/price_data_ab.csv', index_col=0, parse_dates=True).ffill()
hy = pd.read_csv('data/cache/ab_hy_prices.csv', index_col=0, parse_dates=True)
hy.index = pd.to_datetime(hy.index).normalize()

# Synthetic HY index = equal-weight of the two surviving hedged ETFs (ZHY, XHY).
hr = hy[['ZHY.TO', 'XHY.TO']].pct_change()
hy_ret = hr.mean(axis=1)                          # average daily return
hy_idx = (1 + hy_ret.fillna(0)).cumprod()
hy_idx[hy_ret.isna().all() if False else hy_ret.isna()] = np.nan
price['HY'] = hy_idx.reindex(price.index).ffill()
# also expose the two singles for robustness
price['ZHY'] = hy['ZHY.TO'].reindex(price.index).ffill()
price['XHY'] = hy['XHY.TO'].reindex(price.index).ffill()
avail = list(price.columns)

# ── Lagged macro regime history (identical to run_backtest.py) ──────────────
m = pickle.load(open('data/cache/macro_data.pkl', 'rb'))
vix = m['vix']; vix.index = pd.to_datetime(vix.index)
cpi = m['cpi']; gdp = m['gdp']; ff = m['ff_rate']
cpi_yoy = cpi.pct_change(12) * 100
cpi_yoy.index = pd.to_datetime(cpi_yoy.index) + pd.DateOffset(months=1)
cpi_m = cpi_yoy.resample('MS').last().ffill()
gdp = gdp.copy(); gdp.index = pd.to_datetime(gdp.index) + pd.DateOffset(months=4)
gdp_m = gdp.resample('MS').last().ffill()
vix_m = vix.resample('MS').mean()
avg_rf = ff.mean() / 100 if len(ff) else 0.02
spy_mom = price['SPY'].resample('MS').last().pct_change(12)

def classify(d):
    g = gdp_m.asof(d); s = spy_mom.asof(d); growth = (g > 1.5) or (s > 0.05)
    c = cpi_m.asof(d); c3 = cpi_m.asof(d - pd.DateOffset(months=3)); infl = (c > 3.0) and (c > c3)
    if vix_m.asof(d) > 30: return 'deflation'
    if growth and not infl: return 'goldilocks'
    if growth and infl: return 'reflation'
    if not growth and infl: return 'stagflation'
    return 'deflation'
regime_history = pd.DataFrame([{'date': d, 'regime': classify(d)}
                               for d in price.resample('MS').first().index if d >= pd.Timestamp('2005-06-01')])

BASE = {
 'goldilocks': {'QQQ':0.30,'SOXX':0.20,'SPY':0.15,'SPYI':0.10,'TLT':0.08,'GLD':0.10,'DBMF':0.04,'URA':0.03},
 'reflation':  {'QQQ':0.15,'SOXX':0.10,'SPY':0.10,'SPYI':0.08,'GLD':0.20,'URA':0.07,'TLT':0.05,'DBMF':0.25},
 'stagflation':{'GLD':0.30,'DBMF':0.25,'TLT':0.20,'SPYI':0.10,'URA':0.05,'SPY':0.05,'QQQ':0.03,'SOXX':0.02},
 'deflation':  {'TLT':0.35,'GLD':0.20,'DBMF':0.15,'SPYI':0.10,'SPY':0.10,'QQQ':0.05,'SOXX':0.03,'URA':0.02},
}
def add(w, tk, prof):
    w = copy.deepcopy(w)
    for reg, wt in prof.items():
        if reg in w and wt: w[reg][tk] = wt
    return w
def repl(w, old, new):
    w = copy.deepcopy(w)
    for d in w.values():
        if old in d: d[new] = d.pop(old)
    return w

CONFIGS = {
    '8t BASE (URA)':                 BASE,
    '9t +HY (gold8/refl10)':         add(BASE,'HY',{'goldilocks':0.08,'reflation':0.10}),
    '9t +HY (refl only 12)':         add(BASE,'HY',{'reflation':0.12}),
    '9t +HY all-regime 6':           add(BASE,'HY',{'goldilocks':0.06,'reflation':0.08,'stagflation':0.06,'deflation':0.04}),
    '8t SPYI->HY':                   repl(BASE,'SPYI','HY'),
    '10t +HY +ZHYsingle chk':        add(BASE,'HY',{'goldilocks':0.08,'reflation':0.10}),  # same; sanity
}

def filt(d):
    f = {k:v for k,v in d.items() if k in avail}; tot = sum(f.values())
    return {k:v/tot for k,v in f.items()} if tot else {}

# HY standalone stats over its live window (vs the baseline book)
def metrics(r):
    r = r.dropna(); yrs=len(r)/252; tot=(1+r).prod()-1
    cagr=(1+tot)**(1/yrs)-1 if yrs>0 else 0; vol=r.std()*np.sqrt(252)
    eq=(1+r).cumprod(); dd=(eq/eq.expanding().max()-1).min()
    return cagr, vol, (cagr-avg_rf)/vol if vol>0 else 0, dd

engine = BacktestEngine(price_data=price, initial_capital=100_000, risk_free_rate=avg_rf)

def run(w, start=None):
    rw = {reg: filt(d) for reg,d in w.items()}
    res = engine.run_optimized_regime_backtest(regime_history=regime_history, regime_weights=rw,
                                               name='x', vix_data=vix, **STRATEGY_PARAMS)
    return res

print("HY sleeve = avg(ZHY.TO, XHY.TO), CAD-hedged (~US HY). Data from", hy_idx.first_valid_index().date())
hyr = price['HY'].pct_change()
c,v,s,d = metrics(hyr)
print(f"HY standalone (2010+): CAGR {c:.2%} | Vol {v:.2%} | Sharpe {s:.2f} | MaxDD {d:.2%}")
print(f"\n{'Config':28s} {'n':>2s} {'CAGR':>7s} {'Vol':>6s} {'Sharpe':>7s} {'MaxDD':>7s}")
print('-'*64)
rows=[]
for name,w in CONFIGS.items():
    n=len(set().union(*[set(filt(d)) for d in w.values()]))
    r=run(w)
    rows.append((name,r.annual_return,r.sharpe_ratio,r.max_drawdown))
    print(f"{name:28s} {n:2d} {r.annual_return:7.2%} {r.volatility:6.2%} {r.sharpe_ratio:7.2f} {r.max_drawdown:7.2%}")
print('-'*64)
b=rows[0]
print(f"\nDeltas vs 8t BASE ({b[1]:.2%}/{b[2]:.2f}/{b[3]:.2%}):")
for nm,ca,sh,dd in rows[1:]:
    print(f"  {nm:28s} dCAGR {ca-b[1]:+.2%} | dSharpe {sh-b[2]:+.2f} | dMaxDD {dd-b[3]:+.2%}")
