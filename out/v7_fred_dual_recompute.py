#!/usr/bin/env python3
"""v7 dual-sleeve backtest with public FRED CSVs (no API key).
Modes: live=AIPO, backtest=XLY proxy. Macro: CPI +1mo, GDP +4mo.

If data/cache/fred/*.csv are missing, downloads them from
https://fred.stlouisfed.org/graph/fredgraph.csv (public, no key).
"""
from __future__ import annotations
import json, warnings
from pathlib import Path
import urllib.request
import numpy as np, pandas as pd, yfinance as yf

warnings.filterwarnings("ignore")
OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
FRED = ROOT / "data" / "cache" / "fred"

LIVE = ["QQQ", "SOXX", "SPY", "IEF", "GLD", "DBMF", "AIPO"]
BACKTEST = ["QQQ", "SOXX", "SPY", "IEF", "GLD", "DBMF", "XLY"]
DEFENSE = ["SHY", "AGG", "GLD", "IEF"]

# Canonical live weights (AIPO sleeve) — match config/regime_rules.py
REGIME_LIVE = {
    "goldilocks": {"QQQ": 0.30, "SOXX": 0.20, "SPY": 0.25, "IEF": 0.08, "GLD": 0.10, "DBMF": 0.04, "AIPO": 0.03},
    "reflation":  {"QQQ": 0.15, "SOXX": 0.10, "SPY": 0.18, "GLD": 0.20, "AIPO": 0.07, "IEF": 0.05, "DBMF": 0.25},
    "stagflation":{"GLD": 0.30, "DBMF": 0.25, "IEF": 0.20, "SPY": 0.15, "AIPO": 0.05, "QQQ": 0.03, "SOXX": 0.02},
    "deflation":  {"IEF": 0.35, "GLD": 0.20, "DBMF": 0.15, "SPY": 0.20, "QQQ": 0.05, "SOXX": 0.03, "AIPO": 0.02},
}
P = dict(target_vol=0.13, vol_lb=21, vol_lo=0.50, vol_hi=1.50,
         bear_frac=0.70, dd_trigger=0.07, tc_bps=5.0, rp_lb=60, rf=0.02)

FRED_SERIES = ("CPIAUCSL", "A191RL1Q225SBEA", "VIXCLS", "DFF")
FREDGRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def remap(weights, mode):
    if mode == "live":
        return dict(weights)
    return {("XLY" if k == "AIPO" else k): v for k, v in weights.items()}


def _ensure_fred_csv(sid: str) -> Path:
    FRED.mkdir(parents=True, exist_ok=True)
    path = FRED / f"{sid}.csv"
    if path.exists() and path.stat().st_size > 0:
        return path
    url = FREDGRAPH.format(sid=sid)
    print(f"  downloading public FRED {sid} …")
    with urllib.request.urlopen(url, timeout=60) as resp:
        path.write_bytes(resp.read())
    return path


def _read_fred_series(path: Path, sid: str) -> pd.Series:
    df = pd.read_csv(path)
    date_col = "observation_date" if "observation_date" in df.columns else (
        "DATE" if "DATE" in df.columns else df.columns[0]
    )
    value_col = sid if sid in df.columns else df.columns[-1]
    s = pd.to_numeric(df[value_col], errors="coerce")
    idx = pd.to_datetime(df[date_col])
    return pd.Series(s.values, index=idx, name=sid).dropna()


def load_fred():
    for sid in FRED_SERIES:
        _ensure_fred_csv(sid)
    cpi = _read_fred_series(FRED / "CPIAUCSL.csv", "CPIAUCSL")
    gdp = _read_fred_series(FRED / "A191RL1Q225SBEA.csv", "A191RL1Q225SBEA")
    vix = _read_fred_series(FRED / "VIXCLS.csv", "VIXCLS")
    dff = _read_fred_series(FRED / "DFF.csv", "DFF")
    # publication lags
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_yoy.index = cpi_yoy.index + pd.DateOffset(months=1)
    gdp_lag = gdp.copy()
    gdp_lag.index = gdp_lag.index + pd.DateOffset(months=4)
    return cpi_yoy.resample("MS").last().ffill(), gdp_lag.resample("MS").last().ffill(), vix, dff


def download(tickers):
    raw = yf.download(sorted(set(tickers + DEFENSE)), start="2005-01-01", auto_adjust=True, progress=False)
    px = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw.copy()
    px = px.sort_index()
    out = pd.DataFrame(index=px.index)
    for c in px.columns:
        s = px[c]
        first = s.first_valid_index()
        if first is None:
            out[c] = np.nan
            continue
        s2 = s.copy()
        s2.loc[s2.index < first] = np.nan
        out[c] = s2.ffill(limit=3)
        out.loc[out.index < first, c] = np.nan
    return out


