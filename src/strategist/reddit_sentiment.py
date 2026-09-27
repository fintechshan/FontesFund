"""
src/strategist/reddit_sentiment.py
==================================
Reddit retail-attention signal (Tier 3 — EXPERIMENTAL).

Pulls recent posts from retail-flow subreddits, extracts tickers (cashtags,
curated bare symbols, company aliases), and scores the text with VADER.
The ranked output is a stock-pick *watchlist* (``retail_attention``). It is
attached to the AI-trend payload and to ``StrategyAdvisor`` recommendations
as an overlay. It never changes ETF regime weights, the Merrill/GS clock,
or the backtest.

Data source
-----------
* Preferred: Reddit OAuth (script or app-only) when ``REDDIT_CLIENT_ID`` and
  ``REDDIT_CLIENT_SECRET`` are set. Listings include upvote score and
  comment counts. Optional ``REDDIT_USERNAME`` / ``REDDIT_PASSWORD`` select
  the script (password) grant; otherwise client-credentials is used.
* Fallback: public Atom RSS (hot + new). RSS has no upvote score. Up to two
  daily-megathread comment feeds are pulled so ticker talk inside the daily
  thread is not dropped on the floor.

Offline
-------
``aggregate_posts`` is pure. ``python -m src.strategist.reddit_sentiment
--fixture tests/fixtures/reddit_posts.json`` runs it with no network.
``--live`` forces a fresh pull (credentials optional; RSS works without them).
"""
from __future__ import annotations

import html as _html
import json
import logging
import math
import os
import re
import statistics
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger("reddit_sentiment")

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "data" / "cache" / "reddit_sentiment.json"
BASELINE = ROOT / "data" / "cache" / "reddit_attention_baseline.json"
TTL_SECONDS = 12 * 3600
VELOCITY_WINDOW_SECONDS = 12 * 3600
BASELINE_MIN_AGE_SECONDS = 30 * 60
CACHE_MAX_STALE_SECONDS = 48 * 3600
SCHEMA_VERSION = 2

# Public RSS is unauthenticated and easy to 429. Stay near one request / second.
RSS_MIN_INTERVAL = 0.9
OAUTH_MIN_INTERVAL = 0.35
HTTP_TIMEOUT = 6

# High-signal retail subs. Hot+new on the fast ones; hot-only on the slower
# ones so a cold container start stays inside a short fetch budget.
RSS_FEEDS: list[tuple[str, str]] = [
    ("wallstreetbets", "hot"),
    ("wallstreetbets", "new"),
    ("stocks", "hot"),
    ("stocks", "new"),
    ("options", "hot"),
    ("semiconductors", "hot"),
    ("semiconductors", "new"),
    ("investing", "hot"),
]
# OAuth quota (about 60 req/min) can afford a wider corpus.
OAUTH_FEEDS: list[tuple[str, str]] = RSS_FEEDS + [
    ("wallstreetbets", "rising"),
    ("stocks", "rising"),
    ("options", "new"),
    ("StockMarket", "hot"),
    ("StockMarket", "new"),
    ("technology", "hot"),
    ("AMD_Stock", "new"),
    ("NVDA_Stock", "new"),
]
MAX_COMMENT_FEEDS = 2

# ── Score formula (also embedded on every payload as ``formula``) ───────────
# sentiment_mean is the engagement-weighted mean of per-ticker VADER compounds.
# weight_i = 1 + UPVOTE_COEF*min(ln(1+upvotes_i), LOG_CAP)
#              + COMMENT_COEF*min(ln(1+comments_i), LOG_CAP)
# attention  = ln(1+unique_posts)
#              * (1 + UPVOTE_COEF*min(ln(1+upvote_sum), LOG_CAP))
#              * (1 + COMMENT_COEF*min(ln(1+comment_sum), LOG_CAP))
# velocity   = snapshot vs the prior ~12h baseline, blended 0.6/0.4 with the
#              in-pull burst (newer half vs older half) when both exist.
#              snapshot = (unique_now - unique_prior) / max(unique_prior, 1)
# velocity_factor = clip(1 + VELOCITY_COEF*velocity, LO, HI); 1.0 if unknown
# confidence = 1 - exp(-unique_posts / CONF_SCALE)
# mega_factor = MEGA_FACTOR for MEGA_CAPS unless velocity >= MEGA_VEL_RELAX
# composite  = attention * (SENT_FLOOR + SENT_SLOPE*|sentiment_mean|)
#              * velocity_factor * mega_factor * confidence
# pick_score = composite * sign(sentiment_mean)
SENT_FLOOR = 0.25
SENT_SLOPE = 0.75
UPVOTE_COEF = 0.15
COMMENT_COEF = 0.05
LOG_CAP = 6.0
VELOCITY_COEF = 0.50
VEL_FACTOR_LO = 0.50
VEL_FACTOR_HI = 2.50
CONF_SCALE = 3.0
MEGA_FACTOR = 0.70
MEGA_VEL_RELAX = 0.75
WATCH_COMPOSITE = 0.35
WATCH_CONFIDENCE = 0.40
HYPE_MIN_POSTS = 6
HYPE_MEAN = 0.50
HYPE_PCT_BULL = 0.65
HYPE_MIN_VELOCITY = 0.50
MIN_UNIQUE_POSTS = 2
SINGLE_HIT_ABS_SENT = 0.35
LABEL_THRESHOLD = 0.15
MENTION_CAP_PER_POST = 5

