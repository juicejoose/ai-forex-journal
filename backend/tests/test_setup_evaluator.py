"""Offline setup boundary, persistence and AI contract tests. Never use live keys/data."""
import copy
from contextlib import closing
from datetime import date, datetime, timedelta
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from urllib.error import URLError

from fastapi.testclient import TestClient
from openai import APIError
from pydantic import ValidationError
from tests.test_market_data import ENVIRONMENT, main
from tests.test_today import NOW, Clock, instant, view_at
from tests.test_custom_range import range_payload
from journal_grounding import InvalidJournalEvidence
import database as db
import market_data as md
import setup_market as sm
import setup_database as sd
import setup_ai as ai
from setup_models import SetupInput, SetupZone


def inputs(**overrides):
    return {"request_id": str(uuid4()), "direction": "long", "mode": "historical",
            "as_of": NOW.isoformat(), "include_quote": False, "title": "Support test",
            "zones": [{"label": "Support", "kind": "support", "lower": "1.12600", "upper": "1.12680"}],
            "observations": "A possible reaction at support.", **overrides}


def snapshot(**overrides):
    with patch.object(md, "_fetch_candles", return_value=range_payload()), patch.object(sm, "datetime", Clock):
        result = sm.build_setup_snapshot(SetupInput(**inputs(**overrides)))
    result["catalog"] = ai.build_catalog(result)
    return result


def valid_assessment(snap):
    facts = snap["catalog"]["facts"]
    support = [f["id"] for f in facts if f["role"] == "supports"][:3]
    conflicts = [f["id"] for f in facts if f["role"] == "conflicts"][:3]
    direction = snap["rule_evaluation"]["summary"]["direction"]
    verdict = ("insufficient_evidence" if direction == "insufficient_data" else
               "mixed" if support and conflicts else "supported" if support else
               "contradicted" if conflicts else "insufficient_evidence")
    return {"assessment": verdict,
        "explanation": "The proposed direction has support, but opposing momentum and unconfirmed price action call for caution.",
        "supporting_facts": support, "conflicting_facts": conflicts,
        "context_facts": [f["id"] for f in facts if any(key in f["evidence"] for key in ("zone", "reference", "trade_plan"))],
        "watch_conditions": [c["id"] for c in snap["catalog"]["conditions"] if c["kind"] == "watch"][:2],
        "invalidation_conditions": [c["id"] for c in snap["catalog"]["conditions"] if c["kind"] == "invalidation"][:1]}


def quote_at(stamp=NOW, **overrides):
    return {"prices": [{"instrument": "EUR_USD", "status": "tradeable", "time": stamp.isoformat(),
                       "bids": [{"price": "1.12690"}], "asks": [{"price": "1.12710"}], **overrides}]}


