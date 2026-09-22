"""
src/strategist/sentiment_analyzer.py
====================================
AI-sector news sentiment ("Market Sentiment Consensus").

Scores news headlines (SemiAnalysis feed + any licensed bank summaries) to a
[-1 bearish, +1 bullish] sentiment, aggregated by week.

Engine:
  • Primary  — FinBERT (ProsusAI/finbert) via transformers, when torch is
               available (baked into the production image).
  • Fallback — a Loughran-McDonald-style finance lexicon (no heavy deps), used
               for local dev and if the model can't load. The output records
               which engine ran, so the UI never overstates the method.

IMPORTANT: this is a PRESENT-TENSE dashboard indicator only. It is deliberately
NOT fed into the backtest or portfolio weights — there is no 20-year point-in-time
news corpus to validate a sentiment overlay without severe survivorship bias.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger("sentiment")

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "data" / "cache" / "sentiment.json"
TTL_SECONDS = 7 * 24 * 3600  # weekly refresh

# ── Loughran-McDonald-style finance sentiment lexicon (compact subset) ──────
_POS = {
    "beat", "beats", "strong", "surge", "surges", "surged", "record", "growth",
    "rally", "rallies", "gain", "gains", "gained", "boom", "bullish", "upgrade",
    "upgraded", "outperform", "expansion", "expand", "expands", "robust", "soar",
    "soars", "soared", "rise", "rises", "rising", "demand", "ramp", "ramps",
    "accelerate", "accelerating", "breakthrough", "lead", "leads", "leading",
    "win", "wins", "profitable", "profit", "profits", "exceed", "exceeds",
    "optimistic", "momentum", "tailwind", "resilient", "dominant", "dominate",
}
_NEG = {
    "miss", "misses", "missed", "weak", "weakness", "slump", "slumps", "plunge",
    "plunges", "plunged", "crash", "crashes", "decline", "declines", "declining",
    "fall", "falls", "falling", "drop", "drops", "cut", "cuts", "downgrade",
    "downgraded", "underperform", "recession", "slowdown", "shortage", "glut",
    "oversupply", "cancel", "canceled", "cancelled", "delay", "delays", "delayed",
    "loss", "losses", "bearish", "warn", "warns", "warning", "risk", "risks",
    "headwind", "concern", "concerns", "fear", "fears", "bubble", "collapse",
    "constraint", "constraints", "bottleneck", "halt", "halts", "layoff", "layoffs",
}
_NEGATORS = {"not", "no", "never", "without", "stop", "stops", "stop saying"}


def _lexicon_score(text: str) -> float:
    """Return a [-1, 1] sentiment from finance word counts (simple negation-aware)."""
    words = re.findall(r"[a-zA-Z']+", (text or "").lower())
    pos = neg = 0
    for i, w in enumerate(words):
        flip = i > 0 and words[i - 1] in _NEGATORS
        if w in _POS:
            neg += 1 if flip else 0
            pos += 0 if flip else 1
        elif w in _NEG:
            pos += 1 if flip else 0
            neg += 0 if flip else 1
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


# ── FinBERT (lazy singleton) ────────────────────────────────────────────────
_FINBERT = None
_FINBERT_TRIED = False


def _get_finbert():
    global _FINBERT, _FINBERT_TRIED
    if _FINBERT_TRIED:
        return _FINBERT
    _FINBERT_TRIED = True
    # Free/starter Render instances are 512 MB. Loading FinBERT OOMs the process.
    # Unset or "1" keeps the previous behavior (try the model, lexicon on failure).
    if os.getenv("FINBERT_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        logger.info("FINBERT_ENABLED=0; using finance-lexicon fallback.")
        _FINBERT = None
        return None
    try:
        from transformers import pipeline  # heavy import, guarded
        _FINBERT = pipeline("text-classification", model="ProsusAI/finbert",
                            top_k=None, truncation=True, max_length=256)
        logger.info("FinBERT loaded (ProsusAI/finbert).")
    except Exception as e:
        logger.warning(f"FinBERT unavailable ({e}); using finance-lexicon fallback.")
        _FINBERT = None
    return _FINBERT


def _finbert_scores(texts: list[str]) -> Optional[list[float]]:
    clf = _get_finbert()
    if clf is None:
        return None
    try:
        results = clf([t[:256] for t in texts])
        scores = []
        for r in results:
            d = {x["label"].lower(): x["score"] for x in r}
            scores.append(float(d.get("positive", 0.0) - d.get("negative", 0.0)))
        return scores
    except Exception as e:
        logger.warning(f"FinBERT inference failed ({e}); falling back to lexicon.")
        return None


# ── Public API ──────────────────────────────────────────────────────────────
def _label(score: float) -> str:
    return "Bullish" if score > 0.15 else ("Bearish" if score < -0.15 else "Neutral")


def score_texts(texts: list[str]) -> tuple[list[float], str]:
    """Score a batch of texts → ([-1..1] scores, engine_name). FinBERT if
    available, else the finance lexicon. Used by the multi-source news engine."""
    if not texts:
        return [], "none"
    fb = _finbert_scores(texts)
    if fb is not None:
        return fb, "FinBERT"
    return [_lexicon_score(t) for t in texts], "finance-lexicon"


def analyze(items: list[dict]) -> dict:
    """Score a list of {title, summary, date} headlines → sentiment consensus.
    Returns engine, overall score/label, per-week series, and scored items."""
    if not items:
        return {"engine": "none", "score": 0.0, "label": "Neutral",
                "n": 0, "by_week": [], "items": []}

    texts = [f"{it.get('title','')}. {it.get('summary','')}".strip() for it in items]
    fb = _finbert_scores(texts)
    engine = "FinBERT" if fb is not None else "finance-lexicon"
    scores = fb if fb is not None else [_lexicon_score(t) for t in texts]

    scored = []
    for it, s in zip(items, scores):
        scored.append({"title": it.get("title", ""), "date": it.get("date", ""),
                       "score": round(float(s), 3), "label": _label(s)})

    overall = float(sum(scores) / len(scores)) if scores else 0.0

    # Weekly aggregation (ISO week of each item's date)
    df = pd.DataFrame({"date": [it.get("date", "") for it in items], "score": scores})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    by_week = []
    if not df.empty:
        wk = df.set_index("date").resample("W").mean(numeric_only=True).dropna()
        by_week = [{"week": d.strftime("%Y-%m-%d"), "score": round(float(v), 3),
                    "label": _label(v)} for d, v in wk["score"].items()][-8:]

    return {"engine": engine, "score": round(overall, 3), "label": _label(overall),
            "n": len(items), "by_week": by_week, "items": scored}


def get_market_sentiment(items: list[dict], use_cache: bool = True) -> dict:
    """Weekly-cached sentiment consensus. Falls back to recompute on cache miss."""
    if use_cache and CACHE.exists():
        if (time.time() - CACHE.stat().st_mtime) < TTL_SECONDS:
            try:
                return json.loads(CACHE.read_text(encoding="utf-8"))
            except Exception:
                pass
    result = analyze(items)
    result["computed"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass
    return result
