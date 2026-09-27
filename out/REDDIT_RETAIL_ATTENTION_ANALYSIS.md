# Reddit Retail Attention — design, why the live card is weak, and the stock-pick overlay

Experimental signal. It does **not** change ETF regime weights, the GS/Merrill clock, FRED publication lags, or the backtest. Validated offline on `tests/fixtures/reddit_posts.json` (no live Reddit required).

## 1. Current design (before this change)

Implementation: `src/strategist/reddit_sentiment.py`, called from `build_ai_trend_intelligence()` and rendered by `render_ai_intelligence()` in `src/dashboard/app.py`. A one-line label also appeared on the Portfolio tab outlook.

| Piece | Behavior |
|---|---|
| Data source | Public subreddit Atom RSS only (`https://www.reddit.com/r/{sub}/hot.rss`). The `.json` listing is OAuth-gated and 403s without a token. No PRAW. No upvote score, no comment count, no comment bodies. |
| Subreddits | `wallstreetbets`, `stocks`, `semiconductors`. Hot feed only. |
| Time window | Whatever Reddit puts in the hot RSS (typically the latest ~25 entries per sub, not a clock window). Cache TTL 12 hours (`data/cache/reddit_sentiment.json`). |
| Post vs comment | Posts only. Title + first ~400 characters of the RSS HTML body. Daily-discussion threads (where most ticker talk actually is) were kept as a single stub whose body is rules text, not comments. |
| VADER | `SentimentIntensityAnalyzer.polarity_scores(text)["compound"]` in [-1, 1]. One score per post, then the mean of posts that mention the ticker. If VADER is not installed, `sentiment_analyzer._lexicon_score`. |
| Aggregate “Bullish” | Mention-weighted average of those per-ticker means. Label thresholds: Bullish if score > 0.15, Bearish if < -0.15, else Neutral. |
| Per-ticker attention | Closed list of 13 symbols (`NVDA AMD MU TSM AVGO ASML SMH SOXX SOXL TQQQ MSFT GOOGL META AMZN`). Regex `(?<![A-Za-z])\$?TICKER(?![A-Za-z])` **case-sensitive**, so `nvda` / `Nvda` missed. Sorted by raw mention count. No minimum count. |
| Refresh | On dashboard startup and on the in-process AI-trend refresh, if the cache is older than 12h. 1.5s sleep between subs. Failures become `available: false` and the card says the feed is rate-limited. A failed refresh did not keep the previous payload. |
| Failure / empty | Any exception per sub is logged and skipped. Zero posts → Neutral 0.00, empty ticker list. |

The hype flag (mentions high **and** mean compound > 0.5) was described as a contrarian top-tell. Nothing in the engine read it.

## 2. Why the live card looks weak

The production snapshot:

```
Bullish +0.22 (40 posts · r/wsb·stocks·semis)
MU 1× +0.87 Bullish
MSFT 1× +0.00 Neutral
META 1× +0.00 Neutral
AMZN 1× +0.00 Neutral
```

That layout matches the old card (ticker, count, and score were separate CSS boxes, so copied text collapsed to `MU1×+0.87`). The numbers are what the old pipeline produces on a thin pull. Verified causes:

1. **40 posts is about one feed, not three.** Three hot RSS feeds should be on the order of 60–75 entries. `n_posts == 40` means at least one sub returned nothing. Unauthenticated RSS 429s easily; the old code slept 1.5s and then gave up on that sub with an empty list.
2. **Comments were invisible.** WSB ticker flow lives in the daily thread and in comment bodies. RSS listings do not include either. A 400-character strip of the daily-thread body is boilerplate, which VADER scores near 0.00 — the Neutral mega-caps.
3. **Case-sensitive whitelist.** Only 13 symbols, exact uppercase. `$mu` and `nvda` did not count. Cashtags were optional in the regex but unknown tickers (`$SMCI`, `$GME`, `$PLTR`) were impossible.
4. **No minimum count.** One Neutral mention sorted to the top whenever nothing else was mentioned more often. Mega-caps are always in the whitelist, so they occupy the card even when the sample is one indifferent post.
5. **No velocity, no engagement weight, no confidence.** Rank was `mentions` descending. A name with 1 post and compound +0.87 looks like a signal and is not.
6. **Display-only.** `ai_trend["reddit"]` was rendered and the outlook showed the overall label. `StrategyAdvisor.generate_recommendation()` never read it. Regime weights, vol targeting, and the backtest did not see it. The “experimental” badge was accurate: the card could not change a stock pick.

## 3. How it connects to stock selection

**Before:** it did not. The only consumers were the AI-tab card and the outlook label `Retail (Reddit): {label} (experimental)`.

**After:** still not in the ETF book. The same function now returns a `retail_attention` object (`experimental: true`, `affects_regime_weights: false`) that is:

- stored on `build_ai_trend_intelligence()["retail_attention"]` and, when there is an actionable name, appended to the AI-trend report;
- shown on the AI card as a composite rank and on the Portfolio outlook as `Retail picks`;
- attached by `annotate_with_retail_attention()` inside `StrategyAdvisor.generate_recommendation()`, which reads the on-disk cache only (no extra Reddit call) and adds a rationale line plus hype risk flags.

`target_weights` is copied through unchanged. Unit test `test_overlay_does_not_change_weights` locks that.

## 4. Recommended architecture (what shipped, in rank order)

