"""
ab_xsp.py — PLANNING ONLY. A/B: replace the SPY holding with XSP.TO (CAD-hedged S&P500).

Rationale (CAD-cash investor): XSP removes USD/CAD FX risk on the S&P sleeve.
Method: XSP is hedged, so its CAD return ≈ S&P500 (USD) minus hedge cost -> use the
XSP series directly as the holding. SPY is KEPT in the data for the trend/regime
signals (only the weight ticker swaps). Engine = run_backtest.py setup.

Watch-out: XSP has a documented hedging drag (esp. 2002-2011) -> report drag by era.
"""
import copy, pickle
import numpy as np, pandas as pd
import logging; logging.disable(logging.CRITICAL)
from config.regime_rules import STRATEGY_PARAMS
from src.backtester.engine import BacktestEngine

price = pd.read_csv('data/cache/price_data_ab.csv', index_col=0, parse_dates=True).ffill()
xsp = pd.read_csv('data/cache/ab_xsp_prices.csv', index_col=0, parse_dates=True)
xsp.index = pd.to_datetime(xsp.index).normalize()
price['XSP'] = xsp['XSP.TO'].reindex(price.index).ffill()
avail = list(price.columns)

# Hedge drag by era (XSP CAD-hedged vs SPY USD, local total returns)
j = pd.concat([price['SPY'], price['XSP']], axis=1).dropna()
for lbl, s in [('2005-2026', '2005-01-01'), ('2012-2026', '2012-01-01'), ('2018-2026', '2018-01-01')]:
    w = j[j.index >= s]; r = w.pct_change().dropna(); n = len(r)
    da = (1+r['SPY']).prod()**(252/n) - (1+r['XSP']).prod()**(252/n)
    print(f"  hedge drag (SPY-XSP) {lbl}: {da:+.2%}/yr")

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
def repl(w, old, new):
    w = copy.deepcopy(w)
    for d in w.values():
        if old in d: d[new] = d.pop(old)
    return w
def filt(d):
    f = {k:v for k,v in d.items() if k in avail}; tot = sum(f.values())
    return {k:v/tot for k,v in f.items()} if tot else {}

engine = BacktestEngine(price_data=price, initial_capital=100_000, risk_free_rate=avg_rf)
def run(w):
    rw = {reg: filt(d) for reg,d in w.items()}
    return engine.run_optimized_regime_backtest(regime_history=regime_history, regime_weights=rw,
                                                name='x', vix_data=vix, **STRATEGY_PARAMS)

print(f"\n{'Config':24s} {'CAGR':>7s} {'Vol':>6s} {'Sharpe':>7s} {'MaxDD':>7s}")
print('-'*54)
b = run(BASE); x = run(repl(BASE, 'SPY', 'XSP'))
for nm, r in [('8t BASE (SPY)', b), ('8t SPY->XSP (hedged)', x)]:
    print(f"{nm:24s} {r.annual_return:7.2%} {r.volatility:6.2%} {r.sharpe_ratio:7.2f} {r.max_drawdown:7.2%}")
print('-'*54)
print(f"delta SPY->XSP: dCAGR {x.annual_return-b.annual_return:+.2%} | "
      f"dSharpe {x.sharpe_ratio-b.sharpe_ratio:+.2f} | dMaxDD {x.max_drawdown-b.max_drawdown:+.2%}")
