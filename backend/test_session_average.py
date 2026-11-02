"""Full-session averages, incomplete data, and independent end-of-session context."""

import copy
import json
import unittest

from journal_grounding import InvalidJournalEvidence
from strategy_rules import (RULE_SET_ID, RULES_TEXT, MOMENTUM_RULE_SET_ID,
                            SUPPORTED_RULE_SET_IDS, evaluate_strategy, rule_set_definition)
from test_strategy_rules import scoring_snapshot
from test_scored_journal import ScoredJournalTestCase, ENTRY


def late_reversal(snapshot):
    for candle, momentum in zip(snapshot["candles"][-2:], [-0.001, -0.002]):
        candle["indicators"].update(ema20=1.3, sma190=1.35, rsi14=70)
        candle["indicators"]["squeeze"]["momentum"] = momentum


class SessionAverageTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = scoring_snapshot()

    def test_every_candle_contributes_equally_and_final_bias_is_separate(self):
        late_reversal(self.snapshot)
        result = evaluate_strategy(self.snapshot)
        self.assertEqual([(c["bullish_points"], c["bearish_points"]) for c in result["candles"]],
                         [(5, 0), (5, 0), (5, 0), (5, 0), (0, 4), (0, 5)])
        summary = result["summary"]
        self.assertEqual((summary["method"], summary["direction"], summary["max_points"]), ("session_average", "bullish", 5))
        self.assertEqual(summary["bullish_points"], 20 / 6)
        self.assertEqual(summary["bearish_points"], 9 / 6)
        self.assertEqual(summary["net_score"], 11 / 6)
        self.assertAlmostEqual(summary["bullish_alignment_percent"], 100 * 20 / 30)
        self.assertEqual(summary["bearish_alignment_percent"], 30)
        self.assertEqual((summary["evaluated_factors"], summary["expected_factors"], summary["complete_candles"]), (24, 24, 6))
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["candle_ids"], ["C1", "C2", "C3", "C4", "C5", "C6"])
        self.assertNotIn("candle_id", summary)
        self.assertEqual((result["session_end"]["candle_id"], result["session_end"]["direction"], result["session_end"]["bearish_points"]), ("C6", "bearish", 5))

    def test_single_early_change_updates_average_without_changing_session_end(self):
        before = evaluate_strategy(self.snapshot)
        self.snapshot["candles"][0]["indicators"]["rsi14"] = 60
        after = evaluate_strategy(self.snapshot)
        self.assertEqual(after["summary"]["bullish_points"], 29 / 6)
        self.assertEqual(after["summary"]["bearish_points"], 1 / 6)
        self.assertEqual(after["session_end"], before["session_end"])

    def test_half_points_and_reduced_counts_are_averaged_without_rounding(self):
        for candle, momentum in zip(self.snapshot["candles"][-3:], [0.001, 0.0018, 0.0023]):
            candle["indicators"]["squeeze"]["momentum"] = momentum
        self.snapshot["candles"][-1]["indicators"]["rsi14"] = 50
        result = evaluate_strategy(self.snapshot)
        self.assertEqual([c["bullish_points"] for c in result["candles"]], [5, 5, 5, 4, 5, 3.5])
        summary = result["summary"]
        self.assertEqual(summary["bullish_points"], 27.5 / 6)
        self.assertNotEqual(summary["bullish_points"], round(27.5 / 6, 2))
        self.assertAlmostEqual(summary["bullish_alignment_percent"], 100 * 27.5 / 30)
        self.assertEqual((summary["neutral_factors"], summary["reduced_factors"]), (2, 1))
        self.assertEqual(result["session_end"]["bullish_points"], 3.5)

    def test_missing_input_on_any_candle_withholds_all_session_numbers(self):
        base = copy.deepcopy(self.snapshot)
        for index in range(6):
            with self.subTest(candle=index + 1):
                snapshot = copy.deepcopy(base)
                snapshot["candles"][index]["indicators"]["rsi14"] = None
                result = evaluate_strategy(snapshot)
                summary = result["summary"]
                self.assertEqual((summary["direction"], summary["evaluated_factors"], summary["unavailable_factors"]), ("insufficient_data", 23, 1))
                self.assertEqual(summary["complete_candles"], 5)
                self.assertFalse(summary["complete"])
                for key in ("bullish_points", "bearish_points", "net_score", "bullish_alignment_percent", "bearish_alignment_percent"):
                    self.assertIsNone(summary[key])
                self.assertEqual(result["session_end"]["direction"], "insufficient_data" if index == 5 else "bullish")
                self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_missing_history_is_not_silently_dropped_from_denominator(self):
        self.snapshot.pop("previous_candle")
        result = evaluate_strategy(self.snapshot)
        self.assertEqual((result["summary"]["evaluated_factors"], result["summary"]["unavailable_factors"],
                          result["summary"]["complete_candles"]), (21, 3, 4))
        self.assertIsNone(result["summary"]["bullish_points"])
        self.assertEqual(result["session_end"]["direction"], "bullish")

    def test_all_neutral_and_equal_opposing_averages_are_distinct(self):
        for candle in [*self.snapshot["previous_candles"], *self.snapshot["candles"]]:
            candle["indicators"].update(ema20=1.25, sma190=1.25, rsi14=50)
            candle["indicators"]["squeeze"]["momentum"] = 0
        summary = evaluate_strategy(self.snapshot)["summary"]
        self.assertEqual((summary["direction"], summary["bullish_points"], summary["bearish_points"], summary["neutral_factors"]), ("neutral", 0, 0, 24))
        for i, candle in enumerate([*self.snapshot["previous_candles"], *self.snapshot["candles"]]):
            candle["indicators"].update(sma190=1.2, rsi14=60)
            candle["indicators"]["squeeze"]["momentum"] = -0.001 * (i + 1)
        summary = evaluate_strategy(self.snapshot)["summary"]
        self.assertEqual((summary["direction"], summary["bullish_points"], summary["bearish_points"], summary["net_score"]), ("mixed", 2, 2, 0))

    def test_older_versions_keep_final_candle_summary_and_v3_rows_are_identical(self):
        late_reversal(self.snapshot)
        current = evaluate_strategy(self.snapshot)
        for rule_id in SUPPORTED_RULE_SET_IDS[1:]:
            previous = evaluate_strategy(self.snapshot, rule_id)
            self.assertEqual(previous["rule_set"]["summary_method"], "final_candle")
            self.assertEqual((previous["summary"]["method"], previous["summary"]["candle_id"], previous["summary"]["direction"]), ("final_candle", "C6", "bearish"))
            self.assertNotIn("session_end", previous)
        old = evaluate_strategy(self.snapshot, MOMENTUM_RULE_SET_ID)
        self.assertEqual(current["candles"], old["candles"])
        self.assertEqual(current["session_end"], old["summary"])

    def test_default_definition_documents_session_method_and_is_not_shared(self):
        definition = rule_set_definition()
        self.assertEqual((definition["id"], definition["version"], definition["summary_method"]), (RULE_SET_ID, 4, "session_average"))
        self.assertEqual([f["points"] for f in definition["factors"]], [1, 2, 1, 1])
        self.assertIn("all six completed H4 candles", definition["rules"])
        self.assertIn("twenty-four factor checks", definition["rules"])
        definition["factors"][0]["points"] = 999
        self.assertEqual(rule_set_definition()["factors"][0]["points"], 1)

    def test_future_changes_leave_prior_candles_and_input_untouched(self):
        original = copy.deepcopy(self.snapshot)
        before = evaluate_strategy(self.snapshot)
        self.assertEqual(self.snapshot, original)
        self.snapshot["candles"][-1]["indicators"]["rsi14"] = 60
        after = evaluate_strategy(self.snapshot)
        self.assertEqual(before["candles"][:-1], after["candles"][:-1])
        self.assertNotEqual(before["summary"], after["summary"])

    def test_incomplete_candle_lists_cannot_be_averaged(self):
        for candles in (self.snapshot["candles"][:-1], self.snapshot["candles"] + [self.snapshot["candles"][-1]]):
            with self.assertRaises(InvalidJournalEvidence):
                evaluate_strategy({**self.snapshot, "candles": candles})


