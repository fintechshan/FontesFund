"""
ab_walkforward.py — PLANNING ONLY. Airtight walk-forward of the overlay parameters.

Protocol (no look-ahead in parameter choice):
  1. TRAIN: sweep the v5.1 overlay knobs on 2005–2020 data ONLY
     (bear_equity_frac, dd_trigger, target_vol, use_har_vol; all else production-fixed).
  2. SELECT with the same rule used for v5.1: MaxDD < 14.8% first, then max CAGR
     (tie-break: Sharpe). Selection sees NOTHING after 2020-12-31.
  3. TEST: freeze the winner, run the engine on full history, report 2021+ only.

Regime rules & weights are theory-based (never fitted) — unchanged throughout.
"""
import pickle
import numpy as np, pandas as pd
import logging; logging.disable(logging.CRITICAL)
from config.regime_rules import REGIME_WEIGHTS, STRATEGY_PARAMS
from src.backtester.engine import BacktestEngine

SPLIT = pd.Timestamp('2021-01-01')

price_full = pd.read_csv('data/cache/price_data.csv', index_col=0, parse_dates=True).ffill()
m = pickle.load(open('data/cache/macro_data.pkl', 'rb'))
vix = m['vix']; vix.index = pd.to_datetime(vix.index)
cpi = m['cpi']; gdp = m['gdp']; ff = m['ff_rate']; ff.index = pd.to_datetime(ff.index)
cpi_yoy = cpi.pct_change(12) * 100
cpi_yoy.index = pd.to_datetime(cpi_yoy.index) + pd.DateOffset(months=1)
cpi_m = cpi_yoy.resample('MS').last().ffill()
gdp = gdp.copy(); gdp.index = pd.to_datetime(gdp.index) + pd.DateOffset(months=4)
gdp_m = gdp.resample('MS').last().ffill()
vix_m = vix.resample('MS').mean()
spy_mom_full = price_full['SPY'].resample('MS').last().pct_change(12)

def classify(d, spy_mom):
    g = gdp_m.asof(d); s = spy_mom.asof(d); growth = (g > 1.5) or (s > 0.05)
    c = cpi_m.asof(d); c3 = cpi_m.asof(d - pd.DateOffset(months=3)); infl = (c > 3.0) and (c > c3)
    if vix_m.asof(d) > 30: return 'deflation'
    if growth and not infl: return 'goldilocks'
    if growth and infl: return 'reflation'
    if not growth and infl: return 'stagflation'
    return 'deflation'

def regime_hist(price):
    sm = price['SPY'].resample('MS').last().pct_change(12)
    return pd.DataFrame([{'date': d, 'regime': classify(d, sm)}
                         for d in price.resample('MS').first().index if d >= pd.Timestamp('2005-06-01')])

def filt(w, avail):
    f = {k: v for k, v in w.items() if k in avail}; t = sum(f.values())
    return {k: v / t for k, v in f.items()} if t else {}

def run(price, params):
    avail = list(price.columns)
    rw = {r: filt(w, avail) for r, w in REGIME_WEIGHTS.items()}
    rf = ff[ff.index <= price.index.max()].mean() / 100
    eng = BacktestEngine(price_data=price, initial_capital=100_000, risk_free_rate=rf)
    return eng.run_optimized_regime_backtest(regime_history=regime_hist(price), regime_weights=rw,
                                             name='wf', vix_data=vix, **params)

def wmetrics(r, lo=None):
    if lo is not None: r = r[r.index >= lo]
    rf_w = ff[ff.index >= (lo or ff.index.min())]
    rf = rf_w.mean() / 100 if len(rf_w) else 0.02
    yrs = len(r) / 252; tot = (1 + r).prod() - 1
    cagr = (1 + tot) ** (1 / yrs) - 1 if yrs > 0 else 0
    vol = r.std() * np.sqrt(252)
    e = (1 + r).cumprod(); dd = (e / e.expanding().max() - 1).min()
    return cagr, vol, (cagr - rf) / vol if vol > 0 else 0, dd, tot

