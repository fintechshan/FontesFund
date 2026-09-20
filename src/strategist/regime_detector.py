"""
src/strategist/regime_detector.py
=================================
Macro-regime classification using a Gaussian Hidden Markov Model.

Classifies the economy into one of four regimes based on engineered
macroeconomic features:

* **Goldilocks** — rising growth, falling inflation
* **Reflation** — rising growth, rising inflation
* **Stagflation** — falling growth, rising inflation
* **Deflation** — falling growth, falling inflation

The primary prediction method is :meth:`walk_forward_predict`, which
uses an expanding-window approach to avoid look-ahead bias.

Typical usage::

    from src.strategist.feature_engineer import FeatureEngineer
    from src.strategist.regime_detector import RegimeDetector

    features = feature_engineer.compute_regime_features()
    detector = RegimeDetector(n_regimes=4)
    detector.train(features)
    regime, confidence = detector.predict_regime(features)
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    from hmmlearn.hmm import GaussianHMM
    _HAS_HMMLEARN = True
except ImportError:
    from sklearn.mixture import GaussianMixture as GaussianHMM  # Fallback
    _HAS_HMMLEARN = False
    logger.warning(
        "hmmlearn not installed (needs C++ build tools). "
        "Falling back to sklearn GaussianMixture for regime detection."
    )

# Valid regime labels in canonical order
_REGIME_LABELS: list[str] = [
    "goldilocks",
    "reflation",
    "stagflation",
    "deflation",
]


class RegimeDetector:
    """Classifies the economy into macro regimes using a Gaussian HMM.

    Parameters
    ----------
    n_regimes : int, default 4
        Number of hidden states.  Must equal ``len(_REGIME_LABELS)``.
    random_state : int, default 42
        Seed for reproducible HMM training.

    Attributes
    ----------
    model : GaussianHMM | None
        Trained HMM, set after calling :meth:`train`.
    regime_history : pd.DataFrame | None
        Full historical regime classification after :meth:`predict_regime_history`
        or :meth:`walk_forward_predict`.
    label_mapping : dict[int, str]
        Mapping from HMM integer state to human-readable regime name.
    """

    def __init__(self, n_regimes: int = 4, random_state: int = 42) -> None:
        if n_regimes != len(_REGIME_LABELS):
            raise ValueError(
                f"n_regimes must be {len(_REGIME_LABELS)} (got {n_regimes}). "
                f"Labels: {_REGIME_LABELS}"
            )

        self.n_regimes: int = n_regimes
        self.random_state: int = random_state
        self.regime_labels: list[str] = list(_REGIME_LABELS)

        self.model = None  # GaussianHMM or GaussianMixture
        self.regime_history: pd.DataFrame | None = None
        self.label_mapping: dict[int, str] = {}

        logger.info(
            "RegimeDetector initialised: n_regimes=%d, random_state=%d",
            n_regimes,
            random_state,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Training
    # ══════════════════════════════════════════════════════════════════════

    def train(
        self,
        features: pd.DataFrame,
        min_history_months: int = 36,
    ) -> None:
        """Fit the Gaussian HMM on historical feature data.

        Parameters
        ----------
        features : pd.DataFrame
            Z-score normalised feature matrix produced by
            :meth:`FeatureEngineer.compute_regime_features`.
            Must contain at least ``min_history_months`` rows.
        min_history_months : int, default 36
            Minimum number of monthly observations required to train.

        Raises
        ------
        ValueError
            If *features* has fewer rows than *min_history_months*.
        """
        if len(features) < min_history_months:
            raise ValueError(
                f"Insufficient training data: {len(features)} rows "
                f"(need >= {min_history_months})."
            )

        logger.info(
            "Training GaussianHMM on %d rows × %d features …",
            len(features),
            features.shape[1],
        )

        if _HAS_HMMLEARN:
            hmm = GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="full",
                n_iter=1000,
                random_state=self.random_state,
            )
        else:
            # Fallback: GaussianMixture (no temporal modelling)
            from sklearn.mixture import GaussianMixture
            hmm = GaussianMixture(
                n_components=self.n_regimes,
                covariance_type="full",
                max_iter=1000,
                random_state=self.random_state,
            )

        X = features.values
        hmm.fit(X)

        states = hmm.predict(X)
        self.label_mapping = self._assign_regime_labels(features, states)
        self.model = hmm

        logger.info(
            "HMM training complete.  Label mapping: %s",
            self.label_mapping,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Label assignment
    # ══════════════════════════════════════════════════════════════════════

    def _assign_regime_labels(
        self,
        features: pd.DataFrame,
        states: np.ndarray,
    ) -> dict[int, str]:
        """Map HMM integer states to meaningful regime names.

        For each HMM state we compute the mean of key features
        (``gdp_growth``, ``cpi_yoy``, ``vix_zscore``) and use a scoring
        approach to assign one of the four canonical regime names.

        Scoring logic
        -------------
        * **goldilocks**: highest growth + lowest inflation
        * **reflation**: highest growth + highest inflation
        * **stagflation**: lowest growth + highest inflation
        * **deflation**: lowest growth + lowest inflation

        Parameters
        ----------
        features : pd.DataFrame
            Feature matrix used during training.
        states : np.ndarray
            Predicted HMM states (integer array, same length as *features*).

        Returns
        -------
        dict[int, str]
            ``{hmm_state_int: regime_label}``.
        """
        # Determine available scoring columns
        growth_col = self._pick_column(features, ["gdp_growth", "sp500_momentum"])
        inflation_col = self._pick_column(features, ["cpi_yoy", "breakeven_5y"])
        risk_col = self._pick_column(features, ["vix_zscore", "hy_spread"])

        unique_states = sorted(set(states))

        # Compute per-state means for the key axes
        state_stats: dict[int, dict[str, float]] = {}
        for s in unique_states:
            mask = states == s
            subset = features.loc[mask] if isinstance(mask, pd.Series) else features.iloc[mask]

            growth_mean = subset[growth_col].mean() if growth_col else 0.0
            inflation_mean = subset[inflation_col].mean() if inflation_col else 0.0
            risk_mean = subset[risk_col].mean() if risk_col else 0.0

            state_stats[s] = {
                "growth": float(growth_mean),
                "inflation": float(inflation_mean),
                "risk": float(risk_mean),
            }

        logger.debug("State statistics: %s", state_stats)

        # Score each state for each regime candidate
        # goldilocks:   high growth, low inflation
        # reflation:    high growth, high inflation
        # stagflation:  low growth,  high inflation
        # deflation:    low growth,  low inflation
        scores: dict[int, dict[str, float]] = {}
        for s, stats in state_stats.items():
            g = stats["growth"]
            i = stats["inflation"]
            scores[s] = {
                "goldilocks": g - i,        # high growth, low inflation
                "reflation": g + i,         # high growth, high inflation
                "stagflation": -g + i,      # low growth,  high inflation
                "deflation": -g - i,        # low growth,  low inflation
            }

        # Greedy assignment: pick the best (state, regime) pair, remove
        # both from the available pool, and repeat.
        mapping: dict[int, str] = {}
        available_states = set(unique_states)
        available_regimes = set(_REGIME_LABELS)

        while available_states and available_regimes:
            best_score = -np.inf
            best_state: int = -1
            best_regime: str = ""

            for s in available_states:
                for r in available_regimes:
                    sc = scores[s][r]
                    if sc > best_score:
                        best_score = sc
                        best_state = s
                        best_regime = r

            mapping[best_state] = best_regime
            available_states.discard(best_state)
            available_regimes.discard(best_regime)

        logger.info("Regime label assignment: %s", mapping)
        return mapping

    @staticmethod
    def _pick_column(
        df: pd.DataFrame,
        candidates: list[str],
    ) -> str | None:
        """Return the first column name from *candidates* present in *df*."""
        for c in candidates:
            if c in df.columns:
                return c
        return None

    # ══════════════════════════════════════════════════════════════════════
    # Prediction — single point
    # ══════════════════════════════════════════════════════════════════════

    def predict_regime(
        self,
        features: pd.DataFrame,
    ) -> tuple[str, float]:
        """Predict the current regime from the latest observation.

        Parameters
        ----------
        features : pd.DataFrame
            Feature matrix; the *last row* is treated as "current".

        Returns
        -------
        tuple[str, float]
            ``(regime_name, confidence_score)`` where confidence is
            the posterior probability assigned to the most-likely state.

        Raises
        ------
        RuntimeError
            If the model has not been trained yet.
        """
        self._ensure_trained()

        assert self.model is not None  # type guard after _ensure_trained

        probas = self.model.predict_proba(features.values)
        latest_proba = probas[-1]

        best_state = int(np.argmax(latest_proba))
        confidence = float(latest_proba[best_state])
        regime_name = self.label_mapping.get(best_state, f"unknown_{best_state}")

        logger.info(
            "Current regime: %s (state=%d, confidence=%.2f%%)",
            regime_name,
            best_state,
            confidence * 100,
        )
        return regime_name, confidence

    # ══════════════════════════════════════════════════════════════════════
    # Prediction — full history
    # ══════════════════════════════════════════════════════════════════════

    def predict_regime_history(
        self,
        features: pd.DataFrame,
    ) -> pd.DataFrame:
        """Classify every historical row into a regime.

        Parameters
        ----------
        features : pd.DataFrame
            Full feature matrix (datetime-indexed).

        Returns
        -------
        pd.DataFrame
            Columns: ``date``, ``regime``, ``confidence``, ``raw_state``.
            A persistence filter is applied to prevent whipsawing.
        """
        self._ensure_trained()
        assert self.model is not None

        X = features.values
        raw_states = self.model.predict(X)
        probas = self.model.predict_proba(X)

        # Map states to regime names
        regime_names = pd.Series(
            [self.label_mapping.get(int(s), f"unknown_{s}") for s in raw_states],
            index=features.index,
            name="regime",
        )
        confidence = pd.Series(
            [float(probas[i, int(s)]) for i, s in enumerate(raw_states)],
            index=features.index,
            name="confidence",
        )

        # Apply persistence filter
        filtered_regimes = self._apply_persistence_filter(regime_names)

        history = pd.DataFrame(
            {
                "date": features.index,
                "regime": filtered_regimes.values,
                "confidence": confidence.values,
                "raw_state": raw_states,
            }
        )
        history.set_index("date", inplace=True)

        self.regime_history = history
        logger.info(
            "Regime history computed: %d rows, regimes=%s",
            len(history),
            history["regime"].value_counts().to_dict(),
        )
        return history

    # ══════════════════════════════════════════════════════════════════════
    # Persistence filter
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _apply_persistence_filter(
        regime_series: pd.Series,
        min_periods: int = 2,
    ) -> pd.Series:
        """Require ``min_periods`` consecutive identical signals before switching.

        Prevents whipsawing between regimes on noisy month-to-month
        transitions.  The filter keeps the *previous* regime until the
        new regime has been signalled for ``min_periods`` consecutive
        observations.

        Parameters
        ----------
        regime_series : pd.Series
            Raw (unfiltered) regime string series.
        min_periods : int, default 2
            Number of consecutive identical signals required before
            switching.

        Returns
        -------
        pd.Series
            Filtered regime series with reduced whipsawing.
        """
        if len(regime_series) <= min_periods:
            return regime_series.copy()

        filtered = regime_series.copy()
        current_regime = filtered.iloc[0]
        streak = 1

        for i in range(1, len(filtered)):
            candidate = regime_series.iloc[i]
            if candidate == current_regime:
                streak += 1
                filtered.iloc[i] = current_regime
            else:
                # Check if there are enough consecutive signals ahead
                consecutive = 1
                for j in range(i + 1, min(i + min_periods, len(regime_series))):
                    if regime_series.iloc[j] == candidate:
                        consecutive += 1
                    else:
                        break

                if consecutive >= min_periods:
                    # Genuine switch
                    current_regime = candidate
                    streak = 1
                    filtered.iloc[i] = current_regime
                else:
                    # Keep old regime
                    filtered.iloc[i] = current_regime

        return filtered

    # ══════════════════════════════════════════════════════════════════════
    # Walk-forward validation (PRIMARY method)
    # ══════════════════════════════════════════════════════════════════════

    def walk_forward_predict(
        self,
        features: pd.DataFrame,
        initial_train_months: int = 60,
        step_months: int = 1,
    ) -> pd.DataFrame:
        """Walk-forward regime prediction to avoid look-ahead bias.

        This is the **primary prediction method**.  It trains the HMM on
        an expanding window and predicts the next ``step_months`` out of
        sample at each step.

        Workflow
        --------
        1. Start with the first ``initial_train_months`` of data.
        2. Train the HMM on that window.
        3. Predict the next ``step_months``.
        4. Expand the window by ``step_months``.
        5. Repeat until the end of the data.
        6. Return the combined predictions.

        Parameters
        ----------
        features : pd.DataFrame
            Full feature matrix (monthly frequency, datetime-indexed).
        initial_train_months : int, default 60
            Size of the first training window in months.
        step_months : int, default 1
            Number of months to predict and advance at each step.

        Returns
        -------
        pd.DataFrame
            Columns: ``date``, ``regime``, ``confidence``, ``raw_state``.

        Raises
        ------
        ValueError
            If *features* has fewer rows than *initial_train_months*.
        """
        n = len(features)
        if n < initial_train_months:
            raise ValueError(
                f"Insufficient data for walk-forward: {n} rows "
                f"(need >= {initial_train_months})."
            )

        logger.info(
            "Walk-forward prediction: %d total rows, "
            "initial_train=%d months, step=%d month(s).",
            n,
            initial_train_months,
            step_months,
        )

        all_predictions: list[dict[str, Any]] = []
        train_end = initial_train_months

        while train_end < n:
            # --- Train on [0 : train_end) ---
            train_data = features.iloc[:train_end]
            try:
                self.train(train_data, min_history_months=36)
            except Exception:
                logger.warning(
                    "Walk-forward: training failed at train_end=%d, skipping.",
                    train_end,
                    exc_info=True,
                )
                train_end += step_months
                continue

            assert self.model is not None

            # --- Predict [train_end : train_end + step_months) ---
            predict_end = min(train_end + step_months, n)
            predict_data = features.iloc[:predict_end]  # full history up to predict

            X_all = predict_data.values
            states = self.model.predict(X_all)
            probas = self.model.predict_proba(X_all)

            # Only keep the newly predicted rows
            for idx in range(train_end, predict_end):
                state = int(states[idx])
                conf = float(probas[idx, state])
                regime = self.label_mapping.get(state, f"unknown_{state}")
                all_predictions.append(
                    {
                        "date": features.index[idx],
                        "regime": regime,
                        "confidence": conf,
                        "raw_state": state,
                    }
                )

            train_end += step_months

        if not all_predictions:
            logger.warning("Walk-forward produced no predictions.")
            return pd.DataFrame(
                columns=["date", "regime", "confidence", "raw_state"]
            )

        result = pd.DataFrame(all_predictions)
        result.set_index("date", inplace=True)

        # Apply persistence filter to the walk-forward predictions
        result["regime"] = self._apply_persistence_filter(
            result["regime"]
        ).values

        self.regime_history = result

        logger.info(
            "Walk-forward complete: %d predictions. Distribution: %s",
            len(result),
            result["regime"].value_counts().to_dict(),
        )
        return result

    # ══════════════════════════════════════════════════════════════════════
    # Summary & diagnostics
    # ══════════════════════════════════════════════════════════════════════

    def get_regime_summary(self) -> dict[str, Any]:
        """Return summary statistics about regime classifications.

        Returns
        -------
        dict
            Keys:

            * ``pct_time`` – ``dict[str, float]`` percentage of time in
              each regime.
            * ``avg_duration`` – ``dict[str, float]`` average consecutive
              duration (months) per regime.
            * ``transition_matrix`` – ``pd.DataFrame`` regime transition
              probabilities.
            * ``total_observations`` – ``int`` total classified rows.

        Raises
        ------
        RuntimeError
            If no regime history is available.
        """
        if self.regime_history is None or self.regime_history.empty:
            raise RuntimeError(
                "No regime history available.  Run predict_regime_history() "
                "or walk_forward_predict() first."
            )

        history = self.regime_history
        regimes = history["regime"]
        total = len(regimes)

        # Percentage of time in each regime
        pct_time: dict[str, float] = {}
        for label in _REGIME_LABELS:
            count = int((regimes == label).sum())
            pct_time[label] = round(count / total * 100, 2) if total > 0 else 0.0

        # Average consecutive duration
        avg_duration = self._compute_avg_duration(regimes)

        # Transition matrix
        trans_matrix = self.get_transition_matrix()

        summary = {
            "pct_time": pct_time,
            "avg_duration": avg_duration,
            "transition_matrix": trans_matrix,
            "total_observations": total,
        }

        logger.info("Regime summary: %s", {k: v for k, v in summary.items() if k != "transition_matrix"})
        return summary

    @staticmethod
    def _compute_avg_duration(regimes: pd.Series) -> dict[str, float]:
        """Compute the average consecutive run-length per regime.

        Parameters
        ----------
        regimes : pd.Series
            Series of regime labels.

        Returns
        -------
        dict[str, float]
            Average duration (in observations / months) per regime.
        """
        durations: dict[str, list[int]] = {r: [] for r in _REGIME_LABELS}

        if len(regimes) == 0:
            return {r: 0.0 for r in _REGIME_LABELS}

        current = regimes.iloc[0]
        run_length = 1

        for i in range(1, len(regimes)):
            if regimes.iloc[i] == current:
                run_length += 1
            else:
                if current in durations:
                    durations[current].append(run_length)
                current = regimes.iloc[i]
                run_length = 1

        # Final run
        if current in durations:
            durations[current].append(run_length)

        avg: dict[str, float] = {}
        for regime, runs in durations.items():
            avg[regime] = round(np.mean(runs), 2) if runs else 0.0

        return avg

    def get_transition_matrix(self) -> pd.DataFrame:
        """Compute empirical regime transition probabilities.

        Returns
        -------
        pd.DataFrame
            Square DataFrame where ``[row, col]`` is the probability of
            transitioning from regime ``row`` to regime ``col``.

        Raises
        ------
        RuntimeError
            If no regime history is available.
        """
        if self.regime_history is None or self.regime_history.empty:
            raise RuntimeError(
                "No regime history available.  Run predict_regime_history() "
                "or walk_forward_predict() first."
            )

        regimes = self.regime_history["regime"]
        labels = _REGIME_LABELS

        # Count transitions
        counts = pd.DataFrame(
            np.zeros((len(labels), len(labels)), dtype=float),
            index=labels,
            columns=labels,
        )

        for i in range(len(regimes) - 1):
            from_regime = regimes.iloc[i]
            to_regime = regimes.iloc[i + 1]
            if from_regime in labels and to_regime in labels:
                counts.loc[from_regime, to_regime] += 1

        # Normalise rows to probabilities
        row_sums = counts.sum(axis=1)
        trans_matrix = counts.div(row_sums, axis=0).fillna(0.0)

        logger.debug("Transition matrix:\n%s", trans_matrix)
        return trans_matrix

    # ══════════════════════════════════════════════════════════════════════
    # Model persistence
    # ══════════════════════════════════════════════════════════════════════

    def save_model(self, path: Path) -> None:
        """Serialise the trained model, label mapping, and metadata to disk.

        Parameters
        ----------
        path : Path
            Destination file path (typically ``*.pkl``).

        Raises
        ------
        RuntimeError
            If the model has not been trained yet.
        """
        self._ensure_trained()

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "model": self.model,
            "label_mapping": self.label_mapping,
            "n_regimes": self.n_regimes,
            "random_state": self.random_state,
            "regime_history": self.regime_history,
        }

        with open(path, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)

        logger.info("Model saved to %s", path)

    def load_model(self, path: Path) -> None:
        """Load a previously serialised model from disk.

        Parameters
        ----------
        path : Path
            Source file path (typically ``*.pkl``).

        Raises
        ------
        FileNotFoundError
            If *path* does not exist.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        with open(path, "rb") as fh:
            payload: dict[str, Any] = pickle.load(fh)  # noqa: S301

        self.model = payload["model"]
        self.label_mapping = payload["label_mapping"]
        self.n_regimes = payload.get("n_regimes", self.n_regimes)
        self.random_state = payload.get("random_state", self.random_state)
        self.regime_history = payload.get("regime_history")

        logger.info(
            "Model loaded from %s.  Label mapping: %s",
            path,
            self.label_mapping,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ══════════════════════════════════════════════════════════════════════

    def _ensure_trained(self) -> None:
        """Raise if the model has not been trained."""
        if self.model is None:
            raise RuntimeError(
                "RegimeDetector model has not been trained.  "
                "Call train() or load_model() first."
            )
