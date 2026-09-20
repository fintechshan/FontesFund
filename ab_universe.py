"""
ab_universe.py — Production-engine search over 8/9/10-ETF universes.

Goal: starting from the 8-ETF core, find the best 8-10 ticker config (user OK'd up
to 10) including the URA->XLY swap. Same lagged-macro / HAR / VIX-gate / STRATEGY_PARAMS
setup as run_backtest.py, so numbers are comparable to the validated baseline.
Decision rule: maximise Sharpe, keep MaxDD as low as possible (the binding constraint).
"""
import copy, pickle
import numpy as np, pandas as pd
import logging; logging.disable(logging.CRITICAL)
from config.regime_rules import STRATEGY_PARAMS
from src.backtester.engine import BacktestEngine

# Full universe with history (SMH/DRAM/XSD/etc.)
price = pd.read_csv('data/cache/price_data_ab.csv', index_col=0, parse_dates=True).ffill()
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

# ── Base 8-ETF weights (URA version = pre-swap production) ──────────────────
BASE = {
 'goldilocks': {'QQQ':0.30,'SOXX':0.20,'SPY':0.15,'SPYI':0.10,'TLT':0.08,'GLD':0.10,'DBMF':0.04,'URA':0.03},
 'reflation':  {'QQQ':0.15,'SOXX':0.10,'SPY':0.10,'SPYI':0.08,'GLD':0.20,'URA':0.07,'TLT':0.05,'DBMF':0.25},
 'stagflation':{'GLD':0.30,'DBMF':0.25,'TLT':0.20,'SPYI':0.10,'URA':0.05,'SPY':0.05,'QQQ':0.03,'SOXX':0.02},
 'deflation':  {'TLT':0.35,'GLD':0.20,'DBMF':0.15,'SPYI':0.10,'SPY':0.10,'QQQ':0.05,'SOXX':0.03,'URA':0.02},
}

def swap(w, old, new):
    w = copy.deepcopy(w)
    for d in w.values():
        if old in d: d[new] = d.pop(old)
    return w

def add(w, ticker, by_regime):
    """Add a ticker at given per-regime weights (renormalised later by filter)."""
    w = copy.deepcopy(w)
    for reg, wt in by_regime.items():
        if reg in w: w[reg][ticker] = wt
    return w

# Growth-sleeve add profiles (goldilocks/reflation heavy; token elsewhere)
G = lambda a,b: {'goldilocks':a,'reflation':b,'stagflation':b*0.4,'deflation':b*0.3}

CONFIGS = {
    '8t BASE (URA)':                    BASE,
    '8t URA->XLY':                      swap(BASE,'URA','XLY'),
    '9t URA + XLY':                     add(BASE,'XLY',G(0.05,0.05)),
    '9t (URA->XLY) + SMH':              add(swap(BASE,'URA','XLY'),'SMH',G(0.08,0.05)),
    '9t URA + SMH':                     add(BASE,'SMH',G(0.08,0.05)),
    '10t (URA->XLY) + SMH + AIPO':      add(add(swap(BASE,'URA','XLY'),'SMH',G(0.08,0.05)),'AIPO',G(0.04,0.04)),
    '10t URA + XLY + SMH':              add(add(BASE,'XLY',G(0.05,0.05)),'SMH',G(0.08,0.05)),
    '10t URA + XLY + AIPO':             add(add(BASE,'XLY',G(0.05,0.05)),'AIPO',G(0.04,0.04)),
    '9t (URA->XLY) + DRAM':             add(swap(BASE,'URA','XLY'),'DRAM',G(0.05,0.03)),
}

def filt(d):
    f = {k:v for k,v in d.items() if k in avail}; tot = sum(f.values())
    return {k:v/tot for k,v in f.items()} if tot else {}

engine = BacktestEngine(price_data=price, initial_capital=100_000, risk_free_rate=avg_rf)
print(f"{'Config':30s} {'n':>2s} {'CAGR':>7s} {'Vol':>6s} {'Sharpe':>7s} {'MaxDD':>7s} {'Calmar':>6s}")
print('-'*72)
rows=[]
for name, w in CONFIGS.items():
    rw = {reg: filt(d) for reg,d in w.items()}
    n = len(set().union(*[set(d) for d in rw.values()]))
    res = engine.run_optimized_regime_backtest(regime_history=regime_history, regime_weights=rw,
                                                name=name, vix_data=vix, **STRATEGY_PARAMS)
    rows.append((name,n,res.annual_return,res.volatility,res.sharpe_ratio,res.max_drawdown,
                 res.annual_return/abs(res.max_drawdown)))
    print(f"{name:30s} {n:2d} {res.annual_return:7.2%} {res.volatility:6.2%} "
          f"{res.sharpe_ratio:7.2f} {res.max_drawdown:7.2%} {rows[-1][6]:6.2f}")
print('-'*72)
base = rows[0]
print(f"\nRanked by Sharpe (vs 8t BASE {base[2]:.2%}/{base[4]:.2f}/{base[5]:.2%}):")
for r in sorted(rows, key=lambda x:-x[4])[:5]:
    print(f"  {r[0]:30s} Sharpe {r[4]:.2f} ({r[4]-base[4]:+.2f}) | CAGR {r[2]:.2%} ({r[2]-base[2]:+.2%}) | "
          f"MaxDD {r[5]:.2%} ({r[5]-base[5]:+.2%})")
