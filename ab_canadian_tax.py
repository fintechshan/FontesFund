"""
ab_canadian_tax.py — PLANNING ONLY. After-US-tax comparison for a Canadian resident.

Q1: What is the net annual return of the US-ETF strategy AFTER 15% US withholding tax?
Q2: How does an all-Canadian-listed portfolio (no US WHT) compare, side-by-side, in CAD?

Method:
  • US withholding only hits DISTRIBUTIONS, not total return. Drag_t = sum_i W[i,t] * yield_i * 0.15,
    computed from each ETF's trailing-12m distribution yield and the strategy's ACTUAL rotating weights.
  • US strategy returns come from the production engine logic (risk-parity book + trend + vol-target + DD
    breaker), then converted USD->CAD via USDCAD=X so the comparison is in the investor's home currency.
  • Account scenarios: RRSP (0% WHT, treaty-exempt), Taxable (15% withheld but recoverable as a foreign
    tax credit ~ neutral), TFSA/RESP (15% withheld, NON-recoverable -> full permanent drag).
  • All-Canadian book: XIC/ZWB/XEI/ZFL/CGL, native CAD, no US WHT (eligible Cdn dividends).

Caveats: FX is real (USD appreciated vs CAD over the window -> tailwind for the US book in CAD).
Canada has NO listed equivalent for the semis/AI/managed-futures/uranium sleeves, so the all-Canadian
book is a structurally different (financials/energy/materials) portfolio, not a true replica.
"""
import numpy as np, pandas as pd, optimize_strategy as O

CAD = pd.read_csv('data/cache/ab_canada_prices.csv', index_col=0, parse_dates=True)
CAD.index = pd.to_datetime(CAD.index).normalize()
CAD = CAD[~CAD.index.duplicated(keep='last')]

YIELD = {'QQQ':0.0043,'SOXX':0.0024,'SPY':0.0102,'SPYI':0.1203,
         'TLT':0.0448,'GLD':0.0,'DBMF':0.0527,'URA':0.0476}
WHT = 0.15
PROD = dict(bear=0.70, target=0.13, lo=0.50, hi=1.50, lb=21, trig=0.07, borrow=0.01, bps=5.0)
START = '2012-02-01'   # common window start (limited by XEI.TO inception 2012-01)


def rp_book(price, R, Rf, avail, regime_weights):
    vol = R.rolling(60).std()*np.sqrt(252); invvol = (1.0/vol).shift(1)
    tickers = list(price.columns)
    W = pd.DataFrame(0.0, index=R.index, columns=tickers)
    last_m=(-1,-1); cur={}
    for i,date in enumerate(R.index):
        m=(date.year,date.month)
        if m!=last_m or not cur:
            last_m=m
            reg=O.regime_hist.loc[O.regime_hist.index<=date]
            if len(reg):
                raw=regime_weights.get(reg.iloc[-1],{})
                iv=invvol.iloc[i] if i>0 else invvol.iloc[0]
                a={t:w*iv.get(t,np.nan) for t,w in raw.items()
                   if t in tickers and avail.iloc[i-1].get(t,False) and pd.notna(iv.get(t,np.nan))}
                tot=sum(a.values()); cur={t:w/tot for t,w in a.items()} if tot>0 else {}
        for t,w in cur.items(): W.iat[i,W.columns.get_loc(t)]=w
    return W


# ── US strategy (USD) + its rotating weight matrix ──────────────────────────
price=O.price; R=price.pct_change(); Rf=R.fillna(0.0); avail=price.notna()
W = rp_book(price, R, Rf, avail, O.REGIME_WEIGHTS)
book = (W*Rf).sum(axis=1)
tx = W.diff().abs().sum(axis=1)/2*(PROD['bps']/10000)
r = O.trend_overlay(book-tx, O.r_def, O.trend_ok_200, PROD['bear'])
r_usd = O.dd_breaker(O.vol_target(r, PROD['target'], PROD['lb'], PROD['lo'], PROD['hi'], borrow=PROD['borrow']),
                     PROD['trig'])

# Time-varying daily WHT drag from the actual weights (annual -> daily)
yld = pd.Series(YIELD)
wht_annual = (W[[c for c in W.columns if c in YIELD]] * yld.reindex(W.columns).dropna()).sum(axis=1) * WHT
wht_daily = wht_annual/252

# USD -> CAD
fx = CAD['USDCAD=X'].reindex(price.index).ffill()      # CAD per 1 USD
fx_ret = fx.pct_change().fillna(0.0)
r_usd_cad = (1+r_usd)*(1+fx_ret)-1                      # US strategy expressed in CAD

def win(s): return s[s.index>=START].dropna()

scen = {
    'US strat — GROSS (CAD)':            win(r_usd_cad),
    'US strat — RRSP (0% WHT)':          win(r_usd_cad),                      # treaty-exempt
    'US strat — Taxable (FTC ~recover)': win(r_usd_cad - wht_daily*0.0),      # ~neutral (recovered)
    'US strat — TFSA (15% lost)':        win(r_usd_cad - wht_daily),          # full permanent drag
}

# ── All-Canadian portfolio (native CAD, no US WHT) ──────────────────────────
CW = {'XIC.TO':0.35,'ZWB.TO':0.20,'XEI.TO':0.15,'ZFL.TO':0.15,'CGL.TO':0.15}
cad_px = CAD[list(CW)].reindex(price.index).ffill()
cad_ret = cad_px.pct_change().fillna(0.0)
r_cad_book = sum(w*cad_ret[t] for t,w in CW.items())   # fixed-weight (daily reb) CAD portfolio
r_cad_book = win(r_cad_book)

