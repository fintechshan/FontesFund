#!/usr/bin/env python3
"""
scripts/weekly_audit_snapshot.py
================================
Weekly Saturday Data Accuracy & Backtest Accuracy Auditor for ETF Regime Strategist.
Generates `data/weekly_audit_snapshot.json` consumed by `src/dashboard/auditor.py`.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "weekly_audit_snapshot.json"
COMPARISON_CSV = ROOT / "data" / "backtest_results" / "20yr_comparison.csv"
LAG_HONESTY_CSV = ROOT / "data" / "backtest_results" / "lag_honesty.csv"
EQUITY_CSV = ROOT / "data" / "backtest_results" / "aggressive_equity_curve.csv"
ALL_EQUITY_CSV = ROOT / "data" / "backtest_results" / "all_equity_curves.csv"
MONTHLY_CSV = ROOT / "data" / "backtest_results" / "aggressive_monthly_returns.csv"
COVERAGE_CSV = ROOT / "data" / "backtest_results" / "coverage_windows.csv"
NOTIFY_STATE_JSON = ROOT / "data" / "notify_state.json"
RISK_FLAGS_JSON = ROOT / "data" / "risk_flags" / "flags.json"

PRODUCTION_SLEEVE = ["SPY", "QQQ", "SOXX", "IEF", "GLD", "DBMF", "AIPO"]
CAGR_ABS_TOL = 0.0005      # 5 bps
TOTAL_ABS_TOL = 0.0010     # 10 bps
DAILY_DD_ABS_TOL = 0.0005  # 5 bps
TRADING_DAYS = 252.0


def _clean_pct(val: Any) -> float:
    if val is None:
        return 0.0
    s = str(val).strip().replace("%", "")
    if not s or s == "-":
        return 0.0
    return float(s) / 100.0


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check_backtest_consistency() -> Dict[str, Any]:
    """Reconciles 20yr_comparison.csv, lag_honesty.csv, all_equity_curves.csv, and monthly returns."""
    comp_rows = {r["Strategy"]: r for r in _read_csv_rows(COMPARISON_CSV) if "Strategy" in r}
    lag_rows = {r["mode"]: r for r in _read_csv_rows(LAG_HONESTY_CSV) if "mode" in r}
    eq_rows = _read_csv_rows(ALL_EQUITY_CSV)
    mo_rows = _read_csv_rows(MONTHLY_CSV)

    if not eq_rows or "Optimized Regime Strategy" not in comp_rows:
        return {
            "status": "WARNING",
            "summary": "Backtest result CSVs missing or incomplete in data/backtest_results/.",
            "strategies": {},
        }

    n_rows = len(eq_rows)
    start_date = eq_rows[0].get("Date", "")
    end_date = eq_rows[-1].get("Date", "")

    opt_series = [float(r["Optimized Regime Strategy"]) for r in eq_rows]
    opt_start, opt_end = opt_series[0], opt_series[-1]
    curve_total = opt_end / opt_start - 1.0
    cagr_252 = (1.0 + curve_total) ** (TRADING_DAYS / n_rows) - 1.0

    peak = opt_series[0]
    max_dd = 0.0
    for val in opt_series:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd

    heatmap_prod = 1.0
    for r in mo_rows:
        val_str = r.get("0") or r.get("Return") or "0"
        heatmap_prod *= (1.0 + float(val_str.strip()))
    heatmap_total = heatmap_prod - 1.0

    rep_opt = comp_rows["Optimized Regime Strategy"]
    rep_total = _clean_pct(rep_opt.get("Total Return"))
    rep_cagr = _clean_pct(rep_opt.get("Annual Return"))
    rep_dd = _clean_pct(rep_opt.get("Max Drawdown"))

    total_diff = abs(curve_total - rep_total)
    cagr_diff = abs(cagr_252 - rep_cagr)
    dd_diff = abs(max_dd - rep_dd)
    heatmap_diff = abs(heatmap_total - curve_total)

    passed = (
        total_diff <= TOTAL_ABS_TOL
        and cagr_diff <= CAGR_ABS_TOL
        and dd_diff <= DAILY_DD_ABS_TOL
    )

    benchmark_notes: List[str] = []
    for strat_name, row in comp_rows.items():
        if strat_name not in eq_rows[0]:
            continue
        # All Weather's day-1 cell is blank in all_equity_curves.csv. Skip
        # non-numeric bases so the Saturday job still writes the snapshot.
        raw0 = str(eq_rows[0].get(strat_name, "")).strip()
        raw1 = str(eq_rows[-1].get(strat_name, "")).strip()
        if not raw0 or not raw1:
            continue
        try:
            s0 = float(raw0)
            s1 = float(raw1)
        except ValueError:
            continue
        if s0 == 0.0:
            continue
        if abs(s0 - 1.0) > 1e-4:
            gap_pct = (s1 / s0 - 1.0) - (s1 - 1.0)
            benchmark_notes.append(
                f"{strat_name}: Day-1 base={s0:.4f} (End/Start-1 differs from End-1 by {gap_pct:+.2%})"
            )

    return {
        "status": "PASS" if passed else "FAIL",
        "backtest_start": start_date,
        "backtest_end": end_date,
        "sessions": n_rows,
        "reported_cagr": round(rep_cagr, 6),
        "recomputed_cagr_252": round(cagr_252, 6),
        "cagr_diff_bps": round(cagr_diff * 10000, 2),
        "reported_total_return": round(rep_total, 6),
        "recomputed_total_return": round(curve_total, 6),
        "total_diff_bps": round(total_diff * 10000, 2),
        "reported_max_dd": round(rep_dd, 6),
        "recomputed_max_dd": round(max_dd, 6),
        "dd_diff_bps": round(dd_diff * 10000, 2),
        "heatmap_vs_equity_diff_bps": round(heatmap_diff * 10000, 2),
        "lag_paths": {
            mode: {
                "cagr": float(r.get("cagr", 0.0)),
                "max_dd": float(r.get("max_dd", 0.0)),
                "sharpe": float(r.get("sharpe", 0.0)),
                "end": r.get("end", ""),
            }
            for mode, r in lag_rows.items()
        },
        "benchmark_normalization_notes": benchmark_notes,
    }


def fetch_live_sleeve_prices(refresh: bool = False) -> Dict[str, Any]:
    """Fetches latest Friday closes for the 7-ETF production sleeve + VIX when --refresh is enabled."""
    if not refresh:
        return {"refreshed": False, "tickers": {}}
    try:
        import yfinance as yf  # type: ignore

        tickers = PRODUCTION_SLEEVE + ["^VIX"]
        df = yf.download(tickers, period="2mo", interval="1d", progress=False, auto_adjust=True)
        close = df["Close"] if "Close" in df else df
        latest_date = str(close.index[-1].date())
        snapshot: Dict[str, Dict[str, float]] = {}
        for t in tickers:
            label = "VIX" if t == "^VIX" else t
            series = close[t].dropna()
            if len(series) >= 6:
                cur = float(series.iloc[-1])
                wk_ago = float(series.iloc[-6])
                snapshot[label] = {
                    "close": round(cur, 4),
                    "weekly_change_pct": round((cur / wk_ago - 1.0) * 100.0, 2),
                }
        return {"refreshed": True, "latest_market_date": latest_date, "tickers": snapshot}
    except Exception as exc:
        return {"refreshed": False, "error": str(exc), "tickers": {}}


def build_snapshot(refresh: bool = False) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    bt = check_backtest_consistency()
    notify_state = _load_json(NOTIFY_STATE_JSON)
    risk_flags = _load_json(RISK_FLAGS_JSON)
    cov_rows = _read_csv_rows(COVERAGE_CSV)
    live = fetch_live_sleeve_prices(refresh=refresh)

    bt_end = bt.get("backtest_end") or "n/a"
    notify_asof = notify_state.get("price_asof") or "n/a"
    flags_asof = risk_flags.get("as_of") or "n/a"
    latest_mkt = live.get("latest_market_date") or notify_asof

    stale_days: Optional[int] = None
    try:
        if bt_end != "n/a" and latest_mkt != "n/a":
            d_bt = date.fromisoformat(bt_end)
            d_mkt = date.fromisoformat(latest_mkt)
            stale_days = (d_mkt - d_bt).days
    except Exception:
        stale_days = None

    freshness_status = "PASS"
    if stale_days is not None and stale_days > 7:
        freshness_status = "WARNING"

    overall_status = "PASS"
    if bt.get("status") == "FAIL":
        overall_status = "FAIL"
    elif freshness_status == "WARNING" or bt.get("status") == "WARNING":
        overall_status = "WARNING"

    return {
        "schema": 1,
        "generated_at": now_utc,
        "overall_status": overall_status,
        "freshness": {
            "status": freshness_status,
            "backtest_end": bt_end,
            "notify_price_asof": notify_asof,
            "risk_flags_asof": flags_asof,
            "latest_market_date": latest_mkt,
            "backtest_lag_calendar_days": stale_days,
        },
        "regime_state": {
            "regime": notify_state.get("regime", "n/a"),
            "vix": notify_state.get("vix"),
            "vix_band": notify_state.get("vix_band", "n/a"),
            "cpi_yoy": notify_state.get("cpi_yoy"),
            "gdp": notify_state.get("gdp"),
            "spy_momentum": notify_state.get("spy_momentum"),
        },
        "backtest_consistency": bt,
        "coverage": {
            r["ticker"]: {
                "first_date": r.get("first_date"),
                "sessions": int(float(r.get("sessions", 0))),
                "coverage_pct": round(float(r.get("coverage", 0.0)) * 100.0, 2),
            }
            for r in cov_rows
            if "ticker" in r
        },
        "live_market_check": live,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weekly data & backtest audit snapshot.")
    parser.add_argument("--refresh", action="store_true", help="Fetch live ETF/VIX closes via yfinance.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT, help="Output JSON path.")
    args = parser.parse_args()

    snap = build_snapshot(refresh=args.refresh)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[weekly_audit_snapshot] wrote {args.output} (status={snap['overall_status']})")
    return 0 if snap["overall_status"] != "FAIL" else 3


if __name__ == "__main__":
    raise SystemExit(main())
