"""
ab_production.py — Production-engine A/B of candidate REGIME_WEIGHTS changes.

Replicates run_backtest.py's EXACT setup (macro publication lag CPI+1mo / GDP+4mo,
HAR vol, VIX gate, STRATEGY_PARAMS) so numbers are directly comparable to the
validated 14.68% / 0.99 / 14.78% baseline — then swaps weights and re-runs.

Variants:
  BASELINE         current REGIME_WEIGHTS (must reproduce ~14.68%)
  URA->XLY         consumer-disc swap
  URA+AIPO split   keep 60% URA, add 40% AIPO (AI&power infra; ~11mo history)
  +CAD sleeve ZWB  add 10% ZWB.TO (CAD->USD converted) as a diversifier, renormalised
  AIPO + ZWB       combine the two additive ideas
"""
import copy, pickle, logging
import numpy as np, pandas as pd
logging.disable(logging.CRITICAL)
from config.regime_rules import REGIME_WEIGHTS, STRATEGY_PARAMS
from src.backtester.engine import BacktestEngine

CPI_LAG, GDP_LAG = 1, 4

# ── Macro with publication lag (identical to run_backtest.py) ──────────────
m = pickle.load(open('data/cache/macro_data.pkl', 'rb'))
vix = m['vix']; vix.index = pd.to_datetime(vix.index)
cpi = m['cpi']; gdp = m['gdp']; ff = m['ff_rate']
cpi_yoy = cpi.pct_change(12) * 100
cpi_yoy.index = pd.to_datetime(cpi_yoy.index) + pd.DateOffset(months=CPI_LAG)
cpi_monthly = cpi_yoy.resample('MS').last().ffill()
gdp = gdp.copy(); gdp.index = pd.to_datetime(gdp.index) + pd.DateOffset(months=GDP_LAG)
gdp_monthly = gdp.resample('MS').last().ffill()
vix_monthly = vix.resample('MS').mean()
avg_rf = ff.mean() / 100 if len(ff) else 0.02

# ── Prices: cache + A/B tickers (AIPO/XLY native USD, ZWB.TO CAD->USD) ──────
price = pd.read_csv('data/cache/price_data.csv', index_col=0, parse_dates=True).ffill()
extra = pd.read_csv('data/cache/ab_extra_prices.csv', index_col=0, parse_dates=True)
extra.index = pd.to_datetime(extra.index).normalize()
extra = extra[~extra.index.duplicated(keep='last')]
cad = pd.read_csv('data/cache/ab_canada_prices.csv', index_col=0, parse_dates=True)
cad.index = pd.to_datetime(cad.index).normalize()
# FX and TSX ETFs arrive on interleaved rows (different intraday stamps) -> collapse
# same-date rows taking the first non-null per column, then ffill so the ratio aligns.
cad = cad.groupby(level=0).first().sort_index().ffill()

price['AIPO'] = extra['AIPO'].reindex(price.index).ffill()
price['XLY']  = extra['XLY'].reindex(price.index).ffill()
zwb_usd = (cad['ZWB.TO'] / cad['USDCAD=X']).reindex(price.index).ffill()   # CAD->USD
price['ZWB'] = zwb_usd
avail = list(price.columns)

spy_monthly = price['SPY'].resample('MS').last()
spy_mom_12m = spy_monthly.pct_change(12)
monthly_dates = price.resample('MS').first().index


def classify(date):
    g = gdp_monthly.asof(date); s = spy_mom_12m.asof(date)
    growth = (g > 1.5) or (s > 0.05)
    c = cpi_monthly.asof(date); c3 = cpi_monthly.asof(date - pd.DateOffset(months=3))
    infl = (c > 3.0) and (c > c3)
    if vix_monthly.asof(date) > 30: return 'deflation'
    if growth and not infl: return 'goldilocks'
    if growth and infl:     return 'reflation'
    if not growth and infl: return 'stagflation'
    return 'deflation'

regime_history = pd.DataFrame(
    [{'date': d, 'regime': classify(d)} for d in monthly_dates if d >= pd.Timestamp('2005-06-01')])


def filt(weights):
    f = {k: v for k, v in weights.items() if k in avail}
    tot = sum(f.values())
    return {k: v / tot for k, v in f.items()} if tot else {}


def variant_weights(transform):
    return {reg: filt(transform(copy.deepcopy(d))) for reg, d in REGIME_WEIGHTS.items()}

def t_baseline(d): return d
def t_xly(d):
    if 'URA' in d: d['XLY'] = d.pop('URA')
    return d
def t_aipo(d):
    if 'URA' in d:
        w = d.pop('URA'); d['URA'] = w * 0.60; d['AIPO'] = w * 0.40
    return d
def t_zwb(d):
    d['ZWB'] = 0.10  # renormalised by filt -> ~9% sleeve
    return d
def t_aipo_zwb(d):
    return t_zwb(t_aipo(d))

VARIANTS = [
    ('BASELINE (URA)', t_baseline),
    ('URA->XLY', t_xly),
    ('URA+AIPO split (60/40)', t_aipo),
    ('+CAD sleeve ZWB ~9%', t_zwb),
    ('URA+AIPO & +ZWB', t_aipo_zwb),
]

engine = BacktestEngine(price_data=price, initial_capital=100_000, risk_free_rate=avg_rf)
print(f"{'Variant':26s} {'CAGR':>7s} {'Vol':>7s} {'Sharpe':>7s} {'MaxDD':>8s}  vs baseline")
print('-' * 78)
base = None
for name, tf in VARIANTS:
    rw = variant_weights(tf)
    res = engine.run_optimized_regime_backtest(
        regime_history=regime_history, regime_weights=rw, name=name, vix_data=vix, **STRATEGY_PARAMS)
    cagr, vol, sh, dd = res.annual_return, res.volatility, res.sharpe_ratio, res.max_drawdown
    if base is None:
        base = (cagr, sh, dd); delta = ''
    else:
        delta = f"dCAGR {cagr-base[0]:+.2%} | dSharpe {sh-base[1]:+.2f} | dMaxDD {dd-base[2]:+.2%}"
    print(f"{name:26s} {cagr:7.2%} {vol:7.2%} {sh:7.2f} {dd:8.2%}  {delta}")