def regimes_from_fred(px, cpi_m, gdp_m, vix):
    spy = px["SPY"].dropna()
    months = pd.date_range(spy.index.min(), spy.index.max(), freq="MS")
    spy_mom = spy.resample("MS").last().pct_change(12)
    vix_m = vix.resample("MS").mean()
    out = {}
    for d in months:
        g = gdp_m.asof(d); s = spy_mom.asof(d)
        growth = bool((pd.notna(g) and g > 1.5) or (pd.notna(s) and s > 0.05))
        c = cpi_m.asof(d); c3 = cpi_m.asof(d - pd.DateOffset(months=3))
        infl = bool(pd.notna(c) and pd.notna(c3) and c > 3.0 and c > c3)
        vv = vix_m.asof(d)
        if pd.notna(vv) and vv > 30:
            out[d] = "deflation"
        elif growth and not infl:
            out[d] = "goldilocks"
        elif growth and infl:
            out[d] = "reflation"
        elif (not growth) and infl:
            out[d] = "stagflation"
        else:
            out[d] = "deflation"
    return pd.Series(out)


def sleeve_weights(regime, avail, mode, weight_mode):
    raw = remap(REGIME_LIVE[regime], mode)
    w = {t: 0.0 for t in (LIVE if mode == "live" else BACKTEST)}
    cash = 0.0
    for t, wt in raw.items():
        if bool(avail.get(t, False)):
            w[t] = wt
        else:
            cash += wt
    if weight_mode == "renorm":
        s = sum(w.values())
        if s > 0:
            w = {t: v / s for t, v in w.items()}
    return w


def rp_tilt(w, rets, i, lb):
    active = [t for t, v in w.items() if v > 0]
    if len(active) < 2 or i < lb:
        return w
    window = rets[active].iloc[max(0, i - lb):i]
    vol = window.std() * np.sqrt(252)
    inv = (1.0 / vol.replace(0, np.nan)).fillna(0.0)
    if inv.sum() <= 0:
        return w
    invested = sum(w[t] for t in active)
    rp = (inv / inv.sum()) * invested
    return {t: float(rp[t]) if t in rp.index else 0.0 for t in w}


def run(px, regimes, mode="backtest", weight_mode="cash"):
    universe = LIVE if mode == "live" else BACKTEST
    spy = px["SPY"].dropna()
    idx = spy.index
    pxu = px.reindex(index=idx, columns=universe)
    rets = pxu.pct_change()
    avail = pxu.notna()
    reg_d = regimes.reindex(idx, method="ffill")
    ma200 = spy.rolling(200).mean().shift(1)
    bear = spy.shift(1) < ma200
    def_base = {"SHY": 0.35, "AGG": 0.25, "GLD": 0.25, "IEF": 0.15}
    def_rets = {t: px[t].reindex(idx).pct_change() for t in def_base if t in px.columns}

    port, prev_w = [], {t: 0.0 for t in universe}
    equity, peak = 1.0, 1.0
    for i in range(1, len(idx)):
        reg = reg_d.iloc[i - 1]
        if pd.isna(reg):
            reg = "deflation"
        w = sleeve_weights(reg, avail.iloc[i - 1], mode, weight_mode)
        w = rp_tilt(w, rets.fillna(0.0), i - 1, P["rp_lb"])
        def_extra = {}
        if bool(bear.iloc[i]) if pd.notna(bear.iloc[i]) else False:
            bf = P["bear_frac"]
            dw = {t: wt for t, wt in def_base.items()
                  if t in px.columns and pd.notna(px[t].reindex(idx).iloc[i - 1])}
            ds = sum(dw.values()) or 1.0
            dw = {t: v / ds for t, v in dw.items()}
            w = {t: v * bf for t, v in w.items()}
            for t, wt in dw.items():
                add = wt * (1 - bf)
                if t in w:
                    w[t] += add
                else:
                    def_extra[t] = add
        act = [t for t, v in w.items() if v > 0]
        if len(act) >= 1 and i > P["vol_lb"]:
            cov = rets[act].iloc[i - P["vol_lb"]:i].cov() * 252
            ww = np.array([w[t] for t in cov.columns])
            try:
                pvol = float(np.sqrt(max(0.0, ww @ cov.values @ ww)))
            except Exception:
                pvol = 0.0
            if pvol > 1e-8:
                scale = min(P["vol_hi"], max(P["vol_lo"], P["target_vol"] / pvol))
                w = {t: v * scale for t, v in w.items()}
                def_extra = {t: v * scale for t, v in def_extra.items()}
        peak = max(peak, equity)
        if equity / peak - 1.0 <= -P["dd_trigger"]:
            w = {t: v * 0.5 for t, v in w.items()}
            def_extra = {t: v * 0.5 for t, v in def_extra.items()}
        turn = 0.5 * sum(abs(w.get(t, 0.0) - prev_w.get(t, 0.0)) for t in universe)
        cost = turn * (P["tc_bps"] / 10000.0)
        r = -cost
        for t, wt in w.items():
            ri = rets[t].iloc[i]
            if wt and pd.notna(ri):
                r += wt * float(ri)
        for t, wt in def_extra.items():
            ri = def_rets[t].iloc[i]
            if wt and pd.notna(ri):
                r += wt * float(ri)
        equity *= (1 + r)
        port.append(r)
        prev_w = dict(w)
    return pd.Series(port, index=idx[1:], name=f"{mode}_{weight_mode}")