# Mega-caps always occupy retail threads. Dampen them unless attention is
# actually accelerating, so a quiet MSFT mention cannot outrank a smaller name.
MEGA_CAPS = frozenset({
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "NVDA",
})

# ETFs are context, not single-stock picks. Indices are not equities.
ETFS = frozenset({
    "SMH", "SOXX", "SOXL", "TQQQ", "SQQQ", "QQQ", "SPY", "IWM", "TNA",
    "UVXY", "SPYI", "QQQI",
})
INDICES = frozenset({"SPX", "VIX", "NDX", "DJI", "DXY", "TNX", "VVIX"})

# Curated bare-ticker whitelist. The long tail still enters via $CASHTAG.
# Symbols that are also English words use mode "upper" so "arm" / "meta" /
# "snow" do not count unless written as ARM / META / SNOW or as a cashtag.
# "any" = case-insensitive; "upper" = ticker must be written in uppercase.
BARE_TICKERS: dict[str, str] = {
    "NVDA": "any", "AMD": "any", "MU": "any", "TSM": "any", "AVGO": "any",
    "ASML": "any", "AMAT": "any", "LRCX": "any", "KLAC": "any", "SMCI": "any",
    "INTC": "any", "QCOM": "any", "MRVL": "any", "AMKR": "any", "WDC": "any",
    "STX": "any", "ARM": "upper", "AAPL": "any", "MSFT": "any", "GOOGL": "any",
    "GOOG": "any", "META": "upper", "AMZN": "any", "TSLA": "any", "PLTR": "any",
    "SOFI": "any", "HOOD": "any", "COIN": "any", "MSTR": "any", "GME": "any",
    "AMC": "any", "RIVN": "any", "NIO": "any", "BABA": "any", "NFLX": "upper",
    "CRM": "any", "ORCL": "any", "SNOW": "upper", "NET": "upper", "CRWD": "any",
    "PANW": "any", "UBER": "any", "DELL": "any", "ANET": "any", "VRT": "any",
    "CEG": "any", "APP": "upper", "IONQ": "any", "RDDT": "any", "SMH": "any",
    "SOXX": "any", "SOXL": "any", "TQQQ": "any", "QQQ": "any", "SPY": "any",
    "IWM": "any",
}

# Company names that retail writes instead of the symbol. Do not alias the
# symbol itself (that would double-count the bare regex).
ALIASES: dict[str, str] = {
    "nvidia": "NVDA",
    "micron": "MU",
    "advanced micro devices": "AMD",
    "taiwan semiconductor": "TSM",
    "tsmc": "TSM",
    "broadcom": "AVGO",
    "super micro": "SMCI",
    "supermicro": "SMCI",
    "palantir": "PLTR",
    "tesla": "TSLA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "facebook": "META",
    "amazon": "AMZN",
    "gamestop": "GME",
    "coinbase": "COIN",
    "microstrategy": "MSTR",
    "robinhood": "HOOD",
    "netflix": "NFLX",
    "snowflake": "SNOW",
    "intel": "INTC",
    "qualcomm": "QCOM",
    "asml holding": "ASML",
}

# Cashtags that are Reddit slang / macro acronyms, not equities.
CASHTAG_BLOCK = frozenset({
    "DD", "YOLO", "FOMO", "ATH", "IMO", "TLDR", "OP", "EDIT", "USA", "USD",
    "IPO", "CEO", "CFO", "EPS", "RSI", "EOD", "OTC", "NYSE", "API", "FAQ",
    "PSA", "LOL", "WSB", "MOD", "GDP", "CPI", "FED", "SEC", "NFA", "DYOR",
    "HODL", "FUD", "MOON", "DIP", "BAG", "RH", "ETF", "IRS", "UK", "EU",
    "US", "PM", "AH", "TA", "IV", "OTM", "ITM", "DTE", "EOW", "BUY", "SELL",
    "HOLD", "CALL", "PUT", "CALLS", "PUTS", "GAN", "WSB", "MODS",
})

_CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9])\$([A-Za-z]{1,5})(?![A-Za-z])")
_MEGATHREAD_RE = re.compile(
    r"daily discussion|what are your moves|weekend discussion|weekly discussion|"
    r"megathread|daily thread|earnings thread|daily general",
    re.I,
)
_BOILER_RE = re.compile(
    r"submitted by\s+/u/\S+|\[link\]|\[comments\]|https?://\S+|/?u/[A-Za-z0-9_-]+",
    re.I,
)
_BARE_RE: dict[str, re.Pattern[str]] = {}
_ALIAS_RE: dict[str, re.Pattern[str]] = {}


