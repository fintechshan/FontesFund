"""One-series check for a published backtest.

The reported CAGR, the equity curve, and the monthly heatmap are three views
of one return series. A few basis points of CAGR can appear when the same
total return is annualized with a 252-day year instead of a calendar year.
That gap is year-count rounding. It is not a second backtest.

A monthly snapshot of the equity curve can also print a shallower max
drawdown than the daily peak-to-trough (about one to two percentage points
on this book). The published MaxDD is the daily one. This check does not
treat the monthly snapshot as the headline.

What fails the check is a real series split: the heatmap's compounded total
return, or the equity curve's total return / 252-day CAGR / daily max
drawdown, disagreeing with the reported row by more than the rounding tolerance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Displayed percents are rounded to 0.01 percentage point, and the engine
# stores total return and max drawdown to 4 decimals. 5bp covers that
# rounding. A different backtest path is percentage points away, not basis points.
CAGR_ABS_TOL = 0.0005
TOTAL_ABS_TOL = 0.001
DAILY_DD_ABS_TOL = 0.0005
TRADING_DAYS = 252


@dataclass
class ConsistencyReport:
    ok: bool
    messages: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def text(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines = [f"consistency {status}"]
        lines.extend(self.messages)
        return "\n".join(lines)


def _as_float_series(series: pd.Series) -> pd.Series:
    out = pd.Series(series).dropna().astype(float).sort_index()
    out.index = pd.to_datetime(out.index)
    return out


def equity_total_return(equity: pd.Series) -> float:
    """Total return of an engine equity curve.

    ``(1 + daily_returns).cumprod()`` ends at ``1 + total_return``, including
    when the first point is exactly 1 (a zero first-day return).
    """
    eq = _as_float_series(equity)
    if len(eq) == 0:
        return float("nan")
    return float(eq.iloc[-1] - 1.0)


def trading_day_cagr(total_return: float, n_days: int) -> float:
    years = max(n_days, 1) / TRADING_DAYS
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def calendar_cagr(total_return: float, equity: pd.Series) -> float:
    eq = _as_float_series(equity)
    if len(eq) < 2:
        return float("nan")
    years = max((eq.index[-1] - eq.index[0]).days, 1) / 365.25
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def compound_total(monthly: pd.Series) -> float:
    mr = _as_float_series(monthly)
    if len(mr) == 0:
        return float("nan")
    return float((1.0 + mr).prod() - 1.0)


def daily_max_drawdown(equity: pd.Series) -> float:
    eq = _as_float_series(equity)
    if len(eq) == 0:
        return float("nan")
    drawdown = eq / eq.cummax() - 1.0
    return float(abs(drawdown.min()))


def monthly_max_drawdown(equity: pd.Series) -> float:
    """Peak-to-trough using month-end equity only. Shallower than the daily path."""
    eq = _as_float_series(equity)
    if len(eq) == 0:
        return float("nan")
    month_end = eq.resample("ME").last().dropna()
    if len(month_end) == 0:
        return float("nan")
    drawdown = month_end / month_end.cummax() - 1.0
    return float(abs(drawdown.min()))


def verify_series(
    reported_cagr: float,
    reported_total: float,
    reported_max_dd: float,
    equity: pd.Series,
    monthly: pd.Series | None = None,
) -> ConsistencyReport:
    """Compare one reported row with its equity curve and monthly heatmap."""
    eq = _as_float_series(equity)
    messages: list[str] = []
    if len(eq) < 2 or not np.isfinite(reported_cagr) or not np.isfinite(reported_total):
        return ConsistencyReport(False, ["equity curve or reported CAGR/total is missing"])

    curve_total = equity_total_return(eq)
    curve_cagr = trading_day_cagr(curve_total, len(eq))
    curve_dd = daily_max_drawdown(eq)
    cal_cagr = calendar_cagr(curve_total, eq)
    month_dd = monthly_max_drawdown(eq)
    year_count_gap = curve_cagr - cal_cagr

    details = {
        "reported_cagr": reported_cagr,
        "reported_total": reported_total,
        "reported_max_dd_daily": reported_max_dd,
        "equity_total": curve_total,
        "equity_cagr_252": curve_cagr,
        "equity_cagr_calendar": cal_cagr,
        "year_count_gap": year_count_gap,
        "equity_max_dd_daily": curve_dd,
        "equity_max_dd_monthly_snapshot": month_dd,
        "max_dd_sampling_gap": curve_dd - month_dd,
    }

    def _close(name: str, left: float, right: float, tol: float) -> None:
        gap = abs(left - right)
        details[f"gap_{name}"] = gap
        if not np.isfinite(left) or not np.isfinite(right) or gap > tol:
            messages.append(
                f"{name} disagrees: reported {left:.6f} vs series {right:.6f} "
                f"(gap {gap:.6f}, tolerance {tol:.6f})"
            )

    _close("total_return", reported_total, curve_total, TOTAL_ABS_TOL)
    _close("cagr_252", reported_cagr, curve_cagr, CAGR_ABS_TOL)
    _close("max_dd_daily", reported_max_dd, curve_dd, DAILY_DD_ABS_TOL)

    if monthly is not None and len(_as_float_series(monthly)):
        heat_total = compound_total(monthly)
        details["heatmap_total"] = heat_total
        _close("heatmap_total", reported_total, heat_total, TOTAL_ABS_TOL)
        _close("heatmap_vs_equity", curve_total, heat_total, TOTAL_ABS_TOL)
    else:
        messages.append("monthly heatmap series is missing")

    messages.append(
        f"year-count gap {year_count_gap:.6f} "
        f"(252-day CAGR {curve_cagr:.6f}, calendar CAGR {cal_cagr:.6f}). "
        "A few basis points here is one series counted two ways."
    )
    messages.append(
        f"max-drawdown sampling gap {curve_dd - month_dd:.6f} "
        f"(daily {curve_dd:.6f}, month-end snapshot {month_dd:.6f}). "
        "The published figure is the daily peak-to-trough."
    )
    return ConsistencyReport(ok=not any(m.startswith(("total_return", "cagr_252", "max_dd_daily", "heatmap_", "monthly heatmap")) for m in messages), messages=messages, details=details)


def parse_percent(value) -> float:
    """'10.92%' -> 0.1092. A bare float is returned as-is."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return float("nan")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "—", "-", "nan"}:
        return float("nan")
    if text.endswith("%"):
        return float(text[:-1]) / 100.0
    return float(text)


def load_series_csv(path) -> pd.Series:
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    if frame.shape[1] == 0:
        return pd.Series(dtype=float)
    return frame.iloc[:, 0]


def verify_files(comparison_csv, equity_csv, monthly_csv, strategy: str = "Optimized Regime Strategy") -> ConsistencyReport:
    """Check the CSVs ``run_backtest.py`` writes for the headline strategy."""
    table = pd.read_csv(comparison_csv, index_col=0)
    if strategy not in table.index:
        return ConsistencyReport(False, [f"{strategy} is not in {comparison_csv}"])
    row = table.loc[strategy]
    return verify_series(
        reported_cagr=parse_percent(row.get("Annual Return")),
        reported_total=parse_percent(row.get("Total Return")),
        reported_max_dd=parse_percent(row.get("Max Drawdown")),
        equity=load_series_csv(equity_csv),
        monthly=load_series_csv(monthly_csv),
    )