1. **Precision ticker extraction** — cashtags (`$MU`, including names outside the whitelist), a curated bare-symbol list (case-insensitive except English words such as `ARM` / `META` / `SNOW`, which must be uppercase), and company aliases (`Micron` → `MU`). Slang cashtags (`$YOLO`, `$DD`, `$FOMO`) and index symbols (`$SPX`) are blocked or kept out of the pick list. Mention spam inside one post is capped at 5.
2. **Composite rank instead of raw counts.** See the formula below. One Neutral mega-cap mention no longer appears.
3. **Velocity** — unique posts versus the previous baseline snapshot (rolled every 12h, `data/cache/reddit_attention_baseline.json`), blended with an in-pull burst (newer half vs older half of timestamped posts) when both exist. This is the retail spike.
4. **Wider corpus, still bounded for Cloud Run startup.** Public RSS: hot+new on WSB, stocks, semis, plus options hot and investing hot (8 requests, ~1s apart). Up to two daily-thread **comment** feeds; the parent stub is dropped so its rules text is not scored, and comments whose titles quote the thread are kept. If `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` are set, OAuth listings (score + `num_comments`, limit 100, extra subs including rising / StockMarket / technology / AMD_Stock / NVDA_Stock) replace RSS, and up to two stickied megathreads contribute their top comments.
5. **Stock-pick actions, experimental.** `watch_long`, `watch_avoid`, `hype_caution`, or `monitor`. Hype is a crowded long (many posts, very bullish, attention still rising) and is a risk flag, not a buy. A three-post bullish MU does **not** trip hype; the old rule did, because the leader of a tiny sample always looked “extreme.”
6. **Do not put this in the backtest until there is a point-in-time archive.** Same reason news sentiment stays out of the weights: there is no survivorship-safe history of these posts. Next step, if wanted, is to log `retail_attention` daily and only then test an overlay rule.

## Score formula

Per ticker, after the inclusion filter (at least 2 posts, **or** 1 post that is a cashtag or an alias with |sentiment| ≥ 0.35):

```
weight_i = 1
         + 0.15 * min(ln(1 + upvotes_i), 6)
         + 0.05 * min(ln(1 + comments_i), 6)

sentiment_mean = engagement-weighted mean of per-ticker VADER compounds
                 (sentences that mention the name when the score is computed live;
                  RSS upvotes and comments are 0, so weights are 1)

attention = ln(1 + unique_posts)
          * (1 + 0.15 * min(ln(1 + upvote_sum), 6))
          * (1 + 0.05 * min(ln(1 + comment_sum), 6))

snapshot = (unique_now - unique_prior) / max(unique_prior, 1)   # vs ~12h baseline
burst    = (newer_half - older_half) / max(older_half, 1)       # this pull, if ≥4 timestamps
velocity = snapshot                         if only snapshot
         = burst                            if only burst
         = 0.6 * snapshot + 0.4 * burst     if both
velocity_factor = clip(1 + 0.50 * velocity, 0.50, 2.50)   # 1.0 if velocity is unknown

confidence = 1 - exp(-unique_posts / 3)
mega_factor = 0.70 for AAPL MSFT GOOGL GOOG AMZN META TSLA NVDA
              unless velocity ≥ 0.75, else 1

composite  = attention * (0.25 + 0.75 * |sentiment_mean|)
             * velocity_factor * mega_factor * confidence
pick_score = composite * sign(sentiment_mean)
```

Rank by `composite` descending.

| Action | Rule |
|---|---|
| `hype_caution` | unique posts ≥ 6, sentiment_mean > 0.50, % bullish ≥ 0.65, velocity ≥ 0.50. Contrarian. Not a buy. |
| `watch_long` | not hype, sentiment_mean > 0.15, composite ≥ 0.35, confidence ≥ 0.40 |
| `watch_avoid` | bearish mirror of watch_long |
| `monitor` | passed the inclusion filter, not strong enough to pick |

Also reported, unweighted: median compound, % bullish, % bearish, mention count, unique posts, upvote sum, comment sum.

The card line is literal text, not CSS columns:

```
MU  ·  3 posts  ·  4 mentions  ·  +0.60 Bullish  ·  vel +200%  ·  conf 0.63  ·  composite 1.23  ·  watch long
```

`vel +200%` means unique posts doubled versus the prior baseline `(3 - 1) / 1 = 2`.

## How to run

Offline (CI, no credentials):

```bash
python3 -m unittest tests.test_reddit_sentiment
python3 -m src.strategist.reddit_sentiment --fixture tests/fixtures/reddit_posts.json
```

Live pull (RSS works with no keys; OAuth is richer):

```bash
# optional, in .env — never commit values
# REDDIT_CLIENT_ID REDDIT_CLIENT_SECRET REDDIT_USER_AGENT
# REDDIT_USERNAME REDDIT_PASSWORD   # script-app password grant; omit for client-credentials
python3 -m src.strategist.reddit_sentiment --live
```

Cache: `data/cache/reddit_sentiment.json` (schema 2, 12h). Baseline for velocity: `data/cache/reddit_attention_baseline.json`. Both are gitignored. A schema-1 file is ignored so the new score is computed on the next refresh. If a live pull fails and an older file exists, that file is returned with `stale: true` instead of wiping the card.

Rate limits: public RSS is about one request per second and 429s under bursts (8 listing calls + up to 2 comment feeds). OAuth app-only or script auth is about 60 requests/minute; the OAuth path uses a 0.35s gap. Set the user-agent to something unique. Reddit’s script apps need a username and password; app-only `client_credentials` is tried when those are absent.

## Follow-ups (not in this change)

- Log the daily `retail_attention` payload and only then backtest a sleeve overlay. Do not fit the regime book to a few weeks of Reddit.
- Persist the JSON in the GCS cache bucket so a new Cloud Run instance does not pay the RSS budget on every cold start.
- Comment-level sampling beyond the two megathreads, once OAuth is configured in production.
