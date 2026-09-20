"""
src/strategist/edgar_capex.py
=============================
Hyperscaler CapEx pulse from SEC EDGAR XBRL (Tier 2, hard numbers).

Pulls quarterly capital-expenditure figures (us-gaap:PaymentsToAcquireProperty
PlantAndEquipment) straight from SEC's structured XBRL company-concept API for
the four AI datacenter spenders (MSFT / GOOGL / AMZN / META) and computes the
latest-quarter capex + year-over-year growth, aggregated across all four.

This is the *hard* leading indicator that sits next to the FinBERT capex-
commentary sentiment: hyperscaler capex commitments are cash that converts to
semiconductor/HBM revenue 1-3 quarters later.

DISPLAY-ONLY (not in the backtest). Free, structured, no HTML parsing. Cached.
SEC requires a descriptive User-Agent and ≤10 req/s — we make 4 calls, cached.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger("edgar_capex")

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "data" / "cache" / "edgar_capex.json"
TTL_SECONDS = 7 * 24 * 3600  # capex updates quarterly; weekly refresh is ample

# Hyperscalers = the AI-datacenter capex spenders (demand for semis/HBM)
HYPERSCALERS = {
    "MSFT":  ("Microsoft", "0000789019"),
    "GOOGL": ("Alphabet", "0001652044"),
    "AMZN":  ("Amazon", "0001018724"),
    "META":  ("Meta", "0001326801"),
}
CONCEPTS = ["PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets"]
UA = {"User-Agent": "ETF-Regime-Strategist research (contact via dashboard)"}


def _fetch_company_quarters(cik: str):
    """Return a DataFrame[end, val] of QUARTERLY capex for a CIK, or None.
    Tries multiple us-gaap concepts (companies tag capex differently — e.g. Amazon
    uses PaymentsToAcquireProductiveAssets) and keeps the series with the MOST
    RECENT data so we don't latch onto a stale/sparse tag."""
    import requests
    best = None
    best_end = pd.Timestamp.min
    for concept in CONCEPTS:
        url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
        try:
            r = requests.get(url, headers=UA, timeout=15)
            if r.status_code != 200:
                continue
            usd = r.json().get("units", {}).get("USD", [])
            if not usd:
                continue
            df = pd.DataFrame(usd)
            df["start"] = pd.to_datetime(df["start"])
            df["end"] = pd.to_datetime(df["end"])
            df["days"] = (df["end"] - df["start"]).dt.days
            q = (df[(df["days"] >= 80) & (df["days"] <= 100)]
                 .drop_duplicates("end", keep="last").sort_values("end"))
            if len(q) >= 4 and q["end"].iloc[-1] > best_end:
                best = q[["end", "val"]].reset_index(drop=True)
                best_end = q["end"].iloc[-1]
        except Exception as e:
            logger.warning(f"EDGAR fetch failed CIK{cik}/{concept} ({e}).")
            continue
    return best


def _yoy(df: pd.DataFrame):
    """(latest_end, latest_val, yoy_pct) using the same fiscal quarter a year ago."""
    latest = df.iloc[-1]
    target = latest["end"] - pd.Timedelta(days=365)
    prior = df[(df["end"] - target).abs() <= pd.Timedelta(days=50)]
    yoy = None
    prior_val = None
    if not prior.empty:
        prior_val = float(prior.iloc[-1]["val"])
        if prior_val:
            yoy = latest["val"] / prior_val - 1.0
    return latest["end"], float(latest["val"]), yoy, prior_val


def capex_pulse(use_cache: bool = True) -> dict:
    """Per-company latest-quarter capex + YoY, aggregated across hyperscalers."""
    if use_cache and CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < TTL_SECONDS:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass

    companies = []
    agg_latest = agg_prior = 0.0
    for tkr, (name, cik) in HYPERSCALERS.items():
        df = _fetch_company_quarters(cik)
        if df is None or df.empty:
            continue
        end, val, yoy, prior_val = _yoy(df)
        companies.append({
            "ticker": tkr, "name": name,
            "quarter": end.strftime("%Y-%m-%d"),
            "capex_b": round(val / 1e9, 2),
            "yoy": round(yoy, 3) if yoy is not None else None,
        })
        agg_latest += val
        if prior_val:
            agg_prior += prior_val

    agg_yoy = (agg_latest / agg_prior - 1.0) if agg_prior else None
    result = {
        "companies": companies,
        "agg_capex_b": round(agg_latest / 1e9, 1),
        "agg_yoy": round(agg_yoy, 3) if agg_yoy is not None else None,
        "n": len(companies),
        "source": "SEC EDGAR XBRL (us-gaap:PaymentsToAcquirePPE)",
        "computed": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    }
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass
    return result
