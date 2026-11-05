"""Summary format, grounding boundaries and compatibility without provider calls."""

import copy
import json

from journal_grounding import InvalidJournalEvidence
from scored_journal import build_summary_context, parse_commentary, render_scored_journal
from strategy_rules import RULE_SET_ID, evaluate_strategy
from tests.test_scored_journal import ENTRY, ScoredJournalTestCase, valid_scored_commentary
from tests.test_session_average import late_reversal
import database as db


class JournalSummaryTests(ScoredJournalTestCase):
    entry = {**ENTRY, "rule_set_id": RULE_SET_ID}

    def test_full_evidence_and_canonical_summary_reach_ai_but_report_stays_short(self):
        late_reversal(self.snapshot)
        self.snapshot["summary"].update(close=999, change_percent=999)
        draft = self.generate()
        sent = json.loads(self.ai.call_args.kwargs["input"])
        self.assertEqual(sent["market_data"], self.snapshot)
        self.assertEqual(sent["rule_evaluation"], draft["rule_evaluation"])
        self.assertEqual(len(sent["evidence_catalog"]), 6)
        self.assertEqual(sent["summary_context"]["market"]["close"], 1.25)
        self.assertAlmostEqual(sent["summary_context"]["market"]["change_percent"], 100 / 24)
        self.assertEqual(sent["summary_context"]["direction"], "bullish")
        self.assertEqual(sent["summary_context"]["session_end_direction"], "bearish")
        self.assertEqual([line for line in draft["draft"].splitlines() if line.startswith("## ")], [
            "## Session recap", "## Agreement and conflict", "## Directional consensus", "## Concerns"])
        for verbose_text in ("Candle-by-candle factors", "References:", "Rule definitions", "999"):
            self.assertNotIn(verbose_text, draft["draft"])
        self.assertIn("3.33 bull / 1.50 bear", draft["draft"])
        self.assertLess(len(draft["draft"].split()), 220)

    def test_wrong_market_or_consensus_metadata_rejected_without_staging(self):
        late_reversal(self.snapshot)
        context = build_summary_context(self.snapshot, evaluate_strategy(self.snapshot))
        correct = valid_scored_commentary(context)
        for section, key, wrong in (
            ("session_review", "price_direction", "down"),
            ("consensus", "direction", "bearish"),
            ("consensus", "session_end_direction", "bullish"),
            ("consensus", "method", "final_candle"),
        ):
            with self.subTest(section=section, key=key):
                value = copy.deepcopy(correct)
                value[section][key] = wrong
                self.ai.return_value.output_text = json.dumps(value)
                response = self.client.post("/journal/generate", json=self.entry)
                self.assertEqual(response.status_code, 502, response.text)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_drafts").fetchone()[0], 0)

    def test_incomplete_average_cannot_be_replaced_by_valid_final_candle(self):
        self.snapshot["candles"][0]["indicators"]["rsi14"] = None
        context = build_summary_context(self.snapshot, evaluate_strategy(self.snapshot))
        value = valid_scored_commentary(context)
        value["consensus"]["direction"] = "bullish"
        self.ai.return_value.output_text = json.dumps(value)
        self.assertEqual(self.client.post("/journal/generate", json=self.entry).status_code, 502)
        draft = self.generate()
        self.assertIn("Session-average bias: Incomplete", draft["draft"])
        self.assertNotIn("bull /", draft["draft"])
        self.assertIn("Session-end bias: Bullish", draft["draft"])

    def test_oversized_commentary_is_rejected_not_silently_truncated(self):
        value = valid_scored_commentary()
        for key in ("session_review", "conflicts", "consensus", "limitations"):
            value[key]["explanation"] = "Factors agree. " * 21
        with self.assertRaisesRegex(InvalidJournalEvidence, "word limit"):
            parse_commentary(json.dumps(value))

    def test_each_section_rejects_invented_numbers_and_duplicate_references(self):
        for key in ("session_review", "conflicts", "consensus", "limitations"):
            for bad in ("numbers", "duplicates"):
                value = valid_scored_commentary()
                if bad == "numbers":
                    value[key]["explanation"] = "The result has 90% confidence."
                else:
                    value[key]["results"] *= 2
                with self.subTest(section=key, invalid=bad), self.assertRaises(InvalidJournalEvidence):
                    parse_commentary(json.dumps(value))

    def test_actual_price_direction_stays_distinct_from_strategy_bias(self):
        for close, direction, text in ((1.1, "down", "closed lower: -8.33%"),
                                        (1.2, "unchanged", "closed unchanged: 0.00%")):
            snapshot = copy.deepcopy(self.snapshot)
            snapshot["candles"][-1]["close"] = close
            evaluation = evaluate_strategy(snapshot)
            context = build_summary_context(snapshot, evaluation)
            self.assertEqual(context["market"]["price_direction"], direction)
            self.assertEqual(context["direction"], "bullish")
            raw = json.dumps(valid_scored_commentary(context))
            draft = render_scored_journal(raw, snapshot, evaluation)
            self.assertIn(text, draft)
            self.assertIn("Session-average bias: Bullish", draft)

    def test_mixed_and_neutral_consensus_have_no_invented_direction(self):
        for mixed in (False, True):
            snapshot = copy.deepcopy(self.snapshot)
            for index, candle in enumerate([*snapshot["previous_candles"], *snapshot["candles"]]):
                candle["indicators"].update(ema20=1.25, sma190=1.2 if mixed else 1.25,
                                            rsi14=60 if mixed else 50)
                candle["indicators"]["squeeze"]["momentum"] = -0.001 * (index + 1) if mixed else 0
            evaluation = evaluate_strategy(snapshot)
            context = build_summary_context(snapshot, evaluation)
            expected = "mixed" if mixed else "neutral"
            self.assertEqual(context["direction"], expected)
            draft = render_scored_journal(json.dumps(valid_scored_commentary(context)), snapshot, evaluation)
            self.assertIn(f"Session-average bias: {expected.capitalize()}", draft)

    def test_saved_and_pending_old_long_journals_are_not_reformatted(self):
        evaluation = evaluate_strategy(self.snapshot)
        old_text = "1. Market summary\nOriginal report.\n\n3. Candle-by-candle factors\nC1 original evidence."
        old_id = db.store_generated_draft(self.entry, old_text, self.snapshot, evaluation)
        existing = db.save_generated_journal(old_id, old_text + "\nMy edit.")
        pending = db.store_generated_draft(self.entry, old_text, self.snapshot, evaluation)
        current = self.generate()
        saved = self.client.post("/journals", json={"generation_id": current["generation_id"], "edited_draft": current["draft"]}).json()
        self.market.reset_mock()
        self.ai.reset_mock()
        db.init_db()
        for journal in (existing, db.save_generated_journal(pending, old_text), saved):
            reopened = self.client.get(f"/journals/{journal['id']}").json()
            self.assertEqual(reopened["original_draft"], journal["original_draft"])
            self.assertEqual(reopened["edited_draft"], journal["edited_draft"])
            self.assertEqual(reopened["rule_evaluation"], evaluation)
        self.market.assert_not_called()
        self.ai.assert_not_called()
