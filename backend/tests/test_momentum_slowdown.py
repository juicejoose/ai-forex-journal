"""Three-candle momentum scoring, boundary behavior and legacy compatibility."""

import copy
import unittest

from strategy_rules import (LEGACY_RULE_SET_ID, WEIGHTED_RULE_SET_ID, MOMENTUM_RULE_SET_ID, SESSION_RULE_SET_ID, _momentum_with_pace,
                            evaluate_strategy, rule_set_definition)
from tests.test_strategy_rules import scoring_snapshot


class MomentumSlowdownTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = scoring_snapshot()

    def first(self, values):
        candles = [*self.snapshot["previous_candles"], self.snapshot["candles"][0]]
        for candle, value in zip(candles, values):
            candle["indicators"]["squeeze"]["momentum"] = value
        return evaluate_strategy(self.snapshot, SESSION_RULE_SET_ID)["candles"][0]["factors"][-1]

    def test_bullish_slowdown_uses_exactly_three_candles(self):
        result = self.first([0.001, 0.0018, 0.0023])
        self.assertEqual((result["outcome"], result["bullish_points"], result["bearish_points"]), ("bullish", 0.5, 0))
        self.assertEqual(result["momentum_change"]["pace"], "slowing")
        self.assertAlmostEqual(result["momentum_change"]["previous_delta"], 0.0008)
        self.assertAlmostEqual(result["momentum_change"]["current_delta"], 0.0005)
        self.assertEqual([item["candle_id"] for item in result["evidence"]], ["P-1", "P0", "C1"])

    def test_negative_deltas_compare_magnitudes_not_signed_order(self):
        result = self.first([-0.001, -0.0018, -0.0023])
        self.assertEqual((result["outcome"], result["bullish_points"], result["bearish_points"]), ("bearish", 0, 0.5))
        self.assertEqual(result["momentum_change"]["pace"], "slowing")
        self.assertAlmostEqual(result["momentum_change"]["previous_delta"], -0.0008)
        self.assertAlmostEqual(result["momentum_change"]["current_delta"], -0.0005)

    def test_acceleration_keeps_full_point_on_either_side(self):
        for sign, side in [(1, "bullish"), (-1, "bearish")]:
            result = self.first([sign * value for value in [0.001, 0.0015, 0.0023]])
            self.assertEqual(result[f"{side}_points"], 1)
            self.assertEqual(result["momentum_change"]["pace"], "accelerating")

    def test_equal_deltas_and_floating_point_artifacts_are_steady(self):
        for values in ([0.005, 0.006, 0.007], [-0.005, -0.006, -0.007],
                       [0.001, 0.002, 0.003 - 1e-13]):
            result = self.first(values)
            self.assertEqual(result["momentum_change"]["pace"], "steady")
            self.assertEqual(result["bullish_points"] + result["bearish_points"], 1)
        self.assertEqual(self.first([0.001, 0.002, 0.003 - 1e-9])["momentum_change"]["pace"], "slowing")

    def test_unchanged_or_wrong_sign_movements_award_neither_side(self):
        for values in ([0.003, 0.002, 0.0015], [-0.003, -0.002, -0.0015],
                       [0.001, 0.002, 0.002], [-0.001, -0.002, -0.002], [0, 0, 0]):
            result = self.first(values)
            self.assertEqual((result["outcome"], result["bullish_points"], result["bearish_points"]), ("neutral", 0, 0))

    def test_zero_crossing_or_touch_resets_then_next_same_side_window_can_slow(self):
        for values in ([-0.001, 0.001, 0.0015], [0, 0.001, 0.0015],
                       [0.001, -0.001, -0.0015], [0, -0.001, -0.0015]):
            result = self.first(values)
            self.assertEqual(result["momentum_change"]["pace"], "transition")
            self.assertEqual(result["bullish_points"] + result["bearish_points"], 1)
        self.first([-0.001, 0.001, 0.0015])
        self.snapshot["candles"][1]["indicators"]["squeeze"]["momentum"] = 0.0017
        result = evaluate_strategy(self.snapshot, SESSION_RULE_SET_ID)["candles"][1]["factors"][-1]
        self.assertEqual((result["momentum_change"]["pace"], result["bullish_points"]), ("slowing", 0.5))
        self.assertEqual([item["candle_id"] for item in result["evidence"]], ["P0", "C1", "C2"])

    def test_new_direction_without_two_matching_deltas_retains_base_point(self):
        for values in ([0.002, 0.001, 0.0015], [-0.002, -0.001, -0.0015], [0.001, 0.001, 0.0015]):
            result = self.first(values)
            self.assertEqual(result["momentum_change"]["pace"], "new_move")
            self.assertEqual(result["bullish_points"] + result["bearish_points"], 1)

    def test_missing_oldest_history_is_unavailable_then_recovers(self):
        self.snapshot.pop("previous_candles")
        result = evaluate_strategy(self.snapshot, SESSION_RULE_SET_ID)
        first = result["candles"][0]
        self.assertEqual(first["factors"][-1]["outcome"], "unavailable")
        self.assertEqual((first["direction"], first["evaluated_factors"], first["max_points"]), ("insufficient_data", 3, 5))
        self.assertEqual(first["bullish_alignment_percent"], 80)
        self.assertEqual(result["candles"][1]["evaluated_factors"], 4)

    def test_incomplete_invalid_or_mismatched_context_never_earns_full_point(self):
        base = copy.deepcopy(self.snapshot)
        cases = [lambda s: s.update(previous_candles=[]),
                 lambda s: s["previous_candles"][0]["indicators"]["squeeze"].update(momentum=None),
                 lambda s: s["previous_candles"][0]["indicators"]["squeeze"].update(momentum=float("nan")),
                 lambda s: s["previous_candles"][0]["indicators"]["squeeze"].update(momentum=float("inf")),
                 lambda s: s["previous_candles"][0].update(close_time=s["candles"][-1]["close_time"]),
                 lambda s: s["previous_candles"].__setitem__(1, copy.deepcopy(s["candles"][0]))]
        for change in cases:
            snapshot = copy.deepcopy(base)
            change(snapshot)
            result = evaluate_strategy(snapshot, SESSION_RULE_SET_ID)["candles"][0]["factors"][-1]
            self.assertEqual((result["outcome"], result["bullish_points"], result["bearish_points"]), ("unavailable", 0, 0))
            self.assertEqual(result["momentum_change"]["pace"], "unavailable")

    def test_weekend_dst_chain_is_valid_but_missing_trading_bar_is_not(self):
        for older_times, previous_times, current_times in [
            (("2026-10-30T17:00:00+00:00", "2026-10-30T21:00:00+00:00"),
             ("2026-11-01T22:00:00+00:00", "2026-11-02T02:00:00+00:00"),
             ("2026-11-02T02:00:00+00:00", "2026-11-02T06:00:00+00:00")),
            (("2026-03-06T14:00:00+00:00", "2026-03-06T18:00:00+00:00"),
             ("2026-03-06T18:00:00+00:00", "2026-03-06T22:00:00+00:00"),
             ("2026-03-08T21:00:00+00:00", "2026-03-09T01:00:00+00:00")),
        ]:
            candles = [{"open_time": times[0], "close_time": times[1], "indicators": {"squeeze": {"momentum": value}}}
                       for times, value in zip((older_times, previous_times, current_times), (0.001, 0.0018, 0.0023))]
            factor = rule_set_definition(SESSION_RULE_SET_ID)["factors"][-1]
            result = _momentum_with_pace(factor, *candles, "P-1", "P0", "C1")
            self.assertEqual(result["bullish_points"], 0.5)
            candles[0]["close_time"] = candles[0]["open_time"]
            self.assertEqual(_momentum_with_pace(factor, *candles, "P-1", "P0", "C1")["outcome"], "unavailable")

    def test_partial_score_coverage_and_saved_definition_are_explicit(self):
        for candle, value in zip(self.snapshot["candles"][-3:], (0.001, 0.0018, 0.0023)):
            candle["indicators"]["squeeze"]["momentum"] = value
        self.snapshot["candles"][-1]["indicators"]["rsi14"] = 50
        result = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)
        summary = result["summary"]
        self.assertEqual((summary["bullish_points"], summary["bearish_points"], summary["net_score"]), (3.5, 0, 3.5))
        self.assertEqual((summary["evaluated_factors"], summary["neutral_factors"], summary["reduced_factors"]), (4, 1, 1))
        self.assertEqual(summary["bullish_alignment_percent"], 70)
        self.assertEqual(result["rule_set"]["factors"][-1]["slowdown"]["lookback_candles"], 3)
        self.assertEqual(result["rule_set"]["factors"][-1]["slowdown"]["reduced_points"], 0.5)

    def test_future_momentum_changes_do_not_change_previous_scores_or_inputs(self):
        before = copy.deepcopy(self.snapshot)
        result = evaluate_strategy(self.snapshot, SESSION_RULE_SET_ID)
        self.assertEqual(self.snapshot, before)
        self.snapshot["candles"][-1]["indicators"]["squeeze"]["momentum"] = -0.1
        after = evaluate_strategy(self.snapshot, SESSION_RULE_SET_ID)
        self.assertEqual(result["candles"][:-1], after["candles"][:-1])
        self.assertNotEqual(result["summary"], after["summary"])

    def test_prior_versions_keep_full_points_without_three_candle_history(self):
        self.first([0.001, 0.0018, 0.0023])
        self.snapshot.pop("previous_candles")
        for rule_id, maximum in [(LEGACY_RULE_SET_ID, 4), (WEIGHTED_RULE_SET_ID, 5)]:
            result = evaluate_strategy(self.snapshot, rule_id)
            factor = result["candles"][0]["factors"][-1]
            self.assertEqual(factor["bullish_points"], 1)
            self.assertNotIn("momentum_change", factor)
            self.assertEqual(result["summary"]["max_points"], maximum)

    def test_market_snapshot_retains_two_preceding_candles_outside_session(self):
        history = self.snapshot["previous_candles"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1], self.snapshot["previous_candle"])
        self.assertEqual(history[0]["close_time"], history[1]["open_time"])
        self.assertEqual(history[1]["close_time"], self.snapshot["session"]["start_utc"])
        self.assertEqual(len(self.snapshot["candles"]), 6)
        self.assertEqual(self.snapshot["schema_version"], 4)
        self.assertTrue(all(c not in self.snapshot["candles"] for c in history))


if __name__ == "__main__":
    unittest.main()
