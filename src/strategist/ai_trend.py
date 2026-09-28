"""
src/strategist/ai_trend.py
==========================
AI Trend Intelligence — Sector Alpha engine.

Three inputs, combined into one report that is then cross-checked against the
production portfolio strategy:

  1. SemiAnalysis news feed  — live PUBLIC RSS (semianalysis.com/feed). Only the
     publisher's own headline/summary/link are shown; no paywalled content.
  2. Investment-bank AI research — loaded from config/ai_research_feed.json.
     This is USER-SUPPLIED: paste summaries from your *licensed* MS / GS /
     Bernstein / JPM reports there. We do NOT fabricate proprietary research;
     the file ships with official public research-hub links as a template.
  3. AI-sector price signals — computed from the app's own ETF price history
     (SOXX, QQQ, SOXL, TQQQ vs SPY): momentum, trend, relative strength, vol.

`build_ai_trend_intelligence()` returns a dict the dashboard renders, including a
generated narrative and a verdict on whether the live AI signal AGREES with the
strategy's current AI allocation.

All network access is best-effort with on-disk caching and graceful fallback, so
the dashboard never blocks or crashes if a feed is unavailable.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("ai_trend")

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "cache"
FEED_CACHE = CACHE_DIR / "semianalysis_feed.json"
AI_PRICE_CACHE = CACHE_DIR / "ai_extra_prices.csv"
RESEARCH_CONFIG = ROOT / "config" / "ai_research_feed.json"

# SemiAnalysis migrated to Substack — the Substack feed is current; the legacy
# WordPress feed stopped updating (stale at Sep-2025). Try Substack first.
SEMIANALYSIS_FEEDS = [
    "https://newsletter.semianalysis.com/feed",
    "https://semianalysis.substack.com/feed",
    "https://semianalysis.com/feed/",
]
FEED_TTL_SECONDS = 24 * 3600        # refresh ~daily (well within "weekly")
AI_PRICE_TTL_SECONDS = 24 * 3600    # refresh extra ETF prices ~daily

# AI-sector ETFs we track and their role. Tickers not in the backtest price
# cache (DRAM, SMH, XSD) are fetched live via yfinance — the signal panel can
# follow more of the AI complex than the strategy actually trades.
AI_TICKERS = {
    "SOXX": "Semiconductors (chip supply chain — NVDA, AMD, TSMC, ASML)",
    "SMH":  "Broad semiconductors (NVDA/TSMC-heavy)",
    "DRAM": "AI memory / HBM + GPU & CPU compute",
    "XSD":  "Equal-weight US semiconductors",
    "QQQ":  "AI mega-cap software (MSFT, GOOGL, META, AMZN, NVDA)",
    "SOXL": "3x Semiconductors (leveraged, VIX-gated)",
    "TQQQ": "3x Nasdaq-100 (leveraged, VIX-gated)",
}
# Tickers driving the strategy's actual AI allocation (used for the verdict).
# All AI-trend ETFs (incl. SMH/DRAM/XSD) are now part of REGIME_WEIGHTS, so they
# all count toward the strategy's AI exposure and show "held" in the signal table.
AI_ALLOC_TICKERS = ["SOXX", "SMH", "DRAM", "XSD", "QQQ", "SOXL", "TQQQ", "SSO"]
# AI tickers fetched live only if absent from the backtest price cache (fallback).
AI_EXTRA_TICKERS = ["SMH", "DRAM", "XSD"]


# ──────────────────────────────────────────────────────────────────────
# 1. SemiAnalysis live RSS (public)
# ──────────────────────────────────────────────────────────────────────
def fetch_semianalysis(max_items: int = 6, timeout: int = 8) -> dict:
    """Fetch the public SemiAnalysis feed (Substack first, WordPress fallback),
    cached with a TTL. Returns {items, source, fetched} where items are
    {title, link, date, summary}. Falls back to cache (then empty) on failure."""
    # Serve from cache if fresh
    if FEED_CACHE.exists():
        age = time.time() - FEED_CACHE.stat().st_mtime
        if age < FEED_TTL_SECONDS:
            try:
                cached = json.loads(FEED_CACHE.read_text(encoding="utf-8"))
                cached["items"] = cached.get("items", [])[:max_items]
                return cached
            except Exception:
                pass

    import requests
    for url in SEMIANALYSIS_FEEDS:
        try:
            resp = requests.get(
                url, timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (ETF-Regime-Strategist)"},
            )
            resp.raise_for_status()
            items = _parse_rss(resp.text, max_items)
            if items:
                is_substack = ("substack" in url or "newsletter" in url)
                source = "SemiAnalysis (Substack)" if is_substack else "SemiAnalysis"
                # Human-readable archive/homepage to link to (not the raw feed XML)
                home = "https://newsletter.semianalysis.com/archive" if is_substack else "https://semianalysis.com"
                out = {"items": items, "source": source, "url": url, "home": home,
                       "fetched": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
                FEED_CACHE.parent.mkdir(parents=True, exist_ok=True)
                FEED_CACHE.write_text(json.dumps(out), encoding="utf-8")
                return out
        except Exception as e:
            logger.warning(f"SemiAnalysis feed fetch failed for {url} ({e}).")
            continue
    # All fetches failed — fall back to stale cache if present
    if FEED_CACHE.exists():
        try:
            return json.loads(FEED_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"items": [], "source": "SemiAnalysis", "url": SEMIANALYSIS_FEEDS[0],
            "home": "https://newsletter.semianalysis.com/archive", "fetched": ""}


def _parse_rss(xml_text: str, max_items: int) -> list[dict]:
    """Minimal, dependency-free RSS <item> parser."""
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)[:max_items]:
        def grab(tag):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL)
            if not m:
                return ""
            val = m.group(1)
            val = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", val, flags=re.DOTALL)
            val = re.sub(r"<[^>]+>", "", val)  # strip nested HTML
            return html.unescape(val).strip()  # decode &#8217; etc.
        title = grab("title")
        link = grab("link")
        date = grab("pubDate")
        summary = grab("description")
        if summary:
            summary = (summary[:220] + "…") if len(summary) > 220 else summary
        try:
            date = pd.to_datetime(date).strftime("%Y-%m-%d") if date else ""
        except Exception:
            pass
        if title:
            out.append({"title": title, "link": link, "date": date, "summary": summary})
    return out


# ──────────────────────────────────────────────────────────────────────
# 2. Investment-bank AI research (user-supplied via config; no fabrication)
# ──────────────────────────────────────────────────────────────────────
def load_bank_research() -> dict:
    """Load config/ai_research_feed.json (banks + links + user summaries).
    Returns a dict with 'banks' and 'disclaimer'. Self-heals if missing."""
    if not RESEARCH_CONFIG.exists():
        _write_default_research_config()
    try:
        return json.loads(RESEARCH_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"ai_research_feed.json unreadable ({e}); regenerating default.")
        _write_default_research_config()
        return json.loads(RESEARCH_CONFIG.read_text(encoding="utf-8"))


def _write_default_research_config():
    """Seed the research feed with OFFICIAL PUBLIC hub links and clearly-labelled
    template summaries. Replace 'summary'/'stance' with your licensed report notes."""
    default = {
        "disclaimer": (
            "Template — summaries below are placeholders, not actual proprietary "
            "research. Paste notes from your LICENSED reports into each 'summary'. "
            "Links point to each firm's official public AI research hub."
        ),
        "updated": "",
        "banks": [
            {"name": "Morgan Stanley", "stance": "—",
             "url": "https://www.morganstanley.com/ideas",
             "summary": "Add your licensed MS AI/semis monthly summary here."},
            {"name": "Goldman Sachs", "stance": "—",
             "url": "https://www.goldmansachs.com/insights/topics/artificial-intelligence",
             "summary": "Add your licensed GS AI capex/monetization summary here."},
            {"name": "Bernstein", "stance": "—",
             "url": "https://www.bernsteinresearch.com/",
             "summary": "Add your licensed Bernstein semis/AI summary here."},
            {"name": "JP Morgan", "stance": "—",
             "url": "https://www.jpmorgan.com/insights",
             "summary": "Add your licensed JPM AI infrastructure summary here."},
        ],
    }
    RESEARCH_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    RESEARCH_CONFIG.write_text(json.dumps(default, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# 3. AI-sector price signals (from the app's own data — fully grounded)
# ──────────────────────────────────────────────────────────────────────
def _ret(series: pd.Series, ndays: int) -> Optional[float]:
    s = series.dropna()
    if len(s) <= ndays:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - ndays] - 1)


def _get_extra_prices(tickers: list[str], timeout: int = 15) -> pd.DataFrame:
    """Close prices for AI ETFs not in the backtest cache (DRAM/SMH/XSD),
    fetched via yfinance and cached daily. Empty DataFrame on failure."""
    tickers = [t for t in tickers if t]
    if not tickers:
        return pd.DataFrame()
    if AI_PRICE_CACHE.exists() and (time.time() - AI_PRICE_CACHE.stat().st_mtime) < AI_PRICE_TTL_SECONDS:
        try:
            df = pd.read_csv(AI_PRICE_CACHE, index_col=0, parse_dates=True)
            if all(t in df.columns for t in tickers):
                return df
        except Exception:
            pass
    try:
        import yfinance as yf
        raw = yf.download(tickers, period="2y", auto_adjust=True,
                          progress=False, threads=True)
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw["Close"]
        elif "Close" in raw.columns:  # single ticker
            raw = raw[["Close"]].rename(columns={"Close": tickers[0]})
        raw = raw.dropna(axis=1, how="all")
        if not raw.empty:
            AI_PRICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            raw.to_csv(AI_PRICE_CACHE)
        return raw
    except Exception as e:
        logger.warning(f"AI extra price fetch failed ({e}).")
        if AI_PRICE_CACHE.exists():
            try:
                return pd.read_csv(AI_PRICE_CACHE, index_col=0, parse_dates=True)
            except Exception:
                pass
    return pd.DataFrame()


def compute_ai_signals(price_data: pd.DataFrame) -> dict:
    """Per-ticker momentum / trend / relative-strength / vol for AI ETFs.
    Combines the backtest price cache with live-fetched ETFs (DRAM/SMH/XSD) and
    handles short-history tickers gracefully. Records data source + as-of date."""
    out = {"tickers": {}, "available": [], "as_of": None,
           "source": "Yahoo Finance (live) + backtest price cache"}
    if price_data is None or price_data.empty or "SPY" not in price_data.columns:
        out["sector_signal"], out["breadth"] = "N/A", "—"
        return out

    # Assemble each AI ticker's series from cache (preferred) or live fetch.
    extra = _get_extra_prices([t for t in AI_EXTRA_TICKERS if t not in price_data.columns])
    frames: dict[str, pd.Series] = {}
    for t in AI_TICKERS:
        if t in price_data.columns:
            frames[t] = price_data[t].dropna()
        elif not extra.empty and t in extra.columns:
            frames[t] = extra[t].dropna()

    spy = price_data["SPY"].dropna()
    spy_3m = _ret(spy, 63)
    last_dates = []

    for t, s in frames.items():
        if len(s) < 25:
            continue
        desc = AI_TICKERS[t]
        days = len(s)
        last_dates.append(s.index[-1])
        px = float(s.iloc[-1])
        r1, r3, r6, r12 = _ret(s, 21), _ret(s, 63), _ret(s, 126), _ret(s, 252)
        ma50 = float(s.rolling(50).mean().iloc[-1]) if days >= 50 else None
        ma200 = float(s.rolling(200).mean().iloc[-1]) if days >= 200 else None
        above50 = (px >= ma50) if ma50 is not None else None
        above200 = (px >= ma200) if ma200 is not None else None
        vol21 = float(s.pct_change().rolling(21).std().iloc[-1] * np.sqrt(252))
        rel3 = (r3 - spy_3m) if (r3 is not None and spy_3m is not None) else None

        # Momentum blend (prefer 3/6/12m; fall back to 1m for short-history ETFs)
        comps = [x for x in (r3, r6, r12) if x is not None] or [x for x in (r1,) if x is not None]
        mom = float(np.mean(comps)) if comps else 0.0
        trend_factor = 1.0 if above200 else (0.85 if (above200 is None and above50) else 0.6)
        score = 100 * np.tanh(2.5 * mom) * trend_factor

        if days < 60:
            signal = "NEW"           # insufficient history for a trend read
        elif score > 25 and (above200 or (above200 is None and above50)):
            signal = "STRONG"
        elif score < -10 or above200 is False:
            signal = "WEAK"
        else:
            signal = "NEUTRAL"

        out["tickers"][t] = {
            "desc": desc, "price": px, "ret_1m": r1, "ret_3m": r3,
            "ret_6m": r6, "ret_12m": r12, "rel_3m_vs_spy": rel3,
            "above_50ma": above50, "above_200ma": above200, "vol_21d": vol21,
            "hist_days": days, "score": round(float(score), 1), "signal": signal,
            "in_strategy": t in AI_ALLOC_TICKERS,
        }
        out["available"].append(t)

    if last_dates:
        out["as_of"] = max(last_dates).strftime("%Y-%m-%d")

    # Sector composite from full-history core gauges (SOXX & QQQ)
    core = [out["tickers"][t]["score"] for t in ("SOXX", "QQQ") if t in out["tickers"]]
    out["sector_score"] = round(float(np.mean(core)), 1) if core else 0.0
    if core:
        sc = out["sector_score"]
        out["sector_signal"] = "STRONG" if sc > 25 else ("WEAK" if sc < -10 else "NEUTRAL")
        trend_known = [t for t in out["available"] if out["tickers"][t]["above_200ma"] is not None]
        n_above = sum(out["tickers"][t]["above_200ma"] for t in trend_known)
        out["breadth"] = f"{n_above}/{len(trend_known)} above 200-day" if trend_known else "—"
    else:
        out["sector_signal"], out["breadth"] = "N/A", "—"
    return out


# ──────────────────────────────────────────────────────────────────────
# 4. Verify the AI signal against the live portfolio strategy
# ──────────────────────────────────────────────────────────────────────
def verify_with_strategy(signals: dict, weights: dict, regime: str) -> dict:
    """Cross-check: does the AI-sector signal AGREE with the strategy's current
    AI allocation? Returns {verdict, status, reasoning, ai_weight}."""
    weights = weights or {}
    ai_weight = sum(weights.get(t, 0.0) for t in AI_ALLOC_TICKERS)
    sec_sig = signals.get("sector_signal", "N/A")
    sec_score = signals.get("sector_score", 0.0)
    reasoning = []

    if sec_sig == "N/A":
        return {"verdict": "NO DATA", "status": "NO_DATA", "ai_weight": ai_weight,
                "reasoning": ["AI-sector price signals unavailable (insufficient history)."]}

    heavy = ai_weight >= 0.20
    reasoning.append(
        f"Strategy AI allocation: {ai_weight:.1%} (SOXX/QQQ/SOXL/TQQQ/SSO) in the "
        f"{regime} regime.")
    reasoning.append(
        f"AI-sector signal: {sec_sig} (composite score {sec_score:+.0f}, "
        f"breadth {signals.get('breadth','—')}).")

    if sec_sig == "STRONG" and heavy:
        status, verdict = "ALIGNED", "ALIGNED ✅"
        reasoning.append("Momentum confirms the overweight — the strategy is "
                         "positioned with the trend, not against it.")
    elif sec_sig == "STRONG" and not heavy:
        status, verdict = "UNDEREXPOSED", "UNDEREXPOSED ⚠️"
        reasoning.append("AI momentum is strong but the current (defensive) regime "
                         "caps AI exposure — upside is intentionally not chased "
                         "outside goldilocks/reflation.")
    elif sec_sig == "WEAK" and heavy:
        status, verdict = "DIVERGENCE", "DIVERGENCE ⚠️"
        reasoning.append("The book is overweight AI while momentum is deteriorating. "
                         "The 200-day trend hedge, VIX gate on TQQQ/SOXL, and the "
                         "drawdown breaker are the designed safety valves here.")
    elif sec_sig == "WEAK" and not heavy:
        status, verdict = "ALIGNED", "ALIGNED ✅"
        reasoning.append("Weak momentum and low AI exposure agree — the regime model "
                         "has already rotated the book defensive.")
    else:  # NEUTRAL
        status, verdict = "NEUTRAL", "NEUTRAL ➖"
        reasoning.append("Mixed momentum; allocation is reasonable. No strong "
                         "agree/disagree signal versus the strategy.")
    return {"verdict": verdict, "status": status, "ai_weight": ai_weight,
            "reasoning": reasoning}


# ──────────────────────────────────────────────────────────────────────
# 5. Generate the narrative report + assemble everything
# ──────────────────────────────────────────────────────────────────────
def _fmt(x, pct=True):
    if x is None:
        return "—"
    return f"{x:+.1%}" if pct else f"{x:.1f}"


def generate_report(signals: dict, verification: dict, regime: str,
                    semi: dict, bank: dict) -> list[str]:
    """Deterministic narrative built only from the computed numbers + feed counts."""
    lines = []
    if signals.get("sector_signal", "N/A") == "N/A":
        return ["AI Trend Intelligence: insufficient price history to compute signals."]
    soxx = signals["tickers"].get("SOXX", {})
    qqq = signals["tickers"].get("QQQ", {})
    dram = signals["tickers"].get("DRAM", {})
    lines.append(
        f"AI-sector composite is **{signals['sector_signal']}** "
        f"(score {signals['sector_score']:+.0f}, {signals.get('breadth','—')}).")
    if soxx:
        lines.append(
            f"Semiconductors (SOXX): 3m {_fmt(soxx.get('ret_3m'))}, "
            f"12m {_fmt(soxx.get('ret_12m'))}, "
            f"{'above' if soxx.get('above_200ma') else 'below'} 200-day, "
            f"rel-strength vs SPY (3m) {_fmt(soxx.get('rel_3m_vs_spy'))}.")
    if dram:
        lines.append(
            f"AI memory/HBM (DRAM): 1m {_fmt(dram.get('ret_1m'))}, "
            f"3m {_fmt(dram.get('ret_3m'))} "
            f"(signal {dram.get('signal')}, {dram.get('hist_days')}d history).")
    if qqq:
        lines.append(
            f"AI mega-cap (QQQ): 3m {_fmt(qqq.get('ret_3m'))}, "
            f"12m {_fmt(qqq.get('ret_12m'))}, "
            f"{'above' if qqq.get('above_200ma') else 'below'} 200-day.")
    lines.append(
        f"Strategy verification: **{verification['verdict']}** — "
        + verification["reasoning"][-1])
    n_items = len(semi.get("items", []))
    lines.append(
        f"Inputs: {n_items} {semi.get('source','SemiAnalysis')} headlines + "
        f"{len(bank.get('banks', []))} bank research entries. "
        f"Signals as of {signals.get('as_of','—')}; feed fetched {semi.get('fetched','—')}.")
    return lines


def build_ai_trend_intelligence(price_data: pd.DataFrame, regime: str,
                                weights: dict) -> dict:
    """Top-level entry point used by the dashboard at startup."""
    try:
        semi = fetch_semianalysis()
    except Exception as e:
        logger.warning(f"SemiAnalysis fetch error: {e}")
        semi = {"items": [], "source": "SemiAnalysis", "url": "", "fetched": ""}
    bank = load_bank_research()
    signals = compute_ai_signals(price_data)
    verification = verify_with_strategy(signals, weights, regime)
    report = generate_report(signals, verification, regime, semi, bank)

    # Market Sentiment Consensus (Tiers 1-2) — multi-source FinBERT news sentiment
    # across Mag7 / semis / HBM-memory + a CapEx-pulse leading indicator. Present-
    # tense DISPLAY ONLY; never fed into the backtest or weights.
    market_sentiment = {}
    try:
        from src.strategist.news_sentiment import analyze_news
        market_sentiment = analyze_news()
    except Exception as e:
        logger.warning(f"Market sentiment unavailable: {e}")

    # Tier 2 hard data — hyperscaler CapEx from SEC EDGAR (next to the commentary).
    edgar = {}
    try:
        from src.strategist.edgar_capex import capex_pulse
        edgar = capex_pulse()
    except Exception as e:
        logger.warning(f"EDGAR capex unavailable: {e}")

    # Tier 3 (experimental) — Reddit retail attention (VADER, display-only).
    reddit = {}
    try:
        from src.strategist.reddit_sentiment import analyze_reddit
        reddit = analyze_reddit()
    except Exception as e:
        logger.warning(f"Reddit sentiment unavailable: {e}")

    return {
        "signals": signals,
        "verification": verification,
        "report": report,
        "semianalysis": semi,
        "bank_research": bank,
        "market_sentiment": market_sentiment,
        "edgar_capex": edgar,
        "reddit": reddit,
        "generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "price_as_of": signals.get("as_of"),
    }
