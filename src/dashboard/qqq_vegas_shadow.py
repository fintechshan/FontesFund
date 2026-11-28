"""Dashboard panel for the QQQ Vegas 2-day shadow. Not the official card."""
from __future__ import annotations

import json
from pathlib import Path

SHADOW_DIR = Path(__file__).resolve().parents[2] / "data" / "qqq_vegas" / "shadow_2day_confirm"


def load_shadow_summary(directory=None):
    path = Path(directory or SHADOW_DIR) / "summary.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _pct(block, key="return_pct"):
    if not isinstance(block, dict):
        return "—"
    value = block.get(key)
    if value is None and "rounded_pct" in block:
        value = block.get("rounded_pct")
    if value is None:
        return "—"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _num(value, digits=2):
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def build_shadow_panel(summary=None):
    """Amber experimental panel. Official v9 markup is not built here."""
    from dash import html

    payload = summary if isinstance(summary, dict) else load_shadow_summary()
    border = "1px dashed #f5a623"
    box = {
        "backgroundColor": "#1a1208",
        "border": border,
        "borderRadius": "12px",
        "padding": "16px",
        "marginBottom": "16px",
    }
    title = html.H5(
        "影子 / 实验 · Shadow · 2-day confirmation",
        style={"color": "#f5a623", "marginBottom": "6px", "fontWeight": "700"},
    )
    banner = html.Div(
        "这不是官方 QQQ Vegas v9 卡，不改锁定信号，不下单，也不发实盘 ENTER/EXIT 提醒。"
        " Paper history only. Not a live book and not a recommendation to unfreeze v9.",
        style={"color": "#f5a623", "fontSize": "13px", "fontWeight": "700", "marginBottom": "8px"},
    )
    if not payload:
        return html.Div([
            title,
            banner,
            html.Div(
                "影子包尚未生成。运行 python scripts/refresh_qqq_vegas_shadow.py。"
                " 官方 data/qqq_vegas 文件不会被这个面板改写。",
                style={"color": "#c8c8d4", "fontSize": "12px"},
            ),
        ], id="qqq-vegas-shadow", style=box)

    comparison = payload.get("paper_comparison") if isinstance(payload.get("paper_comparison"), dict) else {}
    windows = comparison.get("windows") if isinstance(comparison.get("windows"), dict) else {}
    full = comparison.get("full_sample") if isinstance(comparison.get("full_sample"), dict) else {}
    official_full = full.get("official") if isinstance(full.get("official"), dict) else {}
    shadow_full = full.get("shadow") if isinstance(full.get("shadow"), dict) else {}
    feb = windows.get("2026-02") if isinstance(windows.get("2026-02"), dict) else {}
    mar = windows.get("2026-03") if isinstance(windows.get("2026-03"), dict) else {}
    both = windows.get("2026-02-03_from_jan_month_end") if isinstance(windows.get("2026-02-03_from_jan_month_end"), dict) else {}
    nov = windows.get("2026-11_from_2026-10-30_to_as_of") if isinstance(windows.get("2026-11_from_2026-10-30_to_as_of"), dict) else {}
    execs = comparison.get("shadow_2026_exec") if isinstance(comparison.get("shadow_2026_exec"), list) else []
    lines = [
        f"as_of {payload.get('as_of') or '—'} · confirm {payload.get('confirm_sessions') or 2} consecutive closes · "
        f"70/30 vs BIL · cost {payload.get('cost_bps')} bps on a shadow position change",
        payload.get("rule_zh") or "",
        payload.get("rule_en") or "",
        (
            f"纸面调仓 {comparison.get('shadow_flips_full')} vs 官方 {comparison.get('official_flips_full')}；"
            f"2026 {comparison.get('shadow_flips_2026')} vs {comparison.get('official_flips_2026')}；"
            f"2026-02/03 {comparison.get('shadow_flips_2026_02_03')} vs {comparison.get('official_flips_2026_02_03')}。"
        ),
        (
            f"全样本 CAGR 影子 {_num(shadow_full.get('CAGR_pct'))}% / 官方 {_num(official_full.get('CAGR_pct'))}% · "
            f"MaxDD 影子 {_num(shadow_full.get('MaxDD_pct'))}% / 官方 {_num(official_full.get('MaxDD_pct'))}% · "
            f"Sharpe 影子 {_num(shadow_full.get('Sharpe'), 3)} / 官方 {_num(official_full.get('Sharpe'), 3)}"
        ),
        (
            f"2026-02 影子 {_pct(feb.get('shadow'), 'rounded_pct')} / 官方 {_pct(feb.get('official'), 'rounded_pct')} · "
            f"2026-03 影子 {_pct(mar.get('shadow'), 'rounded_pct')} / 官方 {_pct(mar.get('official'), 'rounded_pct')} · "
            f"两月连乘 影子 {_pct(both.get('shadow'))} / 官方 {_pct(both.get('official'))}"
        ),
        f"2026-10-30 → as_of 影子 {_pct(nov.get('shadow'))} / 官方 {_pct(nov.get('official'))}",
        "2026 纸面执行日：" + ("；".join(str(item) for item in execs) if execs else "—"),
        comparison.get("rule_difference_vs_exit_only_replay") or "",
        payload.get("disclaimer") or "",
        "Source: data/qqq_vegas/shadow_2day_confirm/. Official v9 remains data/qqq_vegas/.",
    ]
    return html.Div([
        title,
        banner,
        html.Div(
            [html.Div(line, style={"marginBottom": "6px"}) for line in lines if line],
            style={"color": "#c8c8d4", "fontSize": "12px", "lineHeight": "1.45"},
        ),
    ], id="qqq-vegas-shadow", style=box)