def formula_text() -> str:
    """Human-readable composite used by the watchlist and the analysis note."""
    megas = ", ".join(sorted(MEGA_CAPS))
    return (
        f"sentiment_mean = engagement-weighted mean of per-ticker VADER compounds "
        f"(weight = 1 + {UPVOTE_COEF}*min(ln(1+upvotes), {LOG_CAP}) "
        f"+ {COMMENT_COEF}*min(ln(1+comments), {LOG_CAP}); RSS upvotes/comments are 0). "
        f"attention = ln(1+unique_posts) "
        f"* (1+{UPVOTE_COEF}*min(ln(1+upvote_sum), {LOG_CAP})) "
        f"* (1+{COMMENT_COEF}*min(ln(1+comment_sum), {LOG_CAP})). "
        f"velocity blends snapshot vs the prior ~12h baseline (weight 0.6) with "
        f"in-pull burst, newer half vs older half (weight 0.4), when both exist; "
        f"snapshot = (unique_now - unique_prior) / max(unique_prior, 1). "
        f"velocity_factor = clip(1 + {VELOCITY_COEF}*velocity, {VEL_FACTOR_LO}, {VEL_FACTOR_HI}) "
        f"and is 1 when velocity is unknown. "
        f"confidence = 1 - exp(-unique_posts / {CONF_SCALE}). "
        f"mega_factor = {MEGA_FACTOR} for [{megas}] unless velocity >= {MEGA_VEL_RELAX}, else 1. "
        f"composite = attention * ({SENT_FLOOR} + {SENT_SLOPE}*|sentiment_mean|) "
        f"* velocity_factor * mega_factor * confidence. "
        f"pick_score = composite * sign(sentiment_mean). "
        f"Rank by composite. "
        f"Include a name when unique_posts >= {MIN_UNIQUE_POSTS}, or when 1 post "
        f"has a cashtag or alias and |sentiment_mean| >= {SINGLE_HIT_ABS_SENT}. "
        f"watch_long: sentiment_mean > {LABEL_THRESHOLD}, composite >= {WATCH_COMPOSITE}, "
        f"confidence >= {WATCH_CONFIDENCE}, and not hype. "
        f"watch_avoid is the bearish mirror. "
        f"hype_caution (contrarian, not a buy): unique_posts >= {HYPE_MIN_POSTS}, "
        f"sentiment_mean > {HYPE_MEAN}, pct_bullish >= {HYPE_PCT_BULL}, "
        f"velocity >= {HYPE_MIN_VELOCITY}. "
        f"ETF regime weights are never modified."
    )


def _bare_re(tkr: str, mode: str) -> re.Pattern[str]:
    key = f"{mode}:{tkr}"
    pat = _BARE_RE.get(key)
    if pat is None:
        flags = 0 if mode == "upper" else re.I
        pat = re.compile(rf"(?<![A-Za-z$]){re.escape(tkr)}(?![A-Za-z])", flags)
        _BARE_RE[key] = pat
    return pat


def _alias_re(alias: str) -> re.Pattern[str]:
    pat = _ALIAS_RE.get(alias)
    if pat is None:
        pat = re.compile(rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])", re.I)
        _ALIAS_RE[alias] = pat
    return pat


def extract_ticker_hits(text: str) -> dict[str, dict]:
    """Map ticker -> {mentions, cashtag, alias, bare} inside one text.

    Cashtags (``$MU``) are the high-precision path and are not limited to the
    whitelist. Bare symbols are whitelist-only so ordinary words (IT, FOR,
    ALL, AI) are not treated as tickers. Aliases map company names to symbols.
    """
    hits: dict[str, dict] = {}

    def add(tkr: str, n: int, **flags: bool) -> None:
        if n <= 0 or not tkr:
            return
        row = hits.setdefault(tkr, {
            "mentions": 0, "cashtag": False, "alias": False, "bare": False,
        })
        row["mentions"] += n
        for key, val in flags.items():
            if val:
                row[key] = True

    raw = text or ""
    for match in _CASHTAG_RE.finditer(raw):
        sym = match.group(1).upper()
        if sym in CASHTAG_BLOCK or len(sym) < 1:
            continue
        add(sym, 1, cashtag=True)

    for tkr, mode in BARE_TICKERS.items():
        add(tkr, len(_bare_re(tkr, mode).findall(raw)), bare=True)

    for alias, tkr in ALIASES.items():
        add(tkr, len(_alias_re(alias).findall(raw)), alias=True)

    for row in hits.values():
        row["mentions"] = min(int(row["mentions"]), MENTION_CAP_PER_POST)
    return hits


def _kind(tkr: str) -> str:
    if tkr in ETFS:
        return "etf"
    if tkr in INDICES:
        return "index"
    return "stock"


def _label(score: float) -> str:
    if score > LABEL_THRESHOLD:
        return "Bullish"
    if score < -LABEL_THRESHOLD:
        return "Bearish"
    return "Neutral"


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _engagement_weight(upvotes: int, comments: int) -> float:
    up = max(int(upvotes or 0), 0)
    cm = max(int(comments or 0), 0)
    return (
        1.0
        + UPVOTE_COEF * min(math.log1p(up), LOG_CAP)
        + COMMENT_COEF * min(math.log1p(cm), LOG_CAP)
    )


def _clean_text(title: str, body: str) -> str:
    body_c = _BOILER_RE.sub(" ", body or "")
    body_c = re.sub(r"\s+", " ", body_c).strip()
    title_c = re.sub(r"\s+", " ", (title or "")).strip()
    # Title carries the emotion on Reddit; repeat it so a long neutral body
    # cannot wash the score out. Drop boilerplate-only bodies.
    if len(body_c) < 40:
        return title_c
    return f"{title_c}. {title_c}. {body_c[:800]}"


