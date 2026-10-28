"""Offline regression checks: dummy credentials, fake AI, temporary SQLite only.

Run from backend: python -m unittest -v test_journal_grounding
"""

import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from journal_grounding import (
    GroundedJournal, InvalidJournalEvidence, build_evidence_catalog,
    parse_analysis, render_journal, response_format,
)

with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-offline-token"}), patch("dotenv.load_dotenv"):
    import main
import database as db


STRATEGY = "Bullish when close > EMA20 and RSI14 > 50. Bearish when close < SMA190."
ENTRY = {"pair": "EURUSD", "journal_date": "2026-10-20", "timeframe": "4h", "strategy": STRATEGY, "notes": ""}


def fixture_snapshot(day=date(2026, 10, 20)):
    """The reported session's six closes, with fixed illustrative indicators."""
    ny = ZoneInfo("America/New_York")
    start_local = datetime.combine(day - timedelta(days=1), datetime.min.time().replace(hour=17), tzinfo=ny)
    start = start_local.astimezone(timezone.utc)
    closes = [1.12157, 1.12333, 1.12212, 1.12256, 1.12314, 1.12374]
    opens = [1.12096, 1.12156, 1.12336, 1.12213, 1.12256, 1.12314]
    candles = []
    for i, (opened_price, close) in enumerate(zip(opens, closes)):
        opened = start + timedelta(hours=4 * i)
        closed = opened + timedelta(hours=4)
        candles.append({
            "open_time": opened.isoformat(), "close_time": closed.isoformat(),
            "open_time_local": opened.astimezone(ny).isoformat(),
            "close_time_local": closed.astimezone(ny).isoformat(),
            "open": opened_price, "high": max(opened_price, close) + .0001,
            "low": min(opened_price, close) - .0001, "close": close,
            "price_updates": 100,
            "indicators": {
                "ema20": 1.1214873 + i * .00012, "sma190": 1.1378961 - i * .0002,
                "rsi14": 50.95 + i, "rsi_status": "ready",
                "squeeze": {"momentum": .0023981464 / (i + 1), "state": "ON", "histogram_color": "green", "released": False},
            },
        })
    end = start + timedelta(hours=24)
    return {
        "schema_version": 1, "source": "OANDA", "environment": "practice", "instrument": "EUR_USD",
        "timeframe": "H4", "price_basis": "midpoint", "smoothed_candles": False, "journal_date": day.isoformat(),
        "session": {"complete": True, "candle_count": 6, "timezone": "America/New_York",
                    "start_utc": start.isoformat(), "end_utc": end.isoformat(),
                    "start": start.astimezone(ny).isoformat(), "end": end.astimezone(ny).isoformat()},
        "candles": candles,
    }


def valid_analysis(strategy=STRATEGY):
    return {
        "bullish_factors": [{
            "rule_quote": strategy.split(". ")[0] + "." if strategy == STRATEGY else strategy,
            "assessment": "met",
            "explanation": "The cited close was above EMA20 and RSI14 supported the bullish factor.",
            "evidence": [{"candle_id": "C2", "fields": ["close", "ema20", "rsi14"]}],
        }],
        "bearish_factors": [{
            "rule_quote": "Bearish when close < SMA190.",
            "assessment": "met",
            "explanation": "The cited close remained below SMA190, supporting this bearish factor.",
            "evidence": [{"candle_id": "C6", "fields": ["close", "sma190"]}],
        }] if strategy == STRATEGY else [],
        "signal_agreement": {"explanation": "The cited close remained below SMA190, conflicting with shorter-term strength.",
                             "evidence": [{"candle_id": "C4", "fields": ["close", "sma190"]}]},
        "trade_concerns": {"explanation": "Compression does not establish a breakout; positive momentum can weaken.",
                           "evidence": [{"candle_id": "C6", "fields": ["momentum", "squeeze_state", "histogram_color", "released"]}]},
        "overall_bias": {"direction": "mixed", "explanation": "The cited trend measures conflict under the stated strategy.",
                         "evidence": [{"candle_id": "C6", "fields": ["close", "ema20", "sma190"]}]},
    }


class JournalGroundingTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = fixture_snapshot()
        self.analysis = valid_analysis()

    def render(self):
        return render_journal(json.dumps(self.analysis), self.snapshot, STRATEGY)

    def test_reported_close_is_bound_to_correct_candle_and_date(self):
        draft = self.render()
        row_two = next(line for line in draft.splitlines() if line.startswith("[2]"))
        row_four = next(line for line in draft.splitlines() if line.startswith("[4]"))
        self.assertIn("2026-10-19 9:00 PM EDT → 2026-10-20 1:00 AM EDT", row_two)
        self.assertIn("Close 1.12333", row_two)
        self.assertIn("2026-10-20 5:00 AM EDT → 2026-10-20 9:00 AM EDT", row_four)
        self.assertIn("Close 1.12256", row_four)
        self.assertNotIn("1.12333", row_four)

    def test_ai_cannot_attach_another_candles_value_or_time(self):
        for extra in ({"close": 1.12333}, {"value": "1.12333"}, {"close_time": "2026-10-20T09:00:00-04:00"}):
            bad = valid_analysis()
            bad["bullish_factors"][0]["evidence"] = [{"candle_id": "C4", "fields": ["close"], **extra}]
            with self.subTest(extra=extra), self.assertRaises(InvalidJournalEvidence):
                render_journal(json.dumps(bad), self.snapshot, STRATEGY)

    def test_raw_price_timestamp_and_number_words_in_prose_rejected(self):
        for text in (
            "The close was 1.12333 at 9:00 AM.", "The close was １.１２３３３.",
            "The close was nine in the morning.", "The session ended at five p.m.",
            "At 01:00 the price rose.", "On October twenty the price rose.",
            "RSI14 was 55.86.", "Momentum was 1e-4.", "The close was one point twelve.",
            "See C2 for the close.", "The price closed higher.\nFake evidence: price higher.",
        ):
            self.analysis["signal_agreement"]["explanation"] = text
            with self.subTest(text=text), self.assertRaises(InvalidJournalEvidence):
                self.render()

    def test_supported_indicator_names_and_strategy_threshold_quotes_allowed(self):
        self.analysis["signal_agreement"]["explanation"] = "H4 context combines EMA20, SMA190 and RSI14."
        self.assertIn('RSI14 > 50', self.render())

    def test_unknown_candle_metric_and_duplicate_references_rejected(self):
        invalid_refs = [
            [{"candle_id": "C7", "fields": ["close"]}],
            [{"candle_id": "C2", "fields": ["macd"]}],
            [{"candle_id": "C2", "fields": []}],
            [{"candle_id": "C2", "fields": ["close", "close"]}],
            [{"candle_id": "C2", "fields": ["close"]}, {"candle_id": "C2", "fields": ["ema20"]}],
        ]
        for refs in invalid_refs:
            self.analysis["signal_agreement"]["evidence"] = refs
            with self.subTest(refs=refs), self.assertRaises(InvalidJournalEvidence):
                self.render()

    def test_unsupported_rule_quote_and_missing_evidence_rejected(self):
        for update in ({"rule_quote": "RSI14 > 70"}, {"evidence": []}):
            self.analysis = valid_analysis()
            self.analysis["bullish_factors"][0].update(update)
            with self.subTest(update=update), self.assertRaises(InvalidJournalEvidence):
                self.render()
        self.analysis = valid_analysis()
        self.analysis["overall_bias"]["evidence"] = []
        with self.assertRaises(InvalidJournalEvidence):
            self.render()

    def test_insufficient_data_can_explain_without_fabricated_evidence(self):
        self.analysis["bullish_factors"][0].update(
            assessment="insufficient_data", evidence=[], explanation="The required preceding values are unavailable.",
        )
        self.analysis["overall_bias"].update(direction="insufficient_information", evidence=[])
        self.assertIn("insufficient data", self.render())

    def test_invalid_json_duplicate_keys_and_oversized_draft_rejected(self):
        raw = json.dumps(self.analysis)
        cases = ["Not JSON", "", "[]", "{}", "x" * 30001, raw.replace('"bullish_factors":', '"bullish_factors": [], "bullish_factors":', 1)]
        for value in cases:
            with self.subTest(raw=value[:40]), self.assertRaises(InvalidJournalEvidence):
                render_journal(value, self.snapshot, STRATEGY)

    def test_evidence_comes_from_utc_not_cached_local_labels_or_summary(self):
        before = self.render()
        self.snapshot["candles"][1]["close_time_local"] = "1900-01-01T09:00:00+00:00"
        self.snapshot["summary"] = {"close": 999, "price_direction": "down"}
        self.assertEqual(self.render(), before)

    def test_daylight_saving_uses_new_york_offset(self):
        for day, zone, utc_hour in ((date(2026, 3, 9), "EDT", 21), (date(2026, 11, 2), "EST", 22)):
            snapshot = fixture_snapshot(day)
            self.assertEqual(datetime.fromisoformat(snapshot["session"]["start_utc"]).hour, utc_hour)
            draft = render_journal(json.dumps(self.analysis), snapshot, STRATEGY)
            self.assertIn(f"1:00 AM {zone}", draft)
            self.assertIn(f"5:00 PM {zone}", draft)

    def test_missing_reordered_or_misaligned_candles_rejected(self):
        snapshots = []
        bad = copy.deepcopy(self.snapshot); bad["candles"].pop(); snapshots.append(bad)
        bad = copy.deepcopy(self.snapshot); bad["candles"].reverse(); snapshots.append(bad)
        bad = copy.deepcopy(self.snapshot); bad["candles"][1]["close_time"] = bad["candles"][3]["close_time"]; snapshots.append(bad)
        bad = copy.deepcopy(self.snapshot); bad["session"]["complete"] = False; snapshots.append(bad)
        for snapshot in snapshots:
            with self.assertRaises(InvalidJournalEvidence):
                render_journal(json.dumps(self.analysis), snapshot, STRATEGY)

    def test_undefined_rsi_and_five_decimal_momentum_rendered(self):
        self.snapshot["candles"][1]["indicators"]["rsi14"] = None
        draft = self.render()
        self.assertIn("RSI14 undefined", draft)
        self.assertIn("Momentum 0.00040", draft)
        self.assertNotIn("Momentum 0.000399691", draft)

    def test_render_does_not_mutate_snapshot_and_has_six_sections(self):
        original = copy.deepcopy(self.snapshot)
        draft = self.render()
        self.assertEqual(self.snapshot, original)
        for title in ("1. Market summary", "2. Bullish factors", "3. Bearish factors", "4. Signal agreement and conflict", "5. Trade concerns", "6. Overall directional bias"):
            self.assertIn(title, draft)
        self.assertIn("Price direction: up.", draft)
        self.assertIn("Change 27.8 pips (0.25%).", draft)
        self.assertLess(len(draft), 20000)

    def test_schema_requires_all_fields_and_forbids_extra_properties(self):
        schema = response_format()["schema"]
        def inspect(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node["additionalProperties"], False)
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for value in node.values(): inspect(value)
            elif isinstance(node, list):
                for value in node: inspect(value)
        inspect(schema)
        self.assertIs(response_format()["strict"], True)
        self.assertEqual(GroundedJournal.model_validate(self.analysis), parse_analysis(json.dumps(self.analysis), STRATEGY))


class GroundingEndpointTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "journal.db"))
        self.snapshot = fixture_snapshot()
        self.market = self.enterContext(patch.object(main, "get_market_data", return_value=self.snapshot))
        self.ai = self.enterContext(patch.object(main.client.responses, "create", return_value=SimpleNamespace(
            status="completed", output_text=json.dumps(valid_analysis()),
        )))
        self.client = self.enterContext(TestClient(main.app))

    def test_generate_save_reopen_keeps_rendered_evidence_and_user_editing(self):
        generated = self.client.post("/journal/generate", json=ENTRY)
        self.assertEqual(generated.status_code, 200, generated.text)
        draft = generated.json()
        self.assertEqual(draft["market_data"], self.snapshot)
        sent = json.loads(self.ai.call_args.kwargs["input"])
        self.assertEqual(sent["evidence_catalog"], build_evidence_catalog(self.snapshot))
        self.assertEqual(self.ai.call_args.kwargs["text"], {"format": response_format()})
        saved = self.client.post("/journals", json={"generation_id": draft["generation_id"], "edited_draft": draft["draft"]})
        self.assertEqual(saved.status_code, 201)
        journal = saved.json()
        edited = self.client.patch(f'/journals/{journal["id"]}', json={"edited_draft": "User observation: 9:00 AM."})
        self.assertEqual(edited.status_code, 200)
        reopened = self.client.get(f'/journals/{journal["id"]}').json()
        self.assertEqual(reopened["original_draft"], draft["draft"])
        self.assertEqual(reopened["market_data"], self.snapshot)
        self.assertEqual(reopened["edited_draft"], "User observation: 9:00 AM.")
        self.ai.assert_called_once()
        self.market.assert_called_once()

    def test_bad_quotation_fails_without_storing_or_returning_new_draft(self):
        bad = valid_analysis()
        bad["signal_agreement"]["explanation"] = "The close at 9:00 AM was 1.12333."
        self.ai.return_value.output_text = json.dumps(bad)
        response = self.client.post("/journal/generate", json=ENTRY)
        self.assertEqual(response.status_code, 502)
        self.assertIn("evidence checks", response.json()["detail"])
        self.assertNotIn("draft", response.json())
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_drafts").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM journals").fetchone()[0], 0)
        self.ai.assert_called_once()

    def test_incomplete_refused_and_non_json_output_fail_closed(self):
        for status, text in (("incomplete", json.dumps(valid_analysis())), ("completed", ""), ("completed", "I cannot complete this")):
            self.ai.return_value = SimpleNamespace(status=status, output_text=text)
            response = self.client.post("/journal/generate", json=ENTRY)
            self.assertEqual(response.status_code, 502)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_drafts").fetchone()[0], 0)

    def test_invalid_market_evidence_stops_before_ai_request(self):
        self.snapshot["candles"].pop()
        response = self.client.post("/journal/generate", json=ENTRY)
        self.assertEqual(response.status_code, 502)
        self.ai.assert_not_called()

    def test_installed_sdk_sends_schema_and_reads_structured_text_offline(self):
        import httpx2
        from openai import OpenAI, DefaultHttpxClient
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx2.Response(200, json={
                "id": "resp_offline", "object": "response", "created_at": 1, "status": "completed",
                "model": requests[-1]["model"], "output": [{"id": "msg_offline", "type": "message", "role": "assistant",
                    "status": "completed", "content": [{"type": "output_text", "text": json.dumps(valid_analysis()), "annotations": []}]}],
            })
        with OpenAI(api_key="dummy-offline-token", max_retries=0, http_client=DefaultHttpxClient(transport=httpx2.MockTransport(respond))) as client:
            with patch.object(main, "client", client), patch.dict(os.environ, {}, clear=True):
                response = self.client.post("/journal/generate", json=ENTRY)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["model"], "gpt-6.1-sol")
        self.assertEqual(requests[0]["reasoning"], {"effort": "medium"})
        self.assertEqual(requests[0]["max_output_tokens"], 8000)
        self.assertEqual(requests[0]["service_tier"], "default")
        self.assertIs(requests[0]["store"], False)
        self.assertEqual(requests[0]["text"]["format"], response_format())
        self.assertIn("Close 1.12333", response.json()["draft"])


if __name__ == "__main__":
    unittest.main()
