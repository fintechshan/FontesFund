"""Feature engineering module for the ETF Investment Application.

Transforms raw macroeconomic data collected by MacroDataCollector into
features suitable for the HMM regime classifier. All normalization uses
rolling/expanding windows to prevent look-ahead bias.

Typical usage::

    from src.strategist.data_collector import MacroDataCollector
    from src.strategist.feature_engineer import FeatureEngineer

    collector = MacroDataCollector()
    engineer = FeatureEngineer(collector)
    regime_features = engineer.compute_regime_features(resample_freq='M')
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from src.strategist.data_collector import MacroDataCollector

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Transforms raw macroeconomic data into features for regime detection.

    This class takes a ``MacroDataCollector`` instance, pulls the raw time
    series it has collected, and engineers features grouped into five
    categories: growth, inflation, risk, monetary, and sentiment. The final
    output can be a full feature matrix or a curated, z-score-normalised
    subset specifically designed for the HMM regime classifier.

    Parameters
    ----------
    data_collector : MacroDataCollector
        A fully-initialised (and ideally already-loaded) data collector
        that exposes ``get_*`` accessor methods for each macro series.

    Attributes
    ----------
    dc : MacroDataCollector
        Reference to the injected data collector.
    _feature_cache : dict[str, pd.DataFrame]
        Internal cache of computed feature groups to avoid redundant work.
    """

    # ---- Key features selected for HMM regime detection ----
    REGIME_FEATURES: list[str] = [
        "gdp_growth",
        "unemployment_momentum",
        "sp500_momentum",
        "cpi_yoy",
        "breakeven_5y",
        "vix_zscore",
        "hy_spread",
        "yield_curve",
    ]

    # Rolling z-score window (months) for normalisation
    ZSCORE_WINDOW: int = 36

    def __init__(self, data_collector: MacroDataCollector) -> None:
        self.dc = data_collector
        self._feature_cache: dict[str, pd.DataFrame] = {}
        logger.info("FeatureEngineer initialised.")

    # ------------------------------------------------------------------
    # Individual Feature Computation
    # ------------------------------------------------------------------

    def compute_growth_features(self) -> pd.DataFrame:
        """Compute growth-related features.

        Returns
        -------
        pd.DataFrame
            DataFrame indexed by datetime with columns:

            * ``gdp_growth`` – GDP growth rate, forward-filled to daily.
            * ``unemployment_momentum`` – 3-month change in unemployment rate.
            * ``sp500_momentum`` – S&P 500 12-month price momentum.
            * ``sp500_ma_cross`` – 50-day MA / 200-day MA ratio.
            * ``sp500_above_200ma`` – Binary flag: 1 if price > 200-day MA.
        """
        logger.info("Computing growth features …")
        frames: dict[str, pd.Series] = {}

        # --- GDP growth rate ---
        try:
            gdp = self.dc.get_gdp()
            gdp = self._ensure_tz_naive(gdp)
            gdp_growth = gdp.pct_change()
            frames["gdp_growth"] = gdp_growth.resample("D").ffill()
            logger.debug("GDP growth feature computed (%d obs).", len(frames["gdp_growth"].dropna()))
        except Exception:
            logger.warning("Failed to compute GDP growth feature.", exc_info=True)
            frames["gdp_growth"] = pd.Series(dtype=float)

        # --- Unemployment momentum (3-month Δ) ---
        try:
            unemployment = self.dc.get_unemployment_rate()
            unemployment = self._ensure_tz_naive(unemployment)
            unemp_daily = unemployment.resample("D").ffill()
            frames["unemployment_momentum"] = unemp_daily - unemp_daily.shift(63)  # ~3 months
            logger.debug("Unemployment momentum computed.")
        except Exception:
            logger.warning("Failed to compute unemployment momentum.", exc_info=True)
            frames["unemployment_momentum"] = pd.Series(dtype=float)

        # --- S&P 500 momentum & MA features ---
        try:
            sp500 = self.dc.get_sp500()
            sp500 = self._ensure_tz_naive(sp500)

            # 12-month momentum
            frames["sp500_momentum"] = sp500 / sp500.shift(252) - 1

            # Moving-average crossover
            ma50 = sp500.rolling(window=50, min_periods=50).mean()
            ma200 = sp500.rolling(window=200, min_periods=200).mean()
            frames["sp500_ma_cross"] = ma50 / ma200

            # Above 200-day MA binary flag
            frames["sp500_above_200ma"] = (sp500 > ma200).astype(float)
            logger.debug("S&P 500 features computed.")
        except Exception:
            logger.warning("Failed to compute S&P 500 features.", exc_info=True)
            for col in ("sp500_momentum", "sp500_ma_cross", "sp500_above_200ma"):
                frames[col] = pd.Series(dtype=float)

        result = self._combine(frames, "growth")
        self._feature_cache["growth"] = result
        return result

    def compute_inflation_features(self) -> pd.DataFrame:
        """Compute inflation-related features.

        Returns
        -------
        pd.DataFrame
            DataFrame indexed by datetime with columns:

            * ``cpi_yoy`` – CPI year-over-year rate of change.
            * ``core_cpi_yoy`` – Core CPI year-over-year change.
            * ``cpi_momentum`` – 3-month change in CPI YoY.
            * ``breakeven_5y`` – 5-year breakeven inflation rate.
            * ``breakeven_10y`` – 10-year breakeven inflation rate.
            * ``inflation_trend`` – Sign of 3-month MA of CPI momentum.
        """
        logger.info("Computing inflation features …")
        frames: dict[str, pd.Series] = {}

        # --- CPI YoY ---
        try:
            cpi = self.dc.get_cpi()
            cpi = self._ensure_tz_naive(cpi)
            cpi_yoy = cpi.pct_change(periods=12)  # monthly series ⇒ 12 periods = 1 year
            cpi_yoy_daily = cpi_yoy.resample("D").ffill()
            frames["cpi_yoy"] = cpi_yoy_daily

            # CPI momentum: 3-month change in the YoY rate
            cpi_momentum = cpi_yoy - cpi_yoy.shift(3)
            cpi_momentum_daily = cpi_momentum.resample("D").ffill()
            frames["cpi_momentum"] = cpi_momentum_daily

            # Inflation trend: sign of 3-month MA of momentum
            inflation_trend = np.sign(
                cpi_momentum.rolling(window=3, min_periods=1).mean()
            )
            frames["inflation_trend"] = inflation_trend.resample("D").ffill()
            logger.debug("CPI features computed.")
        except Exception:
            logger.warning("Failed to compute CPI features.", exc_info=True)
            for col in ("cpi_yoy", "cpi_momentum", "inflation_trend"):
                frames[col] = pd.Series(dtype=float)

        # --- Core CPI YoY ---
        try:
            core_cpi = self.dc.get_core_cpi()
            core_cpi = self._ensure_tz_naive(core_cpi)
            frames["core_cpi_yoy"] = core_cpi.pct_change(periods=12).resample("D").ffill()
            logger.debug("Core CPI feature computed.")
        except Exception:
            logger.warning("Failed to compute core CPI feature.", exc_info=True)
            frames["core_cpi_yoy"] = pd.Series(dtype=float)

        # --- Breakeven inflation rates ---
        try:
            be5 = self.dc.get_breakeven_5y()
            be5 = self._ensure_tz_naive(be5)
            frames["breakeven_5y"] = be5
            logger.debug("5Y breakeven inflation feature computed.")
        except Exception:
            logger.warning("Failed to compute 5Y breakeven inflation.", exc_info=True)
            frames["breakeven_5y"] = pd.Series(dtype=float)

        try:
            be10 = self.dc.get_breakeven_10y()
            be10 = self._ensure_tz_naive(be10)
            frames["breakeven_10y"] = be10
            logger.debug("10Y breakeven inflation feature computed.")
        except Exception:
            logger.warning("Failed to compute 10Y breakeven inflation.", exc_info=True)
            frames["breakeven_10y"] = pd.Series(dtype=float)

        result = self._combine(frames, "inflation")
        self._feature_cache["inflation"] = result
        return result

    def compute_risk_features(self) -> pd.DataFrame:
        """Compute risk and volatility features.

        Returns
        -------
        pd.DataFrame
            DataFrame indexed by datetime with columns:

            * ``vix_level`` – Raw VIX level.
            * ``vix_zscore`` – VIX 20-day rolling z-score.
            * ``vix_regime`` – Categorical: low / normal / elevated / crisis.
            * ``hy_spread`` – High-yield credit spread level.
            * ``hy_spread_momentum`` – 20-day change in HY spread.
            * ``ig_spread`` – Investment-grade credit spread.
            * ``yield_curve`` – 10Y−2Y yield curve slope.
            * ``yield_curve_inverted`` – Binary, 1 if yield curve < 0.
        """
        logger.info("Computing risk features …")
        frames: dict[str, pd.Series] = {}

        # --- VIX features ---
        try:
            vix = self.dc.get_vix()
            vix = self._ensure_tz_naive(vix)
            frames["vix_level"] = vix

            # 20-day rolling z-score
            vix_mean = vix.rolling(window=20, min_periods=20).mean()
            vix_std = vix.rolling(window=20, min_periods=20).std()
            frames["vix_zscore"] = (vix - vix_mean) / vix_std

            # Regime classification
            frames["vix_regime"] = self._classify_vix_regime(vix)
            logger.debug("VIX features computed.")
        except Exception:
            logger.warning("Failed to compute VIX features.", exc_info=True)
            for col in ("vix_level", "vix_zscore", "vix_regime"):
                frames[col] = pd.Series(dtype=float)

        # --- High-yield spread ---
        try:
            hy = self.dc.get_hy_spread()
            hy = self._ensure_tz_naive(hy)
            frames["hy_spread"] = hy
            frames["hy_spread_momentum"] = hy - hy.shift(20)
            logger.debug("HY spread features computed.")
        except Exception:
            logger.warning("Failed to compute HY spread features.", exc_info=True)
            frames["hy_spread"] = pd.Series(dtype=float)
            frames["hy_spread_momentum"] = pd.Series(dtype=float)

        # --- IG spread ---
        try:
            ig = self.dc.get_ig_spread()
            ig = self._ensure_tz_naive(ig)
            frames["ig_spread"] = ig
            logger.debug("IG spread feature computed.")
        except Exception:
            logger.warning("Failed to compute IG spread feature.", exc_info=True)
            frames["ig_spread"] = pd.Series(dtype=float)

        # --- Yield curve ---
        try:
            t10 = self.dc.get_treasury_10y()
            t2 = self.dc.get_treasury_2y()
            t10 = self._ensure_tz_naive(t10)
            t2 = self._ensure_tz_naive(t2)

            yield_curve = t10 - t2
            frames["yield_curve"] = yield_curve
            frames["yield_curve_inverted"] = (yield_curve < 0).astype(float)
            logger.debug("Yield curve features computed.")
        except Exception:
            logger.warning("Failed to compute yield curve features.", exc_info=True)
            frames["yield_curve"] = pd.Series(dtype=float)
            frames["yield_curve_inverted"] = pd.Series(dtype=float)

        result = self._combine(frames, "risk")
        self._feature_cache["risk"] = result
        return result

    def compute_monetary_features(self) -> pd.DataFrame:
        """Compute monetary-policy features.

        Returns
        -------
        pd.DataFrame
            DataFrame indexed by datetime with columns:

            * ``fed_funds_rate`` – Current federal-funds rate.
            * ``fed_funds_momentum`` – 3-month change in fed funds rate.
            * ``real_rate`` – Approximate real rate (fed funds − CPI YoY).
            * ``treasury_10y`` – 10-year Treasury yield.
            * ``treasury_2y`` – 2-year Treasury yield.
        """
        logger.info("Computing monetary features …")
        frames: dict[str, pd.Series] = {}

        # --- Fed funds rate ---
        try:
            ffr = self.dc.get_fed_funds_rate()
            ffr = self._ensure_tz_naive(ffr)
            ffr_daily = ffr.resample("D").ffill()
            frames["fed_funds_rate"] = ffr_daily
            frames["fed_funds_momentum"] = ffr_daily - ffr_daily.shift(63)  # ~3 months
            logger.debug("Fed funds features computed.")
        except Exception:
            logger.warning("Failed to compute fed funds features.", exc_info=True)
            frames["fed_funds_rate"] = pd.Series(dtype=float)
            frames["fed_funds_momentum"] = pd.Series(dtype=float)

        # --- Real rate (approximate: fed funds − CPI YoY) ---
        try:
            ffr_rate = frames.get("fed_funds_rate")
            cpi = self.dc.get_cpi()
            cpi = self._ensure_tz_naive(cpi)
            cpi_yoy = cpi.pct_change(periods=12).resample("D").ffill()

            if ffr_rate is not None and not ffr_rate.empty:
                # Align on common index
                combined = pd.DataFrame({"ffr": ffr_rate, "cpi_yoy": cpi_yoy})
                combined = combined.ffill()
                frames["real_rate"] = combined["ffr"] - combined["cpi_yoy"] * 100
            else:
                frames["real_rate"] = pd.Series(dtype=float)
            logger.debug("Real rate feature computed.")
        except Exception:
            logger.warning("Failed to compute real rate feature.", exc_info=True)
            frames["real_rate"] = pd.Series(dtype=float)

        # --- Treasury yields ---
        try:
            t10 = self.dc.get_treasury_10y()
            t10 = self._ensure_tz_naive(t10)
            frames["treasury_10y"] = t10
            logger.debug("10Y Treasury feature computed.")
        except Exception:
            logger.warning("Failed to compute 10Y Treasury feature.", exc_info=True)
            frames["treasury_10y"] = pd.Series(dtype=float)

        try:
            t2 = self.dc.get_treasury_2y()
            t2 = self._ensure_tz_naive(t2)
            frames["treasury_2y"] = t2
            logger.debug("2Y Treasury feature computed.")
        except Exception:
            logger.warning("Failed to compute 2Y Treasury feature.", exc_info=True)
            frames["treasury_2y"] = pd.Series(dtype=float)

        result = self._combine(frames, "monetary")
        self._feature_cache["monetary"] = result
        return result

    def compute_sentiment_features(self) -> pd.DataFrame:
        """Compute consumer-sentiment features.

        Returns
        -------
        pd.DataFrame
            DataFrame indexed by datetime with columns:

            * ``consumer_sentiment`` – UMich consumer sentiment index.
            * ``sentiment_momentum`` – 3-month change in sentiment.
        """
        logger.info("Computing sentiment features …")
        frames: dict[str, pd.Series] = {}

        try:
            sentiment = self.dc.get_consumer_sentiment()
            sentiment = self._ensure_tz_naive(sentiment)
            sentiment_daily = sentiment.resample("D").ffill()
            frames["consumer_sentiment"] = sentiment_daily
            frames["sentiment_momentum"] = sentiment_daily - sentiment_daily.shift(63)
            logger.debug("Sentiment features computed.")
        except Exception:
            logger.warning("Failed to compute sentiment features.", exc_info=True)
            frames["consumer_sentiment"] = pd.Series(dtype=float)
            frames["sentiment_momentum"] = pd.Series(dtype=float)

        result = self._combine(frames, "sentiment")
        self._feature_cache["sentiment"] = result
        return result

    # ------------------------------------------------------------------
    # Main / Aggregate Methods
    # ------------------------------------------------------------------

    def compute_all_features(self, resample_freq: str = "M") -> pd.DataFrame:
        """Compute every feature group and merge into a single DataFrame.

        Workflow
        --------
        1. Call all individual ``compute_*`` methods.
        2. Outer-join on the date index, then forward-fill gaps.
        3. Resample to *resample_freq* (default monthly).
        4. Drop rows that still contain NaN (early history).

        Parameters
        ----------
        resample_freq : str, default ``'M'``
            Pandas offset alias for the target frequency.

        Returns
        -------
        pd.DataFrame
            Combined feature matrix at the requested frequency.
        """
        logger.info("Computing all features (resample_freq=%s) …", resample_freq)

        growth = self.compute_growth_features()
        inflation = self.compute_inflation_features()
        risk = self.compute_risk_features()
        monetary = self.compute_monetary_features()
        sentiment = self.compute_sentiment_features()

        all_frames = [growth, inflation, risk, monetary, sentiment]
        # Filter out empty DataFrames
        all_frames = [df for df in all_frames if not df.empty]

        if not all_frames:
            logger.error("No feature groups produced data. Returning empty DataFrame.")
            return pd.DataFrame()

        combined = all_frames[0]
        for df in all_frames[1:]:
            combined = combined.join(df, how="outer")

        # Forward-fill, then resample to the requested frequency (last obs)
        combined = combined.ffill()
        combined = combined.resample(resample_freq).last()

        # Drop rows with remaining NaN (early dates without full coverage)
        n_before = len(combined)
        combined = combined.dropna()
        n_dropped = n_before - len(combined)
        if n_dropped:
            logger.info(
                "Dropped %d rows with NaN after forward-fill (%d → %d).",
                n_dropped,
                n_before,
                len(combined),
            )

        logger.info("All features computed: %d rows × %d columns.", *combined.shape)
        return combined

    def compute_regime_features(self, resample_freq: str = "M") -> pd.DataFrame:
        """Compute the curated, z-score-normalised feature matrix for the HMM.

        Workflow
        --------
        1. Call :meth:`compute_all_features`.
        2. Select only the key features in :attr:`REGIME_FEATURES`.
        3. Apply rolling z-score normalisation (36-month expanding window)
           to avoid look-ahead bias.

        Parameters
        ----------
        resample_freq : str, default ``'M'``
            Pandas offset alias for the target frequency.

        Returns
        -------
        pd.DataFrame
            Normalised feature matrix ready for the HMM classifier.
        """
        logger.info("Computing regime features (resample_freq=%s) …", resample_freq)

        all_features = self.compute_all_features(resample_freq=resample_freq)

        if all_features.empty:
            logger.error("No features available – returning empty DataFrame.")
            return pd.DataFrame()

        # Select key columns (only those present in the data)
        available = [c for c in self.REGIME_FEATURES if c in all_features.columns]
        missing = set(self.REGIME_FEATURES) - set(available)
        if missing:
            logger.warning("Regime features missing from data: %s", missing)

        regime_df = all_features[available].copy()

        # Rolling z-score normalisation (expanding with min 36-month window)
        regime_df = self._rolling_zscore(regime_df, min_periods=self.ZSCORE_WINDOW)

        # Drop any rows that couldn't be normalised (warm-up period)
        n_before = len(regime_df)
        regime_df = regime_df.dropna()
        n_dropped = n_before - len(regime_df)
        if n_dropped:
            logger.info(
                "Dropped %d warm-up rows after z-score normalisation (%d → %d).",
                n_dropped,
                n_before,
                len(regime_df),
            )

        logger.info(
            "Regime features ready: %d rows × %d columns.", *regime_df.shape
        )
        return regime_df

    def get_current_snapshot(self) -> dict[str, float | str | None]:
        """Return the latest value of every feature as a flat dictionary.

        This is useful for populating dashboard widgets or generating a
        quick summary of current market conditions.

        Returns
        -------
        dict[str, float | str | None]
            Mapping of feature name → latest value.  Features that could
            not be computed are represented as ``None``.
        """
        logger.info("Building current feature snapshot …")

        all_features = self.compute_all_features(resample_freq="D")

        if all_features.empty:
            logger.warning("No features available for snapshot.")
            return {}

        latest = all_features.iloc[-1]
        snapshot: dict[str, float | str | None] = {}
        for col in latest.index:
            val = latest[col]
            if pd.isna(val):
                snapshot[col] = None
            elif isinstance(val, (np.floating, float)):
                snapshot[col] = float(val)
            elif isinstance(val, (np.integer, int)):
                snapshot[col] = int(val)
            else:
                snapshot[col] = val  # type: ignore[assignment]

        logger.info("Snapshot built with %d features (as of %s).", len(snapshot), all_features.index[-1])
        return snapshot

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_tz_naive(series: pd.Series) -> pd.Series:
        """Convert a timezone-aware DatetimeIndex to timezone-naive.

        Parameters
        ----------
        series : pd.Series
            Input series whose index may or may not be tz-aware.

        Returns
        -------
        pd.Series
            Series with a guaranteed tz-naive DatetimeIndex.
        """
        if hasattr(series.index, "tz") and series.index.tz is not None:
            series = series.copy()
            series.index = series.index.tz_localize(None)
        return series

    @staticmethod
    def _classify_vix_regime(vix: pd.Series) -> pd.Series:
        """Map raw VIX levels to categorical regime labels.

        Thresholds
        ----------
        * **low**: VIX < 15
        * **normal**: 15 ≤ VIX < 25
        * **elevated**: 25 ≤ VIX < 35
        * **crisis**: VIX ≥ 35

        Parameters
        ----------
        vix : pd.Series
            Raw VIX level series.

        Returns
        -------
        pd.Series
            Categorical string series with the same index.
        """
        conditions = [
            vix < 15,
            (vix >= 15) & (vix < 25),
            (vix >= 25) & (vix < 35),
            vix >= 35,
        ]
        labels = ["low", "normal", "elevated", "crisis"]
        return pd.Series(
            np.select(conditions, labels, default="normal"),
            index=vix.index,
            name="vix_regime",
        )

    @staticmethod
    def _rolling_zscore(
        df: pd.DataFrame,
        min_periods: int = 36,
    ) -> pd.DataFrame:
        """Apply expanding-window z-score normalisation to each column.

        Uses an *expanding* window (with a minimum observation count of
        *min_periods*) so that only past data is used at each point,
        preventing look-ahead bias.

        Parameters
        ----------
        df : pd.DataFrame
            Raw feature matrix.
        min_periods : int, default 36
            Minimum number of observations required before producing a
            z-score.  Rows before this threshold are set to NaN.

        Returns
        -------
        pd.DataFrame
            Z-score-normalised feature matrix (same shape as input).
        """
        expanding_mean = df.expanding(min_periods=min_periods).mean()
        expanding_std = df.expanding(min_periods=min_periods).std()

        # Avoid division by zero – replace zero std with NaN
        expanding_std = expanding_std.replace(0, np.nan)

        normalised = (df - expanding_mean) / expanding_std
        return normalised

    @staticmethod
    def _combine(
        frames: dict[str, pd.Series],
        group_name: str,
    ) -> pd.DataFrame:
        """Combine a dict of named Series into a single DataFrame.

        Parameters
        ----------
        frames : dict[str, pd.Series]
            Mapping of column name → Series.
        group_name : str
            Human-readable name for logging.

        Returns
        -------
        pd.DataFrame
            Combined DataFrame with one column per entry in *frames*.
        """
        # Filter out empty series
        non_empty = {k: v for k, v in frames.items() if len(v) > 0}

        if not non_empty:
            logger.warning("No data for feature group '%s'.", group_name)
            return pd.DataFrame()

        result = pd.DataFrame(non_empty)

        # Ensure tz-naive datetime index
        if hasattr(result.index, "tz") and result.index.tz is not None:
            result.index = result.index.tz_localize(None)

        logger.info(
            "Feature group '%s': %d rows × %d columns (%s … %s).",
            group_name,
            len(result),
            len(result.columns),
            result.index.min(),
            result.index.max(),
        )
        return result
