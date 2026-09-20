"""
Analyst Monitor Module
======================
Aggregates analyst sentiment from Finnhub and yfinance as a proxy
for investment bank views (Goldman Sachs, Morgan Stanley, JP Morgan, Bernstein).

Provides consensus scores, price targets, and sector-level sentiment analysis.
"""

import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class AnalystSentiment:
    """Sentiment data for a single ticker."""
    ticker: str
    finnhub_score: float = 0.0
    yf_recommendation: str = ""
    yf_score: float = 0.0
    aggregate_score: float = 0.0
    num_analysts: int = 0
    price_target_upside: float = 0.0
    last_updated: Optional[datetime] = None


class AnalystMonitor:
    """
    Aggregates analyst sentiment from Finnhub and yfinance.
    
    Uses Finnhub recommendation trends and yfinance analyst data
    to compute consensus scores as a proxy for investment bank views.
    """

    # Recommendation score mapping
    _SCORE_MAP = {
        'strongBuy': 2.0, 'buy': 1.0, 'hold': 0.0,
        'sell': -1.0, 'strongSell': -2.0,
    }

    # yfinance recommendation mapping
    _YF_SCORE_MAP = {
        'strong_buy': 2.0, 'buy': 1.0, 'outperform': 0.75,
        'overweight': 0.5, 'hold': 0.0, 'neutral': 0.0,
        'equal-weight': 0.0, 'underweight': -0.5,
        'underperform': -0.75, 'sell': -1.0, 'strong_sell': -2.0,
    }

    def __init__(
        self,
        finnhub_api_key: Optional[str] = None,
        cache_db_path: Optional[Path] = None,
    ):
        """
        Initialize the AnalystMonitor.

        Args:
            finnhub_api_key: Finnhub API key. If None, Finnhub data is skipped.
            cache_db_path: Path to SQLite cache database.
        """
        self._finnhub_client = None
        self._lock = threading.Lock()

        # Initialize Finnhub client if key provided
        if finnhub_api_key:
            try:
                import finnhub
                self._finnhub_client = finnhub.Client(api_key=finnhub_api_key)
                logger.info("Finnhub client initialized successfully")
            except ImportError:
                logger.warning("finnhub-python not installed. Install with: pip install finnhub-python")
            except Exception as e:
                logger.error(f"Failed to initialize Finnhub client: {e}")
        else:
            logger.info("No Finnhub API key provided — using yfinance only")

        # Initialize SQLite cache
        if cache_db_path is None:
            try:
                from config.settings import DB_PATH
                cache_db_path = DB_PATH
            except ImportError:
                cache_db_path = Path("data/db/investment.db")

        self._db_path = cache_db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create analyst cache tables."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analyst_cache (
                    ticker TEXT,
                    source TEXT,
                    data_json TEXT,
                    fetched_at TIMESTAMP,
                    PRIMARY KEY (ticker, source)
                )
            """)
            conn.commit()

    # ------------------------------------------------------------------ #
    #                        FINNHUB METHODS                              #
    # ------------------------------------------------------------------ #

    def get_recommendation_trends(self, ticker: str) -> pd.DataFrame:
        """
        Fetch analyst recommendation trends from Finnhub.

        Args:
            ticker: Stock/ETF ticker symbol.

        Returns:
            DataFrame with columns: period, strongBuy, buy, hold, sell, strongSell.
            Empty DataFrame if unavailable.
        """
        if self._finnhub_client is None:
            logger.debug(f"Finnhub unavailable, skipping recommendations for {ticker}")
            return pd.DataFrame()

        try:
            # Rate limit: 60 calls/min on free tier
            time.sleep(1.0)
            data = self._finnhub_client.recommendation_trends(ticker)
            if data:
                df = pd.DataFrame(data)
                logger.debug(f"Fetched {len(df)} recommendation periods for {ticker}")
                return df
            return pd.DataFrame()
        except Exception as e:
            logger.warning(f"Finnhub recommendation fetch failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_consensus_score(self, ticker: str) -> float:
        """
        Compute a consensus score from Finnhub recommendation trends.

        Score is weighted: strongBuy=+2, buy=+1, hold=0, sell=-1, strongSell=-2,
        normalized to [-1.0, +1.0].

        Args:
            ticker: Stock/ETF ticker symbol.

        Returns:
            Consensus score in [-1.0, +1.0]. Returns 0.0 if no data.
        """
        df = self.get_recommendation_trends(ticker)
        if df.empty:
            return 0.0

        try:
            latest = df.iloc[0]
            total = sum(latest.get(k, 0) for k in self._SCORE_MAP)
            if total == 0:
                return 0.0

            weighted_sum = sum(
                latest.get(k, 0) * v for k, v in self._SCORE_MAP.items()
            )
            # Normalize: max possible is 2.0*total, min is -2.0*total
            score = weighted_sum / (2.0 * total)
            return max(-1.0, min(1.0, score))
        except Exception as e:
            logger.warning(f"Failed to compute consensus for {ticker}: {e}")
            return 0.0

    # ------------------------------------------------------------------ #
    #                        YFINANCE METHODS                             #
    # ------------------------------------------------------------------ #

    def get_yf_recommendations(self, ticker: str) -> pd.DataFrame:
        """
        Fetch recent analyst recommendations from yfinance.

        Args:
            ticker: Stock/ETF ticker symbol.

        Returns:
            DataFrame of recent analyst recommendations.
        """
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            recs = t.recommendations
            if recs is not None and not recs.empty:
                return recs
            return pd.DataFrame()
        except Exception as e:
            logger.debug(f"yfinance recommendations unavailable for {ticker}: {e}")
            return pd.DataFrame()

    def get_yf_price_targets(self, ticker: str) -> dict[str, Any]:
        """
        Fetch analyst price targets from yfinance.

        Args:
            ticker: Stock/ETF ticker symbol.

        Returns:
            Dict with keys: current, low, mean, median, high.
        """
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            targets = t.analyst_price_targets
            if targets is not None:
                if isinstance(targets, dict):
                    return targets
                # Some versions return a DataFrame
                return targets.to_dict() if hasattr(targets, 'to_dict') else {}
            return {}
        except Exception as e:
            logger.debug(f"yfinance price targets unavailable for {ticker}: {e}")
            return {}

    def _compute_yf_score(self, ticker: str) -> float:
        """Compute a sentiment score from yfinance recommendations."""
        recs = self.get_yf_recommendations(ticker)
        if recs.empty:
            return 0.0

        try:
            # Get the most recent recommendations (last 3 months)
            recent = recs.tail(10)
            scores = []
            for _, row in recent.iterrows():
                grade = str(row.get('To Grade', row.get('toGrade', ''))).lower().strip()
                for key, score in self._YF_SCORE_MAP.items():
                    if key in grade:
                        scores.append(score)
                        break
            if scores:
                return max(-1.0, min(1.0, sum(scores) / (2.0 * len(scores))))
            return 0.0
        except Exception as e:
            logger.debug(f"Failed to compute yfinance score for {ticker}: {e}")
            return 0.0

    # ------------------------------------------------------------------ #
    #                      AGGREGATE METHODS                              #
    # ------------------------------------------------------------------ #

    def get_etf_sentiment(self, tickers: list[str]) -> pd.DataFrame:
        """
        Compute aggregate analyst sentiment for a list of ETFs.

        Uses ThreadPoolExecutor for parallel fetching with rate limiting.

        Args:
            tickers: List of ETF ticker symbols.

        Returns:
            DataFrame with columns: ticker, finnhub_score, yf_score, aggregate_score.
        """
        results = []

        def _fetch_one(ticker: str) -> AnalystSentiment:
            fh_score = self.get_consensus_score(ticker) if self._finnhub_client else 0.0
            yf_score = self._compute_yf_score(ticker)

            # Weighted average: Finnhub 60%, yfinance 40% (if both available)
            if self._finnhub_client and fh_score != 0.0:
                agg = 0.6 * fh_score + 0.4 * yf_score
            else:
                agg = yf_score

            return AnalystSentiment(
                ticker=ticker,
                finnhub_score=fh_score,
                yf_score=yf_score,
                aggregate_score=round(agg, 4),
                last_updated=datetime.now(),
            )

        # Use ThreadPoolExecutor with limited workers to respect rate limits
        max_workers = 3 if self._finnhub_client else 5
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one, t): t for t in tickers}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.warning(f"Sentiment fetch failed for {ticker}: {e}")
                    results.append(AnalystSentiment(ticker=ticker))

        # Convert to DataFrame
        rows = [
            {
                'ticker': r.ticker,
                'finnhub_score': r.finnhub_score,
                'yf_score': r.yf_score,
                'aggregate_score': r.aggregate_score,
                'last_updated': r.last_updated,
            }
            for r in results
        ]
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values('ticker').reset_index(drop=True)
        return df

    def get_portfolio_sentiment(self, weights: dict[str, float]) -> float:
        """
        Compute weighted average sentiment for a portfolio.

        Args:
            weights: Dict of ticker -> portfolio weight.

        Returns:
            Portfolio sentiment score in [-1.0, +1.0].
        """
        tickers = list(weights.keys())
        sentiment_df = self.get_etf_sentiment(tickers)

        if sentiment_df.empty:
            return 0.0

        total_score = 0.0
        total_weight = 0.0
        for _, row in sentiment_df.iterrows():
            w = weights.get(row['ticker'], 0.0)
            total_score += w * row['aggregate_score']
            total_weight += w

        if total_weight == 0:
            return 0.0
        return round(total_score / total_weight, 4)

    def get_sector_sentiment(self) -> dict[str, float]:
        """
        Compute average sentiment grouped by ETF category.

        Returns:
            Dict mapping category name to average sentiment score.
        """
        try:
            from config.etf_universe import ALL_ETFS, get_etf
        except ImportError:
            logger.warning("Could not import etf_universe, returning empty sector sentiment")
            return {}

        # Group tickers by category
        categories: dict[str, list[str]] = {}
        for ticker in ALL_ETFS:
            info = get_etf(ticker)
            if info:
                cat = info.category
                categories.setdefault(cat, []).append(ticker)

        result = {}
        for category, tickers in categories.items():
            sentiment_df = self.get_etf_sentiment(tickers)
            if not sentiment_df.empty:
                result[category] = round(sentiment_df['aggregate_score'].mean(), 4)
            else:
                result[category] = 0.0

        return result

    # ------------------------------------------------------------------ #
    #                 NEWS / RSS PLACEHOLDERS                             #
    # ------------------------------------------------------------------ #

    def get_financial_news(
        self, query: str = "market outlook", limit: int = 10
    ) -> list[dict]:
        """
        Fetch financial news articles.

        Note:
            Placeholder — will integrate with news APIs in a future update.

        Args:
            query: Search query string.
            limit: Maximum number of articles.

        Returns:
            List of news article dicts (currently empty).
        """
        logger.info(
            f"Financial news fetch is a placeholder (query='{query}'). "
            "Future: integrate Marketaux/Alpha Vantage news API."
        )
        return []

    def get_bank_commentary_summary(self) -> dict[str, str]:
        """
        Get latest commentary summaries from major investment banks.

        Note:
            Placeholder — proprietary research is not publicly available via API.
            Will support manual PDF upload + summary in a future update.

        Returns:
            Dict mapping bank name to summary status.
        """
        banks = {
            "Morgan Stanley": "No public API available — placeholder for manual ingestion",
            "Goldman Sachs": "No public API available — placeholder for manual ingestion",
            "JP Morgan": "No public API available — placeholder for manual ingestion",
            "Bernstein": "No public API available — placeholder for manual ingestion",
        }
        logger.info(
            "Bank commentary is placeholder. Proprietary research requires "
            "institutional access. Use Finnhub consensus as proxy."
        )
        return banks

    # ------------------------------------------------------------------ #
    #                        REPORTING                                    #
    # ------------------------------------------------------------------ #

    def generate_sentiment_report(self, tickers: list[str]) -> dict[str, Any]:
        """
        Generate a comprehensive analyst sentiment report.

        Args:
            tickers: List of ETF tickers to analyze.

        Returns:
            Dict with per-ticker scores, portfolio-level metrics,
            top bullish/bearish picks, and data freshness info.
        """
        sentiment_df = self.get_etf_sentiment(tickers)

        if sentiment_df.empty:
            return {
                "status": "no_data",
                "tickers_analyzed": 0,
                "message": "No analyst data available for provided tickers",
            }

        # Sort for top bullish / bearish
        sorted_df = sentiment_df.sort_values('aggregate_score', ascending=False)

        report = {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "tickers_analyzed": len(sentiment_df),
            "per_ticker": sentiment_df.to_dict('records'),
            "overall_sentiment": round(sentiment_df['aggregate_score'].mean(), 4),
            "top_bullish": sorted_df.head(3)[['ticker', 'aggregate_score']].to_dict('records'),
            "top_bearish": sorted_df.tail(3)[['ticker', 'aggregate_score']].to_dict('records'),
            "data_sources": {
                "finnhub": self._finnhub_client is not None,
                "yfinance": True,
            },
            "warnings": [],
        }

        # Add warnings for tickers with no data
        zero_data = sentiment_df[
            (sentiment_df['finnhub_score'] == 0) & (sentiment_df['yf_score'] == 0)
        ]
        if not zero_data.empty:
            report['warnings'].append(
                f"No analyst data for: {', '.join(zero_data['ticker'].tolist())}"
            )

        return report
