"""Shadow 2-day confirmation. Official v9 files are only read."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.refresh_qqq_vegas_shadow import build_shadow_pack  # noqa: E402
from src.dashboard.gcs_sync import VEGAS_SHADOW_FILES, VEGAS_SIGNAL_FILES  # noqa: E402
from src.qqq_vegas.shadow_2day import (  # noqa: E402
    CONFIRM_SESSIONS,
    shadow_position,
    shadow_strategy_return,
)

OFFICIAL = ROOT / "data" / "qqq_vegas"
OFFICIAL_NAMES = (
    "daily_signal.csv",
    "equity_curve.csv",
    "rebalances.csv",
    "signal_current.json",
    "summary.json",
    "strategy.json",
    "live_snapshot.json",
)


class ConfirmRuleTests(unittest.TestCase):
    def test_entry_and_exit_need_two_consecutive_sessions(self):
        raw = pd.Series([0, 1, 1, 1, 0, 1, 0, 0, 0], index=pd.bdate_range("2020-01-02", periods=9))
        frame = shadow_position(raw)
        self.assertEqual(CONFIRM_SESSIONS, 2)
        self.assertEqual(list(frame["confirmed_signal"]), [0, 0, 1, 1, 1, 1, 1, 0, 0])
        # Next-session fill. The first bar stays cash.
        self.assertEqual(list(frame["pos"]), [0, 0, 0, 1, 1, 1, 1, 1, 0])

    def test_a_one_day_flip_does_not_trade(self):
        raw = pd.Series([1, 1, 0, 1, 1], index=pd.bdate_range("2020-01-02", periods=5))
        frame = shadow_position(raw)
        self.assertEqual(list(frame["confirmed_signal"]), [0, 1, 1, 1, 1])
        self.assertNotIn(0, list(frame["pos"])[2:])

    def test_shared_days_use_official_return_and_skipped_cost_is_not_charged(self):
        index = pd.bdate_range("2020-01-02", periods=4)
        qqq = pd.Series(0.01, index=index)
        qld = pd.Series(0.02, index=index)
        cash = pd.Series(0.0001, index=index)
        # Official enters on day 2 (pos becomes 1) and stays long.
        official_pos = pd.Series([0, 0, 1, 1], index=index)
        gross = 0.7 * 0.01 + 0.3 * 0.02
        official_strat = pd.Series([0.0, 0.0001, gross - 0.0004, gross], index=index)
        # Shadow is already long on the official entry day, so it should not pay that 4 bps.
        shadow_pos = pd.Series([0, 1, 1, 1], index=index)
        out = shadow_strategy_return(qqq, qld, cash, shadow_pos, official_pos, official_strat)
        self.assertAlmostEqual(float(out.iloc[0]), 0.0)
        self.assertAlmostEqual(float(out.iloc[2]), gross)
        self.assertAlmostEqual(float(out.iloc[3]), gross)


class OfficialPackTests(unittest.TestCase):
    def test_shadow_build_does_not_modify_official_v9_files(self):
        before = {name: (OFFICIAL / name).read_bytes() for name in OFFICIAL_NAMES}
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_shadow_pack(official_dir=OFFICIAL, output_dir=Path(tmp))
            daily = pd.read_csv(Path(tmp) / "daily_signal.csv", parse_dates=["date"]).set_index("date")
            official = pd.read_csv(OFFICIAL / "daily_signal.csv", parse_dates=["date"]).set_index("date")
        after = {name: (OFFICIAL / name).read_bytes() for name in OFFICIAL_NAMES}
        self.assertEqual(before, after)
        rebuilt = shadow_position(official["signal"])
        self.assertTrue((daily["pos"].astype(int) == rebuilt["pos"].astype(int)).all())
        self.assertTrue((daily["raw_signal"].astype(int) == official["signal"].astype(int)).all())
        self.assertFalse(summary["replaces_official_v9"])
        self.assertFalse(summary["emits_live_alerts"])
        self.assertFalse(summary["live_orders"])
        self.assertIn("影子", summary["label_zh"])
        self.assertIn("实验", summary["rule_zh"])
        self.assertNotIn("1.15", summary["rule_en"])
        self.assertIn("No price band", summary["rule_en"])
        comparison = summary["paper_comparison"]
        self.assertGreater(comparison["official_flips_full"], comparison["shadow_flips_full"])
        self.assertGreater(comparison["shadow_flips_full"], 0)
        self.assertEqual(summary["official_strategy_id"], "qqq_vegas_rv20_q80")
        for name in VEGAS_SIGNAL_FILES:
            self.assertNotIn("shadow_2day_confirm", name)
        for name in VEGAS_SHADOW_FILES:
            self.assertIn("shadow_2day_confirm", name)
            self.assertNotIn(name, VEGAS_SIGNAL_FILES)

    def test_notify_copy_does_not_mention_the_shadow_book(self):
        text = (ROOT / "scripts" / "notify_regime.py").read_text(encoding="utf-8")
        self.assertNotIn("shadow_2day_confirm", text)
        self.assertNotIn("qqq_vegas_shadow", text)

    def test_dashboard_panel_is_labeled_shadow(self):
        from src.dashboard.app import _build_qqq_vegas_body, load_qqq_vegas
        from src.dashboard.qqq_vegas_shadow import build_shadow_panel

        panel = build_shadow_panel({
            "as_of": "2026-11-27",
            "confirm_sessions": 2,
            "cost_bps": 4.0,
            "label_zh": "影子 / 实验",
            "rule_zh": "连续两个收盘",
            "rule_en": "two consecutive closes",
            "disclaimer": "Not the official card.",
            "paper_comparison": {
                "official_flips_full": 10,
                "shadow_flips_full": 4,
                "official_flips_2026": 3,
                "shadow_flips_2026": 1,
                "official_flips_2026_02_03": 7,
                "shadow_flips_2026_02_03": 1,
                "shadow_2026_exec": ["2026-03-16 EXIT"],
                "full_sample": {
                    "official": {"CAGR_pct": 14.69, "MaxDD_pct": -27.81, "Sharpe": 0.829},
                    "shadow": {"CAGR_pct": 14.0, "MaxDD_pct": -28.0, "Sharpe": 0.8},
                },
                "windows": {},
                "rule_difference_vs_exit_only_replay": "both entry and exit",
            },
        })
        blob = "\n".join(_texts(panel))
        self.assertIn("影子", blob)
        self.assertIn("实验", blob)
        self.assertIn("Shadow", blob)
        self.assertIn("不是官方", blob)
        self.assertIn("不发实盘", blob)
        self.assertNotEqual(getattr(panel, "id", None), "qqq-vegas-root")
        bundle = load_qqq_vegas()
        body = _build_qqq_vegas_body(bundle)
        body_text = "\n".join(_texts(body))
        self.assertIn("qqq_vegas_rv20_q80", body_text)
        self.assertIn("影子", body_text)


def _texts(node):
    acc = []

    def _walk(item):
        if item is None or isinstance(item, (int, float, bool)):
            return
        if isinstance(item, str):
            acc.append(item)
            return
        if isinstance(item, dict):
            for value in item.values():
                _walk(value)
            return
        if isinstance(item, (list, tuple)):
            for value in item:
                _walk(value)
            return
        _walk(getattr(item, "children", None))

    _walk(node)
    return acc


if __name__ == "__main__":
    unittest.main()