class SessionAverageJournalTests(ScoredJournalTestCase):
    entry = {**ENTRY, "rule_set_id": RULE_SET_ID, "strategy": RULES_TEXT}

    def test_average_and_final_bias_reach_ai_and_render_as_separate_results(self):
        late_reversal(self.snapshot)
        draft = self.generate()
        sent = json.loads(self.ai.call_args.kwargs["input"])
        self.assertEqual(sent["rule_evaluation"], draft["rule_evaluation"])
        self.assertEqual(sent["entry"]["strategy"], RULES_TEXT)
        self.assertEqual(sent["rule_evaluation"]["summary"]["bullish_points"], 20 / 6)
        self.assertIn("Session-average bias: Bullish (3.33 bull / 1.50 bear out of 5; equal candle weights)", draft["draft"])
        self.assertIn("Session-end bias: Bearish", draft["draft"])
        self.assertAlmostEqual(sent["rule_evaluation"]["summary"]["net_score"], 11 / 6)
        self.assertEqual(sent["summary_context"]["direction"], "bullish")
        self.assertEqual(sent["summary_context"]["session_end_direction"], "bearish")
        instructions = self.ai.call_args.kwargs["instructions"]
        self.assertIn("Follow summary.method", instructions)
        self.assertIn("Never substitute session_end", instructions)
        self.assertLessEqual(len(draft["draft"]), 20000)

    def test_incomplete_average_renders_and_persists_nulls_without_misleading_zeros(self):
        self.snapshot["candles"][0]["indicators"]["rsi14"] = None
        draft = self.generate()
        self.assertIn("Session-average bias: Incomplete", draft["draft"])
        self.assertIn("Session-end bias: Bullish", draft["draft"])
        self.assertEqual(draft["rule_evaluation"]["summary"]["evaluated_factors"], 23)
        self.assertNotIn("Average bullish: 0", draft["draft"])
        sent = json.loads(self.ai.call_args.kwargs["input"])
        self.assertIsNone(sent["rule_evaluation"]["summary"]["bullish_points"])
        saved = self.client.post("/journals", json={"generation_id": draft["generation_id"], "edited_draft": draft["draft"]})
        self.assertEqual(saved.status_code, 201, saved.text)
        reopened = self.client.get(f"/journals/{saved.json()['id']}").json()
        self.assertEqual(reopened["rule_evaluation"], draft["rule_evaluation"])

    def test_v3_profile_upgrade_and_pending_journals_preserve_both_methods(self):
        late_reversal(self.snapshot)
        profile = self.client.post("/strategy-profiles", json={"name": "Session rules", "rules": "Ignored", "rule_set_id": MOMENTUM_RULE_SET_ID}).json()
        old = self.generate({**self.entry, "rule_set_id": MOMENTUM_RULE_SET_ID})
        self.assertEqual(old["rule_evaluation"]["summary"]["method"], "final_candle")
        changed = self.client.patch(f"/strategy-profiles/{profile['id']}", json={"name": "Session rules", "rules": "Ignored", "rule_set_id": RULE_SET_ID})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["rules"], RULES_TEXT)
        current = self.generate()
        expected = copy.deepcopy(current["rule_evaluation"])
        current["rule_evaluation"]["summary"]["bullish_points"] = 999
        self.market.reset_mock()
        self.ai.reset_mock()
        for draft, evaluation in ((old, old["rule_evaluation"]), (current, expected)):
            saved = self.client.post("/journals", json={"generation_id": draft["generation_id"], "edited_draft": draft["draft"]})
            self.assertEqual(saved.status_code, 201, saved.text)
            journal = saved.json()
            self.assertEqual(journal["rule_evaluation"], evaluation)
            for response in [self.client.get(f"/journals/{journal['id']}"),
                             self.client.patch(f"/journals/{journal['id']}", json={"edited_draft": "My review"})]:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["rule_evaluation"], evaluation)
        self.market.assert_not_called()
        self.ai.assert_not_called()

    def test_catalog_and_preview_offer_v4_without_provider_calls(self):
        catalog = self.client.get("/strategy-rule-sets").json()
        self.assertEqual(catalog["default_id"], RULE_SET_ID)
        self.assertEqual([r["id"] for r in catalog["items"]], list(SUPPORTED_RULE_SET_IDS))
        preview = self.client.post("/journal/preview", json={**self.entry, "strategy": "Ignored"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["strategy"], RULES_TEXT)
        self.market.assert_not_called()
        self.ai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