print("="*100)
print(f"AFTER-US-TAX COMPARISON  (CAD terms, common window {START} -> {win(r_usd_cad).index.max().date()})")
print("="*100)
print(f"\nAvg US withholding drag on the rotating book: {wht_annual[wht_annual.index>=START].mean():.3%}/yr "
      f"(range {wht_annual[wht_annual.index>=START].min():.2%}-{wht_annual[wht_annual.index>=START].max():.2%})")
print("Per-sleeve drag at current REFLATION weights (weight x yield x 15%):")
cur_w = {'DBMF':0.256,'GLD':0.196,'QQQ':0.149,'SPY':0.100,'SOXX':0.099,'SPYI':0.081,'URA':0.067,'TLT':0.052}
for t,w in sorted(cur_w.items(), key=lambda x:-x[1]*YIELD[x[0]]):
    print(f"   {t:5s} w {w:5.1%} x yld {YIELD[t]:5.2%} x 15% = {w*YIELD[t]*WHT:.3%}")
print(f"   {'TOTAL':5s} {sum(w*YIELD[t]*WHT for t,w in cur_w.items()):.3%}/yr\n")

hdr = f"  {'Portfolio':34s} {'CAGR':>7s} {'Vol':>7s} {'Sharpe':>7s} {'MaxDD':>8s} {'Calmar':>7s}"
print(hdr); print("  "+"-"*72)
def row(name, s):
    m=O.metrics(s,name)
    print(f"  {name:34s} {m['cagr']:7.2%} {m['vol']:7.2%} {m['sharpe']:7.2f} {m['maxdd']:8.2%} {m['calmar']:7.2f}")
for k,s in scen.items(): row(k,s)
print("  "+"-"*72)
row('ALL-CANADIAN book (CAD, no US WHT)', r_cad_book)
print("\n  Canadian book = 35% XIC + 20% ZWB + 15% XEI + 15% ZFL + 15% CGL (no tech/AI/semis/MF/uranium).")

# ── (a) Account-location scenarios + JSON for the dashboard panel ────────────
import json
from datetime import datetime
window_end = win(r_usd_cad).index.max()
mU = O.metrics(win(r_usd_cad))                       # RRSP / taxable (no net drag)
mT = O.metrics(win(r_usd_cad - wht_daily))           # TFSA (full drag)
mC = O.metrics(r_cad_book)
wht_win = wht_annual[wht_annual.index >= START]

accounts = [
    {'account': 'RRSP / RRIF',          'wht': '0% — treaty-exempt on US-listed ETFs',
     'cagr': mU['cagr'], 'note': 'Best home for the US book — withholding is zero.'},
    {'account': 'Non-registered (taxable)', 'wht': '15% withheld, recoverable via foreign tax credit',
     'cagr': mU['cagr'], 'note': 'Net ~neutral; you reclaim the WHT at tax time.'},
    {'account': 'TFSA / RESP / FHSA',   'wht': '15% withheld, NON-recoverable',
     'cagr': mT['cagr'], 'note': f"Only account where the ~{wht_win.mean():.2%}/yr drag is permanently lost."},
]
study = {
    'as_of': datetime.now().strftime('%Y-%m-%d'),
    'window': f"{START[:7]} → {window_end.strftime('%Y-%m')}",
    'ccy': 'CAD', 'wht_rate': WHT,
    'wht_avg': float(wht_win.mean()), 'wht_min': float(wht_win.min()), 'wht_max': float(wht_win.max()),
    'wht_current': float(sum(w*YIELD[t]*WHT for t,w in cur_w.items())),
    'sleeve_drag': [{'ticker': t, 'weight': w, 'yield': YIELD[t], 'drag': w*YIELD[t]*WHT}
                    for t,w in sorted(cur_w.items(), key=lambda x:-x[1]*YIELD[x[0]])],
    'accounts': accounts,
    'compare': [
        {'name': 'US strategy — RRSP / taxable (CAD)', 'cagr': mU['cagr'], 'vol': mU['vol'],
         'sharpe': mU['sharpe'], 'maxdd': mU['maxdd']},
        {'name': 'US strategy — TFSA, 15% lost (CAD)', 'cagr': mT['cagr'], 'vol': mT['vol'],
         'sharpe': mT['sharpe'], 'maxdd': mT['maxdd']},
        {'name': 'All-Canadian book — no US WHT (CAD)', 'cagr': mC['cagr'], 'vol': mC['vol'],
         'sharpe': mC['sharpe'], 'maxdd': mC['maxdd']},
    ],
    'cad_book': '35% XIC + 20% ZWB + 15% XEI + 15% ZFL + 15% CGL',
    'caveats': 'CAD terms incl. FX (USD rose vs CAD over the window — a tailwind that may not repeat; '
               'local-USD CAGR ~18%). All-Canadian book is static (no regime overlays exist for those '
               'products) and has no tech/AI/semis/MF/uranium equivalent. SPYI/DBMF drag is overstated '
               '(much of their distribution is return-of-capital, not taxable dividend).',
}
OUT = 'data/cache/tax_study.json'
json.dump(study, open(OUT, 'w'), indent=2)
print(f"\nAccount-location net CAGR (CAD): RRSP/Taxable {mU['cagr']:.2%} | TFSA {mT['cagr']:.2%} | "
      f"All-Canadian {mC['cagr']:.2%}")
print(f"Wrote {OUT}")
