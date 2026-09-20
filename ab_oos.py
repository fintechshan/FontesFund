"""
ab_oos.py — PLANNING ONLY. Train/test split view of the production strategy.

Question: treat 2005-2020 as the "training" era and 2021-present as live/unseen.
What did the strategy actually return in the out-of-sample window?

Method: run the production engine ONCE over the full history (lagged macro, HAR,
VIX gate, STRATEGY_PARAMS), then slice the resulting daily equity curve into
2005-2020 (in-sample era) and 2021+ (out-of-sample era) and compute metrics per
window (risk-free = mean DFF within each window). SPY sliced identically.

Honesty note (printed): regime rules/weights are macro-theory-based (never fitted)
so 2021+ is genuinely OOS for them; but the v5.1 OVERLAY params (bear=0.70,
dd=0.07, HAR on, vol target 13%) were tuned on full-sample results INCLUDING
2021-22 — so the OOS slice is partially contaminated for those knobs.
"""
import pickle
import numpy as np, pandas as pd
import logging; logging.disable(logging.CRITICAL)
from config.regime_rules import REGIME_WEIGHTS, STRATEGY_PARAMS
from src.backtester.engine import BacktestEngine

SPLIT = '2021-01-01'

price = pd.read_csv('data/cache/price_data.csv', index_col=0, parse_dates=True).ffill()
m = pickle.load(open('data/cache/macro_data.pkl', 'rb'))
vix = m['vix']; vix.index = pd.to_datetime(vix.index)
cpi = m['cpi']; gdp = m['gdp']; ff = m['ff_rate']; ff.index = pd.to_datetime(ff.index)
cpi_yoy = cpi.pct_change(12) * 100
cpi_yoy.index = pd.to_datetime(cpi_yoy.index) + pd.DateOffset(months=1)
cpi_m = cpi_yoy.resample('MS').last().ffill()
gdp = gdp.copy(); gdp.index = pd.to_datetime(gdp.index) + pd.DateOffset(months=4)
gdp_m = gdp.resample('MS').last().ffill()
vix_m = vix.resample('MS').mean()
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
avg_rf_full = ff.mean() / 100 if len(ff) else 0.02

avail = list(price.columns)
def filt(w):
    f = {k: v for k, v in w.items() if k in avail}; t = sum(f.values())
    return {k: v / t for k, v in f.items()} if t else {}
rw = {r: filt(w) for r, w in REGIME_WEIGHTS.items()}

engine = BacktestEngine(price_data=price, initial_capital=100_000, risk_free_rate=avg_rf_full)
res = engine.run_optimized_regime_backtest(regime_history=regime_history, regime_weights=rw,
                                           name='prod', vix_data=vix, **STRATEGY_PARAMS)
eq = res.equity_curve.dropna()
rets = eq.pct_change().dropna()
spy_rets = price['SPY'].pct_change().reindex(rets.index).dropna()


def window_metrics(r, lo=None, hi=None):
    if lo: r = r[r.index >= lo]
    if hi: r = r[r.index < hi]
    rf_w = ff[(ff.index >= (lo or ff.index.min())) & (ff.index < (hi or ff.index.max()))]
    rf = rf_w.mean() / 100 if len(rf_w) else avg_rf_full
    yrs = len(r) / 252
    tot = (1 + r).prod() - 1
    cagr = (1 + tot) ** (1 / yrs) - 1 if yrs > 0 else 0
    vol = r.std() * np.sqrt(252)
    e = (1 + r).cumprod()
    dd = (e / e.expanding().max() - 1).min()
    sharpe = (cagr - rf) / vol if vol > 0 else 0
    return cagr, vol, sharpe, dd, tot, yrs, rf

print("=" * 96)
print("TRAIN/TEST SPLIT VIEW — production engine, single full-history run, sliced at", SPLIT)
print(f"(data through {eq.index.max().date()}; full-sample headline "
      f"{res.annual_return:.2%} / {res.sharpe_ratio:.2f} / {res.max_drawdown:.2%})")
print("=" * 96)
rows = [('Strategy 2005-2020  (in-sample era)', window_metrics(rets, hi=SPLIT)),
        ('Strategy 2021-now   (OUT-OF-SAMPLE)', window_metrics(rets, lo=SPLIT)),
        ('SPY      2021-now   (benchmark)',     window_metrics(spy_rets, lo=SPLIT))]
print(f"{'Window':38s} {'CAGR':>7s} {'Vol':>7s} {'Sharpe':>7s} {'MaxDD':>8s} {'Total':>9s} {'rf':>5s}")
for name, (cagr, vol, sh, dd, tot, yrs, rf) in rows:
    print(f"{name:38s} {cagr:7.2%} {vol:7.2%} {sh:7.2f} {dd:8.2%} {tot:9.1%} {rf:5.1%}")

print("\nStrategy year-by-year, out-of-sample era:")
yr = rets[rets.index >= SPLIT].resample('YE').apply(lambda x: (1 + x).prod() - 1)
spy_yr = spy_rets[spy_rets.index >= SPLIT].resample('YE').apply(lambda x: (1 + x).prod() - 1)
for d, v in yr.items():
    print(f"  {d.year}: strategy {v:+7.2%}   SPY {spy_yr.get(d, float('nan')):+7.2%}")

print("\nHONESTY NOTES:")
print(" • Regime rules & weights are macro-theory-based, never fitted -> genuinely OOS in 2021+.")
print(" • BUT v5.1 overlay knobs (bear=0.70, dd=0.07, HAR, 13% vol target) were tuned on the FULL")
print("   sample incl. 2021-22 -> the OOS slice is partially contaminated for those parameters.")
print(" • Slice of one continuous run: path-dependent overlays (DD breaker) carry state across the split.")
