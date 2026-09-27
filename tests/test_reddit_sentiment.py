"""Offline tests for Reddit retail attention. No network."""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from src.strategist.reddit_sentiment import (
    CONF_SCALE,
    MEGA_FACTOR,
    SENT_FLOOR,
    SENT_SLOPE,
    VELOCITY_COEF,
    WATCH_COMPOSITE,
    _drop_megathread_parents,
    aggregate_posts,
    extract_ticker_hits,
    format_attention_row,
)
from src.strategist.strategy_advisor import (
    StrategyRecommendation,
    annotate_with_retail_attention,
)

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "reddit_posts.json"


def _load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TickerExtractTests(unittest.TestCase):
    def test_cashtag_alias_and_lowercase_bare(self):
        hits = extract_ticker_hits("$MU calls. Micron ripping. nvda weak. $SMCI")
        self.assertTrue(hits["MU"]["cashtag"])
        self.assertTrue(hits["MU"]["alias"])
        self.assertGreaterEqual(hits["MU"]["mentions"], 2)
        self.assertIn("NVDA", hits)
        self.assertTrue(hits["SMCI"]["cashtag"])

    def test_common_words_are_not_tickers(self):
        hits = extract_ticker_hits("I think IT is FOR ALL of US and the AI trade")
        for bad in ("I", "IT", "FOR", "ALL", "US", "AI", "IS"):
            self.assertNotIn(bad, hits)

    def test_english_words_need_uppercase_or_cashtag(self):
        self.assertNotIn("ARM", extract_ticker_hits("I hurt my arm yesterday"))
        self.assertNotIn("META", extract_ticker_hits("this is a meta analysis of the trade"))
        upper = extract_ticker_hits("ARM is squeezing and META earnings are tonight")
        self.assertIn("ARM", upper)
        self.assertIn("META", upper)

    def test_slang_cashtags_blocked_real_cashtag_kept(self):
        hits = extract_ticker_hits("$YOLO $DD $AI is the name")
        self.assertNotIn("YOLO", hits)
        self.assertNotIn("DD", hits)
        self.assertIn("AI", hits)
        self.assertTrue(hits["AI"]["cashtag"])

    def test_megathread_parent_dropped_comments_kept(self):
        posts = [
            {"id": "p", "title": "Daily Discussion Thread", "text": "rules", "is_comment": False},
            {"id": "c", "title": "user on Daily Discussion Thread", "text": "$MU calls",
             "is_comment": True},
        ]
        kept = _drop_megathread_parents(posts)
        self.assertEqual([p["id"] for p in kept], ["c"])

    def test_mention_cap(self):
        hits = extract_ticker_hits("MU " * 20)
        self.assertEqual(hits["MU"]["mentions"], 5)

    def test_index_cashtag_extracted_but_not_a_stock_pick(self):
        hits = extract_ticker_hits("$SPX calls printed")
        self.assertIn("SPX", hits)