class SetupMarketTests(unittest.TestCase):
    def test_cutoff_retains_reproducible_inputs_and_preserves_strategy(self):
        snap = snapshot()
        self.assertEqual(len(snap["source_candles"]), 303)
        self.assertEqual(snap["rule_evaluation"], view_at()["rule_evaluation"])
        self.assertEqual(snap["rule_evaluation"]["rule_set"]["id"], "four_factor_v7")
        self.assertEqual(snap["rule_evaluation"]["rule_set"]["revision"], 1)
        self.assertTrue(all(datetime.fromisoformat(c["close_time"]) <= NOW for c in snap["source_candles"]))
        self.assertEqual(snap["observation_provenance"], "retrospective_user_input")
        self.assertEqual(len(snap["calculation_version"]), 64)
        self.assertNotIn("calculation_inputs", snap["market_data"])

    def test_future_candles_cannot_change_snapshot_evidence(self):
        original = snapshot()
        raw = range_payload()
        for candle in raw["candles"][-3:]:
            candle["mid"] = {key: "999" for key in "ohlc"}
        with patch.object(md, "_fetch_candles", return_value=raw), patch.object(sm, "datetime", Clock):
            changed = sm.build_setup_snapshot(SetupInput(**inputs()))
        for key in ("source_candles", "rule_evaluation", "zones", "reference_price"):
            self.assertEqual(original[key], changed[key], key)
        self.assertTrue(all(datetime.fromisoformat(c["close_time"]) <= NOW for c in changed["market_data"]["chart_context"]["candles"]))

    def test_first_close_rollover_weekend_and_dst(self):
        cases = [
            ("2026-10-22T18:00:00", True, "2026-10-22", 6),
            ("2026-10-22T21:00:00", False, "2026-10-23", 1),
            ("2026-10-24T12:00:00", False, "2026-10-23", 6),
            ("2026-10-25T18:00:00", True, "2026-10-23", 6),
            ("2026-11-01T18:00:00", True, "2026-10-30", 6),
            ("2026-11-01T21:00:00", False, "2026-11-02", 1),
        ]
        for stamp, prior, label, count in cases:
            cutoff = instant(stamp)
            with self.subTest(stamp=stamp), patch.object(md, "_fetch_candles", return_value=range_payload(date(2026, 11, 2))):
                snap = sm.build_setup_snapshot(SetupInput(**inputs(as_of=cutoff.isoformat())))
            self.assertEqual(snap["prior_session_context"], prior)
            self.assertEqual(snap["market_data"]["journal_date"], label)
            self.assertEqual(len(snap["market_data"]["candles"]), count)
            self.assertTrue(all(datetime.fromisoformat(c["close_time"]) <= cutoff for c in snap["source_candles"]))

    def test_rejects_future_cutoff_zone_time_and_ambiguous_time(self):
        with patch.object(sm, "datetime", Clock), patch.object(md, "_fetch_candles") as fetch:
            for values in ({"as_of": (NOW + timedelta(seconds=1)).isoformat()},
                           {"zones": [{"label": "Future", "kind": "support", "lower": "1.1", "upper": "1.2",
                                       "observed_at": (NOW + timedelta(seconds=1)).isoformat()}]}):
                with self.assertRaises(md.MarketDataError):
                    sm.build_setup_snapshot(SetupInput(**inputs(**values)))
            fetch.assert_not_called()
        for values in ({"as_of": "2026-10-23T06:00:00"}, {"include_quote": True},
                       {"mode": "live"}, {"as_of": None}):
            with self.assertRaises(ValidationError):
                SetupInput(**inputs(**values))

    def test_historical_never_requests_current_quote(self):
        with patch.object(sm, "fetch_quote") as fetch:
            snapshot()
        fetch.assert_not_called()

    def test_live_quote_is_separate_from_scores_and_falls_back_on_failure(self):
        with patch.object(sm, "fetch_quote", return_value=quote_at()):
            live = snapshot(mode="live", as_of=None, include_quote=True)
        self.assertEqual(live["quote"]["status"], "available")
        self.assertAlmostEqual(live["reference_price"]["value"], 1.127)
        self.assertEqual(live["rule_evaluation"], view_at()["rule_evaluation"])
        with patch.object(sm, "fetch_quote", side_effect=md.MarketDataError("Unavailable", 503)):
            failed = snapshot(mode="live", as_of=None, include_quote=True)
        self.assertEqual(failed["quote"]["status"], "unavailable")
        self.assertEqual(failed["reference_price"]["basis"], "last_completed_close")

    def test_quote_rejects_stale_future_closed_malformed_and_crossed_prices(self):
        cases = [quote_at(NOW - timedelta(seconds=121)), quote_at(NOW + timedelta(microseconds=1)),
                 quote_at(status="non-tradeable"), quote_at(time=None), quote_at(bids=[]),
                 quote_at(bids=[{"price": "NaN"}]), quote_at(asks=[{"price": "1.1"}]),
                 {"prices": []}, {}, None]
        for value in cases:
            self.assertEqual(sm.validated_quote(value, NOW)["status"], "unavailable", value)
        self.assertEqual(sm.validated_quote(quote_at(NOW - timedelta(seconds=120)), NOW)["status"], "available")

    def test_quote_endpoint_is_read_only_and_practice_only(self):
        with patch.dict(os.environ, ENVIRONMENT, clear=True), patch.object(sm, "urlopen", return_value=io.BytesIO(json.dumps(quote_at()).encode())) as fetch:
            self.assertEqual(sm.fetch_quote(), quote_at())
        request = fetch.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "https://api-fxpractice.oanda.com/v3/accounts/dummy-account/pricing?instruments=EUR_USD")
        with patch.dict(os.environ, {**ENVIRONMENT, "OANDA_API_URL": "https://evil.example"}, clear=True), patch.object(sm, "urlopen") as fetch:
            with self.assertRaises(md.MarketDataError): sm.fetch_quote()
            fetch.assert_not_called()
        with patch.dict(os.environ, ENVIRONMENT, clear=True), patch.object(sm, "urlopen", side_effect=URLError("failed")):
            with self.assertRaises(md.MarketDataError): sm.fetch_quote()

    def test_zone_boundaries_distance_and_overlap(self):
        zones = [SetupZone(label="Level", kind="support", lower="1.1", upper="1.2")]
        candle = {"close": 1.15, "low": 1.09, "high": 1.1}
        for value, position, distance in ((1.09, "below", 100), (1.1, "inside", 0),
                                          (1.2, "inside", 0), (1.201, "above", 10)):
            result = sm.zone_evidence(zones, {"value": value}, candle)[0]
            self.assertEqual(result["price_position"], position)
            self.assertAlmostEqual(result["distance_pips"], distance)
            self.assertTrue(result["last_candle_overlaps"])
            self.assertEqual(result["last_close_position"], "inside")

    def test_zone_validation(self):
        for lower, upper in (("-1", "1.2"), ("NaN", "1.2"), ("1.3", "1.2"), ("1.123456", "1.2")):
            with self.assertRaises(ValidationError):
                SetupZone(label="Zone", kind="support", lower=lower, upper=upper)
        zone = inputs()["zones"][0]
        with self.assertRaises(ValidationError): SetupInput(**inputs(zones=[zone, zone]))
        with self.assertRaises(ValidationError):
            SetupInput(**inputs(zones=[{**zone, "label": str(i)} for i in range(9)]))


class SetupAITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = snapshot()

    def test_valid_output_and_input_are_separate_from_raw_data(self):
        output = valid_assessment(self.snap)
        self.assertEqual(ai.parse_assessment(json.dumps(output), self.snap), output)
        payload = ai.ai_input(self.snap)
        self.assertNotIn("source_candles", payload)
        self.assertNotIn("market_data", payload)
        self.assertEqual(payload["strategy"]["id"], "four_factor_v7")
        self.assertEqual(payload["mode"], "historical")
        self.assertFalse(ai.response_format()["schema"]["additionalProperties"])

    def test_unknown_wrong_role_duplicate_and_missing_zone_references_fail(self):
        good = valid_assessment(self.snap)
        cases = [
            {"supporting_facts": ["F999"]}, {"supporting_facts": good["conflicting_facts"]},
            {"supporting_facts": good["supporting_facts"] * 2}, {"context_facts": []},
            {"watch_conditions": ["W999"]}, {"watch_conditions": good["invalidation_conditions"]},
            {"conflicting_facts": []}, {"strategy_score": 5}, {"assessment": "guaranteed"},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(InvalidJournalEvidence):
                ai.parse_assessment(json.dumps({**good, **changes}), self.snap)

    def test_invented_numbers_guarantees_confirmed_patterns_and_bad_json_fail(self):
        good = valid_assessment(self.snap)
        for explanation in ("Price hit 1.12345.", "The setup has a confirmed breakout.", "Buy now.",
                            "Profit is guaranteed.", "There are three bullish signals.", "Line one\nLine two"):
            with self.subTest(explanation=explanation), self.assertRaises(InvalidJournalEvidence):
                ai.parse_assessment(json.dumps({**good, "explanation": explanation}), self.snap)
        for raw in ("", "not json", "{}", " " * 17000, '{"assessment":"mixed","assessment":"supported"}'):
            with self.assertRaises(InvalidJournalEvidence): ai.parse_assessment(raw, self.snap)

    def test_insufficient_strategy_cannot_be_presented_as_supported(self):
        snap = copy.deepcopy(self.snap)
        snap["rule_evaluation"]["summary"]["direction"] = "insufficient_data"
        snap["catalog"] = ai.build_catalog(snap)
        output = valid_assessment(snap)
        self.assertEqual(ai.parse_assessment(json.dumps(output), snap)["assessment"], "insufficient_evidence")
        output["assessment"] = "supported"
        with self.assertRaises(InvalidJournalEvidence): ai.parse_assessment(json.dumps(output), snap)

    def test_no_zones_has_no_invented_conditions(self):
        snap = snapshot(zones=[])
        self.assertEqual(snap["catalog"]["conditions"], [])
        self.assertTrue(any("No support/resistance" in text for text in snap["catalog"]["limitations"]))


class SetupPersistenceAndAPITests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = root / "journal.db"
        self.enterContext(patch.object(db, "DB_PATH", self.path))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        db.init_db()
        sd.init_setup_db()
        self.client = self.enterContext(TestClient(main.app))
        self.snap = snapshot()
        self.builder = self.enterContext(patch("setup_api.build_setup_snapshot", return_value=self.snap))
        self.provider = self.enterContext(patch.object(main.client.responses, "create"))
        self.provider.return_value = SimpleNamespace(status="completed", output_text=json.dumps(valid_assessment(self.snap)),
                                                     model="test-model", id="test-response")

    def capture(self, body=None):
        response = self.client.post("/setup-snapshots", json=body or inputs())
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_capture_saved_before_ai_and_survives_restart(self):
        record = self.capture()
        self.provider.assert_not_called()
        sd.init_setup_db()
        fetched = self.client.get(f"/setup-snapshots/{record['id']}").json()
        self.assertEqual(fetched, record)
        self.assertEqual(len(list(self.path.parent.glob("*.before-setup-v1-*.db"))), 1)
        backup = next(self.path.parent.glob("*.before-setup-v1-*.db"))
        with closing(sqlite3.connect(backup)) as connection:
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='journals'").fetchone())
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='setup_snapshots'").fetchone())

    def test_duplicate_capture_same_request_returns_saved_without_fetching(self):
        body = inputs()
        first = self.capture(body)
        self.assertEqual(self.capture(body), first)
        self.builder.assert_called_once()
        self.assertEqual(self.client.post("/setup-snapshots", json={**body, "direction": "short"}).status_code, 409)
        self.assertEqual(self.client.get("/setup-snapshots").json()["total"], 1)

    def test_snapshot_database_guards_and_foreign_keys(self):
        record = self.capture()
        for statement in ("UPDATE setup_snapshots SET snapshot_json='{}'", "DELETE FROM setup_snapshots"):
            with self.assertRaises(sqlite3.IntegrityError), db.get_connection(write=True) as connection:
                connection.execute(statement)
        with self.assertRaises(sd.SetupNotFound):
            sd.begin_evaluation(uuid4(), uuid4(), "test", ai.PROMPT_VERSION)
        self.assertEqual(sd.fetch_snapshot(record["id"])["snapshot"], self.snap)

    def test_integrity_failure_refuses_ai(self):
        record = self.capture()
        with db.get_connection(write=True) as connection:
            connection.execute("DROP TRIGGER setup_snapshot_no_update")
            connection.execute("UPDATE setup_snapshots SET snapshot_hash='tampered'")
        response = self.client.post(f"/setup-snapshots/{record['id']}/evaluate", json={"request_id": str(uuid4())})
        self.assertEqual(response.status_code, 409)
        self.provider.assert_not_called()

    def test_ai_success_is_validated_stored_and_idempotent(self):
        record = self.capture()
        body = {"request_id": str(uuid4())}
        url = f"/setup-snapshots/{record['id']}/evaluate"
        first = self.client.post(url, json=body).json()
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["provider_model"], "test-model")
        self.assertEqual(first["prompt_version"], "setup_review_v4_trade_plan")
        self.assertEqual(self.client.post(url, json=body).json(), first)
        self.provider.assert_called_once()
        args = self.provider.call_args.kwargs
        self.assertFalse(args["store"])
        self.assertEqual(args["reasoning"], {"effort": "medium"})
        self.assertNotIn("source_candles", json.loads(args["input"]))
        self.assertEqual(self.client.get(f"/setup-snapshots/{record['id']}").json()["evaluations"], [first])
        for statement in ("UPDATE setup_evaluations SET error_message='changed'", "DELETE FROM setup_evaluations"):
            with self.assertRaises(sqlite3.IntegrityError), db.get_connection(write=True) as connection:
                connection.execute(statement)

    def test_failed_refused_or_incomplete_ai_keeps_snapshot_and_allows_new_attempt(self):
        record = self.capture()
        url = f"/setup-snapshots/{record['id']}/evaluate"
        for status, output in (("incomplete", ""), ("completed", ""), ("completed", '{"made_up": true}')):
            self.provider.return_value = SimpleNamespace(status=status, output_text=output)
            attempt = self.client.post(url, json={"request_id": str(uuid4())}).json()
            self.assertEqual(attempt["status"], "failed")
            self.assertIsNone(attempt["result"])
            self.assertIn("saved", attempt["error_message"])
        self.assertEqual(sd.fetch_snapshot(record["id"])["snapshot"], self.snap)
        self.assertEqual(len(sd.list_evaluations(record["id"])), 3)

    def test_pending_prevents_duplicate_ai_and_stale_attempt_can_recover(self):
        record = self.capture()
        attempt, _ = sd.begin_evaluation(record["id"], uuid4(), "test", ai.PROMPT_VERSION)
        url = f"/setup-snapshots/{record['id']}/evaluate"
        self.assertEqual(self.client.post(url, json={"request_id": str(uuid4())}).status_code, 409)
        self.provider.assert_not_called()
        with db.get_connection(write=True) as connection:
            connection.execute("UPDATE setup_evaluations SET created_at=? WHERE id=?",
                               ((datetime.now(md.UTC)-timedelta(minutes=6)).isoformat(), attempt["id"]))
        retried = self.client.post(url, json={"request_id": attempt["request_id"]}).json()
        self.assertEqual(retried["status"], "failed")
        self.provider.assert_not_called()
        self.assertEqual(self.client.post(url, json={"request_id": str(uuid4())}).json()["status"], "completed")
        self.assertEqual({x["status"] for x in sd.list_evaluations(record["id"])}, {"completed", "failed"})

    def test_provider_error_keeps_evidence_and_safe_message(self):
        record = self.capture()
        self.provider.side_effect = APIError("dummy private error", request=SimpleNamespace(), body=None)
        attempt = self.client.post(f"/setup-snapshots/{record['id']}/evaluate", json={"request_id": str(uuid4())}).json()
        self.assertEqual(attempt["status"], "failed")
        self.assertNotIn("dummy", attempt["error_message"])
        self.assertEqual(sd.fetch_snapshot(record["id"])["snapshot"], self.snap)

    def test_list_pagination_validation_and_missing_routes(self):
        self.capture()
        self.capture(inputs(title="Another"))
        page = self.client.get("/setup-snapshots?limit=1&offset=1").json()
        self.assertEqual((len(page["items"]), page["total"]), (1, 2))
        self.assertNotIn("snapshot", page["items"][0])
        self.assertEqual(self.client.get("/setup-snapshots?limit=101").status_code, 422)
        self.assertEqual(self.client.get(f"/setup-snapshots/{uuid4()}").status_code, 404)
        self.assertEqual(self.client.post("/setup-snapshots", json=inputs(as_of="invalid")).status_code, 422)
