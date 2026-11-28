"""Read-only daily-overlay turnover ledger. It does not change official equity.

Production ``turnover_basis='legacy'`` charges 5 bps on monthly ``W_base``
only. The 200-day blend is a return mix. ``turnover_basis='book'`` charges
the pre-leverage book (``w_book``). HAR-RV ``vol_scale`` and the drawdown
scale are multiplied into returns and are not a separate turnover charge.

This ledger prices the asset vector the engine actually holds:

    w_final_t = vol_scale_t * dd_scale_t * w_book_t
    L1_t = sum_j |w_final_t,j - w_final_{t-1,j}|
    one_way_t = L1_t / 2
    cost_t(bps) = one_way_t * bps / 10_000

The first row has no prior weight, so its one-way turnover is 0. The vector
has no cash residual. ``one_way`` is the same convention as
``W_base.diff().abs().sum(axis=1) / 2`` in the engine.

Cost already inside the official return of this run, at that run's
``transaction_cost_bps`` (production is 5):

    legacy: blend * one_way(W_base) * bps * vol_scale * dd_scale
    sleeve: one_way(W_base) * bps * vol_scale * dd_scale
    book:   one_way(w_book) * bps * vol_scale * dd_scale

``blend = trend_ok + (1 - trend_ok) * bear_equity_frac``, which is the
weight on ``(r_base - sleeve_tx)`` in the legacy return mix. Because that
charge is inside the return, vol and drawdown scales multiply it.

Missed at 5 bps is ``cost(5) - embedded``. Missed at 8 bps is ``cost(8) -
embedded``. 8 bps is a sensitivity. It is not ``transaction_cost_bps`` and
it does not change the official book. Drag is the CAGR and total-return gap
from subtracting that missed series from this run's unadjusted returns.
CAGR uses ``len(days) / 252``, the same year as ``_compute_result``.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

FORMULA_ID = "final_position_half_l1_v1"
PRODUCTION_BPS = 5.0
SENSITIVITY_BPS = 8.0
TRADING_DAYS = 252.0

FORMULA = (
    "w_final = vol_scale * dd_scale * w_book; "
    "one_way = 0.5 * L1(w_final_t - w_final_{t-1}); "
    "cost(bps) = one_way * bps / 10000; "
    "embedded(legacy) = blend * one_way(W_base) * transaction_cost_bps * vol_scale * dd_scale; "
    "blend = trend_ok + (1 - trend_ok) * bear_equity_frac; "
    "missed(bps) = cost(bps) - embedded; "
    "drag = official unadjusted CAGR/total minus the same statistics after subtracting missed. "
    "8 bps is a sensitivity. Official equity is not rewritten."
)


def one_way_turnover(weights: pd.DataFrame) -> pd.Series:
    """Half the L1 of the day-to-day weight change. First row is 0."""
    frame = pd.DataFrame(weights).astype(float)
    turnover = frame.diff().abs().sum(axis=1) / 2.0
    return turnover.fillna(0.0).rename("one_way")


def final_position_weights(
    w_book: pd.DataFrame,
    vol_scale: pd.Series,
    dd_scale: pd.Series,
) -> pd.DataFrame:
    """Asset weights implied by leverage scale times drawdown scale times the book."""
    book = pd.DataFrame(w_book).astype(float)
    vol = pd.Series(vol_scale, index=book.index, dtype=float).reindex(book.index).astype(float)
    dd = pd.Series(dd_scale, index=book.index, dtype=float).reindex(book.index).astype(float)
    factor = vol * dd
    return book.mul(factor, axis=0)


def _align_factor(values, index: pd.Index) -> pd.Series:
    series = pd.Series(values, index=index, dtype=float).reindex(index).astype(float)
    return series.fillna(1.0)


def embedded_cost(
    *,
    turnover_basis: str,
    w_base: pd.DataFrame,
    w_book: pd.DataFrame,
    blend: pd.Series,
    vol_scale: pd.Series,
    dd_scale: pd.Series,
    transaction_cost_bps: float,
) -> pd.Series:
    """Transaction cost already inside this run's portfolio return, in return units."""
    index = pd.DataFrame(w_book).index
    rate = float(transaction_cost_bps) / 10_000.0
    sleeve_tx = one_way_turnover(w_base).reindex(index).fillna(0.0) * rate
    book_tx = one_way_turnover(w_book).reindex(index).fillna(0.0) * rate
    factor = _align_factor(vol_scale, index) * _align_factor(dd_scale, index)
    basis = str(turnover_basis or "legacy")
    if basis == "book":
        embedded = book_tx * factor
    elif basis == "sleeve":
        embedded = sleeve_tx * factor
    else:
        mix = pd.Series(blend, index=index, dtype=float).reindex(index).fillna(1.0)
        embedded = mix * sleeve_tx * factor
    return embedded.rename("embedded_cost")


