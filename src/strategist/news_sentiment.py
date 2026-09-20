"""
src/strategist/news_sentiment.py
================================
Multi-source AI-sector news sentiment ("Market Sentiment Consensus", Tiers 1-2).

Tier 1 — Financial news sentiment (weekly): per-ticker Google News headlines for
         Mag7 + semiconductor + memory/HBM names, FinBERT-scored, rolled up into
         theme gauges (Mag7 / Semis / HBM-Memory) + per-ticker breakdown.
Tier 2 — CapEx / datacenter pulse: the subset of hyperscaler headlines mentioning
         capex / data-center / GPU / HBM / backlog — a leading read on AI-semis
         demand (Gemini's insight, scoped to free public news).

DISPLAY-ONLY. This never feeds the backtest or portfolio weights — there is no
point-in-time historical news archive to validate a trading rule on. Cached weekly.
Scoring reuses the FinBERT/lexicon engine in sentiment_analyzer.
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger("news_sentiment")

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "data" / "cache" / "news_sentiment.json"
TTL_SECONDS = 7 * 24 * 3600  # weekly

# ticker -> (display name, [themes], is_hyperscaler-for-capex)
WATCHLIST = {
    "NVDA":  ("Nvidia", ["Mag7", "Semis"], True),
    "MSFT":  ("Microsoft", ["Mag7"], True),
    "GOOGL": ("Alphabet", ["Mag7"], True),
    "AMZN":  ("Amazon", ["Mag7"], True),
    "META":  ("Meta", ["Mag7"], True),
    "AVGO":  ("Broadcom", ["Semis"], False),
    "TSM":   ("TSMC", ["Semis"], False),
    "ASML":  ("ASML", ["Semis"], False),
    "AMD":   ("AMD", ["Semis"], False),
    "MU":    ("Micron", ["HBM/Memory"], False),
}
THEME_ORDER = ["Mag7", "Semis", "HBM/Memory"]
CAPEX_RE = re.compile(
    r"capex|capital expenditure|data ?cent|gpu|hbm|backlog|capacity|ai spend|"
    r"hyperscal|infrastructure|build-?out", re.I)
# Dedicated Tier-2 queries so the CapEx pulse has direct, on-topic input.
CAPEX_QUERIES = [
    "hyperscaler AI data center capex spending",
    "Nvidia HBM data center GPU demand",
    "AI capital expenditure semiconductors 2026",
]


def _label(score: float) -> str:
    return "Bullish" if score > 0.15 else ("Bearish" if score < -0.15 else "Neutral")


def _google_news(query: str, n: int = 4, timeout: int = 8) -> list[dict]:
    """Fetch the latest Google News RSS items for a query."""
    import requests
    url = ("https://news.google.com/rss/search?q="
           + requests.utils.quote(query) + "&hl=en-US&gl=US&ceid=US:en")
    out = []
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        for block in re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)[:n]:
            def g(tag):
                m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL)
                if not m:
                    return ""
                v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.DOTALL)
                v = re.sub(r"<[^>]+>", "", v)
                return _html.unescape(v).strip()
            title, date, link, src = g("title"), g("pubDate"), g("link"), g("source")
            try:
                date = pd.to_datetime(date).strftime("%Y-%m-%d") if date else ""
            except Exception:
                pass
            if title:
                out.append({"title": title, "date": date, "link": link, "source": src})
    except Exception as e:
        logger.warning(f"Google News fetch failed for '{query}' ({e}).")
    return out


def _fetch_all(per_ticker: int = 4) -> list[dict]:
    """One Google News query per watchlist ticker; tag each headline with ticker."""
    headlines = []
    seen = set()
    for tkr, (name, themes, _) in WATCHLIST.items():
        for it in _google_news(f"{name} {tkr} stock", n=per_ticker):
            key = it["title"][:80].lower()
            if key in seen:
                continue
            seen.add(key)
            it.update({"ticker": tkr, "name": name, "themes": themes, "is_capex": False})
            headlines.append(it)
    # Tier 2 — dedicated CapEx / datacenter queries (tagged is_capex)
    for q in CAPEX_QUERIES:
        for it in _google_news(q, n=4):
            key = it["title"][:80].lower()
            if key in seen:
                continue
            seen.add(key)
            it.update({"ticker": "CapEx", "name": "CapEx", "themes": ["Semis"], "is_capex": True})
            headlines.append(it)
    return headlines


def analyze_news(use_cache: bool = True) -> dict:
    """Fetch, FinBERT-score and aggregate per theme / per ticker / CapEx pulse."""
    if use_cache and CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < TTL_SECONDS:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass

    headlines = _fetch_all()
    if not headlines:
        return {"engine": "none", "n": 0, "overall": {"score": 0.0, "label": "Neutral"},
                "themes": [], "tickers": [], "capex": {"score": 0.0, "label": "Neutral", "n": 0},
                "headlines": [], "computed": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}

    from src.strategist.sentiment_analyzer import score_texts
    scores, engine = score_texts([h["title"] for h in headlines])
    for h, s in zip(headlines, scores):
        h["score"] = round(float(s), 3)
        h["label"] = _label(s)

    def agg(items):
        vals = [h["score"] for h in items]
        m = sum(vals) / len(vals) if vals else 0.0
        return round(m, 3), _label(m), len(vals)

    overall_s, overall_l, _ = agg(headlines)
    themes = []
    for th in THEME_ORDER:
        members = [h for h in headlines if th in h["themes"]]
        if members:
            s, l, n = agg(members)
            themes.append({"name": th, "score": s, "label": l, "n": n})

    by_ticker = []
    for tkr, (name, _, _) in WATCHLIST.items():
        members = [h for h in headlines if h["ticker"] == tkr]
        if members:
            s, l, n = agg(members)
            by_ticker.append({"ticker": tkr, "name": name, "score": s, "label": l, "n": n})
    by_ticker.sort(key=lambda x: x["score"])

    # Tier 2 — CapEx pulse: dedicated capex queries + hyperscaler headlines that
    # mention capex / data-center / HBM / GPU / backlog.
    hyper = {t for t, (_, _, cap) in WATCHLIST.items() if cap}
    capex_items = [h for h in headlines
                   if h.get("is_capex") or (h["ticker"] in hyper and CAPEX_RE.search(h["title"]))]
    cs, cl, cn = agg(capex_items)

    top = sorted(headlines, key=lambda h: abs(h["score"]), reverse=True)[:6]
    result = {
        "engine": engine, "n": len(headlines),
        "overall": {"score": overall_s, "label": overall_l},
        "themes": themes, "tickers": by_ticker,
        "capex": {"score": cs, "label": cl, "n": cn},
        "headlines": [{"ticker": h["ticker"], "title": h["title"][:90], "date": h["date"],
                       "score": h["score"], "label": h["label"], "source": h.get("source", ""),
                       "link": h.get("link", "")} for h in top],
        "computed": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    }
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass
    return result