# ── 1. TRAIN sweep on 2005-2020 only ────────────────────────────────────────
price_train = price_full[price_full.index < SPLIT]
GRID = [(har, bear, ddt, tv)
        for har in (True, False)
        for bear in (0.5, 0.6, 0.7, 0.8)
        for ddt in (0.06, 0.07, 0.08, 0.10)
        for tv in (0.12, 0.13)]
print(f"TRAIN sweep: {len(GRID)} configs on 2005-01..2020-12 ({len(price_train)} days). All else = production.")
rows = []
for har, bear, ddt, tv in GRID:
    p = dict(STRATEGY_PARAMS); p.update(use_har_vol=har, bear_equity_frac=bear, dd_trigger=ddt, target_vol=tv)
    r = run(price_train, p)
    rows.append({'har': har, 'bear': bear, 'dd_trigger': ddt, 'tv': tv,
                 'cagr': r.annual_return, 'sharpe': r.sharpe_ratio, 'maxdd': r.max_drawdown})
df = pd.DataFrame(rows)
ok = df[df['maxdd'] < 0.148].sort_values(['cagr', 'sharpe'], ascending=False)
sel = ok.iloc[0] if len(ok) else df.sort_values('maxdd').iloc[0]

print(f"\nConfigs meeting train MaxDD<14.8%: {len(ok)}/{len(df)}.  Top 8 by train CAGR:")
print(f"  {'har':>5s} {'bear':>5s} {'ddtrg':>6s} {'tv':>5s} {'CAGR':>7s} {'Sharpe':>7s} {'MaxDD':>7s}")
for _, x in ok.head(8).iterrows():
    print(f"  {str(bool(x['har'])):>5s} {x['bear']:5.2f} {x['dd_trigger']:6.2f} {x['tv']:5.2f} "
          f"{x['cagr']:7.2%} {x['sharpe']:7.2f} {x['maxdd']:7.2%}")

# Where do the production v5.1 params rank on train-only data?
pv = df[(df['har'] == STRATEGY_PARAMS['use_har_vol']) & (df['bear'] == STRATEGY_PARAMS['bear_equity_frac'])
        & (df['dd_trigger'] == STRATEGY_PARAMS['dd_trigger']) & (df['tv'] == STRATEGY_PARAMS['target_vol'])]
if len(pv):
    x = pv.iloc[0]
    print(f"\nProduction v5.1 params on TRAIN only: CAGR {x['cagr']:.2%} | Sharpe {x['sharpe']:.2f} | "
          f"MaxDD {x['maxdd']:.2%} (DD<14.8%: {'yes' if x['maxdd'] < 0.148 else 'NO'})")

print(f"\nFROZEN WINNER (chosen on 2005-2020 only): har={bool(sel['har'])} bear={sel['bear']:.2f} "
      f"dd={sel['dd_trigger']:.2f} tv={sel['tv']:.2f}")

# ── 2. TEST: frozen winner on 2021+ ─────────────────────────────────────────
pw = dict(STRATEGY_PARAMS); pw.update(use_har_vol=bool(sel['har']), bear_equity_frac=float(sel['bear']),
                                      dd_trigger=float(sel['dd_trigger']), target_vol=float(sel['tv']))
res = run(price_full, pw)
rets = res.equity_curve.dropna().pct_change().dropna()
c, v, s, d, t = wmetrics(rets, lo=SPLIT)
print("\n" + "=" * 88)
print("OUT-OF-SAMPLE (2021 -> now), parameters FROZEN from the 2005-2020 sweep:")
print(f"  WALK-FORWARD OOS:  CAGR {c:7.2%} | Vol {v:.2%} | Sharpe {s:.2f} | MaxDD {d:.2%} | Total {t:+.1%}")
# reference: production params' OOS on the same slice
res_p = run(price_full, dict(STRATEGY_PARAMS))
rp = res_p.equity_curve.dropna().pct_change().dropna()
c2, v2, s2, d2, t2 = wmetrics(rp, lo=SPLIT)
print(f"  (production v5.1): CAGR {c2:7.2%} | Vol {v2:.2%} | Sharpe {s2:.2f} | MaxDD {d2:.2%} | Total {t2:+.1%}")
print("=" * 88)
