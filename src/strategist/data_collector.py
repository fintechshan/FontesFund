"""
Comprehensive data collection module for the ETF Investment Application.

Fetches and caches macroeconomic data from FRED and market data from Yahoo Finance.
Uses a process-local in-memory cache with configurable staleness thresholds.

Author: Antigravity Investment System
Created: 2026-06-17
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from fredapi import Fred

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Staleness thresholds (hours)
# ---------------------------------------------------------------------------
_DAILY_MAX_AGE_HOURS: int = 24
_MONTHLY_MAX_AGE_HOURS: int = 168  # 7 days
_QUARTERLY_MAX_AGE_HOURS: int = 168  # 7 days

# Retry configuration
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 2.0  # seconds, exponential backoff


# ═══════════════════════════════════════════════════════════════════════════
# In-memory cache  (replaces the former SQLite layer)
# ═══════════════════════════════════════════════════════════════════════════
#
# NOTE (audit 2026-06-22): the previous thread-safe SQLiteCache was DEAD CODE —
# the runtime app (run_dashboard.py) and validation (run_backtest.py) use the
# CSV/pickle caches, never this module, and on ephemeral Cloud Run a local SQLite
# file gives no cross-instance benefit. The SQLite layer was removed. This tiny
# process-local cache preserves the MacroDataCollector interface for any legacy
# importer (feature_engineer / strategy_advisor) without persistence.


class _MemoryCache:
    """Process-local, thread-safe in-memory time-series cache.

    Drop-in replacement for the removed SQLiteCache (same method signatures).
    No persistence — the production data path uses the CSV/pickle caches.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path  # accepted for signature compatibility; unused
        self._store: dict[tuple[str, str], tuple[pd.Series, float]] = {}
        self._lock = threading.Lock()

    def create_tables(self) -> None:  # no-op (kept for interface compatibility)
        return None

    def store_series(self, table: str, series_id: str, data: pd.Series) -> None:
        with self._lock:
            self._store[(table, series_id)] = (data.copy(), time.time())

    def get_series(
        self, table: str, series_id: str, max_age_hours: int
    ) -> Optional[pd.Series]:
        with self._lock:
            entry = self._store.get((table, series_id))
        if entry is None:
            return None
        data, fetched_at = entry
        if (time.time() - fetched_at) > max_age_hours * 3600:
            return None
        return data.copy()

    def is_stale(self, table: str, series_id: str, max_age_hours: int) -> bool:
        return self.get_series(table, series_id, max_age_hours) is None

    def get_all_freshness(self) -> pd.DataFrame:
        with self._lock:
            records = [
                {
                    "table": t,
                    "series_id": sid,
                    "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "rows": len(data),
                }
                for (t, sid), (data, ts) in self._store.items()
            ]
        return pd.DataFrame(records)


# ═══════════════════════════════════════════════════════════════════════════
# MacroDataCollector
# ═══════════════════════════════════════════════════════════════════════════