def _sentences_mentioning(text: str, tkr: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    alias_names = [a for a, sym in ALIASES.items() if sym == tkr]
    kept = []
    for part in parts:
        hits = extract_ticker_hits(part)
        if tkr in hits or any(a.lower() in part.lower() for a in alias_names):
            kept.append(part.strip())
    return " ".join(p for p in kept if p)


# ── VADER ────────────────────────────────────────────────────────────────────
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
        return float(v.polarity_scores(text or "")["compound"])
    from src.strategist.sentiment_analyzer import _lexicon_score
    return _lexicon_score(text or "")


def _engine_name() -> str:
    return "VADER (social)" if _get_vader() is not None else "finance-lexicon"


def _compound_for(post: dict, tkr: str, text: str, scored: list[bool]) -> float:
    custom = post.get("compounds")
    if isinstance(custom, dict) and tkr in custom:
        return float(custom[tkr])
    if post.get("compound") is not None:
        return float(post["compound"])
    scored.append(True)
    relevant = _sentences_mentioning(text, tkr)
    return _score(relevant or text)


def _post_level_compound(post: dict, text: str, scored: list[bool]) -> float:
    if post.get("compound") is not None:
        return float(post["compound"])
    scored.append(True)
    return _score(text)


def _created_ts(post: dict) -> float | None:
    raw = post.get("created")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    try:
        ts = pd.to_datetime(raw, utc=True)
        return float(ts.timestamp())
    except Exception:
        return None


def _dedupe(posts: list[dict]) -> list[dict]:
    seen: set = set()
    out = []
    for post in posts:
        key = post.get("id") or (
            post.get("sub"), (post.get("title") or "").strip().lower()[:160],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(post)
    return out


def _burst_by_ticker(groups: dict[str, list[dict]]) -> dict[str, float]:
    stamped: list[tuple[str, float]] = []
    for tkr, items in groups.items():
        for item in items:
            ts = item.get("created")
            if ts is not None:
                stamped.append((tkr, float(ts)))
    if len(stamped) < 4:
        return {}
    cutoff = statistics.median(ts for _, ts in stamped)
    recent: dict[str, int] = {}
    older: dict[str, int] = {}
    for tkr, ts in stamped:
        bucket = recent if ts >= cutoff else older
        bucket[tkr] = bucket.get(tkr, 0) + 1
    out = {}
    for tkr in set(recent) | set(older):
        r = recent.get(tkr, 0)
        o = older.get(tkr, 0)
        out[tkr] = (r - o) / max(o, 1)
    return out


def _blend_velocity(snapshot: float | None, burst: float | None) -> float | None:
    if snapshot is None and burst is None:
        return None
    if snapshot is None:
        return burst
    if burst is None:
        return snapshot
    return 0.6 * snapshot + 0.4 * burst


def _action_for(row: dict) -> str:
    if row["kind"] != "stock":
        return "context"
    if row["hype"]:
        return "hype_caution"
    mean = row["sentiment_mean"]
    if (mean > LABEL_THRESHOLD and row["composite"] >= WATCH_COMPOSITE
            and row["confidence"] >= WATCH_CONFIDENCE):
        return "watch_long"
    if (mean < -LABEL_THRESHOLD and row["composite"] >= WATCH_COMPOSITE
            and row["confidence"] >= WATCH_CONFIDENCE):
        return "watch_avoid"
    return "monitor"


def _include(row: dict) -> bool:
    if row["unique_posts"] >= MIN_UNIQUE_POSTS:
        return True
    precise = row["cashtag"] or row["alias"]
    return bool(precise and abs(row["sentiment_mean"]) >= SINGLE_HIT_ABS_SENT)


def aggregate_posts(
    posts: list[dict],
    prior_counts: dict[str, int] | None = None,
    source: str = "fixture",
    subs: list[str] | None = None,
) -> dict:
    """Score and rank a post corpus. No network and no cache writes.

    Each post is a dict with ``title`` and/or ``text``. Optional fields:
    ``compound`` (force one score for every ticker in the post), ``compounds``
    (per-ticker override), ``upvotes``, ``comments``, ``created`` (unix or
    ISO), ``id``, ``sub``.
    """
    posts = _dedupe(list(posts or []))
    scored: list[bool] = []
    groups: dict[str, list[dict]] = {}
    post_level: list[tuple[float, float]] = []

    for post in posts:
        title = post.get("title") or ""
        text = post.get("text") or _clean_text(title, post.get("body") or "")
        if not text:
            text = title
        hits = extract_ticker_hits(text)
        if not hits:
            continue
        created = _created_ts(post)
        upvotes = int(post.get("upvotes") or 0)
        comments = int(post.get("comments") or 0)
        weight = _engagement_weight(upvotes, comments)
        post_level.append((_post_level_compound(post, text, scored), weight))
        for tkr, meta in hits.items():
            groups.setdefault(tkr, []).append({
                "compound": _compound_for(post, tkr, text, scored),
                "mentions": int(meta["mentions"]),
                "cashtag": bool(meta["cashtag"]),
                "alias": bool(meta["alias"]),
                "bare": bool(meta["bare"]),
                "upvotes": upvotes,
                "comments": comments,
                "weight": weight,
                "created": created,
            })

    burst = _burst_by_ticker(groups)
    rows = []
    raw_counts: dict[str, int] = {}
    for tkr, items in groups.items():
        raw_counts[tkr] = len(items)
        weights = [it["weight"] for it in items]
        comps = [it["compound"] for it in items]
        wsum = sum(weights) or 1.0
        mean = sum(c * w for c, w in zip(comps, weights)) / wsum
        median = float(statistics.median(comps))
        pct_bull = sum(c > LABEL_THRESHOLD for c in comps) / len(comps)
        pct_bear = sum(c < -LABEL_THRESHOLD for c in comps) / len(comps)
        unique_posts = len(items)
        mentions = sum(it["mentions"] for it in items)
        upvote_sum = sum(max(it["upvotes"], 0) for it in items)
        comment_sum = sum(max(it["comments"], 0) for it in items)
        attention = (
            math.log1p(unique_posts)
            * (1.0 + UPVOTE_COEF * min(math.log1p(upvote_sum), LOG_CAP))
            * (1.0 + COMMENT_COEF * min(math.log1p(comment_sum), LOG_CAP))
        )
        if prior_counts is None:
            snapshot = None
        else:
            prev = int(prior_counts.get(tkr, 0))
            snapshot = (unique_posts - prev) / max(prev, 1)
        velocity = _blend_velocity(snapshot, burst.get(tkr))
        if velocity is None:
            vel_factor = 1.0
        else:
            vel_factor = _clip(1.0 + VELOCITY_COEF * velocity, VEL_FACTOR_LO, VEL_FACTOR_HI)
        mega_factor = 1.0
        if tkr in MEGA_CAPS and (velocity is None or velocity < MEGA_VEL_RELAX):
            mega_factor = MEGA_FACTOR
        confidence = 1.0 - math.exp(-unique_posts / CONF_SCALE)
        sent_term = SENT_FLOOR + SENT_SLOPE * min(1.0, abs(mean))
        composite = attention * sent_term * vel_factor * mega_factor * confidence
        sign = 1.0 if mean > 0 else (-1.0 if mean < 0 else 0.0)
        hype = (
            unique_posts >= HYPE_MIN_POSTS
            and mean > HYPE_MEAN
            and pct_bull >= HYPE_PCT_BULL
            and velocity is not None
            and velocity >= HYPE_MIN_VELOCITY
        )
        row = {
            "ticker": tkr,
            "kind": _kind(tkr),
            "mentions": int(mentions),
            "unique_posts": int(unique_posts),
            "upvotes": int(upvote_sum),
            "comments": int(comment_sum),
            "score": round(mean, 3),
            "sentiment_mean": round(mean, 3),
            "sentiment_median": round(median, 3),
            "pct_bullish": round(pct_bull, 3),
            "pct_bearish": round(pct_bear, 3),
            "label": _label(mean),
            "velocity": None if velocity is None else round(velocity, 3),
            "velocity_factor": round(vel_factor, 3),
            "confidence": round(confidence, 3),
            "composite": round(composite, 3),
            "pick_score": round(composite * sign, 3),
            "mega_factor": mega_factor,
            "cashtag": any(it["cashtag"] for it in items),
            "alias": any(it["alias"] for it in items),
            "hype": hype,
        }
        rows.append(row)

    for row in rows:
        row["action"] = _action_for(row)
        row["hype"] = bool(row["hype"])

    visible = [r for r in rows if _include(r) and r["kind"] != "index"]
    visible.sort(key=lambda r: (r["composite"], r["unique_posts"]), reverse=True)

    if post_level:
        wsum = sum(w for _, w in post_level) or 1.0
        overall = sum(c * w for c, w in post_level) / wsum
        overall_n = len(post_level)
    else:
        overall = 0.0
        overall_n = 0

    hype = [r["ticker"] for r in visible if r["action"] == "hype_caution"]
    stocks = [r for r in visible if r["kind"] == "stock"]
    etfs = [r for r in visible if r["kind"] == "etf"]
    actionable = {"watch_long", "watch_avoid", "hype_caution"}
    watchlist = [r for r in stocks if r["action"] in actionable]

    sub_list = list(subs or [])
    if not sub_list:
        sub_list = sorted({p.get("sub") for p in posts if p.get("sub")})

    engine = "precomputed" if not scored else _engine_name()
    computed = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    available = bool(posts)

    result = {
        "schema": SCHEMA_VERSION,
        "engine": engine,
        "source": source,
        "available": available,
        "experimental": True,
        "affects_regime_weights": False,
        "n_posts": len(posts),
        "n_ticker_posts": overall_n,
        "subs": sub_list,
        "tickers": [
            {k: v for k, v in r.items() if k not in {"cashtag", "alias"}}
            for r in visible[:12]
        ],
        "overall": {
            "score": round(overall, 3),
            "label": _label(overall),
            "n": overall_n,
        },
        "hype": hype,
        "formula": formula_text(),
        "computed": computed,
        "raw_counts": raw_counts,
    }
    result["retail_attention"] = _retail_attention(result, stocks, etfs, watchlist)
    return result


def _public_row(row: dict) -> dict:
    skip = {"cashtag", "alias", "hype", "mega_factor"}
    return {k: v for k, v in row.items() if k not in skip}


def _retail_attention(result: dict, stocks: list[dict], etfs: list[dict],
                      watchlist: list[dict]) -> dict:
    def tickers(rows: list[dict]) -> list[str]:
        return [r["ticker"] for r in rows]

    return {
        "experimental": True,
        "affects_regime_weights": False,
        "as_of": result["computed"],
        "engine": result["engine"],
        "source": result["source"],
        "n_posts": result["n_posts"],
        "n_ticker_posts": result["n_ticker_posts"],
        "subs": result["subs"],
        "formula": result["formula"],
        "overall": result["overall"],
        "ranked_stocks": [_public_row(r) for r in stocks[:8]],
        "watchlist": [_public_row(r) for r in watchlist[:8]],
        "etf_attention": [_public_row(r) for r in etfs[:6]],
        "hype_caution": result["hype"],
        "picks": {
            "watch_long": tickers([r for r in watchlist if r["action"] == "watch_long"]),
            "watch_avoid": tickers([r for r in watchlist if r["action"] == "watch_avoid"]),
            "hype_caution": list(result["hype"]),
        },
    }


def format_attention_row(row: dict) -> str:
    """Single-line card text with explicit separators (readable when copied)."""
    posts = row.get("unique_posts", row.get("mentions", 0))
    mentions = row.get("mentions", 0)
    vel = row.get("velocity")
    vel_s = "vel n/a" if vel is None else f"vel {vel:+.0%}"
    action = (row.get("action") or "monitor").replace("_", " ")
    kind = row.get("kind")
    kind_s = f"  ·  {kind}" if kind and kind != "stock" else ""
    score = row.get("score", row.get("sentiment_mean", 0.0)) or 0.0
    return (
        f"{row.get('ticker', '?')}  ·  {posts} posts  ·  {mentions} mentions  ·  "
        f"{score:+.2f} {row.get('label', 'Neutral')}  ·  {vel_s}  ·  "
        f"conf {float(row.get('confidence') or 0):.2f}  ·  "
        f"composite {float(row.get('composite') or 0):.2f}  ·  {action}{kind_s}"
    )


# ── Network fetch ────────────────────────────────────────────────────────────
_LAST_HTTP = 0.0


def _polite_get(url: str, headers: dict, min_interval: float, timeout: int = HTTP_TIMEOUT):
    global _LAST_HTTP
    import requests
    wait = min_interval - (time.time() - _LAST_HTTP)
    if wait > 0:
        time.sleep(wait)
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    finally:
        _LAST_HTTP = time.time()
    if resp.status_code == 429:
        logger.warning(f"Reddit rate-limited (429) for {url}")
        return None
    resp.raise_for_status()
    return resp


def _parse_atom(xml: str, sub: str) -> list[dict]:
    out = []
    for block in re.findall(r"<entry>(.*?)</entry>", xml or "", re.DOTALL):
        def grab(tag: str) -> str:
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL)
            if not m:
                return ""
            v = re.sub(r"<[^>]+>", "", m.group(1))
            return _html.unescape(v).strip()

        title = grab("title")
        body = grab("content")
        updated = grab("updated") or grab("published")
        id_raw = grab("id")
        link_m = re.search(r'<link[^>]*href="([^"]+)"', block)
        link = link_m.group(1) if link_m else ""
        post_id = ""
        id_m = re.search(r"t3_([a-z0-9]+)", id_raw or link, re.I)
        if id_m:
            post_id = id_m.group(1)
        if not title:
            continue
        out.append({
            "id": post_id or id_raw or f"{sub}:{title[:80]}",
            "sub": sub,
            "title": title,
            "text": _clean_text(title, body),
            "link": link,
            "created": updated,
            "upvotes": 0,
            "comments": 0,
        })
    return out


def _reddit_rss(sub: str, sort: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{sub}/{sort}.rss?limit=25"
    headers = {"User-Agent": "fontesfund-retail-attention/1.0 (research; public RSS)"}
    try:
        resp = _polite_get(url, headers, RSS_MIN_INTERVAL)
        if resp is None:
            return []
        return _parse_atom(resp.text, sub)
    except Exception as e:
        logger.warning(f"Reddit RSS failed for r/{sub}/{sort} ({e}).")
        return []


def _comment_rss(sub: str, post_id: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{sub}/comments/{post_id}.rss?limit=25"
    headers = {"User-Agent": "fontesfund-retail-attention/1.0 (research; public RSS)"}
    try:
        resp = _polite_get(url, headers, RSS_MIN_INTERVAL)
        if resp is None:
            return []
        comments = _parse_atom(resp.text, sub)
        # The first entry is usually the parent post; comments follow.
        # Tag comments so a title like "user on Daily Discussion" is kept.
        comments = comments[1:] if len(comments) > 1 else []
        for comment in comments:
            comment["is_comment"] = True
        return comments
    except Exception as e:
        logger.warning(f"Reddit comment RSS failed for {sub}/{post_id} ({e}).")
        return []


def _oauth_token() -> str | None:
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        return None
    import requests
    ua = os.getenv("REDDIT_USER_AGENT", "fontesfund:retail-attention:v1 (research)")
    username = os.getenv("REDDIT_USERNAME", "").strip()
    password = os.getenv("REDDIT_PASSWORD", "").strip()
    if username and password:
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
    else:
        data = {"grant_type": "client_credentials"}
    try:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            data=data,
            auth=(client_id, secret),
            headers={"User-Agent": ua},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        token = (resp.json() or {}).get("access_token")
        return token or None
    except Exception as e:
        logger.warning(f"Reddit OAuth token failed ({e}); falling back to RSS.")
        return None


def _listing_post(data: dict, sub: str) -> dict | None:
    title = data.get("title") or ""
    if not title:
        return None
    return {
        "id": data.get("id") or data.get("name"),
        "sub": sub,
        "title": title,
        "text": _clean_text(title, (data.get("selftext") or "")[:1200]),
        "link": "https://www.reddit.com" + (data.get("permalink") or ""),
        "created": data.get("created_utc"),
        "upvotes": int(data.get("score") or 0),
        "comments": int(data.get("num_comments") or 0),
        "stickied": bool(data.get("stickied")),
    }


def _oauth_listing(token: str, sub: str, sort: str) -> tuple[list[dict], list[dict]]:
    """Return (posts, stickied_megathreads). Stickies are not scored as posts."""
    ua = os.getenv("REDDIT_USER_AGENT", "fontesfund:retail-attention:v1 (research)")
    url = f"https://oauth.reddit.com/r/{sub}/{sort}?limit=100&raw_json=1"
    headers = {"Authorization": f"bearer {token}", "User-Agent": ua}
    try:
        resp = _polite_get(url, headers, OAUTH_MIN_INTERVAL)
        if resp is None:
            return [], []
        children = ((resp.json() or {}).get("data") or {}).get("children") or []
    except Exception as e:
        logger.warning(f"Reddit OAuth listing failed for r/{sub}/{sort} ({e}).")
        return [], []
    posts = []
    stickies = []
    for child in children:
        data = child.get("data") or {}
        parsed = _listing_post(data, sub)
        if parsed is None:
            continue
        if data.get("stickied"):
            if _is_megathread(parsed):
                stickies.append(parsed)
            continue
        posts.append(parsed)
    return posts, stickies


def _oauth_comments(token: str, sub: str, post_id: str) -> list[dict]:
    ua = os.getenv("REDDIT_USER_AGENT", "fontesfund:retail-attention:v1 (research)")
    url = (f"https://oauth.reddit.com/r/{sub}/comments/{post_id}"
           f"?limit=25&depth=1&sort=top&raw_json=1")
    headers = {"Authorization": f"bearer {token}", "User-Agent": ua}
    try:
        resp = _polite_get(url, headers, OAUTH_MIN_INTERVAL)
        if resp is None:
            return []
        payload = resp.json()
    except Exception as e:
        logger.warning(f"Reddit OAuth comments failed for {sub}/{post_id} ({e}).")
        return []
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    children = ((payload[1] or {}).get("data") or {}).get("children") or []
    out = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data") or {}
        body = (data.get("body") or "").strip()
        if not body or body in ("[deleted]", "[removed]"):
            continue
        out.append({
            "id": data.get("id") or f"{post_id}:{body[:40]}",
            "sub": sub,
            "title": body[:160],
            "text": body[:800],
            "link": "https://www.reddit.com" + (data.get("permalink") or ""),
            "created": data.get("created_utc"),
            "upvotes": int(data.get("score") or 0),
            "comments": 0,
            "is_comment": True,
        })
    return out


def _is_megathread(post: dict) -> bool:
    return bool(_MEGATHREAD_RE.search(post.get("title") or ""))


def _drop_megathread_parents(posts: list[dict]) -> list[dict]:
    """Drop daily-thread stubs. Keep comments, even when their title quotes the thread."""
    return [p for p in posts if p.get("is_comment") or not _is_megathread(p)]


def fetch_posts() -> tuple[list[dict], str, list[str]]:
    """Return (posts, source, subs_with_data). OAuth when credentials exist."""
    token = _oauth_token()
    posts: list[dict] = []
    subs_ok: list[str] = []
    if token:
        stickies: list[dict] = []
        seen_sticky: set[str] = set()
        for sub, sort in OAUTH_FEEDS:
            batch, sticky = _oauth_listing(token, sub, sort)
            if batch:
                posts.extend(batch)
                if sub not in subs_ok:
                    subs_ok.append(sub)
            for item in sticky:
                sid = str(item.get("id") or "")
                if sid and sid not in seen_sticky:
                    seen_sticky.add(sid)
                    stickies.append(item)
        # Daily-thread comments are the actual ticker tape. Cap the extra calls.
        for parent in stickies[:MAX_COMMENT_FEEDS]:
            comments = _oauth_comments(token, parent.get("sub") or "", str(parent.get("id")))
            posts.extend(comments)
        source = "reddit_oauth"
    else:
        for sub, sort in RSS_FEEDS:
            batch = _reddit_rss(sub, sort)
            if batch:
                posts.extend(batch)
                if sub not in subs_ok:
                    subs_ok.append(sub)
        source = "reddit_rss"
        # Comment text is where the daily thread actually names tickers.
        # RSS listings do not include it. Cap the extra fetches.
        megas = [p for p in posts if _is_megathread(p) and p.get("id")]
        seen_ids: set[str] = set()
        pulled = 0
        for parent in megas:
            pid = str(parent.get("id"))
            if pid in seen_ids or pulled >= MAX_COMMENT_FEEDS:
                continue
            seen_ids.add(pid)
            comments = _comment_rss(parent.get("sub") or "", pid)
            if comments:
                posts.extend(comments)
                pulled += 1
        posts = _drop_megathread_parents(posts)
    return _dedupe(posts), source, subs_ok


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_baseline() -> dict | None:
    if not BASELINE.exists():
        return None
    data = _load_json(BASELINE)
    if not isinstance(data, dict):
        return None
    if "counts" not in data or "as_of_unix" not in data:
        return None
    return data


def _save_baseline(counts: dict[str, int]) -> None:
    payload = {
        "as_of_unix": time.time(),
        "as_of": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "counts": {k: int(v) for k, v in counts.items()},
    }
    try:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not write Reddit attention baseline ({e}).")


def load_retail_attention_cache(max_age: float = CACHE_MAX_STALE_SECONDS) -> dict:
    """Last computed stock-pick overlay, or ``{}`` if missing / too old.

    Does not hit the network. Used by ``StrategyAdvisor`` so a recommendation
    can *see* retail attention without changing weights or blocking on Reddit.
    """
    if not CACHE.exists():
        return {}
    age = time.time() - CACHE.stat().st_mtime
    if age > max_age:
        return {}
    data = _load_json(CACHE)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return {}
    ra = data.get("retail_attention")
    return ra if isinstance(ra, dict) else {}


def _empty_result(engine: str, source: str) -> dict:
    computed = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    result = {
        "schema": SCHEMA_VERSION,
        "engine": engine,
        "source": source,
        "available": False,
        "experimental": True,
        "affects_regime_weights": False,
        "n_posts": 0,
        "n_ticker_posts": 0,
        "subs": [],
        "tickers": [],
        "overall": {"score": 0.0, "label": "Neutral", "n": 0},
        "hype": [],
        "formula": formula_text(),
        "computed": computed,
        "raw_counts": {},
    }
    result["retail_attention"] = _retail_attention(result, [], [], [])
    return result


def analyze_reddit(use_cache: bool = True, *, posts: list[dict] | None = None,
                   write_cache: bool = True) -> dict:
    """Mention, sentiment, velocity, and an experimental stock-pick watchlist.

    ``posts`` skips the network (tests / ``--fixture``). Cached payloads from
    an older schema are ignored so a deploy picks up the new score immediately.
    """
    if posts is None and use_cache and CACHE.exists():
        cached = _load_json(CACHE)
        fresh = (time.time() - CACHE.stat().st_mtime) < TTL_SECONDS
        if (fresh and isinstance(cached, dict)
                and cached.get("schema") == SCHEMA_VERSION):
            return cached

    if posts is not None:
        result = aggregate_posts(posts, prior_counts=None, source="fixture")
        return result

    try:
        fetched, source, subs = fetch_posts()
    except Exception as e:
        logger.warning(f"Reddit fetch failed ({e}).")
        fetched, source, subs = [], "reddit_rss", []

    if not fetched:
        stale = _load_json(CACHE) if CACHE.exists() else None
        if isinstance(stale, dict) and stale.get("tickers"):
            stale = dict(stale)
            stale["stale"] = True
            stale["available"] = True
            return stale
        return _empty_result(_engine_name(), source)

    baseline = _load_baseline()
    prior = None
    baseline_age = None
    if baseline is not None:
        baseline_age = time.time() - float(baseline["as_of_unix"])
        if baseline_age >= BASELINE_MIN_AGE_SECONDS:
            prior = {str(k): int(v) for k, v in (baseline.get("counts") or {}).items()}

    result = aggregate_posts(fetched, prior_counts=prior, source=source, subs=subs)
    # raw_counts is internal; keep it out of the file the dashboard caches
    # after the baseline snapshot is taken.
    counts = result.pop("raw_counts", {})
    should_roll = baseline is None or (
        baseline_age is not None and baseline_age >= VELOCITY_WINDOW_SECONDS
    )
    if write_cache and counts and should_roll:
        _save_baseline(counts)

    if write_cache:
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(result), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not write Reddit cache ({e}).")
    return result


def _main(argv: list[str] | None = None) -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Reddit retail attention — experimental stock-pick overlay",
    )
    parser.add_argument("--live", action="store_true",
                        help="Force a fresh Reddit pull (OAuth if env is set, else RSS)")
    parser.add_argument("--fixture", type=str, default="",
                        help="Aggregate this JSON post list offline (no network)")
    args = parser.parse_args(argv)
    if args.fixture:
        payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        result = aggregate_posts(payload, source="fixture")
        result.pop("raw_counts", None)
    else:
        result = analyze_reddit(use_cache=not args.live)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()