class AggregateTests(unittest.TestCase):
    def test_fixture_ranks_mu_and_drops_one_mention_neutral(self):
        result = aggregate_posts(_load(), prior_counts={"MU": 1}, source="fixture")
        tickers = [r["ticker"] for r in result["tickers"]]
        self.assertIn("MU", tickers)
        self.assertIn("NVDA", tickers)
        self.assertIn("SMCI", tickers)
        self.assertNotIn("MSFT", tickers)
        self.assertNotIn("AI", tickers)
        self.assertNotIn("IT", tickers)
        self.assertEqual(tickers[0], "MU")

        by = {r["ticker"]: r for r in result["tickers"]}
        mu = by["MU"]
        self.assertEqual(mu["unique_posts"], 3)
        self.assertGreaterEqual(mu["mentions"], 3)
        self.assertEqual(mu["label"], "Bullish")
        self.assertEqual(mu["action"], "watch_long")
        self.assertEqual(mu["kind"], "stock")
        self.assertAlmostEqual(mu["velocity"], 2.0, places=3)
        self.assertAlmostEqual(mu["sentiment_mean"], 0.6, places=3)

        attention = math.log1p(3)
        sent = SENT_FLOOR + SENT_SLOPE * 0.6
        vel_factor = min(2.5, max(0.5, 1.0 + VELOCITY_COEF * 2.0))
        confidence = 1.0 - math.exp(-3 / CONF_SCALE)
        expected = round(attention * sent * vel_factor * 1.0 * confidence, 3)
        self.assertAlmostEqual(mu["composite"], expected, places=3)
        self.assertGreater(mu["composite"], WATCH_COMPOSITE)
        self.assertGreater(mu["composite"], by["NVDA"]["composite"])

        nvda = by["NVDA"]
        self.assertEqual(nvda["label"], "Bearish")
        self.assertEqual(nvda["action"], "watch_avoid")
        self.assertEqual(nvda["mega_factor"], 1.0)  # velocity spike relaxes the dampener

        smci = by["SMCI"]
        self.assertEqual(smci["unique_posts"], 1)
        self.assertEqual(smci["action"], "monitor")

        ra = result["retail_attention"]
        self.assertTrue(ra["experimental"])
        self.assertFalse(ra["affects_regime_weights"])
        self.assertIn("MU", ra["picks"]["watch_long"])
        self.assertIn("NVDA", ra["picks"]["watch_avoid"])
        self.assertEqual(ra["hype_caution"], [])
        self.assertIn("composite = attention", ra["formula"])

    def test_mega_dampener_without_a_spike(self):
        posts = [
            {"id": "1", "text": "NVDA up", "compound": 0.4, "upvotes": 0, "comments": 0},
            {"id": "2", "text": "NVDA again", "compound": 0.4, "upvotes": 0, "comments": 0},
        ]
        result = aggregate_posts(posts, prior_counts=None, source="fixture")
        row = result["tickers"][0]
        self.assertEqual(row["ticker"], "NVDA")
        self.assertIsNone(row["velocity"])
        self.assertEqual(row["velocity_factor"], 1.0)
        self.assertEqual(row["mega_factor"], MEGA_FACTOR)

    def test_single_bare_mention_is_dropped(self):
        posts = [{"id": "1", "text": "MSFT looks okay", "compound": 0.8}]
        result = aggregate_posts(posts, source="fixture")
        self.assertEqual(result["tickers"], [])
        self.assertEqual(result["retail_attention"]["ranked_stocks"], [])

    def test_hype_caution_needs_a_crowd_and_a_spike(self):
        posts = [
            {"id": str(i), "text": f"$GME still going {i}", "compound": 0.85,
             "upvotes": 10, "comments": 2}
            for i in range(6)
        ]
        result = aggregate_posts(posts, prior_counts={"GME": 2}, source="fixture")
        row = next(r for r in result["tickers"] if r["ticker"] == "GME")
        self.assertEqual(row["action"], "hype_caution")
        self.assertIn("GME", result["hype"])
        self.assertNotIn("GME", result["retail_attention"]["picks"]["watch_long"])
        self.assertIn("GME", result["retail_attention"]["picks"]["hype_caution"])

    def test_index_not_in_the_pick_list(self):
        posts = [
            {"id": "1", "text": "$SPX to the moon", "compound": 0.6},
            {"id": "2", "text": "$SPX again", "compound": 0.6},
        ]
        result = aggregate_posts(posts, source="fixture")
        self.assertEqual(result["tickers"], [])

    def test_per_ticker_compounds_do_not_share_one_score(self):
        posts = [
            {"id": "1", "text": "MU rip NVDA dump", "compounds": {"MU": 0.8, "NVDA": -0.6}},
            {"id": "2", "text": "MU bid NVDA offered", "compounds": {"MU": 0.6, "NVDA": -0.4}},
        ]
        result = aggregate_posts(posts, source="fixture")
        by = {r["ticker"]: r for r in result["tickers"]}
        self.assertGreater(by["MU"]["sentiment_mean"], 0.5)
        self.assertLess(by["NVDA"]["sentiment_mean"], -0.4)

    def test_row_text_is_spaced_and_has_the_sample(self):
        result = aggregate_posts(_load(), prior_counts={"MU": 1}, source="fixture")
        line = format_attention_row(result["tickers"][0])
        self.assertTrue(line.startswith("MU  ·  3 posts"))
        self.assertIn("mentions", line)
        self.assertIn("vel +200%", line)
        self.assertIn("watch long", line)
        self.assertNotIn("MU3", line)
        self.assertNotIn("1×", line)


class AdvisorOverlayTests(unittest.TestCase):
    def test_overlay_does_not_change_weights(self):
        rec = StrategyRecommendation(
            regime="goldilocks",
            confidence=0.8,
            target_weights={"SPY": 0.6, "AGG": 0.4},
            rationale=["base"],
        )
        payload = aggregate_posts(
            [
                {"id": str(i), "text": f"$GME {i}", "compound": 0.9}
                for i in range(6)
            ],
            prior_counts={"GME": 2},
            source="fixture",
        )["retail_attention"]
        weights = dict(rec.target_weights)
        out = annotate_with_retail_attention(rec, payload)
        self.assertEqual(out.target_weights, weights)
        self.assertEqual(out.target_weights, {"SPY": 0.6, "AGG": 0.4})
        self.assertTrue(out.retail_attention["experimental"])
        self.assertFalse(out.retail_attention["affects_regime_weights"])
        self.assertTrue(any("ETF regime weights are unchanged" in line for line in out.rationale))
        self.assertTrue(any("GME" in flag for flag in out.risk_flags))
        self.assertTrue(out.rationale[0] == "base")

    def test_empty_overlay_is_a_noop(self):
        rec = StrategyRecommendation(
            regime="deflation",
            confidence=0.5,
            target_weights={"SPY": 0.5, "AGG": 0.5},
            rationale=["only"],
        )
        out = annotate_with_retail_attention(rec, {})
        self.assertEqual(out.rationale, ["only"])
        self.assertEqual(out.risk_flags, [])
        self.assertEqual(out.target_weights, {"SPY": 0.5, "AGG": 0.5})


if __name__ == "__main__":
    unittest.main()
