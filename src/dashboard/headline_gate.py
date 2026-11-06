"""Upload gate for the US headline written by ``/tasks/refresh``.

``run_backtest.py`` saves the targeted clock (CPI+1 / GDP+4, VIX and momentum
lagged one month — ``lag_honesty.csv`` row ``B_targeted``) as
``Optimized Regime Strategy``. One extra session moves that 20-year CAGR by
basis points. A broken macro fetch, or a comparison against a different
clock, moves it by whole points.

The on-disk ``20yr_comparison.csv`` at the start of a refresh is whatever
GCS last accepted, or the image bake when the bucket has no object. That
file can still be the month-end look-ahead headline (``A_lookahead``, about
14.47% CAGR / 13.9% max drawdown) from before targeted-path uploads were
accepted. Comparing a fresh targeted run (~13.1% / 14.13%) to that row
trips the 1 percentage-point rail every day and nothing new is uploaded.

Baseline, in order:

1. ``data/backtest_results/headline_baseline.json`` when its ``path`` is
   ``B_targeted``. ``/tasks/refresh`` writes this only after a run it is
   willing to upload, and GCS startup download brings it back. This is the
   day-to-day rail against the last accepted targeted package.
2. Otherwise the ``B_targeted`` row of ``lag_honesty.csv`` when the on-disk
   comparison row is more than the jump limit away from it. The comparison
   row is then a different methodology and is not the baseline.
3. Otherwise the on-disk comparison row, when it agrees with ``B_targeted``
   or when that row is missing (the previous gate).

The rail itself is unchanged: block when absolute CAGR differs by more than
1 percentage point, or when max drawdown worsens by more than 1 percentage
point. An improvement in max drawdown is not a block.

``HEADLINE_GATE_RESET=1`` (also ``true`` / ``yes``) skips this comparison for
one refresh and records the new headline as the next baseline. Use it only
when a real methodology change should move the targeted headline by more
than 1 percentage point. Remove the variable after that refresh succeeds.
Leaving it set disables the rail. The FRED input check and the one-series
consistency check inside ``run_backtest.py`` still run.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Path ``run_backtest.py`` writes, and the matching ``lag_honesty.csv`` row.
PRODUCTION_PATH = "B_targeted"
PRODUCTION_ROW = "Optimized Regime Strategy"

# Same thresholds the refresh route used when it compared the raw CSV row
# to itself: absolute CAGR jump, and max-drawdown worsening, in percentage
# points. Max drawdown is stored as a positive magnitude (14.13 means -14.13%).
CAGR_JUMP_LIMIT_PP = 1.0
MAXDD_WORSEN_LIMIT_PP = 1.0

LAG_HONESTY_REL = "data/backtest_results/lag_honesty.csv"
BASELINE_REL = "data/backtest_results/headline_baseline.json"
RESET_ENV = "HEADLINE_GATE_RESET"


@dataclass(frozen=True)
class HeadlineGateDecision:
    block: bool
    baseline_source: str
    baseline: tuple[float, float] | None
    reason: str
    would_block: bool

    def as_dict(self) -> dict:
        return {
            "block": self.block,
            "baseline_source": self.baseline_source,
            "baseline": _json_pair(self.baseline),
            "reason": self.reason,
            "would_block": self.would_block,
        }


def reset_requested(environ: dict | None = None) -> bool:
    """True when an operator has armed a one-refresh baseline reset."""
    env = os.environ if environ is None else environ
    return str(env.get(RESET_ENV, "")).strip().lower() in {"1", "true", "yes"}


def comparison_headline_pp(annual_return, max_drawdown) -> tuple[float, float] | None:
    """Display percents from ``20yr_comparison.csv`` to percentage points.

    ``"13.10%"`` and ``"13.10"`` both become ``13.10``. That matches the
    previous refresh parser, which stripped a trailing percent sign and
    compared the printed number. A non-numeric cell returns None.
    """
    cagr = _display_percent(annual_return)
    drawdown = _display_percent(max_drawdown)
    if not _finite(cagr) or not _finite(drawdown):
        return None
    return (cagr, drawdown)


def headline_from_comparison_frame(frame: pd.DataFrame | None) -> tuple[float, float] | None:
    """Production row of a comparison CSV, in percentage points."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    if PRODUCTION_ROW in frame.index:
        row = frame.loc[PRODUCTION_ROW]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
    else:
        row = frame.iloc[0]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
    getter = row.get if hasattr(row, "get") else (lambda key, default=None: default)
    return comparison_headline_pp(getter("Annual Return"), getter("Max Drawdown"))


def fraction_headline_pp(cagr, max_drawdown) -> tuple[float, float] | None:
    """Decimal fractions from ``lag_honesty.csv`` (0.131) to percentage points."""
    try:
        cagr_f = float(cagr)
        dd_f = float(max_drawdown)
    except (TypeError, ValueError):
        return None
    if not _finite(cagr_f) or not _finite(dd_f):
        return None
    return (cagr_f * 100.0, dd_f * 100.0)


