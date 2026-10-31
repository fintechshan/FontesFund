"""Auditor checks for the Canadian book.

Same contract as the US checks: a missing series is a failed check, not a
skipped one. Path B is the published CDN book. Path A (month-end look-ahead)
and path C (first-release vintage) are comparison rows.
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from src.backtester.cdn_clock import (
    CDN_BENCHMARK,
    CDN_COMPARISON,
    CDN_CONFIG,
    CDN_EQUITY,
    CDN_HONESTY,
    CDN_MONTHLY,
    CDN_PRICE_CACHE,
    US_EQUITY,
    prove_cdn_clock,
)
from src.backtester.consistency import parse_percent, verify_files

CHECK_PRICE = "CDN price freshness"
CHECK_ARTIFACT = "CDN artifact freshness"
CHECK_CONSISTENCY = "CDN backtest consistency"
CHECK_HEATMAP = "CDN heatmap benchmark"
CHECK_CLOCK = "CDN clock"
CHECK_PATHS = "CDN path A/B/C"

CDN_CHECKS = (
    CHECK_PRICE,
    CHECK_ARTIFACT,
    CHECK_CONSISTENCY,
    CHECK_HEATMAP,
    CHECK_CLOCK,
    CHECK_PATHS,
)

# US daily FRED thresholds. Used only when no US sample is available to
# compare against. The binding CDN test is "not older than the US book".
_STALE_WARN_DAYS = 10
_STALE_FAIL_DAYS = 21
_LAG_VS_US_DAYS = 5
# Same gaps the US auditor uses for lookahead and the unlagged premium.
_LOOKAHEAD_GAP = 0.002
_UNLAGGED_TIE = 0.005
# CLAUDE: vintage (C) should sit at or below targeted (B). Far above means
# the release date was aligned backwards.
_VINTAGE_ABOVE_B = 0.01


def _row(check, status, value, threshold, location, remedy, desc) -> dict:
    return {
        "check": check,
        "status": status,
        "value": value,
        "threshold": threshold,
        "location": location,
        "remedy": remedy,
        "desc": desc,
    }


def _read_series(path) -> pd.Series:
    file = path
    if file is None or not file.exists():
        return pd.Series(dtype=float)
    frame = pd.read_csv(file, index_col=0, parse_dates=True)
    if frame.shape[1] == 0:
        return pd.Series(dtype=float)
    series = frame.iloc[:, 0].dropna()
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


def _end(series) -> pd.Timestamp | None:
    if series is None or len(series) == 0:
        return None
    return pd.Timestamp(series.index.max())


def _internal_gaps(prices: pd.DataFrame) -> list[str]:
    gaps = []
    for col in prices.columns:
        series = prices[col]
        first = series.first_valid_index()
        if first is None:
            continue
        nans = int(series.loc[first:].isna().sum())
        if nans:
            gaps.append(f"{col} ({nans})")
    return gaps


def _published_cagr(comparison_path) -> float:
    if comparison_path is None or not comparison_path.exists():
        return float("nan")
    table = pd.read_csv(comparison_path, index_col=0)
    from config.cdn_regime_rules import CDN_AB_WINNER
    if CDN_AB_WINNER in table.index:
        row = table.loc[CDN_AB_WINNER]
    elif len(table):
        row = table.iloc[0]
    else:
        return float("nan")
    return parse_percent(row.get("Annual Return"))


def _as_float(value) -> float:
    return parse_percent(value)


def audit_cdn_book(
    prices: pd.DataFrame | None = None,
    us_prices: pd.DataFrame | None = None,
    us_equity: pd.Series | None = None,
    cdn_equity: pd.Series | None = None,
    monthly: pd.Series | None = None,
    benchmark: pd.Series | None = None,
    honesty: pd.DataFrame | None = None,
    clock_config: dict | None = None,
    today=None,
    load_defaults: bool = True,
) -> list[dict]:
    """Six CDN checks. Always returned, including when the cache is absent."""
    today = pd.Timestamp(today or datetime.now())
    if today.tzinfo is not None:
        today = today.tz_convert(None)
    today = today.normalize()
    checks = [
        _price_check(prices, us_prices, today, load_defaults),
        _artifact_check(us_equity, cdn_equity, load_defaults),
        _consistency_check(),
        _heatmap_check(monthly, benchmark, cdn_equity, load_defaults),
        _clock_check(clock_config, load_defaults),
        _path_check(honesty, load_defaults),
    ]
    return checks


def _price_check(prices, us_prices, today, load_defaults) -> dict:
    location = "data/cache/cdn_price_data.csv"
    frame = prices
    if frame is None and load_defaults and CDN_PRICE_CACHE.exists():
        frame = pd.read_csv(CDN_PRICE_CACHE, index_col=0, parse_dates=True)
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return _row(
            CHECK_PRICE, "FAIL", "No Data", "TSX price cache present and not behind the US sample",
            location,
            "Run scripts/run_cdn_backtest.py to write data/cache/cdn_price_data.csv.",
            "CDN price cache is missing. This check does not pass by omission.",
        )
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index)
    cdn_end = frame.index.max()
    gaps = _internal_gaps(frame)
    us_end = None
    if isinstance(us_prices, pd.DataFrame) and not us_prices.empty:
        us_index = pd.to_datetime(us_prices.index)
        us_end = us_index.max()
    parts = [f"CDN prices end {pd.Timestamp(cdn_end).date()}."]
    status = "PASS"
    remedy = "None required. CDN prices cover the US sample without internal gaps."
    if us_end is not None:
        lag_days = int((pd.Timestamp(us_end).normalize() - pd.Timestamp(cdn_end).normalize()).days)
        parts.append(f"US prices end {pd.Timestamp(us_end).date()} (CDN is {lag_days}d behind).")
        if lag_days > _LAG_VS_US_DAYS:
            status = "FAIL"
            remedy = "Refresh the TSX cache. CDN prices must not lag the US price sample."
            parts.append(f"CDN price history stops more than {_LAG_VS_US_DAYS} days before US.")
    else:
        age = int((today - pd.Timestamp(cdn_end).normalize()).days)
        parts.append(f"{age}d old versus the audit date.")
        if age > _STALE_FAIL_DAYS:
            status = "FAIL"
            remedy = "Refresh the TSX cache. No US sample was loaded to compare against."
            parts.append(f"Stale CDN prices (>{_STALE_FAIL_DAYS}d).")
        elif age > _STALE_WARN_DAYS:
            status = "WARNING"
            remedy = "Refresh the TSX cache."
            parts.append(f"CDN prices are older than {_STALE_WARN_DAYS} days.")
    if gaps:
        if status == "PASS":
            status = "WARNING"
            remedy = "Forward-fill or re-download the TSX names with internal gaps."
        parts.append("Internal gaps: " + ", ".join(gaps[:4]) + ".")
    return _row(
        CHECK_PRICE, status, pd.Timestamp(cdn_end).strftime("%Y-%m-%d"),
        f"Within {_LAG_VS_US_DAYS}d of the US sample; 0 internal gaps",
        location, remedy, " ".join(parts),
    )


def _artifact_check(us_equity, cdn_equity, load_defaults) -> dict:
    location = "data/backtest_results/cdn_equity_curve.csv"
    if cdn_equity is not None and len(cdn_equity):
        cdn = cdn_equity.dropna().copy()
        cdn.index = pd.to_datetime(cdn.index)
    elif load_defaults:
        cdn = _read_series(CDN_EQUITY)
    else:
        cdn = pd.Series(dtype=float)
    if len(cdn) == 0:
        return _row(
            CHECK_ARTIFACT, "FAIL", "No curve", "CDN equity ends with the US curve",
            location,
            "Run scripts/run_cdn_backtest.py and keep the curve next to the US curve.",
            "CDN equity curve is missing.",
        )
    us = us_equity if us_equity is not None and len(us_equity) else (
        _read_series(US_EQUITY) if load_defaults else pd.Series(dtype=float)
    )
    cdn_end = _end(cdn)
    if us is None or len(us) == 0:
        return _row(
            CHECK_ARTIFACT, "WARNING", pd.Timestamp(cdn_end).strftime("%Y-%m-%d"),
            "US equity curve loaded",
            location,
            "Load the US equity curve so CDN staleness can be compared.",
            f"CDN curve ends {pd.Timestamp(cdn_end).date()}. The US curve was not loaded.",
        )
    us_end = _end(us)
    lag_days = int((pd.Timestamp(us_end).normalize() - pd.Timestamp(cdn_end).normalize()).days)
    status = "PASS" if lag_days <= _LAG_VS_US_DAYS else "FAIL"
    remedy = (
        "None required. The CDN curve ends with the US curve."
        if status == "PASS"
        else "Regenerate the CDN curve with scripts/run_cdn_backtest.py. It is behind the US book."
    )
    return _row(
        CHECK_ARTIFACT, status, pd.Timestamp(cdn_end).strftime("%Y-%m-%d"),
        f"CDN end within {_LAG_VS_US_DAYS}d of US end {pd.Timestamp(us_end).date()}",
        location, remedy,
        f"CDN curve ends {pd.Timestamp(cdn_end).date()}; US curve ends {pd.Timestamp(us_end).date()} "
        f"({lag_days}d).",
    )


def _consistency_check() -> dict:
    location = "data/backtest_results/cdn_comparison.csv"
    from config.cdn_regime_rules import CDN_AB_WINNER
    if not (CDN_COMPARISON.exists() and CDN_EQUITY.exists() and CDN_MONTHLY.exists()):
        return _row(
            CHECK_CONSISTENCY, "FAIL", "Missing file", "CAGR, equity, and heatmap are one series",
            location,
            "Run scripts/run_cdn_backtest.py so the comparison, equity, and monthly files exist.",
            "CDN comparison, equity curve, or monthly heatmap file is missing.",
        )
    report = verify_files(CDN_COMPARISON, CDN_EQUITY, CDN_MONTHLY, strategy=CDN_AB_WINNER)
    status = "PASS" if report.ok else "FAIL"
    detail = next(
        (line for line in report.messages if line.startswith((
            "total_return", "cagr_252", "max_dd_daily", "heatmap_", "monthly heatmap",
            "equity curve",
        ))),
        "CDN comparison, equity curve, and monthly heatmap are one series.",
    )
    return _row(
        CHECK_CONSISTENCY, status, "one series" if report.ok else "split series",
        "Same tolerance as the US book (heatmap total, 252-day CAGR, daily max DD)",
        location,
        "Regenerate the CDN artifacts together. Do not mix a heatmap from another path.",
        detail,
    )


def _heatmap_check(monthly, benchmark, equity, load_defaults) -> dict:
    location = "data/backtest_results/cdn_benchmark_xiu.csv"
    from src.dashboard.app import (
        CDN_BENCH_COLUMN,
        cdn_benchmark_year_returns,
        compounded_year_returns,
    )
    if monthly is None and load_defaults:
        monthly = _read_series(CDN_MONTHLY) if CDN_MONTHLY.exists() else pd.Series(dtype=float)
    if monthly is None:
        monthly = pd.Series(dtype=float)
    if equity is None and load_defaults:
        equity = _read_series(CDN_EQUITY) if CDN_EQUITY.exists() else pd.Series(dtype=float)
    if equity is None:
        equity = pd.Series(dtype=float)
    if benchmark is None and load_defaults:
        bench_px = _read_series(CDN_BENCHMARK) if CDN_BENCHMARK.exists() else pd.Series(dtype=float)
    else:
        bench_px = benchmark if benchmark is not None else pd.Series(dtype=float)
        if len(bench_px):
            bench_px = bench_px.dropna().copy()
            bench_px.index = pd.to_datetime(bench_px.index)
    if len(monthly) == 0 or len(bench_px) == 0:
        missing = "monthly heatmap" if len(monthly) == 0 else "XIU.TO benchmark"
        return _row(
            CHECK_HEATMAP, "FAIL", "Missing",
            f"Strategy year and {CDN_BENCH_COLUMN} year for every heatmap year",
            location,
            "Keep cdn_monthly_returns.csv and cdn_benchmark_xiu.csv (XIU.TO adjusted close).",
            f"CDN heatmap benchmark check failed: {missing} is missing.",
        )
    strategy_years = compounded_year_returns(monthly)
    bench_years = cdn_benchmark_year_returns(bench_px, equity if len(equity) else None)
    uncovered = []
    for year in strategy_years.index:
        value = bench_years.reindex([int(year)])
        if len(value) == 0 or pd.isna(value.iloc[0]):
            uncovered.append(str(int(year)))
    if uncovered:
        return _row(
            CHECK_HEATMAP, "FAIL", f"{len(uncovered)} years",
            f"{CDN_BENCH_COLUMN} (XIU.TO) covers every strategy year",
            location,
            "Extend the XIU.TO series through the CDN equity sample.",
            "TSX60 year is missing for: " + ", ".join(uncovered[:8]) + ".",
        )
    last = int(strategy_years.index.max())
    strat = float(strategy_years.loc[last])
    bench = float(bench_years.loc[last])
    return _row(
        CHECK_HEATMAP, "PASS", f"{last}: {strat:+.1f}% vs {bench:+.1f}%",
        f"Strategy and {CDN_BENCH_COLUMN} (S&P/TSX 60, XIU.TO) on every year",
        location,
        "None required. The heatmap can pair Strategy with TSX60.",
        f"Last overlapping year {last}: strategy {strat:+.1f}%, "
        f"{CDN_BENCH_COLUMN} {bench:+.1f}% (XIU.TO compounded on the CDN sample).",
    )


def _clock_check(clock_config, load_defaults) -> dict:
    location = "config/cdn_regime_rules.py"
    proof = prove_cdn_clock()
    config_ok = True
    config_note = "Published config records targeted CPI+1 / GDP+4."
    payload = None
    if clock_config is not None:
        payload = {"clock": clock_config}
    elif load_defaults and CDN_CONFIG.exists():
        try:
            payload = json.loads(CDN_CONFIG.read_text())
        except Exception as exc:
            config_ok = False
            config_note = f"CDN strategy config is unreadable ({exc})."
    elif load_defaults:
        config_ok = False
        config_note = "cdn_strategy_config.json is missing."
    if payload is not None and config_ok:
        clock = payload.get("clock") if isinstance(payload, dict) else None
        if not isinstance(clock, dict):
            config_ok = False
            config_note = "Published CDN config does not record its clock."
        else:
            config_ok = (
                clock.get("mode") == "targeted"
                and clock.get("same_month_market") is False
                and clock.get("publication_lag") is True
                and int(clock.get("cpi_lag_months", -1)) == 1
                and int(clock.get("gdp_lag_months", -1)) == 4
                and clock.get("momentum") == "VFV.TO"
            )
            if not config_ok:
                config_note = (
                    "Published CDN clock is not the targeted fix "
                    f"({clock.get('mode')}, CPI lag {clock.get('cpi_lag_months')}, "
                    f"GDP lag {clock.get('gdp_lag_months')}, momentum {clock.get('momentum')})."
                )
    ok = bool(proof.get("ok")) and config_ok
    status = "PASS" if ok else "FAIL"
    remedy = (
        "None required. CDN classification is the targeted clock, not month-end look-ahead."
        if ok else
        "Keep classify_cdn_regimes on mode targeted: CPI+1, GDP+4, VFV.TO lagged one month. "
        "Do not publish same-month VIX or momentum."
    )
    desc = (
        f"Classifier {'matches' if proof.get('matches_targeted') else 'does not match'} targeted; "
        f"lookahead {'differs' if proof.get('differs_from_lookahead') else 'does not differ'}. "
        f"{config_note}"
    )
    return _row(
        CHECK_CLOCK, status,
        "targeted" if ok else str(proof.get("mode")),
        "CPI+1 / GDP+4, VFV.TO lagged one month, not same-month",
        location, remedy, desc,
    )


def _path_check(honesty, load_defaults) -> dict:
    location = "data/backtest_results/cdn_lag_honesty.csv"
    frame = honesty
    if frame is None and load_defaults and CDN_HONESTY.exists():
        frame = pd.read_csv(CDN_HONESTY, index_col=0)
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty or "cagr" not in frame.columns:
        return _row(
            CHECK_PATHS, "WARNING", "Not loaded",
            "A lookahead, B targeted, C vintage, plus unlagged and extra month",
            location,
            "Run scripts/run_cdn_backtest.py. It writes cdn_lag_honesty.csv from the same sleeve.",
            "CDN path A/B/C metrics are not loaded. The clock check still runs. "
            "This row is a warning, not a skipped audit.",
        )
    cagr = {str(idx): _as_float(frame.loc[idx, "cagr"]) for idx in frame.index}
    published = _published_cagr(CDN_COMPARISON) if load_defaults else float("nan")
    targeted = cagr.get("B_targeted", float("nan"))
    lookahead = cagr.get("A_lookahead", float("nan"))
    vintage = cagr.get("C_vintage", float("nan"))
    unlagged = cagr.get("unlagged", float("nan"))
    extra = cagr.get("auditor_extra", float("nan"))
    messages = []
    status = "PASS"
    remedy = "None required. Published CDN CAGR is path B. A and C stay comparison rows."

    def _worse(new_status):
        nonlocal status
        rank = {"PASS": 0, "WARNING": 1, "FAIL": 2}
        if rank[new_status] > rank[status]:
            status = new_status

    if pd.isna(targeted) or pd.isna(lookahead):
        _worse("FAIL")
        messages.append("Path A or path B is missing from cdn_lag_honesty.csv.")
        remedy = "Write A_lookahead and B_targeted from the CDN sleeve. Do not drop path B."
    else:
        gap = lookahead - targeted
        messages.append(f"A {lookahead:.2%} versus B {targeted:.2%} (gap {gap:+.2%}).")
        if gap <= _LOOKAHEAD_GAP:
            _worse("WARNING")
            messages.append("Month-end look-ahead is not above the targeted fix.")
            remedy = "Keep shift(1) on VIX and VFV.TO momentum. Do not publish path A."
        if pd.notna(published):
            if abs(published - targeted) > 0.0005 and abs(published - lookahead) + 1e-12 < abs(published - targeted):
                _worse("FAIL")
                messages.append(
                    f"Published CAGR {published:.2%} matches lookahead more closely than targeted."
                )
                remedy = "Regenerate the CDN curve on the targeted clock. The published book is path B."
            elif abs(published - targeted) > 0.0005:
                _worse("FAIL")
                messages.append(
                    f"Published CAGR {published:.2%} is not path B ({targeted:.2%})."
                )
                remedy = "Rewrite cdn_comparison.csv and cdn_lag_honesty.csv from one targeted run."
    if pd.notna(unlagged) and pd.notna(targeted):
        premium = unlagged - targeted
        messages.append(f"Unlagged premium {premium:+.2%}.")
        if abs(premium) < _UNLAGGED_TIE and targeted > 0:
            _worse("WARNING")
            messages.append("Unlagged and targeted are near-identical. Confirm CPI+1 / GDP+4 is still applied.")
            if status != "FAIL":
                remedy = "Keep publication lag on the CDN clock. A ~0 unlagged premium can mean the lag was removed."
    if pd.notna(extra) and pd.notna(targeted) and abs(extra - targeted) < 1e-6:
        _worse("WARNING")
        messages.append("Extra month matches targeted. The regime label may not be moving.")
    if pd.isna(vintage):
        _worse("WARNING")
        messages.append("Path C vintage is not in the CDN table.")
        if status != "FAIL":
            remedy = "Include C_vintage when the first-release table is available. Do not drop the row silently."
    elif pd.notna(targeted) and vintage > targeted + _VINTAGE_ABOVE_B:
        _worse("FAIL")
        messages.append(
            f"Vintage {vintage:.2%} sits more than {_VINTAGE_ABOVE_B:.0%} above targeted {targeted:.2%}."
        )
        remedy = "Check first-release alignment. Path C should sit at or below path B."
    elif pd.notna(vintage):
        messages.append(f"Vintage {vintage:.2%} versus targeted {targeted:.2%}.")
    return _row(
        CHECK_PATHS, status,
        "B targeted" if status == "PASS" else status,
        "Published book is B; A is the old look-ahead; C is not above B",
        location, remedy, " ".join(messages),
    )


def merge_cdn_audit(audit: dict | None, **kwargs) -> dict:
    """Attach CDN rows to an auditor payload. A second call replaces CDN rows."""
    checks = audit_cdn_book(**kwargs)
    payload = dict(audit or {})
    payload["cdn_checks"] = checks
    fresh = [
        row for row in (payload.get("data_checks") or [])
        if row.get("check") not in CDN_CHECKS and row.get("check") != "CDN book"
    ]
    payload["data_checks"] = fresh + checks
    return payload


def build_cdn_audit_panel(checks=None):
    """Auditor panel for the Canadian book. Renders even when a caller forgot the rows."""
    from dash import dash_table, html

    if not checks:
        checks = audit_cdn_book()

    def fmt_status(status):
        if status == "PASS":
            return "✅ PASS"
        if status in {"WARNING", "WARN"}:
            return "⚠️ WARN"
        if status in {"FAIL", "CRITICAL"}:
            return "❌ FAIL"
        return status or "—"

    rows = [{
        "Check": item.get("check", "—"),
        "Status": fmt_status(item.get("status")),
        "Value": item.get("value", "—"),
        "Threshold": item.get("threshold", "—"),
        "Location": item.get("location", "—"),
        "How to Improve": item.get("remedy", "—"),
        "Description": item.get("desc", "—"),
    } for item in checks]
    return html.Div([
        html.H5(
            "🍁 CDN book · freshness, consistency, path A/B/C",
            style={"color": "#f5a623", "marginBottom": "6px", "fontWeight": "700"},
        ),
        html.Div(
            "Same pass/fail contract as the US book. Path B (targeted CPI+1 / GDP+4, "
            "VFV.TO lagged one month) is the published CDN curve. "
            "Path A is month-end look-ahead. Path C is the first-release vintage. "
            "TSX60 on the heatmap is XIU.TO. These rows do not change US sleeve weights.",
            style={"color": "#8888a0", "fontSize": "12px", "marginBottom": "10px"},
        ),
        dash_table.DataTable(
            id="cdn-audit-table",
            columns=[{"name": column, "id": column} for column in (
                "Check", "Status", "Value", "Threshold", "Location", "How to Improve", "Description",
            )],
            data=rows,
            style_header={
                "backgroundColor": "#16213e", "color": "#c8c8d4", "fontWeight": "600",
                "border": "1px solid #2d2d44", "fontFamily": "Inter", "fontSize": "11px",
            },
            style_cell={
                "backgroundColor": "#1a1a2e", "color": "#c8c8d4", "border": "1px solid #2d2d44",
                "fontFamily": "Inter", "fontSize": "11px", "padding": "6px", "textAlign": "left",
                "whiteSpace": "normal", "height": "auto",
            },
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": "#16213e"},
                {"if": {"filter_query": '{Status} contains "PASS"'}, "color": "#00d97e"},
                {"if": {"filter_query": '{Status} contains "WARN"'}, "color": "#f5a623"},
                {"if": {"filter_query": '{Status} contains "FAIL"'}, "color": "#e74c3c", "fontWeight": "bold"},
            ],
        ),
    ], id="cdn-audit", style={
        "backgroundColor": "#1a1a2e", "border": "1px solid #f5a623",
        "borderRadius": "12px", "padding": "20px", "marginBottom": "16px",
    })