class MacroDataCollector:
    """Fetches and caches macroeconomic & market data from FRED and Yahoo Finance.

    Data is cached in-process so that repeat calls
    within the staleness window return instantly without hitting the network.

    Parameters
    ----------
    fred_api_key : str
        API key for the Federal Reserve Economic Data (FRED) service.
    cache_dir : Path
        Directory used for any flat-file caching (e.g. downloaded CSVs).
    db_path : Path
        Accepted for backward compatibility; no longer used (in-memory cache).

    Examples
    --------
    >>> from pathlib import Path
    >>> collector = MacroDataCollector(
    ...     fred_api_key="YOUR_KEY",
    ...     cache_dir=Path("./cache"),
    ...     db_path=Path("./cache/investment.db"),
    ... )
    >>> cpi = collector.get_cpi()
    >>> print(cpi.tail())
    """

    # FRED series catalogue --------------------------------------------------
    _FRED_SERIES: dict[str, dict] = {
        "cpi":                    {"id": "CPIAUCSL",        "freq": "monthly"},
        "core_cpi":               {"id": "CPILFESL",        "freq": "monthly"},
        "fed_funds_rate":         {"id": "DFF",             "freq": "daily"},
        "treasury_10y":           {"id": "DGS10",           "freq": "daily"},
        "treasury_2y":            {"id": "DGS2",            "freq": "daily"},
        "yield_curve":            {"id": "T10Y2Y",          "freq": "daily"},
        "vix":                    {"id": "VIXCLS",          "freq": "daily"},
        "gdp_growth":             {"id": "A191RL1Q225SBEA", "freq": "quarterly"},
        "unemployment":           {"id": "UNRATE",          "freq": "monthly"},
        "breakeven_inflation_5y": {"id": "T5YIE",           "freq": "daily"},
        "breakeven_inflation_10y":{"id": "T10YIE",          "freq": "daily"},
        "hy_credit_spread":       {"id": "BAMLH0A0HYM2",   "freq": "daily"},
        "ig_credit_spread":       {"id": "BAMLC0A0CM",      "freq": "daily"},
        "consumer_sentiment":     {"id": "UMCSENT",         "freq": "monthly"},
        "sp500_index":            {"id": "SP500",           "freq": "daily"},
    }

    _FREQ_TO_MAX_AGE: dict[str, int] = {
        "daily": _DAILY_MAX_AGE_HOURS,
        "monthly": _MONTHLY_MAX_AGE_HOURS,
        "quarterly": _QUARTERLY_MAX_AGE_HOURS,
    }

    def __init__(
        self,
        fred_api_key: str,
        cache_dir: Path,
        db_path: Path,
    ) -> None:
        self._fred_api_key = fred_api_key
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._cache = _MemoryCache(db_path)
        self._fred = Fred(api_key=fred_api_key)

        logger.info(
            "MacroDataCollector initialised  cache_dir=%s  db=%s",
            self._cache_dir,
            db_path,
        )

    # ───────────────────────────────────────────────────────────────────────
    # FRED data – public convenience methods
    # ───────────────────────────────────────────────────────────────────────

    def get_cpi(self) -> pd.Series:
        """Fetch Consumer Price Index for All Urban Consumers (CPIAUCSL), monthly."""
        return self._fetch_fred_series("CPIAUCSL")

    def get_core_cpi(self) -> pd.Series:
        """Fetch Core CPI excluding Food & Energy (CPILFESL), monthly."""
        return self._fetch_fred_series("CPILFESL")

    def get_fed_funds_rate(self) -> pd.Series:
        """Fetch Effective Federal Funds Rate (DFF), daily."""
        return self._fetch_fred_series("DFF")

    def get_treasury_10y(self) -> pd.Series:
        """Fetch 10-Year Treasury Constant Maturity Rate (DGS10), daily."""
        return self._fetch_fred_series("DGS10")

    def get_treasury_2y(self) -> pd.Series:
        """Fetch 2-Year Treasury Constant Maturity Rate (DGS2), daily."""
        return self._fetch_fred_series("DGS2")

    def get_yield_curve(self) -> pd.Series:
        """Fetch 10Y-2Y Treasury Yield Spread (T10Y2Y), daily."""
        return self._fetch_fred_series("T10Y2Y")

    def get_vix(self) -> pd.Series:
        """Fetch CBOE Volatility Index (VIXCLS), daily."""
        return self._fetch_fred_series("VIXCLS")

    def get_gdp_growth(self) -> pd.Series:
        """Fetch Real GDP Growth Rate (A191RL1Q225SBEA), quarterly."""
        return self._fetch_fred_series("A191RL1Q225SBEA")

    def get_unemployment(self) -> pd.Series:
        """Fetch Civilian Unemployment Rate (UNRATE), monthly."""
        return self._fetch_fred_series("UNRATE")

    def get_breakeven_inflation_5y(self) -> pd.Series:
        """Fetch 5-Year Breakeven Inflation Rate (T5YIE), daily."""
        return self._fetch_fred_series("T5YIE")

    def get_breakeven_inflation_10y(self) -> pd.Series:
        """Fetch 10-Year Breakeven Inflation Rate (T10YIE), daily."""
        return self._fetch_fred_series("T10YIE")

    def get_hy_credit_spread(self) -> pd.Series:
        """Fetch High-Yield Corporate Bond Spread (BAMLH0A0HYM2), daily."""
        return self._fetch_fred_series("BAMLH0A0HYM2")

    def get_ig_credit_spread(self) -> pd.Series:
        """Fetch Investment-Grade Corporate Bond Spread (BAMLC0A0CM), daily."""
        return self._fetch_fred_series("BAMLC0A0CM")

    def get_consumer_sentiment(self) -> pd.Series:
        """Fetch University of Michigan Consumer Sentiment (UMCSENT), monthly."""
        return self._fetch_fred_series("UMCSENT")

    def get_sp500_index(self) -> pd.Series:
        """Fetch S&P 500 Index level (SP500), daily."""
        return self._fetch_fred_series("SP500")

    # ───────────────────────────────────────────────────────────────────────
    # FRED – private helper
    # ───────────────────────────────────────────────────────────────────────

    def _fetch_fred_series(
        self, series_id: str, start_date: str = "2010-01-01"
    ) -> pd.Series:
        """Fetch a single FRED series with cache-first semantics.

        1. Check SQLite cache; return immediately if data is fresh.
        2. Otherwise hit the FRED API with exponential-backoff retries.
        3. Store the fresh data in SQLite before returning.

        Parameters
        ----------
        series_id : str
            FRED series identifier (e.g. ``"CPIAUCSL"``).
        start_date : str
            Observation start date in ``YYYY-MM-DD`` format.

        Returns
        -------
        pd.Series
            Datetime-indexed series of observed values.

        Raises
        ------
        RuntimeError
            If all retry attempts are exhausted.
        """
        # Determine staleness threshold for this series
        max_age = self._max_age_for_series(series_id)

        # 1. Try cache
        cached = self._cache.get_series("fred_cache", series_id, max_age)
        if cached is not None:
            logger.debug("Cache HIT for FRED/%s (%d rows)", series_id, len(cached))
            return cached

        # 2. Fetch from FRED with retries
        logger.info("Cache MISS for FRED/%s — fetching from API …", series_id)
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                data: pd.Series = self._fred.get_series(
                    series_id, observation_start=start_date
                )
                data = data.dropna()
                data.name = series_id

                # 3. Store in cache
                self._cache.store_series("fred_cache", series_id, data)
                logger.info(
                    "Fetched FRED/%s: %d observations (%s → %s)",
                    series_id,
                    len(data),
                    data.index.min().date() if len(data) else "N/A",
                    data.index.max().date() if len(data) else "N/A",
                )
                return data

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                delay = _RETRY_BASE_DELAY ** attempt
                logger.warning(
                    "FRED/%s attempt %d/%d failed (%s). Retrying in %.1fs …",
                    series_id,
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    delay,
                )
                time.sleep(delay)

        raise RuntimeError(
            f"Failed to fetch FRED/{series_id} after {_MAX_RETRIES} attempts"
        ) from last_exc

    def _max_age_for_series(self, series_id: str) -> int:
        """Return the max-cache-age (hours) appropriate for a given FRED series."""
        for meta in self._FRED_SERIES.values():
            if meta["id"] == series_id:
                return self._FREQ_TO_MAX_AGE.get(meta["freq"], _DAILY_MAX_AGE_HOURS)
        # Fallback for ad-hoc series not in the catalogue
        return _DAILY_MAX_AGE_HOURS

    # ───────────────────────────────────────────────────────────────────────
    # Market data – yfinance
    # ───────────────────────────────────────────────────────────────────────

    def get_etf_prices(
        self,
        tickers: list[str],
        start_date: str = "2010-01-01",
    ) -> pd.DataFrame:
        """Download adjusted-close prices for a list of ETF tickers.

        Results are cached in the ``etf_prices`` SQLite table.  Stale
        data (older than 24 h) is automatically refreshed.

        Parameters
        ----------
        tickers : list[str]
            Yahoo Finance ticker symbols (e.g. ``["SPY", "TLT", "GLD"]``).
        start_date : str
            Start date in ``YYYY-MM-DD`` format.

        Returns
        -------
        pd.DataFrame
            DataFrame with a ``DatetimeIndex`` and one column per ticker
            containing adjusted close prices.
        """
        frames: dict[str, pd.Series] = {}

        for ticker in tickers:
            cached = self._cache.get_series(
                "etf_prices", ticker, _DAILY_MAX_AGE_HOURS
            )
            if cached is not None:
                logger.debug("Cache HIT for ETF/%s", ticker)
                frames[ticker] = cached
                continue

            logger.info("Cache MISS for ETF/%s — downloading …", ticker)
            last_exc: Exception | None = None

            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    yf_ticker = yf.Ticker(ticker)
                    hist = yf_ticker.history(start=start_date, auto_adjust=True)

                    if hist.empty:
                        logger.warning("No data returned by yfinance for %s", ticker)
                        frames[ticker] = pd.Series(dtype=float, name=ticker)
                        break

                    close: pd.Series = hist["Close"]
                    close.name = ticker
                    close.index = close.index.tz_localize(None)

                    self._cache.store_series("etf_prices", ticker, close)
                    frames[ticker] = close
                    logger.info(
                        "Downloaded ETF/%s: %d rows (%s → %s)",
                        ticker,
                        len(close),
                        close.index.min().date(),
                        close.index.max().date(),
                    )
                    break

                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    delay = _RETRY_BASE_DELAY ** attempt
                    logger.warning(
                        "ETF/%s attempt %d/%d failed (%s). Retrying in %.1fs …",
                        ticker,
                        attempt,
                        _MAX_RETRIES,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
            else:
                raise RuntimeError(
                    f"Failed to download ETF/{ticker} after {_MAX_RETRIES} attempts"
                ) from last_exc

        df = pd.DataFrame(frames)
        df.index.name = "date"
        return df

    def get_etf_returns(
        self,
        tickers: list[str],
        start_date: str = "2010-01-01",
    ) -> pd.DataFrame:
        """Compute daily simple returns for the given ETFs.

        Parameters
        ----------
        tickers : list[str]
            Yahoo Finance ticker symbols.
        start_date : str
            Start date in ``YYYY-MM-DD`` format.

        Returns
        -------
        pd.DataFrame
            Daily percentage returns (decimal form, i.e. 0.01 = 1 %).
        """
        prices = self.get_etf_prices(tickers, start_date=start_date)
        returns = prices.pct_change().dropna(how="all")
        return returns

    def get_sp500_pe_ratio(self) -> pd.Series:
        """Estimate trailing P/E ratio for the S&P 500 via SPY earnings data.

        Uses Yahoo Finance earnings data for SPY to compute a trailing
        price-to-earnings ratio.  Falls back to a simple trailing-12-month
        EPS estimate when granular data is unavailable.

        The result is cached in the ``analyst_data`` table under key
        ``SP500_PE``.

        Returns
        -------
        pd.Series
            Datetime-indexed trailing P/E ratio.
        """
        cache_key = "SP500_PE"
        cached = self._cache.get_series(
            "analyst_data", cache_key, _DAILY_MAX_AGE_HOURS
        )
        if cached is not None:
            logger.debug("Cache HIT for %s", cache_key)
            return cached

        logger.info("Computing S&P 500 trailing P/E ratio via SPY …")

        try:
            spy = yf.Ticker("SPY")

            # Get price history
            hist = spy.history(start="2010-01-01", auto_adjust=True)
            if hist.empty:
                logger.warning("No SPY price history returned.")
                return pd.Series(dtype=float, name=cache_key)

            close = hist["Close"]
            close.index = close.index.tz_localize(None)

            # Attempt to get earnings data
            earnings: pd.DataFrame | None = None
            try:
                earnings = spy.earnings_history  # type: ignore[attr-defined]
            except Exception:
                pass

            if earnings is not None and not earnings.empty and "epsActual" in earnings.columns:
                # Build trailing-12-month EPS from quarterly earnings
                earnings = earnings.sort_index()
                eps_quarterly = earnings["epsActual"].dropna()
                eps_ttm = eps_quarterly.rolling(window=4, min_periods=4).sum()
                eps_ttm = eps_ttm.dropna()

                # Align to daily prices via forward-fill
                eps_daily = eps_ttm.reindex(close.index, method="ffill")
                pe_ratio = close / eps_daily
            else:
                # Fallback: use trailing P/E from info if available
                logger.info(
                    "Detailed earnings unavailable; using info-based trailingPE."
                )
                info = spy.info or {}
                trailing_pe = info.get("trailingPE")

                if trailing_pe is not None:
                    # Create a flat series at today's value (snapshot)
                    pe_ratio = pd.Series(
                        trailing_pe,
                        index=pd.DatetimeIndex([pd.Timestamp.now().normalize()]),
                        name=cache_key,
                    )
                else:
                    logger.warning("Could not determine S&P 500 P/E ratio.")
                    return pd.Series(dtype=float, name=cache_key)

            pe_ratio = pe_ratio.dropna()
            pe_ratio.name = cache_key

            self._cache.store_series("analyst_data", cache_key, pe_ratio)
            logger.info("Stored S&P 500 P/E ratio: %d observations", len(pe_ratio))
            return pe_ratio

        except Exception:
            logger.exception("Failed to compute S&P 500 P/E ratio")
            return pd.Series(dtype=float, name=cache_key)

    # ───────────────────────────────────────────────────────────────────────
    # Convenience / batch methods
    # ───────────────────────────────────────────────────────────────────────

    def get_all_macro_data(self) -> dict[str, pd.Series]:
        """Fetch every registered FRED macro series and return as a dict.

        Returns
        -------
        dict[str, pd.Series]
            Keys are human-readable names (e.g. ``"cpi"``, ``"vix"``),
            values are datetime-indexed ``pd.Series``.
        """
        result: dict[str, pd.Series] = {}
        for name, meta in self._FRED_SERIES.items():
            try:
                result[name] = self._fetch_fred_series(meta["id"])
            except RuntimeError:
                logger.error("Skipping %s (%s) due to fetch failure", name, meta["id"])
        return result

    def refresh_all_data(self) -> None:
        """Force-refresh all cached FRED series, ignoring staleness windows.

        This is useful when you want to guarantee the latest data before
        running a strategy backtest or generating a report.
        """
        logger.info("Force-refreshing all FRED series …")
        for name, meta in self._FRED_SERIES.items():
            try:
                # Bypass cache by fetching directly
                data: pd.Series = self._fred.get_series(
                    meta["id"], observation_start="2010-01-01"
                )
                data = data.dropna()
                data.name = meta["id"]
                self._cache.store_series("fred_cache", meta["id"], data)
                logger.info("Refreshed %s (%s): %d rows", name, meta["id"], len(data))
            except Exception:  # noqa: BLE001
                logger.exception("Failed to refresh %s (%s)", name, meta["id"])

    def get_data_freshness(self) -> pd.DataFrame:
        """Return a summary table showing the freshness of every cached series.

        Returns
        -------
        pd.DataFrame
            Columns: ``table``, ``series_id``, ``last_fetched``,
            ``rows``, ``age_hours``.
        """
        return self._cache.get_all_freshness()
