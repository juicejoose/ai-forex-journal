"""Offline regressions for descriptive zone history and immutable setup integration."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.test_setup_evaluator import inputs, snapshot, valid_assessment
from tests.test_market_data import main
from tests.test_today import NOW, Clock, instant, view_at
from tests.test_custom_range import range_payload
from setup_models import SetupInput
from zone_history import analyze_zone_history, history_summary
import database as db
import setup_database as sd
import setup_market as sm
import setup_ai as ai
import market_data as md


START = instant("2026-10-20T01:00:00")


def candle(index, low, high, close, start=START):
    opened = start + timedelta(hours=index*4)
    return {"open_time": opened.isoformat(), "close_time": (opened+timedelta(hours=4)).isoformat(),
            "open": close, "low": low, "high": high, "close": close, "price_updates": 1}


def history_rows():
    return [candle(i, *values) for i, values in enumerate([
        (1.098, 1.099, 1.0985), (1.099, 1.100, 1.0995), (1.100, 1.1015, 1.1005),
        (1.1012, 1.102, 1.1018), (1.1012, 1.103, 1.1025), (1.1012, 1.104, 1.1035),
        (1.099, 1.0995, 1.0993), (1.100, 1.102, 1.1006), (1.100, 1.101, 1.1008)])]


def zone(**changes):
    return {"id": "Z1", "lower": "1.10000", "upper": "1.10100", "origin_at": START.isoformat(), **changes}


def analyze(rows=None, selected_zone=None, cutoff=None):
    rows = rows if rows is not None else history_rows()
    cutoff = cutoff or datetime.fromisoformat(history_rows()[-1]["close_time"])
    return analyze_zone_history(selected_zone or zone(), rows, cutoff)


class ZoneHistoryCalculationTests(unittest.TestCase):
    def test_consecutive_overlaps_are_grouped_and_edges_count(self):
        result = analyze()
        self.assertEqual(result["status"], "covered")
        self.assertEqual((result["visit_count"], result["overlap_candles"]), (2, 4))
        self.assertEqual(result["close_counts"], {"above": 3, "inside": 3, "below": 3})
        first, last = result["visits"]
        self.assertEqual(first["overlap_candles"], 2)
        self.assertFalse(first["boundary_start"])
        self.assertEqual(first["first_candle"]["open_time"], history_rows()[1]["open_time"])
        self.assertEqual(last["end_status"], "overlapping_at_cutoff")
        self.assertIsNone(last["followup"]["close_change_pips"])
        self.assertEqual(last["followup"]["candle_count"], 0)

    def test_followup_uses_next_three_whole_candles_from_last_overlap_close(self):
        follow = analyze()["visits"][0]["followup"]
        self.assertEqual((follow["candle_count"], follow["stop_reason"]), (3, "complete"))
        self.assertAlmostEqual(follow["close_change_pips"], 30)
        self.assertAlmostEqual(follow["high_above_last_overlap_close_pips"], 35)
        self.assertEqual(follow["low_below_last_overlap_close_pips"], 0)
        self.assertEqual(follow["last_candle"]["open_time"], history_rows()[5]["open_time"])

    def test_followup_stops_at_new_visit(self):
        rows = history_rows()[:4] + [candle(4, 1.100, 1.101, 1.1005)]
        result = analyze(rows, cutoff=datetime.fromisoformat(rows[-1]["close_time"]))
        follow = result["visits"][0]["followup"]
        self.assertEqual((follow["candle_count"], follow["stop_reason"]), (1, "next_visit"))
        self.assertAlmostEqual(follow["close_change_pips"], 13)

    def test_cutoff_keeps_partial_followup_and_never_reads_future_prices(self):
        rows = history_rows()
        cutoff = datetime.fromisoformat(rows[3]["close_time"])
        before = analyze(rows, cutoff=cutoff)
        for row in rows[4:]:
            row["close"] = "not-a-price"
            row["high"] = 999
        self.assertEqual(analyze(rows, cutoff=cutoff), before)
        self.assertEqual(before["visits"][0]["followup"]["candle_count"], 1)
        self.assertEqual(before["visits"][0]["followup"]["stop_reason"], "cutoff")
        self.assertTrue(all(datetime.fromisoformat(e["close_time"]) <= cutoff for e in before["events"]))

    def test_origin_excludes_candle_that_began_before_it(self):
        origin = START + timedelta(hours=1)
        result = analyze(selected_zone=zone(origin_at=origin.isoformat()))
        self.assertEqual(result["coverage_start"], history_rows()[1]["open_time"])
        self.assertEqual(result["candle_count"], 8)
        self.assertTrue(result["visits"][0]["boundary_start"])
        self.assertEqual(result["gap_count"], 0)

    def test_older_origin_marks_partial_coverage_and_boundary_groups(self):
        rows = history_rows()[1:]
        result = analyze(rows, zone(origin_at=(START-timedelta(days=100)).isoformat()))
        self.assertTrue(result["origin_before_history"])
        self.assertEqual(result["status"], "partial_history")
        self.assertTrue(result["visits"][0]["boundary_start"])
        self.assertEqual(result["visit_count"], 2)

    def test_unknown_origin_empty_history_and_unfinished_origin_are_not_zero_visits(self):
        for result in (analyze(selected_zone=zone(origin_at=None)), analyze([]),
                       analyze(selected_zone=zone(origin_at=history_rows()[-1]["close_time"]))):
            self.assertIsNone(result["visit_count"])
            self.assertIsNone(result["close_counts"])
        result = analyze([candle(0, 1.09, 1.099, 1.095)], cutoff=START+timedelta(hours=4))
        self.assertEqual(result["visit_count"], 0)
        self.assertEqual(result["status"], "covered")

    def test_internal_gap_splits_groups_and_stops_followup(self):
        rows = history_rows()
        rows.pop(2)
        result = analyze(rows)
        self.assertEqual(result["status"], "partial_history")
        self.assertEqual(result["gap_count"], 1)
        self.assertEqual(result["visits"][0]["end_status"], "unknown_after_gap")
        self.assertEqual(result["visits"][0]["followup"]["stop_reason"], "data_gap")
        self.assertEqual(result["visits"][0]["followup"]["candle_count"], 0)

    def test_leading_and_trailing_missing_candles_are_flagged(self):
        rows = history_rows()
        origin = rows[1]["open_time"]
        leading = analyze([rows[0], *rows[2:]], zone(origin_at=origin))
        self.assertEqual(leading["gap_count"], 1)
        self.assertEqual(leading["status"], "partial_history")
        trailing = analyze(rows[:-1])
        self.assertEqual(trailing["gap_count"], 1)
        self.assertEqual(trailing["visits"][-1]["end_status"], "unknown_after_gap")

    def test_normal_weekend_and_dst_do_not_split_trading_candle_groups(self):
        for friday, sunday in (("2026-10-30T13:00:00", "2026-11-01T17:00:00"),
                               ("2026-03-06T13:00:00", "2026-03-08T17:00:00")):
            first, second = instant(friday), instant(sunday)
            rows = [candle(0, 1.1, 1.101, 1.1005, start=first), candle(0, 1.1, 1.101, 1.1005, start=second)]
            result = analyze(rows, zone(origin_at=first.isoformat()), second+timedelta(hours=4))
            self.assertEqual((result["visit_count"], result["gap_count"], result["status"]), (1, 0, "covered"))

    def test_single_price_zone_includes_equality_and_never_invents_an_overlap_on_gap_jump(self):
        rows = [candle(0, 1.09, 1.1, 1.1), candle(1, 1.11, 1.12, 1.115)]
        result = analyze(rows, zone(upper="1.10000"), START+timedelta(hours=8))
        self.assertEqual(result["overlap_candles"], 1)
        self.assertEqual(result["close_counts"], {"above": 1, "inside": 1, "below": 0})
        jumps = analyze([candle(0, 1.09, 1.095, 1.092), candle(1, 1.11, 1.12, 1.115)], cutoff=START+timedelta(hours=8))
        self.assertEqual(jumps["visit_count"], 0)
        self.assertEqual(len(jumps["events"]), 2)

    def test_future_origin_duplicate_or_bad_completed_prices_fail(self):
        with self.assertRaises(md.MarketDataError):
            analyze(selected_zone=zone(origin_at=(START+timedelta(days=3)).isoformat()))
        for rows in ([*history_rows(), history_rows()[0]], [{**history_rows()[0], "low": "NaN"}]):
            with self.assertRaises(md.MarketDataError): analyze(rows)

    def test_history_summary_is_bounded_without_losing_totals(self):
        rows = [candle(i, 1.1 if i%2 else 1.11, 1.101 if i%2 else 1.12, 1.1005 if i%2 else 1.115) for i in range(20)]
        result = analyze(rows, cutoff=datetime.fromisoformat(rows[-1]["close_time"]))
        summary = history_summary(result)
        self.assertEqual(len(summary["recent_visits"]), 3)
        self.assertEqual(len(summary["recent_close_changes"]), 3)
        self.assertEqual(summary["visit_count"], result["visit_count"])
        self.assertEqual(summary["omitted_visits"], 7)
        self.assertNotIn("events", summary)


class ZoneHistoryIntegrationTests(unittest.TestCase):
    def test_capture_uses_saved_history_without_changing_scores_or_indicators(self):
        zone_input = {**inputs()["zones"][0], "origin_at": "2026-09-21T21:00:00+00:00"}
        snap = snapshot(zones=[zone_input])
        self.assertEqual(snap["schema_version"], 4)
        self.assertEqual(snap["price_action_version"], "zone_history_v1")
        self.assertEqual(snap["rule_evaluation"], view_at()["rule_evaluation"])
        self.assertEqual(snap["market_data"]["candles"], view_at()["market_data"]["candles"])
        history = snap["zones"][0]["history"]
        self.assertEqual(history["status"], "covered")
        self.assertGreater(history["candle_count"], 60)
        self.assertLessEqual(datetime.fromisoformat(history["coverage_end"]), NOW)
        fact = next(f for f in snap["catalog"]["facts"] if "zone" in f["evidence"])
        self.assertIn("Observed H4 history", fact["text"])
        self.assertIn("recent_visits", fact["evidence"]["zone"]["history"])
        self.assertNotIn("events", fact["evidence"]["zone"]["history"])
        self.assertEqual(ai.parse_assessment(json.dumps(valid_assessment(snap)), snap)["assessment"], "mixed")

    def test_bad_origin_rejected_before_market_fetch(self):
        with patch.object(sm, "datetime", Clock), patch.object(md, "_fetch_candles") as fetch:
            with self.assertRaises(md.MarketDataError):
                sm.build_setup_snapshot(SetupInput(**inputs(zones=[{**inputs()["zones"][0],
                    "origin_at": (NOW+timedelta(seconds=1)).isoformat()}])))
            fetch.assert_not_called()

    def test_snapshot_and_ai_payload_do_not_change_when_future_data_is_added(self):
        zone_input = {**inputs()["zones"][0], "origin_at": "2026-10-01T01:00:00+00:00"}
        before = snapshot(zones=[zone_input])
        raw = range_payload()
        for row in raw["candles"][-3:]:
            row["mid"] = {key: "999" for key in "ohlc"}
        with patch.object(md, "_fetch_candles", return_value=raw), patch.object(sm, "datetime", Clock):
            after = sm.build_setup_snapshot(SetupInput(**inputs(zones=[zone_input])))
        after["catalog"] = ai.build_catalog(after)
        self.assertEqual(before["zones"], after["zones"])
        self.assertEqual(ai.ai_input(before), ai.ai_input(after))

    def test_legacy_capture_retry_and_reopening_never_recompute_history(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db, "DB_PATH", root/"journal.db"))
        db.init_db()
        sd.init_setup_db()
        entry = inputs()
        request = SetupInput(**entry).model_dump(mode="json", exclude={"request_id", "preview_id", "trade_plan"})
        for item in request["zones"]: item.pop("origin_at", None)
        old = snapshot()
        old["schema_version"] = 1
        old["price_action_version"] = "zone_geometry_v1"
        for item in old["zones"]:
            item.pop("history", None)
            item.pop("origin_at", None)
        old["catalog"] = {"facts": [], "conditions": [], "limitations": ["Legacy evidence"]}
        stored = sd.store_snapshot(entry["request_id"], request, old)
        with TestClient(main.app) as client, patch("setup_api.build_setup_snapshot") as build:
            response = client.post("/setup-snapshots", json=entry)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["snapshot"], old)
            self.assertEqual(client.get(f"/setup-snapshots/{stored['id']}").json()["snapshot"], old)
            build.assert_not_called()
