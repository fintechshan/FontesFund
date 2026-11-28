#!/usr/bin/env python3
"""Write the QQQ Vegas 2-day shadow pack. Do not touch the official v9 files.

The shadow confirms the locked v9 boolean already stored in
``data/qqq_vegas/daily_signal.csv``. It does not recompute Vegas or Q80, it
does not write ``signal_current.json`` / ``equity_curve.csv`` / ``rebalances.csv``
in the official directory, and it does not send a notification.

    python scripts/refresh_qqq_vegas_shadow.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.refresh_qqq_vegas_signal import (  # noqa: E402
    _fmt_pct,
    _month_returns,
    _window_stats,
    _year_returns,
    pos_flips,
)
from src.qqq_vegas.shadow_2day import (  # noqa: E402
    CONFIRM_SESSIONS,
    COST,
    RULE_EN,
    RULE_ZH,
    W_QLD,
    W_QQQ,
    leg_returns,
    shadow_position,
    shadow_strategy_return,
)

OFFICIAL_DIR = ROOT / "data" / "qqq_vegas"
SHADOW_DIRNAME = "shadow_2day_confirm"
FILTER_VERSION = "shadow_2day_confirm"
STRATEGY_ID = "qqq_vegas_shadow_2day_confirm"
NOTE = (
    "影子/实验 shadow 2-day confirm of the locked v9 boolean. "
    "Paper replay only. Not a live order and not an alert."
)
REBALANCE_COLUMNS = (
    "date", "signal_date", "exec_date", "action", "from_state", "to_state",
    "qqq_w", "qld_w", "cash_ticker", "cash_w", "filter_version",
    "vegas", "rv_ok", "rv20", "rv20_q80", "notes",
)
OFFICIAL_FILENAMES = {
    "daily_signal.csv",
    "equity_curve.csv",
    "rebalances.csv",
    "monthly_returns.csv",
    "yearly_returns.csv",
    "signal_current.json",
    "summary.json",
    "strategy.json",
    "live_snapshot.json",
}


def shadow_output_dir(official_dir: Path) -> Path:
    return Path(official_dir) / SHADOW_DIRNAME


def _read_official(official_dir: Path):
    signal = pd.read_csv(official_dir / "daily_signal.csv", parse_dates=["date"]).set_index("date").sort_index()
    equity = pd.read_csv(official_dir / "equity_curve.csv", parse_dates=["date"]).set_index("date").sort_index()
    signal.index = pd.to_datetime(signal.index).tz_localize(None)
    equity.index = pd.to_datetime(equity.index).tz_localize(None)
    return signal, equity


def _market_qld(official_dir: Path) -> pd.Series | None:
    path = official_dir / "market_prices.csv"
    if not path.is_file():
        return None
    frame = pd.read_csv(path, parse_dates=["date"])
    if "QLD" not in frame.columns:
        return None
    series = pd.to_numeric(frame.set_index("date")["QLD"], errors="coerce").dropna().sort_index()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _trim(value, digits):
    text = f"{float(value):.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-", "-0"}:
        return "0"
    return text


def _rebalance_frame(signal: pd.DataFrame, shadow: pd.DataFrame) -> pd.DataFrame:
    flips = pos_flips(shadow)
    rows = []
    for flip in flips:
        src = signal.loc[flip["source_stamp"]]
        if isinstance(src, pd.DataFrame):
            src = src.iloc[-1]
        enter = flip["action"] == "ENTER"
        rows.append({
            "date": flip["exec"].strftime("%Y-%m-%d"),
            "signal_date": flip["signal"].strftime("%Y-%m-%d"),
            "exec_date": flip["exec"].strftime("%Y-%m-%d"),
            "action": flip["action"],
            "from_state": flip["from_state"],
            "to_state": flip["to_state"],
            "qqq_w": f"{W_QQQ if enter else 0.0:.1f}",
            "qld_w": f"{W_QLD if enter else 0.0:.1f}",
            "cash_ticker": "" if enter else "BIL",
            "cash_w": f"{0.0 if enter else 1.0:.1f}",
            "filter_version": FILTER_VERSION,
            "vegas": str(int(src["vegas"])) if "vegas" in src.index else "",
            "rv_ok": str(int(src["rv_ok"])) if "rv_ok" in src.index else "",
            "rv20": _trim(src["rv20"], 6) if "rv20" in src.index and pd.notna(src["rv20"]) else "",
            "rv20_q80": _trim(src["rv20_q80"], 6) if "rv20_q80" in src.index and pd.notna(src["rv20_q80"]) else "",
            "notes": NOTE,
        })
    return pd.DataFrame(rows, columns=REBALANCE_COLUMNS)


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False)


def _nav_from_returns(strat_ret: pd.Series) -> pd.Series:
    nav = 100_000.0
    values = []
    for value in strat_ret.astype(float):
        if not np.isfinite(value):
            value = 0.0
        nav = round(nav * (1.0 + float(value)), 3)
        values.append(nav)
    return pd.Series(values, index=strat_ret.index, name="equity")


def _window_return(nav: pd.Series, start: str, end: str) -> dict:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    base_slice = nav.loc[:start_ts]
    last_slice = nav.loc[:end_ts]
    if base_slice.empty or last_slice.empty:
        return {"start": start, "end": end, "return": None}
    base_day = pd.Timestamp(base_slice.index[-1])
    last_day = pd.Timestamp(last_slice.index[-1])
    ratio = float(last_slice.iloc[-1] / base_slice.iloc[-1] - 1.0)
    return {
        "start": base_day.strftime("%Y-%m-%d"),
        "end": last_day.strftime("%Y-%m-%d"),
        "return": ratio,
        "return_pct": round(ratio * 100.0, 4),
    }


def _month_pct(nav: pd.Series, year: int, month: int):
    rets = _month_returns(nav)
    value = rets.get((year, month))
    if value is None:
        return None
    return {"exact_pct": float(value), "rounded_pct": float(_fmt_pct(value))}


def _flip_count(frame: pd.DataFrame, start=None, end=None) -> int:
    if frame.empty:
        return 0
    dates = pd.to_datetime(frame["exec_date"])
    mask = pd.Series(True, index=frame.index)
    if start is not None:
        mask &= dates >= pd.Timestamp(start)
    if end is not None:
        mask &= dates <= pd.Timestamp(end)
    return int(mask.sum())


def _comparison(official_signal, official_equity, shadow_pos, shadow_nav, shadow_ret, shadow_rebalances) -> dict:
    official_flips = pos_flips(official_signal)
    official_nav = pd.to_numeric(official_equity["equity"], errors="coerce")
    official_ret = pd.to_numeric(official_equity["strat_ret"], errors="coerce")
    as_of = pd.Timestamp(shadow_nav.index.max()).strftime("%Y-%m-%d")
    official_stats = _window_stats(official_nav, official_ret, "1999-01-04", as_of)
    shadow_stats = _window_stats(shadow_nav, shadow_ret, shadow_nav.index.min(), as_of)
    exec_2026 = []
    if len(shadow_rebalances):
        dates = pd.to_datetime(shadow_rebalances["exec_date"])
        picked = shadow_rebalances.loc[(dates >= "2026-01-01") & (dates <= "2026-12-31")]
        exec_2026 = [
            f"{str(row.exec_date)[:10]} {row.action}"
            for row in picked.itertuples(index=False)
        ]
    return {
        "label": "纸面历史对照 / paper history. Not a live improvement and not a reason to unfreeze v9.",
        "rule_difference_vs_exit_only_replay": (
            "This shadow requires two consecutive qualifying closes for both entry and exit. "
            "It does not keep a same-day exit when rv20 > 1.15 * q80, and it does not enter on the first raw signal."
        ),
        "official_flips_full": len(official_flips),
        "shadow_flips_full": int(len(shadow_rebalances)),
        "official_flips_2026": sum(1 for flip in official_flips if flip["exec"].year == 2026),
        "shadow_flips_2026": _flip_count(shadow_rebalances, "2026-01-01", "2026-12-31"),
        "official_flips_2026_02_03": sum(
            1 for flip in official_flips
            if pd.Timestamp("2026-02-01") <= flip["exec"] <= pd.Timestamp("2026-03-31")
        ),
        "shadow_flips_2026_02_03": _flip_count(shadow_rebalances, "2026-02-01", "2026-03-31"),
        "shadow_2026_exec": exec_2026,
        "full_sample": {
            "official": official_stats,
            "shadow": shadow_stats,
        },
        "windows": {
            "2026-02": {
                "official": _month_pct(official_nav, 2026, 2),
                "shadow": _month_pct(shadow_nav, 2026, 2),
            },
            "2026-03": {
                "official": _month_pct(official_nav, 2026, 3),
                "shadow": _month_pct(shadow_nav, 2026, 3),
            },
            "2026-02-03_from_jan_month_end": {
                "official": _window_return(official_nav, "2026-01-31", "2026-03-31"),
                "shadow": _window_return(shadow_nav, "2026-01-31", "2026-03-31"),
            },
            "2026-06": {
                "official": _month_pct(official_nav, 2026, 6),
                "shadow": _month_pct(shadow_nav, 2026, 6),
            },
            "2026-11_from_2026-10-30_to_2026-11-25": {
                "official": _window_return(official_nav, "2026-10-30", "2026-11-25"),
                "shadow": _window_return(shadow_nav, "2026-10-30", "2026-11-25"),
            },
            "2026-11_from_2026-10-30_to_as_of": {
                "official": _window_return(official_nav, "2026-10-30", as_of),
                "shadow": _window_return(shadow_nav, "2026-10-30", as_of),
            },
        },
    }


def _monthly_text(nav: pd.Series) -> str:
    rets = _month_returns(nav)
    years = sorted({year for year, _month in rets})
    lines = ["year,M01,M02,M03,M04,M05,M06,M07,M08,M09,M10,M11,M12"]
    for year in years:
        cells = [str(year)]
        for month in range(1, 13):
            value = rets.get((year, month))
            cells.append("" if value is None else _fmt_pct(value))
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def _yearly_text(shadow_nav: pd.Series, official_nav: pd.Series) -> str:
    shadow_years = _year_returns(shadow_nav)
    official_years = _year_returns(official_nav)
    lines = ["year,shadow_pct,official_pct"]
    for year in sorted(set(shadow_years) | set(official_years)):
        shadow_cell = "" if year not in shadow_years else _fmt_pct(shadow_years[year])
        official_cell = "" if year not in official_years else _fmt_pct(official_years[year])
        lines.append(f"{year},{shadow_cell},{official_cell}")
    return "\n".join(lines) + "\n"


def build_shadow_pack(official_dir=None, output_dir=None, now=None) -> dict:
    """Write the shadow pack under ``output_dir``. Official files are only read."""
    official_dir = Path(official_dir) if official_dir is not None else OFFICIAL_DIR
    output_dir = Path(output_dir) if output_dir is not None else shadow_output_dir(official_dir)
    if output_dir.resolve() == official_dir.resolve():
        raise RuntimeError("shadow output must not be the official qqq_vegas directory")
    for name in OFFICIAL_FILENAMES:
        if (output_dir / name).resolve() == (official_dir / name).resolve():
            raise RuntimeError(f"refusing to write official file {name}")
    signal, equity = _read_official(official_dir)
    if not signal.index.equals(equity.index):
        shared = signal.index.intersection(equity.index)
        signal = signal.loc[shared]
        equity = equity.loc[shared]
    if "signal" not in signal.columns or "pos" not in signal.columns:
        raise RuntimeError("official daily_signal.csv has no locked v9 signal/pos columns")
    shadow = shadow_position(signal["signal"])
    shadow.index = signal.index
    legs = leg_returns(signal, equity, _market_qld(official_dir))
    strat = shadow_strategy_return(
        legs["qqq_ret"], legs["qld_ret"], legs["cash_ret"],
        shadow["pos"], signal["pos"], equity["strat_ret"], cost=COST,
    )
    nav = _nav_from_returns(strat)
    drawdown = nav / nav.cummax() - 1.0
    held = shadow["pos"].astype(int)
    daily = pd.DataFrame({
        "date": [stamp.strftime("%Y-%m-%d") for stamp in signal.index],
        "raw_signal": signal["signal"].astype(int).to_numpy(),
        "confirmed_signal": shadow["confirmed_signal"].to_numpy(),
        "pos": held.to_numpy(),
        "vegas": signal["vegas"].astype(int).to_numpy() if "vegas" in signal.columns else 0,
        "rv_ok": signal["rv_ok"].astype(int).to_numpy() if "rv_ok" in signal.columns else 0,
        "qqq_close": pd.to_numeric(signal["qqq_close"], errors="coerce").map(lambda v: _trim(v, 6) if pd.notna(v) else ""),
        "w_qqq": np.where(held.to_numpy() == 1, "0.7", "0.0"),
        "w_qld": np.where(held.to_numpy() == 1, "0.3", "0.0"),
        "w_bil": np.where(held.to_numpy() == 1, "0.0", "1.0"),
    })
    curve = pd.DataFrame({
        "date": daily["date"],
        "equity": nav.map(lambda v: _trim(v, 3)),
        "drawdown": drawdown.map(lambda v: _trim(v, 8)),
        "strat_ret": strat.map(lambda v: _trim(v, 8)),
        "pos": held.to_numpy(),
    })
    rebalances = _rebalance_frame(signal, shadow.assign(pos=held))
    comparison = _comparison(signal, equity, held, nav, strat, rebalances)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    generated_at = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    as_of = pd.Timestamp(signal.index.max()).strftime("%Y-%m-%d")
    summary = {
        "strategy_id": STRATEGY_ID,
        "label_zh": "影子 / 实验",
        "label_en": "shadow / experiment",
        "official_strategy_id": "qqq_vegas_rv20_q80",
        "backtest_tag": "shadow_2day_confirm",
        "replaces_official_v9": False,
        "emits_live_alerts": False,
        "live_orders": False,
        "as_of": as_of,
        "generated_at": generated_at,
        "start_date": pd.Timestamp(signal.index.min()).strftime("%Y-%m-%d"),
        "end_date": as_of,
        "confirm_sessions": CONFIRM_SESSIONS,
        "cost_bps": COST * 10_000.0,
        "w_qqq": W_QQQ,
        "w_qld": W_QLD,
        "cash_ticker": "BIL",
        "rule_zh": RULE_ZH,
        "rule_en": RULE_EN,
        "return_model": legs["diagnostics"],
        "paper_comparison": comparison,
        "disclaimer": (
            "纸面历史对照。不是官方 QQQ Vegas v9，不改密封卡，不发实盘 ENTER/EXIT 提醒，"
            "也不是建议把影子换成实盘。Paper history only. Not the official card."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_text(output_dir / "daily_signal.csv", _csv(daily))
    _atomic_text(output_dir / "equity_curve.csv", _csv(curve))
    _atomic_text(output_dir / "rebalances.csv", _csv(rebalances))
    _atomic_text(output_dir / "monthly_returns.csv", _monthly_text(nav))
    _atomic_text(output_dir / "yearly_returns.csv", _yearly_text(nav, pd.to_numeric(equity["equity"], errors="coerce")))
    _atomic_text(output_dir / "summary.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return summary


def refresh_shadow(official_dir=None, output_dir=None, now=None) -> dict:
    """Refresh hook used after the official pack is safely on disk."""
    return build_shadow_pack(official_dir=official_dir, output_dir=output_dir, now=now)


def main(argv=None) -> int:
    del argv
    try:
        summary = build_shadow_pack()
    except Exception as exc:  # noqa: BLE001 — official pack stays as it was
        print(f"QQQ Vegas shadow pack unchanged: {exc}", file=sys.stderr)
        return 1
    comparison = summary.get("paper_comparison") or {}
    print(
        "shadow 2-day confirm "
        f"as_of={summary.get('as_of')} "
        f"flips {comparison.get('shadow_flips_full')} "
        f"(official {comparison.get('official_flips_full')}). "
        "Not a live alert."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
