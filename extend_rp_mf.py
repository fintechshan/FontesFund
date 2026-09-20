"""
extend_rp_mf.py — Prototype: managed-futures proxy + risk-parity sleeve weighting.
Goal: push Sharpe from 1.11 toward 1.2 via diversification (not more overlays).
"""
from optimize_strategy import *

# ──────────────────────────────────────────────────────────────────────
# A. MANAGED-FUTURES PROXY (full-history CTA replication, no look-ahead)
#    Time-series momentum (12m sign) on a diversified ETF basket,
#    inverse-vol weighted, sleeve scaled to ~10% vol. Long/SHORT.
# ──────────────────────────────────────────────────────────────────────
def managed_futures_proxy(assets, mom_days=252, vol_days=60, sleeve_vol=0.10,
                          sleeve_cap=2.0, long_only=False):
    px = price[assets]
    rets = px.pct_change()
    mom  = px.pct_change(mom_days)
    sig  = np.sign(mom)
    if long_only:
        sig = sig.clip(lower=0.0)
    sig = sig.shift(1)
    vol = rets.rolling(vol_days).std()*np.sqrt(252)
    invvol = (1.0/vol).where(mom.notna() & (vol > 0))
    w = invvol.div(invvol.sum(axis=1), axis=0).shift(1)       # risk-parity within sleeve
    contrib = (w * sig * rets).sum(axis=1)
    sv = contrib.rolling(42).std()*np.sqrt(252)
    scaled = contrib * (sleeve_vol/sv).clip(0.0, sleeve_cap).shift(1)
    return scaled.reindex(R.index).fillna(0.0)

MF = managed_futures_proxy(['SPY','TLT','GLD','DBC'])
MF_big = managed_futures_proxy(['SPY','QQQ','IWM','TLT','IEF','GLD','DBC','VWO'])
MF_lo  = managed_futures_proxy(['SPY','TLT','GLD','DBC'], long_only=True)

print("Managed-futures proxy standalone metrics:")
for nm, s in [("MF 4-asset L/S", MF), ("MF 8-asset L/S", MF_big), ("MF 4-asset long-only", MF_lo)]:
    show(metrics(s, nm))
# Correlation of MF with the core regime book (diversification check)
core_corr = pd.concat([r_base, MF, MF_big], axis=1).dropna().corr().iloc[0]
print(f"\nCorr(regime book, MF 4-asset) = {core_corr.iloc[1]:+.2f} | "
      f"Corr(regime book, MF 8-asset) = {core_corr.iloc[2]:+.2f}")
print("MF return in key crisis years:")
for s,nm in [(MF,'MF4')]:
    yr = s.resample('YE').apply(lambda x:(1+x).prod()-1)
    print("  "+nm+": "+"  ".join(f"{d.year}:{v:+.0%}" for d,v in yr.items() if d.year in (2008,2015,2018,2020,2022)))

# ──────────────────────────────────────────────────────────────────────
# B. RISK-PARITY regime book (inverse-vol reweight of regime sleeves)
# ──────────────────────────────────────────────────────────────────────
def risk_parity_weight_matrix(reg_to_weights):
    """Like build_weight_matrix but scale each holding by inverse 60d vol
    (lagged), then renormalise — equal-risk-ish contribution."""
    vol = R.rolling(60).std()*np.sqrt(252)
    invvol = (1.0/vol).shift(1)
    W = pd.DataFrame(0.0, index=R.index, columns=tickers)
    last_month=(-1,-1); cur={}
    for i,date in enumerate(R.index):
        m=(date.year,date.month)
        if m!=last_month or not cur:
            last_month=m
            reg=regime_hist.loc[regime_hist.index<=date]
            if len(reg):
                raw=regime_weights={t:w for t,w in REGIME_WEIGHTS.get(reg.iloc[-1],{}).items()}
                iv=invvol.iloc[i] if i>0 else invvol.iloc[0]
                avail={t:w*iv.get(t,np.nan) for t,w in raw.items()
                       if t in tickers and avail_mask.iloc[i-1].get(t,False) and pd.notna(iv.get(t,np.nan))}
                tot=sum(avail.values())
                cur={t:w/tot for t,w in avail.items()} if tot>0 else {}
        for t,w in cur.items():
            W.iat[i,W.columns.get_loc(t)]=w
    return W

W_rp = risk_parity_weight_matrix(REGIME_WEIGHTS)
r_rp = (W_rp*Rf).sum(axis=1)
print("\nRegime book: fixed-weight vs risk-parity (no overlays):")
show(metrics(r_base, "fixed-weight regime book"))
show(metrics(r_rp,   "risk-parity regime book"))

# ──────────────────────────────────────────────────────────────────────
# C. INTEGRATED: core (+MF blended BEFORE vol target) -> vt -> dd
# ──────────────────────────────────────────────────────────────────────
tx = tx_drag(W_base, 5.0); txrp = tx_drag(W_rp, 5.0)
def strat(book_ret, book_tx, mf, a, bear, target, lo, hi, lb, trig):
    core = trend_overlay(book_ret - book_tx, r_def, trend_ok_200, bear)
    combined = (1-a)*core + a*mf
    r = vol_target(combined, target, lb, lo, hi)
    return dd_breaker(r, trig)

print("\n" + "="*116)
print("INTEGRATED GRID  (maximise Sharpe s.t. DD<14.8% & CAGR>=15.5%)")
print("="*116)
cands=[]
for book,btx,bn in [(r_base,tx,'fix'),(r_rp,txrp,'rp')]:
    for mf,mn in [(MF,'mf4'),(MF_big,'mf8')]:
        for a in [0.0,0.10,0.15,0.20,0.25,0.30]:
            for target in [0.115,0.12,0.125,0.13]:
                for hi in [1.2,1.3,1.4]:
                    for bear in [0.5,0.6,0.7]:
                        for trig in [0.09,0.10,0.12]:
                            r=strat(book,btx,mf,a,bear,target,0.5,hi,21,trig)
                            m=metrics(r,f"{bn}/{mn} a{a} vt{target} hi{hi} bear{bear} dd{trig}")
                            cands.append(m)
ok=[m for m in cands if m['maxdd']>-0.148 and m['cagr']>=0.155]
ok.sort(key=lambda m:m['sharpe'],reverse=True)
print(f"Feasible configs: {len(ok)} / {len(cands)}")
print("Top 12 by Sharpe:")
for m in ok[:12]: show(m)
print("\nBest that ALSO clears CAGR>=16%:")
ok16=[m for m in ok if m['cagr']>=0.16]; ok16.sort(key=lambda m:m['sharpe'],reverse=True)
for m in ok16[:6]: show(m)
