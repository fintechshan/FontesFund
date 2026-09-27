"""
ab_gs_throttle.py — Investment Clock vs GS bull/bear throttle.

Fair contrast on one sample, one cost model, and the production macro lags
(CPI +1 month, GDP +4 months). The clock weight tables stay the position
engine. GSBLBR is only a throttle. Nothing here is wired into the deployed
dashboard.

Variants
  A_prod   Clock only, missing ETFs renormalised (historical engine path)
  A        Clock only, AIPO pre-listing weight held as cash
  B        A + derisk throttle (mid band cuts equity and vol; bear band
           overrides the book onto the Deflation table; bull band = clock)
  C        B's derisk, plus an equity/vol boost when the clock is risk-on
           AND the GS band is bull
  grid     Wider bear band, milder mid-band, tilt-only boost, hotter boost,
           and boost-with-no-derisk (does the boost alone raise CAGR?)

Usage
  python3 ab_gs_throttle.py
"""

from __future__ import annotations

import logging
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

logging.disable(logging.CRITICAL)

from config.regime_rules import REGIME_WEIGHTS, STRATEGY_PARAMS
from src.backtester.engine import BacktestEngine
from src.strategist.gs_throttle import (
    assert_throttle_identities,
    build_engine_throttle,
    classify_gs_band,
)

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "cache"
FRED_DIR = CACHE / "fred"
OUT = ROOT / "out"

CPI_LAG, GDP_LAG = 1, 4
START = "2005-01-01"
TICKERS = ["QQQ", "SOXX", "SPY", "IEF", "GLD", "DBMF", "AIPO", "SHY", "AGG", "TLT", "DBC"]
FRED_IDS = {
    "vix": "VIXCLS",
    "gdp": "A191RL1Q225SBEA",
    "cpi": "CPIAUCSL",
    "t10y": "DGS10",
    "t2y": "DGS2",
    "ff_rate": "DFF",
}


def _fred_csv(series_id: str) -> pd.Series:
    FRED_DIR.mkdir(parents=True, exist_ok=True)
    dest = FRED_DIR / f"{series_id}.csv"
    if not dest.exists() or dest.stat().st_size < 50:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        urllib.request.urlretrieve(url, dest)
    df = pd.read_csv(dest)
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.dropna().set_index("date")["value"].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


def load_macro() -> dict:
    macro = {name: _fred_csv(sid) for name, sid in FRED_IDS.items()}
    return macro


def load_prices() -> pd.DataFrame:
    path = CACHE / "price_data.csv"
    need = set(TICKERS)
    if path.exists():
        px = pd.read_csv(path, index_col=0, parse_dates=True)
        if need.issubset(px.columns):
            return _align_prices(px[TICKERS])
    import yfinance as yf
    data = yf.download(TICKERS, start=START, auto_adjust=True, progress=False, threads=True)
    if isinstance(data.columns, pd.MultiIndex):
        data = data["Close"]
    data = data.dropna(axis=1, how="all")
    px = _align_prices(data)
    CACHE.mkdir(parents=True, exist_ok=True)
    px.to_csv(path)
    return px


def _align_prices(raw: pd.DataFrame) -> pd.DataFrame:
    px = raw.copy()
    px.index = pd.to_datetime(px.index)
    if getattr(px.index, "tz", None) is not None:
        px.index = px.index.tz_localize(None)
    px = px.sort_index()
    # Reindex onto SPY's sessions, then restore pre-listing NaNs so a name
    # that does not exist yet is not back-filled from its first print.
    firsts = {c: px[c].first_valid_index() for c in px.columns}
    spy = px["SPY"].dropna()
    px = px.reindex(spy.index).ffill()
    for col, first in firsts.items():
        if first is None:
            px[col] = np.nan
        else:
            px.loc[px.index < first, col] = np.nan
    return px


