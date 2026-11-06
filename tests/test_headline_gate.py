"""US refresh headline gate: same-path baseline, not a mismatched prior row."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.dashboard.gcs_sync import SYNC_FILES, US_BACKTEST_FILES
from src.dashboard.headline_gate import (
    BASELINE_REL,
    CAGR_JUMP_LIMIT_PP,
    LAG_HONESTY_REL,
    MAXDD_WORSEN_LIMIT_PP,
    PRODUCTION_PATH,
    RESET_ENV,
    comparison_headline_pp,
    evaluate_headline_gate,
    fraction_headline_pp,
    headline_from_comparison_frame,
    headline_jumps,
    headlines_agree,
    load_same_path_headline,
    load_uploaded_baseline,
    reset_requested,
    write_uploaded_baseline,
)

ROOT = Path(__file__).resolve().parents[1]

# Observed gate inputs, Nov 2026. Look-ahead is lag_honesty row A_lookahead.
# The targeted run is row B_targeted / 20yr_comparison.csv.
LOOKAHEAD = (14.47, 13.9)
TARGETED = (13.10, 14.13)
DAILY_REFRESH = (13.07, 14.13)


class HeadlineJumpRuleTests(unittest.TestCase):
    def test_limits_stay_one_percentage_point(self):
        self.assertEqual(CAGR_JUMP_LIMIT_PP, 1.0)
        self.assertEqual(MAXDD_WORSEN_LIMIT_PP, 1.0)

    def test_comparison_cells_are_display_percents(self):
        self.assertEqual(comparison_headline_pp("13.10%", "14.13%"), (13.10, 14.13))
        self.assertEqual(comparison_headline_pp("13.10", "14.13"), (13.10, 14.13))
        self.assertIsNone(comparison_headline_pp("—", "14.13%"))

    def test_cagr_boundary_is_exclusive(self):
        base = (13.10, 14.13)
        self.assertFalse(headline_jumps((base[0] + 1.0, base[1]), base))
        self.assertTrue(headline_jumps((base[0] + 1.01, base[1]), base))
        self.assertTrue(headline_jumps((base[0] - 1.01, base[1]), base))

    def test_max_drawdown_blocks_only_when_it_worsens(self):
        base = (13.10, 14.13)
        self.assertFalse(headline_jumps((13.10, 14.13 + 1.0), base))
        self.assertTrue(headline_jumps((13.10, 14.13 + 1.01), base))
        self.assertFalse(headline_jumps((13.10, 14.13 - 2.0), base))

    def test_missing_side_does_not_block(self):
        self.assertFalse(headline_jumps(None, TARGETED))
        self.assertFalse(headline_jumps(DAILY_REFRESH, None))


class MismatchedHeadlineTests(unittest.TestCase):
    def test_lookahead_previous_does_not_block_a_targeted_refresh(self):
        """The live failure: prior row is A_lookahead, the new run is B_targeted."""
        decision = evaluate_headline_gate(
            previous=LOOKAHEAD,
            new=DAILY_REFRESH,
            same_path=TARGETED,
        )
        self.assertFalse(decision.block)
        self.assertEqual(decision.baseline_source, "same_path")
        self.assertEqual(decision.baseline, TARGETED)
        self.assertTrue(headline_jumps(DAILY_REFRESH, LOOKAHEAD))

    def test_garbage_run_still_blocks_against_the_targeted_path(self):
        # 2026-07-12 class of failure: a broken macro fetch, not a new day of prices.
        garbage = (11.82, 15.97)
        decision = evaluate_headline_gate(
            previous=LOOKAHEAD,
            new=garbage,
            same_path=TARGETED,
        )
        self.assertTrue(decision.block)
        self.assertEqual(decision.baseline_source, "same_path")
        self.assertTrue(decision.would_block)

    def test_day_to_day_uses_the_matching_comparison_row(self):
        decision = evaluate_headline_gate(
            previous=TARGETED,
            new=DAILY_REFRESH,
            same_path=TARGETED,
        )
        self.assertFalse(decision.block)
        self.assertEqual(decision.baseline_source, "last_comparison")

    def test_genuine_jump_against_a_matching_row_still_blocks(self):
        decision = evaluate_headline_gate(
            previous=TARGETED,
            new=(14.47, 14.13),
            same_path=TARGETED,
        )
        self.assertTrue(decision.block)
        self.assertEqual(decision.baseline_source, "last_comparison")

    def test_legacy_comparison_when_the_same_path_file_is_missing(self):
        decision = evaluate_headline_gate(
            previous=(14.60, 13.90),
            new=(11.82, 15.97),
            same_path=None,
        )
        self.assertTrue(decision.block)
        self.assertEqual(decision.baseline_source, "last_comparison")

    def test_no_baseline_does_not_block(self):
        decision = evaluate_headline_gate(previous=None, new=DAILY_REFRESH, same_path=None)
        self.assertFalse(decision.block)
        self.assertEqual(decision.baseline_source, "none")


class UploadedBaselineTests(unittest.TestCase):
    def test_last_accepted_upload_beats_a_mismatched_comparison_row(self):
        decision = evaluate_headline_gate(
            previous=LOOKAHEAD,
            new=(13.09, 14.14),
            same_path=TARGETED,
            uploaded=DAILY_REFRESH,
        )
        self.assertFalse(decision.block)
        self.assertEqual(decision.baseline_source, "gcs_last_good")
        self.assertEqual(decision.baseline, DAILY_REFRESH)

    def test_last_accepted_upload_still_blocks_a_real_jump(self):
        decision = evaluate_headline_gate(
            previous=DAILY_REFRESH,
            new=LOOKAHEAD,
            same_path=TARGETED,
            uploaded=DAILY_REFRESH,
        )
        self.assertTrue(decision.block)
        self.assertEqual(decision.baseline_source, "gcs_last_good")

    def test_sidecar_roundtrip_ignores_a_different_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "headline_baseline.json"
            write_uploaded_baseline(path, DAILY_REFRESH)
            self.assertEqual(load_uploaded_baseline(path), DAILY_REFRESH)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["path"] = "A_lookahead"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIsNone(load_uploaded_baseline(path))
            path.write_text("{", encoding="utf-8")
            self.assertIsNone(load_uploaded_baseline(path))
            self.assertIsNone(load_uploaded_baseline(path.with_name("missing.json")))

    def test_sidecar_is_part_of_the_gcs_sync_set(self):
        self.assertEqual(BASELINE_REL, "data/backtest_results/headline_baseline.json")
        self.assertIn(BASELINE_REL, SYNC_FILES)
        self.assertIn(BASELINE_REL, US_BACKTEST_FILES)
        for rel in US_BACKTEST_FILES:
            self.assertIn(rel, SYNC_FILES)
        self.assertEqual(PRODUCTION_PATH, "B_targeted")


class ResetTests(unittest.TestCase):
    def test_reset_allows_one_real_jump_and_reports_that_it_would_have_blocked(self):
        decision = evaluate_headline_gate(
            previous=TARGETED,
            new=LOOKAHEAD,
            same_path=TARGETED,
            uploaded=TARGETED,
            allow_reset=True,
        )
        self.assertFalse(decision.block)
        self.assertTrue(decision.would_block)
        self.assertEqual(decision.baseline_source, "reset")
        self.assertIn(RESET_ENV, decision.reason)

    def test_reset_env_values(self):
        self.assertTrue(reset_requested({RESET_ENV: "1"}))
        self.assertTrue(reset_requested({RESET_ENV: "true"}))
        self.assertTrue(reset_requested({RESET_ENV: " YES "}))
        self.assertFalse(reset_requested({}))
        self.assertFalse(reset_requested({RESET_ENV: "0"}))


class PublishedPackageTests(unittest.TestCase):
    def test_baked_comparison_matches_targeted_not_lookahead(self):
        same = load_same_path_headline(ROOT / LAG_HONESTY_REL)
        baked = headline_from_comparison_frame(
            pd.read_csv(ROOT / "data" / "backtest_results" / "20yr_comparison.csv", index_col=0)
        )
        table = pd.read_csv(ROOT / LAG_HONESTY_REL, index_col=0)
        lookahead = fraction_headline_pp(
            table.loc["A_lookahead", "cagr"],
            table.loc["A_lookahead", "max_dd"],
        )
        self.assertIsNotNone(same)
        self.assertIsNotNone(baked)
        self.assertIsNotNone(lookahead)
        self.assertTrue(headlines_agree(baked, same), (baked, same))
        self.assertFalse(headlines_agree(lookahead, same), (lookahead, same))
        drifted = (same[0] - 0.03, same[1])
        decision = evaluate_headline_gate(
            previous=lookahead,
            new=drifted,
            same_path=same,
        )
        self.assertFalse(decision.block)
        self.assertEqual(decision.baseline_source, "same_path")
        self.assertTrue(headline_jumps(drifted, lookahead))


class RefreshWiringTests(unittest.TestCase):
    def test_tasks_refresh_uses_the_gate_and_keeps_the_error_code(self):
        source = (ROOT / "run_dashboard.py").read_text(encoding="utf-8")
        self.assertIn("evaluate_headline_gate", source)
        self.assertIn("HEADLINE_GATE_RESET", source)
        self.assertIn("write_uploaded_baseline", source)
        self.assertIn("quality_gate_headline_jump", source)
        self.assertNotIn("abs(new[0] - prev[0])", source)
        success = source[source.index("if gate.block:"):]
        us_at = success.index("upload_us_backtest()")
        cdn_at = success.index("refresh_cdn_backtest()")
        self.assertLess(us_at, cdn_at)
        # Vegas and the notify-only scorecard still upload when the US gate blocks.
        gate_at = source.index("if gate.block:")
        failed_at = source.index("error': 'backtest_failed'")
        self.assertLess(failed_at, gate_at)
        blocked = source[gate_at:source.index("cdn_backtest = refresh_cdn_backtest()")]
        self.assertIn("_upload_qqq_vegas_market()", blocked)
        self.assertIn("_upload_qqq_vegas_signal()", blocked)
        self.assertIn("_upload_risk_flags()", blocked)


if __name__ == "__main__":
    unittest.main()