def load_same_path_headline(path: Path, mode: str = PRODUCTION_PATH) -> tuple[float, float] | None:
    """``B_targeted`` CAGR and max drawdown from ``lag_honesty.csv``."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        table = pd.read_csv(path, index_col=0)
    except Exception:
        return None
    if mode not in table.index:
        return None
    row = table.loc[mode]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    return fraction_headline_pp(row.get("cagr"), row.get("max_dd"))


def load_uploaded_baseline(path: Path, mode: str = PRODUCTION_PATH) -> tuple[float, float] | None:
    """Last accepted targeted headline, or None when the file is absent or other-path.

    A sidecar stamped with a different ``path`` is ignored. That is how an
    older look-ahead package cannot become the baseline by sharing a filename.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("path") != mode:
        return None
    try:
        cagr = float(payload["annual_return_pct"])
        drawdown = float(payload["max_drawdown_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    if not _finite(cagr) or not _finite(drawdown):
        return None
    return (cagr, drawdown)


def write_uploaded_baseline(path: Path, headline: tuple[float, float], mode: str = PRODUCTION_PATH) -> None:
    """Record the headline this refresh is about to upload."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "path": mode,
        "annual_return_pct": float(headline[0]),
        "max_drawdown_pct": float(headline[1]),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def headlines_agree(left: tuple[float, float] | None, right: tuple[float, float] | None) -> bool:
    """True when both headlines sit inside the jump limits of each other.

    Used to decide whether the on-disk comparison row is the same methodology
    as ``B_targeted``. The upload block for max drawdown is one-sided
    (worsening only); this check is two-sided so a look-ahead row cannot
    hide on either metric.
    """
    if left is None or right is None:
        return False
    return (
        abs(left[0] - right[0]) <= CAGR_JUMP_LIMIT_PP
        and abs(left[1] - right[1]) <= MAXDD_WORSEN_LIMIT_PP
    )


def headline_jumps(new: tuple[float, float] | None, baseline: tuple[float, float] | None) -> bool:
    """The historical rail: |ΔCAGR| > 1pp, or max drawdown worse by > 1pp."""
    if new is None or baseline is None:
        return False
    cagr_jump = abs(new[0] - baseline[0]) > CAGR_JUMP_LIMIT_PP
    drawdown_worse = (new[1] - baseline[1]) > MAXDD_WORSEN_LIMIT_PP
    return cagr_jump or drawdown_worse


def resolve_baseline(
    uploaded: tuple[float, float] | None,
    previous: tuple[float, float] | None,
    same_path: tuple[float, float] | None,
) -> tuple[tuple[float, float] | None, str, str]:
    """Pick the comparison point. Returns ``(baseline, source, reason)``."""
    if uploaded is not None:
        return (
            uploaded,
            "gcs_last_good",
            "comparing to the last accepted B_targeted upload",
        )
    if same_path is not None and previous is not None and not headlines_agree(previous, same_path):
        return (
            same_path,
            "same_path",
            "on-disk comparison headline disagrees with B_targeted; "
            "using the targeted path instead of that mismatched headline",
        )
    if previous is not None and (same_path is None or headlines_agree(previous, same_path)):
        return (
            previous,
            "last_comparison",
            "comparing to the on-disk production headline",
        )
    if same_path is not None:
        return (
            same_path,
            "same_path",
            "no prior comparison row; comparing to B_targeted",
        )
    return (None, "none", "no headline baseline available")


def evaluate_headline_gate(
    previous: tuple[float, float] | None,
    new: tuple[float, float] | None,
    same_path: tuple[float, float] | None,
    uploaded: tuple[float, float] | None = None,
    allow_reset: bool = False,
) -> HeadlineGateDecision:
    """Decide whether ``/tasks/refresh`` may upload the US backtest package.

    ``previous`` is the production row on disk before ``run_backtest.py``.
    ``new`` is that row after the run. ``same_path`` is ``B_targeted``.
    ``uploaded`` is the sidecar from the last accepted targeted upload.
    ``allow_reset`` records ``new`` as the next baseline without blocking.
    """
    baseline, source, reason = resolve_baseline(uploaded, previous, same_path)
    tripped = headline_jumps(new, baseline)
    if allow_reset:
        return HeadlineGateDecision(
            block=False,
            baseline_source="reset",
            baseline=baseline,
            reason=(
                f"{RESET_ENV} is set; this refresh skips the headline jump check. "
                "Unset it after the upload so the rail applies again."
            ),
            would_block=tripped,
        )
    if tripped:
        return HeadlineGateDecision(
            block=True,
            baseline_source=source,
            baseline=baseline,
            reason=reason + "; jump exceeds the 1 percentage-point rail",
            would_block=True,
        )
    return HeadlineGateDecision(
        block=False,
        baseline_source=source,
        baseline=baseline,
        reason=reason,
        would_block=False,
    )


def _display_percent(value) -> float:
    """``"13.10%"`` → ``13.10``. A bare number is already in percentage points."""
    if value is None or isinstance(value, bool):
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "—", "-", "nan", "None"}:
        return float("nan")
    try:
        return float(text)
    except ValueError:
        return float("nan")


def _finite(value: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in {float("inf"), float("-inf")}


def _json_pair(value: tuple[float, float] | None) -> list[float] | None:
    if value is None:
        return None
    return [round(float(value[0]), 4), round(float(value[1]), 4)]