def _path_stats(returns: pd.Series) -> dict[str, float]:
    series = pd.to_numeric(returns, errors="coerce").fillna(0.0).astype(float)
    total = float((1.0 + series).prod() - 1.0) if len(series) else 0.0
    years = (len(series) / TRADING_DAYS) if len(series) else 0.0
    if years <= 0:
        cagr = 0.0
    else:
        cagr = float((1.0 + total) ** (1.0 / max(years, 0.01)) - 1.0)
    return {
        "sessions": int(len(series)),
        "years_252": float(years),
        "total_return": total,
        "cagr": cagr,
    }


def _finite(value: float) -> Optional[float]:
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def build_overlay_cost_ledger(
    *,
    w_book: pd.DataFrame,
    w_base: pd.DataFrame,
    vol_scale: pd.Series,
    dd_scale: pd.Series,
    blend: pd.Series,
    official_returns: pd.Series,
    turnover_basis: str = "legacy",
    apply_equity_cut: bool = False,
    transaction_cost_bps: float = PRODUCTION_BPS,
    bear_equity_frac: Optional[float] = None,
) -> dict[str, Any]:
    """Diagnostic dict. ``official_returns`` is not modified."""
    book = pd.DataFrame(w_book).astype(float)
    base = pd.DataFrame(w_base).astype(float).reindex(index=book.index).fillna(0.0)
    official = pd.Series(official_returns, index=book.index, dtype=float).reindex(book.index)
    # A copy so a caller that still holds the Series cannot observe a write.
    official = official.copy()
    weights = final_position_weights(book, vol_scale, dd_scale)
    final_one_way = one_way_turnover(weights)
    sleeve_one_way = one_way_turnover(base)
    book_one_way = one_way_turnover(book)
    charged_bps = float(transaction_cost_bps)
    embedded = embedded_cost(
        turnover_basis=turnover_basis,
        w_base=base,
        w_book=book,
        blend=blend,
        vol_scale=vol_scale,
        dd_scale=dd_scale,
        transaction_cost_bps=charged_bps,
    )
    cost_5 = final_one_way * (PRODUCTION_BPS / 10_000.0)
    cost_8 = final_one_way * (SENSITIVITY_BPS / 10_000.0)
    missed_5 = cost_5 - embedded
    missed_8 = cost_8 - embedded
    # Book mode would charge pre-leverage w_book, then that charge would be
    # scaled because it sits inside the return. This is not the official path.
    book_embedded_5 = book_one_way * (PRODUCTION_BPS / 10_000.0) * _align_factor(vol_scale, book.index) * _align_factor(dd_scale, book.index)
    still_missed_vs_book_5 = cost_5 - book_embedded_5

    def drag(missed: pd.Series) -> dict[str, Any]:
        adjusted = official.fillna(0.0) - missed.fillna(0.0)
        base_stats = _path_stats(official.fillna(0.0))
        adj_stats = _path_stats(adjusted)
        years = base_stats["years_252"] or np.nan
        arithmetic = float(missed.fillna(0.0).mean() * TRADING_DAYS) if len(missed) else 0.0
        return {
            "arithmetic_annual_drag": _finite(arithmetic),
            "sum_of_daily_drag": _finite(float(missed.fillna(0.0).sum())),
            "official_cagr": _finite(base_stats["cagr"]),
            "official_total_return": _finite(base_stats["total_return"]),
            "adjusted_cagr": _finite(adj_stats["cagr"]),
            "adjusted_total_return": _finite(adj_stats["total_return"]),
            "cagr_drag": _finite(base_stats["cagr"] - adj_stats["cagr"]),
            "total_return_drag": _finite(base_stats["total_return"] - adj_stats["total_return"]),
            "cagr_drag_bps": _finite((base_stats["cagr"] - adj_stats["cagr"]) * 10_000.0),
            "total_return_drag_bps": _finite((base_stats["total_return"] - adj_stats["total_return"]) * 10_000.0),
            "arithmetic_annual_drag_bps": _finite(arithmetic * 10_000.0),
            "years_252": _finite(years),
        }

    start = None
    end = None
    if len(book.index):
        start = str(pd.Timestamp(book.index[0]).date())
        end = str(pd.Timestamp(book.index[-1]).date())
    annual_final = float(final_one_way.mean() * TRADING_DAYS) if len(final_one_way) else 0.0
    annual_sleeve = float(sleeve_one_way.mean() * TRADING_DAYS) if len(sleeve_one_way) else 0.0
    annual_book = float(book_one_way.mean() * TRADING_DAYS) if len(book_one_way) else 0.0
    return {
        "status": "computed",
        "diagnostic_only": True,
        "changes_official_equity": False,
        "changes_live_positions": False,
        "formula_id": FORMULA_ID,
        "formula": FORMULA,
        "as_of": end,
        "sample_start": start,
        "sessions": int(len(book.index)),
        "turnover_basis": str(turnover_basis or "legacy"),
        "apply_equity_cut": bool(apply_equity_cut),
        "transaction_cost_bps": charged_bps,
        "bear_equity_frac": None if bear_equity_frac is None else float(bear_equity_frac),
        "bps_assumptions": {
            "production_one_way_bps": PRODUCTION_BPS,
            "sensitivity_one_way_bps": SENSITIVITY_BPS,
            "embedded_bps": charged_bps,
            "note": (
                "5 bps is the production one-way rate. 8 bps reprices the same "
                "final-position turnover and does not change transaction_cost_bps. "
                "Embedded cost stays at the rate this run actually charged."
            ),
        },
        "turnover": {
            "final_position_one_way_annualized": _finite(annual_final),
            "legacy_w_base_one_way_annualized": _finite(annual_sleeve),
            "preleverage_book_one_way_annualized": _finite(annual_book),
            "definition": "annualized = mean(daily one-way turnover) * 252",
        },
        "vs_official_unadjusted": {
            "at_5bps": drag(missed_5),
            "at_8bps": drag(missed_8),
        },
        "still_uncosted_if_book_basis": {
            "note": (
                "Counterfactual only. Book mode charges one-way turnover of the "
                "pre-leverage book, then that charge is scaled by vol_scale * dd_scale "
                "because it is inside the return. It still does not charge turnover "
                "that comes from the scales themselves. Not applied to official equity."
            ),
            "at_5bps": drag(still_missed_vs_book_5),
        },
    }


