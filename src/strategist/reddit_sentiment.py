"""
src/strategist/reddit_sentiment.py
==================================
Reddit "retail attention" panel (Tier 3 — EXPERIMENTAL, display-only).

Pulls recent posts from r/wallstreetbets, r/stocks, r/semiconductors via Reddit's
public RSS (the .json API is OAuth-gated / 403s; RSS still works), counts ticker
mentions (= attention), and scores the text with VADER — a SOCIAL-media-tuned
sentiment model (emojis, slang, ALL-CAPS, intensifiers), NOT FinBERT, which is
mismatched to Reddit's register. Falls back to a finance lexicon if VADER is absent.

This is a contrarian ATTENTION indicator, not a clean directional signal: a spike
in mentions + extreme bullishness is a hype flag, often a local-top tell. It is
DISPLAY-ONLY and never feeds the backtest, weights, or the volatility target.
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger("reddit_sentiment")

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "data" / "cache" / "reddit_sentiment.json"
TTL_SECONDS = 12 * 3600  # Reddit moves fast; refresh twice daily

SUBS = ["wallstreetbets", "stocks", "semiconductors"]
# AI / semiconductor names + the strategy's traded ETFs
TICKERS = ["NVDA", "AMD", "MU", "TSM", "AVGO", "ASML", "SMH", "SOXX", "SOXL",
           "TQQQ", "MSFT", "GOOGL", "META", "AMZN"]


def _reddit_rss(sub: str, n: int = 40, timeout: int = 8) -> list[dict]:
    """Fetch a subreddit's hot RSS feed → [{title, text}]."""
    import requests
    url = f"https://www.reddit.com/r/{sub}/hot.rss?limit={n}"
    out = []
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (ETF-Regime-Strategist research)"})
        r.raise_for_status()
        for block in re.findall(r"<entry>(.*?)</entry>", r.text, re.DOTALL):
            m = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
            c = re.search(r"<content[^>]*>(.*?)</content>", block, re.DOTALL)
            title = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
            body = _html.unescape(re.sub(r"<[^>]+>", "", c.group(1))).strip()[:400] if c else ""
            if title:
                out.append({"sub": sub, "title": title, "text": f"{title}. {body}"})
    except Exception as e:
        logger.warning(f"Reddit RSS failed for r/{sub} ({e}).")
    return out


# ── Social-tuned scorer: VADER (preferred), finance-lexicon fallback ──────────
_VADER = None
_VADER_TRIED = False


def _get_vader():
    global _VADER, _VADER_TRIED
    if _VADER_TRIED:
        return _VADER
    _VADER_TRIED = True
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _VADER = SentimentIntensityAnalyzer()
    except Exception as e:
        logger.warning(f"VADER unavailable ({e}); using finance-lexicon fallback.")
        _VADER = None
    return _VADER


def _score(text: str) -> float:
    v = _get_vader()
    if v is not None:
        return float(v.polarity_scores(text)["compound"])  # already [-1, 1]
    from src.strategist.sentiment_analyzer import _lexicon_score
    return _lexicon_score(text)


def _label(s: float) -> str:
    return "Bullish" if s > 0.15 else ("Bearish" if s < -0.15 else "Neutral")


def analyze_reddit(use_cache: bool = True) -> dict:
    """Mention counts (attention) + VADER sentiment per ticker, with a hype flag."""
    if use_cache and CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < TTL_SECONDS:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass

    posts = []
    for i, sub in enumerate(SUBS):
        if i:
            time.sleep(1.5)  # Reddit unauth ≈ 1 req / 2s — avoid 429 bursts
        posts.extend(_reddit_rss(sub))
    engine = "VADER (social)" if _get_vader() is not None else "finance-lexicon"

    if not posts:
        return {"engine": engine, "available": False, "n_posts": 0, "tickers": [],
                "overall": {"score": 0.0, "label": "Neutral"}, "hype": [],
                "computed": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}

    # Score every post once
    for p in posts:
        p["score"] = _score(p["text"])

    rows = []
    for tkr in TICKERS:
        pat = re.compile(rf"(?<![A-Za-z])\$?{re.escape(tkr)}(?![A-Za-z])")
        hits = [p for p in posts if pat.search(p["title"]) or pat.search(p["text"])]
        if not hits:
            continue
        avg = sum(p["score"] for p in hits) / len(hits)
        rows.append({"ticker": tkr, "mentions": len(hits),
                     "score": round(avg, 3), "label": _label(avg)})
    rows.sort(key=lambda x: x["mentions"], reverse=True)

    # Overall = mention-weighted sentiment across tracked tickers
    tot_m = sum(r["mentions"] for r in rows)
    overall = (sum(r["score"] * r["mentions"] for r in rows) / tot_m) if tot_m else 0.0

    # Hype flag = high attention + extreme bullishness (contrarian top-tell)
    max_m = max((r["mentions"] for r in rows), default=0)
    hype = [r["ticker"] for r in rows
            if r["mentions"] >= max(3, max_m * 0.5) and r["score"] > 0.5]

    result = {
        "engine": engine, "available": True, "n_posts": len(posts),
        "subs": SUBS, "tickers": rows[:10],
        "overall": {"score": round(overall, 3), "label": _label(overall)},
        "hype": hype, "computed": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    }
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass
    return result
