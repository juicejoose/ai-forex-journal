"""Deterministic score regressions; synthetic market data, no network or user DB."""

import copy
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from tests.test_market_data import FixedDateTime, payload
import market_data as md
from journal_grounding import InvalidJournalEvidence
from strategy_rules import evaluate_strategy, rule_set_definition, _consecutive, LEGACY_RULE_SET_ID, MOMENTUM_RULE_SET_ID


def scoring_snapshot():
    with patch.object(md, "datetime", FixedDateTime), patch.object(md, "_fetch_candles", return_value=payload()):
        snapshot = md.get_market_data(date(2026, 10, 20))
    for candle in [snapshot["previous_candle"], *snapshot["candles"]]:
        candle.update(open=1.2, high=1.4, low=0.9, close=1.25)
        candle["indicators"].update(ema20=1.2, sma190=1.1, rsi14=30)
        candle["indicators"]["squeeze"]["momentum"] = 0.001
    for index, candle in enumerate(snapshot["candles"]):
        candle["indicators"]["squeeze"]["momentum"] = 0.002 + index * 0.001
    snapshot["summary"].update(open=1.2, close=1.25, high=1.4, low=0.9, change=0.05,
                              change_pips=500, change_percent=100 * 0.05 / 1.2)
    return snapshot


class StrategyRulesTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = scoring_snapshot()

    def outcome(self, factor_index, candle_index=0):
        return evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)["candles"][candle_index]["factors"][factor_index]["outcome"]

    def test_all_bullish_weighted_points_per_candle(self):
        result = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)
        self.assertEqual(len(result["candles"]), 6)
        for candle in result["candles"]:
            self.assertEqual((candle["bullish_points"], candle["bearish_points"], candle["net_score"]), (5, 0, 5))
            self.assertEqual(candle["bullish_alignment_percent"], 100)
        self.assertEqual(result["summary"]["bullish_points"], 5)  # Not a 30-point session sum.
        self.assertEqual(result["summary"]["candle_id"], "C6")

    def test_consecutive_closes_use_each_candles_own_ema(self):
        self.snapshot["previous_candle"]["indicators"]["ema20"] = 1.3
        self.assertEqual(self.outcome(0), "neutral")
        self.snapshot["candles"][0]["indicators"]["ema20"] = 1.3
        self.assertEqual(self.outcome(0), "bearish")
        self.snapshot["previous_candle"]["close"] = 1.3
        self.assertEqual(self.outcome(0), "neutral")

    def test_full_precision_comparison_and_equality(self):
        row = self.snapshot["candles"][0]["indicators"]
        row.update(ema20=1.200000000001, sma190=1.2)
        self.assertEqual(self.outcome(1), "bullish")
        row["ema20"] = 1.2
        self.assertEqual(self.outcome(1), "neutral")
        row["ema20"] = 1.199999999999
        self.assertEqual(self.outcome(1), "bearish")

    def test_rsi_exact_boundaries_and_missing(self):
        for value, outcome in [(0, "bullish"), (39.9, "bullish"), (40, "bullish"),
                               (40.00001, "neutral"), (59.99999, "neutral"),
                               (60, "bearish"), (100, "bearish"), (None, "unavailable"),
                               (-1, "unavailable"), (101, "unavailable")]:
            with self.subTest(value=value):
                self.snapshot["candles"][0]["indicators"]["rsi14"] = value
                self.assertEqual(self.outcome(2), outcome)

    def test_momentum_requires_both_sign_and_change(self):
        for previous, current, outcome in [
            (0.001, 0.002, "bullish"), (0.002, 0.001, "neutral"),
            (-0.002, -0.001, "neutral"), (-0.001, -0.002, "bearish"),
            (0.001, 0.001, "neutral"), (-0.001, -0.001, "neutral"),
            (-0.001, 0, "neutral"), (0.001, 0, "neutral"),
            (-0.001, 0.001, "bullish"), (0.001, -0.001, "bearish"),
        ]:
            with self.subTest(previous=previous, current=current):
                self.snapshot["previous_candle"]["indicators"]["squeeze"]["momentum"] = previous
                self.snapshot["candles"][0]["indicators"]["squeeze"]["momentum"] = current
                self.assertEqual(self.outcome(3), outcome)

    def test_missing_previous_is_unavailable_only_where_needed(self):
        self.snapshot.pop("previous_candle")
        result = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)
        first = result["candles"][0]
        self.assertEqual([f["outcome"] for f in first["factors"]], ["unavailable", "bullish", "bullish", "unavailable"])
        self.assertEqual(first["bullish_alignment_percent"], 60)
        self.assertEqual(first["direction"], "insufficient_data")
        self.assertEqual(result["candles"][1]["evaluated_factors"], 3)
        self.assertEqual(result["candles"][2]["evaluated_factors"], 4)

    def test_final_candle_controls_bias_not_earlier_majority(self):
        for candle in self.snapshot["candles"][-2:]:
            candle["indicators"].update(ema20=1.3, sma190=1.35, rsi14=70)
        self.snapshot["candles"][-2]["indicators"]["squeeze"]["momentum"] = -0.001
        self.snapshot["candles"][-1]["indicators"]["squeeze"]["momentum"] = -0.002
        result = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)
        self.assertEqual(result["candles"][0]["direction"], "bullish")
        self.assertEqual(result["summary"]["direction"], "bearish")
        self.assertEqual(result["summary"]["bearish_points"], 5)
        self.snapshot["candles"][-1]["indicators"]["rsi14"] = None
        incomplete = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)["summary"]
        self.assertEqual(incomplete["direction"], "insufficient_data")
        self.assertEqual(incomplete["bearish_alignment_percent"], 80)

    def test_neutral_and_mixed_are_different(self):
        for candle in [self.snapshot["previous_candle"], *self.snapshot["candles"]]:
            candle["indicators"].update(ema20=1.25, sma190=1.25, rsi14=50)
            candle["indicators"]["squeeze"]["momentum"] = 0
        result = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)["summary"]
        self.assertEqual((result["direction"], result["neutral_factors"]), ("neutral", 4))
        self.snapshot["candles"][-1]["indicators"].update(sma190=1.2, rsi14=60)
        self.snapshot["candles"][-1]["indicators"]["squeeze"]["momentum"] = -0.001
        result = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)["summary"]
        self.assertEqual((result["direction"], result["bullish_points"], result["bearish_points"]), ("mixed", 2, 2))

    def test_future_changes_cannot_change_earlier_scores_and_inputs_are_not_mutated(self):
        before = copy.deepcopy(self.snapshot)
        result = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)
        self.assertEqual(self.snapshot, before)
        self.snapshot["candles"][-1]["indicators"]["rsi14"] = 70
        changed = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)
        self.assertEqual(result["candles"][:-1], changed["candles"][:-1])
        self.assertNotEqual(result["summary"], changed["summary"])

    def test_predecessor_rejects_missing_bar_overlap_and_future(self):
        current = self.snapshot["candles"][0]
        for previous in (None, {}, current, self.snapshot["candles"][-1]):
            self.assertFalse(_consecutive(previous, current))
        previous = self.snapshot["previous_candle"]
        self.assertTrue(_consecutive(previous, current))
        previous["open_time"] = "2026-10-19T09:00:00+00:00"
        previous["close_time"] = "2026-10-19T13:00:00+00:00"
        self.assertFalse(_consecutive(previous, current))

    def test_weekend_continuity_including_dst(self):
        for opened, closed, next_open in [
            ("2026-10-30T17:00:00+00:00", "2026-10-30T21:00:00+00:00", "2026-11-01T22:00:00+00:00"),
            ("2026-03-06T18:00:00+00:00", "2026-03-06T22:00:00+00:00", "2026-03-08T21:00:00+00:00"),
        ]:
            self.assertTrue(_consecutive({"open_time": opened, "close_time": closed}, {"open_time": next_open}))

    def test_real_market_context_has_correct_indicators_and_is_not_in_session(self):
        with patch.object(md, "datetime", FixedDateTime), patch.object(md, "_fetch_candles", return_value=payload()):
            snapshot = md.get_market_data(date(2026, 10, 20))
        previous = snapshot["previous_candle"]
        self.assertEqual(previous["close_time"], snapshot["session"]["start_utc"])
        self.assertEqual(previous["indicators"]["sma190"], 1.2)
        self.assertEqual(len(snapshot["candles"]), 6)
        self.assertNotIn(previous, snapshot["candles"])

    def test_wrong_instrument_periods_and_bad_session_are_rejected(self):
        for change in [lambda s: s.update(instrument="GBP_USD"),
                       lambda s: s["indicator_settings"]["ema"].update(period=50),
                       lambda s: s["candles"].reverse()]:
            value = copy.deepcopy(self.snapshot)
            change(value)
            with self.assertRaises(InvalidJournalEvidence):
                evaluate_strategy(value, MOMENTUM_RULE_SET_ID)

    def test_definition_is_a_fresh_versioned_snapshot(self):
        definition = rule_set_definition()
        self.assertEqual((definition["version"], definition["max_points"]), (4, 5))
        definition["factors"][0]["points"] = 100
        self.assertEqual(rule_set_definition()["factors"][0]["points"], 1)

    def test_ema_sma_weight_changes_bias_and_alignment_without_changing_factor_count(self):
        for candle in [self.snapshot["previous_candle"], *self.snapshot["candles"]]:
            candle["indicators"].update(ema20=1.25, sma190=1.2, rsi14=60)
            candle["indicators"]["squeeze"]["momentum"] = 0
        result = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)
        summary = result["summary"]
        self.assertEqual((summary["bullish_points"], summary["bearish_points"], summary["net_score"]), (2, 1, 1))
        self.assertEqual((summary["bullish_alignment_percent"], summary["bearish_alignment_percent"]), (40, 20))
        self.assertEqual((summary["direction"], summary["evaluated_factors"], summary["max_points"]), ("bullish", 4, 5))
        for candle in result["candles"]:
            self.assertEqual(candle["factors"][1]["bullish_points"], 2)
        self.snapshot["candles"][-1]["indicators"].update(sma190=1.3, rsi14=40)
        summary = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)["summary"]
        self.assertEqual((summary["direction"], summary["bullish_points"], summary["bearish_points"]), ("bearish", 1, 2))
        self.assertEqual((summary["bullish_alignment_percent"], summary["bearish_alignment_percent"]), (20, 40))

    def test_legacy_version_retains_original_thresholds_weights_and_definition(self):
        definition = rule_set_definition(LEGACY_RULE_SET_ID)
        self.assertEqual((definition["version"], definition["max_points"]), (1, 4))
        self.assertEqual([factor["points"] for factor in definition["factors"]], [1, 1, 1, 1])
        for value, expected in [(30, "bullish"), (30.00001, "neutral"), (40, "neutral"),
                                (60, "neutral"), (69.99999, "neutral"), (70, "bearish")]:
            self.snapshot["candles"][-1]["indicators"]["rsi14"] = value
            result = evaluate_strategy(self.snapshot, LEGACY_RULE_SET_ID)
            self.assertEqual(result["candles"][-1]["factors"][2]["outcome"], expected)
            self.assertEqual(result["candles"][-1]["factors"][1]["bullish_points"], 1)
            self.assertEqual(result["summary"]["max_points"], 4)
        with self.assertRaises(InvalidJournalEvidence):
            evaluate_strategy(self.snapshot, "four_factor_v999")


if __name__ == "__main__":
    unittest.main()