def unavailable_ledger(reason: str) -> dict[str, Any]:
    """Placeholder so Auditor section 7 can show the formula before a recompute."""
    return {
        "status": "not_computed",
        "diagnostic_only": True,
        "changes_official_equity": False,
        "changes_live_positions": False,
        "formula_id": FORMULA_ID,
        "formula": FORMULA,
        "reason": reason,
        "bps_assumptions": {
            "production_one_way_bps": PRODUCTION_BPS,
            "sensitivity_one_way_bps": SENSITIVITY_BPS,
            "note": (
                "5 bps is the production one-way rate. 8 bps is a sensitivity. "
                "Neither figure is applied to the official equity curve."
            ),
        },
    }


def attach_saved_equity_rail(
    ledger: Mapping[str, Any],
    engine_equity: pd.Series,
    saved_equity: pd.Series,
    saved_path: str,
) -> dict[str, Any]:
    """Record how this run's equity sits against the published CSV. No rewrite."""
    payload = dict(ledger)
    engine = pd.to_numeric(engine_equity, errors="coerce").dropna()
    saved = pd.to_numeric(saved_equity, errors="coerce").dropna()
    engine.index = pd.to_datetime(engine.index)
    saved.index = pd.to_datetime(saved.index)
    overlap = engine.index.intersection(saved.index)
    gap = None
    if len(overlap):
        gap = float((engine.reindex(overlap) - saved.reindex(overlap)).abs().max())
    payload["saved_equity_rail"] = {
        "path": saved_path,
        "engine_start": str(engine.index.min().date()) if len(engine) else None,
        "engine_end": str(engine.index.max().date()) if len(engine) else None,
        "saved_start": str(saved.index.min().date()) if len(saved) else None,
        "saved_end": str(saved.index.max().date()) if len(saved) else None,
        "overlap_sessions": int(len(overlap)),
        "max_abs_equity_gap": gap,
        "note": (
            "Drag above is versus this run's unadjusted returns. "
            "The saved CSV is the published Path B rail. A gap means this "
            "recompute is not a substitute for the published CAGR."
        ),
    }
    return payload