def metrics(rets, rf=None):
    rets = rets.dropna()
    if len(rets) < 50:
        return {}
    if rf is None:
        rf = P["rf"]
    yrs = len(rets) / 252.0
    tot = float((1 + rets).prod() - 1)
    cagr = float((1 + tot) ** (1 / yrs) - 1)
    vol = float(rets.std() * np.sqrt(252))
    eq = (1 + rets).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    sharpe = float((cagr - rf) / vol) if vol > 0 else 0.0
    down = rets[rets < 0].std() * np.sqrt(252)
    sortino = float((cagr - rf) / down) if down and down > 0 else 0.0
    calmar = float(cagr / abs(dd)) if dd < 0 else 0.0
    return dict(cagr=cagr, vol=vol, sharpe=sharpe, maxdd=dd, sortino=sortino,
                calmar=calmar, total_return=tot, n_days=int(len(rets)),
                start=str(rets.index[0].date()), end=str(rets.index[-1].date()))


def main():
    print("Loading FRED...")
    cpi_m, gdp_m, vix, dff = load_fred()
    avg_rf = float(dff.loc["2005-01-01":].mean() / 100.0)
    print(f"avg DFF rf={avg_rf:.3%}")
    tickers = sorted(set(LIVE + BACKTEST + DEFENSE))
    print("Downloading", tickers)
    px = download(tickers)
    for t in tickers:
        if t in px.columns:
            s = px[t].dropna()
            print(f"  {t}: n={len(s)} first={None if s.empty else s.index.min().date()}")
    regimes = regimes_from_fred(px, cpi_m, gdp_m, vix)
    print("regime counts:\n", regimes.value_counts())

    results, curves = {}, {}
    for mode in ("backtest", "live"):
        for wm in ("cash",):
            key = f"{mode}_{wm}"
            print("run", key)
            rets = run(px, regimes, mode=mode, weight_mode=wm)
            results[key] = metrics(rets, rf=avg_rf)
            curves[key] = (1 + rets).cumprod()
            m = results[key]
            print(key, {k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()})

    # benchmarks
    spy_r = px["SPY"].pct_change().dropna()
    results["SPY"] = metrics(spy_r.loc[curves["backtest_cash"].index.min():], rf=avg_rf)
    mix = (0.6 * px["SPY"].pct_change() + 0.4 * px["IEF"].pct_change()).dropna()
    results["60_40"] = metrics(mix.loc[curves["backtest_cash"].index.min():], rf=avg_rf)

    payload = dict(
        as_of=str(pd.Timestamp.today().date()),
        macro="FRED public CSV: CPIAUCSL +1mo, A191RL1Q225SBEA +4mo, VIXCLS, DFF",
        engine="simplified honest (not bit-identical to src/backtester/engine.py)",
        dual_sleeve={"live": "AIPO", "backtest": "XLY"},
        params=P,
        avg_rf_dff=avg_rf,
        inception={
            "AIPO": str(px["AIPO"].first_valid_index().date()) if "AIPO" in px and px["AIPO"].notna().any() else None,
            "XLY": str(px["XLY"].first_valid_index().date()) if "XLY" in px and px["XLY"].notna().any() else None,
            "DBMF": str(px["DBMF"].first_valid_index().date()) if "DBMF" in px and px["DBMF"].notna().any() else None,
        },
        metrics=results,
    )
    (OUT / "v7_fred_dual_metrics.json").write_text(json.dumps(payload, indent=2, default=str))
    pd.DataFrame({k: v for k, v in curves.items()}).to_csv(OUT / "v7_fred_dual_equity.csv")
    print("Wrote", OUT / "v7_fred_dual_metrics.json")


if __name__ == "__main__":
    main()
