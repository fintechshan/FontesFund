# Reddit Retail Attention — restored display-only panel

The experimental stock-pick overlay from PR #6 (squash `2d773bc`) was reverted. User feedback was that the optimized card was worse. This file describes the panel that is live again: the version on main at `f6c53d9`, before that overlay.

ETF regime weights, the Merrill clock, the GS throttle, publication lags, and the backtest are unchanged. The Backtest tab still defaults to Auditor Lagged.

## What the panel does

Implementation: `analyze_reddit()` in `src/strategist/reddit_sentiment.py`, called from `build_ai_trend_intelligence()` and rendered by `render_ai_intelligence()` in `src/dashboard/app.py`. The Portfolio tab outlook shows one line: `Retail (Reddit): {label} (experimental)`.

| Piece | Behavior |
|---|---|
| Data source | Public subreddit Atom RSS only (`https://www.reddit.com/r/{sub}/hot.rss`). No OAuth, no upvote score, no comment bodies. |
| Subreddits | `wallstreetbets`, `stocks`, `semiconductors`. Hot feed only. |
| Cache | `data/cache/reddit_sentiment.json`, 12-hour TTL. |
| Tickers | Case-sensitive whitelist: NVDA, AMD, MU, TSM, AVGO, ASML, SMH, SOXX, SOXL, TQQQ, MSFT, GOOGL, META, AMZN. |
| Score | VADER compound in [-1, 1], mean of posts that mention the ticker. If VADER is missing, `sentiment_analyzer._lexicon_score`. |
| Rank | Raw mention count. The card shows the top mentions as `{ticker} {n}× {score} {label}`. |
| Overall | Mention-weighted mean of those ticker scores. Labels: Bullish > 0.15, Bearish < -0.15, otherwise Neutral. |
| Hype flag | Mentions ≥ max(3, half the leader's count) and score > 0.5. Contrarian attention flag on the card. |
| Consumers | AI-tab card and the outlook label. `StrategyAdvisor` does not read it. |

The card footer is: public RSS + VADER, contrarian attention signal, experimental, display-only, not in the backtest.