def build_clock(price: pd.DataFrame, macro: dict):
    """Production classifier: CPI +1mo, GDP +4mo, VIX>30 → deflation."""
    cpi = macro["cpi"]
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_yoy.index = pd.to_datetime(cpi_yoy.index) + pd.DateOffset(months=CPI_LAG)
    cpi_monthly = cpi_yoy.resample("MS").last().ffill()

    gdp = macro["gdp"].copy()
    gdp.index = pd.to_datetime(gdp.index) + pd.DateOffset(months=GDP_LAG)
    gdp_monthly = gdp.resample("MS").last().ffill()

    vix = macro["vix"].copy()
    vix.index = pd.to_datetime(vix.index)
    vix_monthly = vix.resample("MS").mean()

    spy_monthly = price["SPY"].resample("MS").last()
    spy_mom_12m = spy_monthly.pct_change(12)
    monthly_dates = price.resample("MS").first().index

    def classify(date):
        gdp_val = gdp_monthly.asof(date) if len(gdp_monthly) else 2.0
        spy_val = spy_mom_12m.asof(date) if len(spy_mom_12m) else 0.05
        growth = (gdp_val > 1.5) or (spy_val > 0.05)
        cpi_val = cpi_monthly.asof(date) if len(cpi_monthly) else 2.0
        cpi_3m = cpi_monthly.asof(date - pd.DateOffset(months=3)) if len(cpi_monthly) else 2.0
        infl = (cpi_val > 3.0) and (cpi_val > cpi_3m)
        vix_val = vix_monthly.asof(date) if len(vix_monthly) else 15.0
        if vix_val > 30:
            return "deflation"
        if growth and not infl:
            return "goldilocks"
        if growth and infl:
            return "reflation"
        if (not growth) and infl:
            return "stagflation"
        return "deflation"

    rows = [{"date": d, "regime": classify(d)} for d in monthly_dates if d >= pd.Timestamp("2005-06-01")]
    history = pd.DataFrame(rows)
    return history, vix


def unrounded_metrics(result, rf: float) -> dict:
    """Same formulas as BacktestEngine._compute_result, without rounding."""
    eq = result.equity_curve.dropna()
    rets = eq.pct_change()
    rets.iloc[0] = eq.iloc[0] - 1.0
    rets = rets.replace([np.inf, -np.inf], np.nan).dropna()
    total = float((1.0 + rets).prod() - 1.0)
    n_years = len(rets) / 252.0
    cagr = float((1.0 + total) ** (1.0 / max(n_years, 0.01)) - 1.0)
    vol = float(rets.std() * np.sqrt(252))
    sharpe = float((cagr - rf) / vol) if vol > 0 else 0.0
    peak = eq.cummax()
    # equity starts at 1+r0, so drawdown vs its own running peak matches the engine
    dd = (eq / peak - 1.0).min()
    maxdd = float(abs(dd))
    calmar = float(cagr / maxdd) if maxdd > 0 else 0.0
    by_year = {}
    for year, chunk in rets.groupby(rets.index.year):
        by_year[int(year)] = float((1.0 + chunk).prod() - 1.0)
    return {
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "maxdd": maxdd,
        "calmar": calmar,
        "start": str(rets.index[0].date()),
        "end": str(rets.index[-1].date()),
        "years": n_years,
        "by_year": by_year,
    }


def preflight_engine():
    """Cash-park and bear-override change the book in the expected direction."""
    idx = pd.bdate_range("2018-01-02", periods=60)
    spy = pd.Series(np.linspace(100, 130, len(idx)), index=idx)
    flat = pd.Series(100.0, index=idx)
    px = pd.DataFrame({
        "SPY": spy, "IEF": flat, "AIPO": np.nan, "GLD": flat, "SHY": flat, "AGG": flat,
    })
    rh = pd.DataFrame({"date": [idx[0]], "regime": ["goldilocks"]})
    rw = {"goldilocks": {"SPY": 0.50, "AIPO": 0.50}, "deflation": {"IEF": 1.0}}
    eng = BacktestEngine(price_data=px, initial_capital=100_000, risk_free_rate=0.0)
    common = dict(
        risk_parity=False, target_vol=0.10, vol_lo=1.0, vol_hi=1.0,
        bear_equity_frac=1.0, dd_trigger=0.99, transaction_cost_bps=0.0,
        borrow_spread=0.0, use_har_vol=False, mf_alloc=0.0, vix_data=None,
    )
    norm = eng.run_optimized_regime_backtest(rh, rw, name="norm", **common)
    park = eng.run_optimized_regime_backtest(
        rh, rw, name="park", cash_park_tickers=("AIPO",), **common,
    )
    # Flat IEF override should earn ~0; a renormalised goldilocks book is 100% SPY.
    assert norm.total_return > 0.15, norm.total_return
    assert 0.4 * norm.total_return < park.total_return < 0.7 * norm.total_return, (
        norm.total_return, park.total_return,
    )
    gs = pd.Series([90.0], index=pd.to_datetime(["2017-12-31"]))
    thr = build_engine_throttle(gs, mode="derisk", release_lag_months=0)
    thr["deflation_weights"] = {"IEF": 1.0}
    bear = eng.run_optimized_regime_backtest(rh, rw, name="bear", gs_throttle=thr, **common)
    assert abs(bear.total_return) < 0.01, bear.total_return


def run():
    assert_throttle_identities()
    preflight_engine()
    print("preflight ok")

    macro = load_macro()
    price = load_prices()
    history, vix = build_clock(price, macro)
    ff = macro["ff_rate"]
    rf = float(ff.loc["2005-01-01":].mean() / 100.0) if len(ff) else 0.02
    gs_raw = pd.read_csv(CACHE / "gsblbr_history.csv", index_col=0, parse_dates=True)["GSBLBR"]

    counts = history["regime"].value_counts(normalize=True)
    print("clock mix:", ", ".join(f"{k} {v:.0%}" for k, v in counts.items()))
    print(f"sample prices {price.index[0].date()} → {price.index[-1].date()}  rf {rf:.2%}")
    aipo = price["AIPO"].dropna()
    print(f"AIPO {aipo.index[0].date()} → {aipo.index[-1].date()} ({len(aipo)} sessions)")

    # Band occupancy on clock months, using the same +1mo release lag as the runs.
    released = build_engine_throttle(gs_raw, mode="derisk")["score"]
    bands = []
    for d in history["date"]:
        bands.append(classify_gs_band(released.asof(pd.Timestamp(d)), 45.0, 70.0))
    band_s = pd.Series(bands)
    print("primary bands (bull<45, bear>=70):",
          ", ".join(f"{k} {v:.0%}" for k, v in band_s.value_counts(normalize=True).items()))

    engine = BacktestEngine(price_data=price, initial_capital=100_000, risk_free_rate=rf)
    base_kwargs = dict(STRATEGY_PARAMS)
    base_kwargs["vix_data"] = vix

    variants = [
        ("A_prod", "Clock only, renormalise missing (production path)", None, None),
        ("A", "Clock only, AIPO pre-listing held as cash", None, ("AIPO",)),
        ("B", "Clock + GS derisk (bull<45, bear>=70)", "derisk", ("AIPO",)),
        ("C", "Clock + derisk + alignment boost", "boost", ("AIPO",)),
        ("B_wide", "Derisk, wider stress band (bull<50, bear>=65)", "derisk", ("AIPO",),
         {"bull_max": 50.0, "bear_min": 65.0}),
        ("B_mild", "Derisk, milder mid band (equity ×0.85, vol ×0.85)", "derisk", ("AIPO",),
         {"mid_equity_scale": 0.85, "mid_vol_mult": 0.85, "bear_vol_mult": 0.80}),
        ("C_tilt", "Derisk + equity tilt only (×1.20, vol mult 1)", "boost", ("AIPO",),
         {"bull_equity_scale": 1.20, "bull_vol_mult": 1.0}),
        ("C_hot", "Derisk + hotter bull vol (equity ×1.15, vol ×1.15)", "boost", ("AIPO",),
         {"bull_equity_scale": 1.15, "bull_vol_mult": 1.15}),
        ("C_boost_only", "Alignment boost with NO mid/bear derisk", "boost", ("AIPO",),
         {"mid_equity_scale": 1.0, "mid_vol_mult": 1.0, "mid_vol_hi": None,
          "bear_blend": 0.0, "bear_vol_mult": 1.0, "bear_vol_hi": None}),
    ]

    rows = []
    OUT.mkdir(parents=True, exist_ok=True)
    for spec in variants:
        name, label, mode, park = spec[0], spec[1], spec[2], spec[3]
        overrides = spec[4] if len(spec) > 4 else {}
        throttle = None
        if mode is not None:
            throttle = build_engine_throttle(gs_raw, mode=mode, **overrides)
        t0 = time.time()
        res = engine.run_optimized_regime_backtest(
            regime_history=history,
            regime_weights=REGIME_WEIGHTS,
            name=name,
            gs_throttle=throttle,
            cash_park_tickers=park,
            **base_kwargs,
        )
        m = unrounded_metrics(res, rf)
        m.update({"name": name, "label": label, "seconds": time.time() - t0})
        rows.append(m)
        print(
            f"{name:14s} CAGR {m['cagr']:7.2%}  MaxDD {m['maxdd']:7.2%}  "
            f"Sharpe {m['sharpe']:5.2f}  Vol {m['vol']:6.2%}  Calmar {m['calmar']:5.2f}  "
            f"({m['seconds']:.0f}s)"
        )
        _write_rows(rows)

    # Reference clocks, not throttle variants. A_unlag drops the CPI/GDP
    # publication lag (look-ahead). A_auditor shifts the already-lagged
    # regime one extra month — that is the dashboard auditor's "lagged"
    # series, and it is harsher than production.
    global CPI_LAG, GDP_LAG
    saved = (CPI_LAG, GDP_LAG)
    CPI_LAG, GDP_LAG = 0, 0
    hist_un, _ = build_clock(price, macro)
    CPI_LAG, GDP_LAG = saved
    hist_extra = history.copy()
    hist_extra["regime"] = hist_extra["regime"].shift(1).bfill()
    for name, label, hist_ref, park in (
        ("A_unlag", "Clock only, NO publication lag (look-ahead reference)", hist_un, ("AIPO",)),
        ("A_auditor", "Publication lag PLUS an extra month (auditor 'lagged' series)", hist_extra, None),
    ):
        t0 = time.time()
        res = engine.run_optimized_regime_backtest(
            regime_history=hist_ref,
            regime_weights=REGIME_WEIGHTS,
            name=name,
            cash_park_tickers=park,
            **base_kwargs,
        )
        m = unrounded_metrics(res, rf)
        m.update({"name": name, "label": label, "seconds": time.time() - t0})
        rows.append(m)
        print(
            f"{name:14s} CAGR {m['cagr']:7.2%}  MaxDD {m['maxdd']:7.2%}  "
            f"Sharpe {m['sharpe']:5.2f}  Vol {m['vol']:6.2%}  Calmar {m['calmar']:5.2f}  "
            f"({m['seconds']:.0f}s)"
        )
        _write_rows(rows)

    _print_deltas(rows)
    return rows


def _write_rows(rows: list[dict]) -> None:
    flat = []
    for m in rows:
        flat.append({
            "name": m["name"],
            "label": m["label"],
            "cagr": m["cagr"],
            "maxdd": m["maxdd"],
            "sharpe": m["sharpe"],
            "vol": m["vol"],
            "calmar": m["calmar"],
            "start": m["start"],
            "end": m["end"],
            "y2008": m["by_year"].get(2008, np.nan),
            "y2020": m["by_year"].get(2020, np.nan),
            "y2022": m["by_year"].get(2022, np.nan),
        })
    pd.DataFrame(flat).to_csv(OUT / "gs_throttle_results.csv", index=False)


def _print_deltas(rows: list[dict]) -> None:
    base = next(r for r in rows if r["name"] == "A")
    print("\nvs A (clock, AIPO cash):")
    for m in rows:
        if m["name"] == "A":
            continue
        print(
            f"  {m['name']:14s} dCAGR {m['cagr'] - base['cagr']:+.2%}  "
            f"dMaxDD {m['maxdd'] - base['maxdd']:+.2%}  "
            f"dSharpe {m['sharpe'] - base['sharpe']:+.2f}"
        )


if __name__ == "__main__":
    run()
