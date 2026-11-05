"""Offline custom range checks: complete sessions, shared rules and isolated saving."""

import copy
import io
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from tests.test_market_data import ENVIRONMENT, main
from tests.test_scored_journal import valid_scored_commentary
from scored_journal import build_summary_context, render_scored_journal
from journal_grounding import InvalidJournalEvidence
from strategy_rules import evaluate_strategy
import market_data as md
import date_range as dr
import database as db
import range_database as rd


class RangeClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 20, 12, tzinfo=timezone.utc).astimezone(tz)


def range_payload(end=date(2026, 10, 23)):
    rows = []
    for offset in range(160, -1, -1):
        label = end - timedelta(days=offset)
        if label.weekday() >= 5:
            continue
        start, _ = md.session_bounds(label)
        for i in range(6):
            opened = 1.12 + len(rows) * 0.00001
            closed = opened + (0.00008 if i % 3 else -0.00004)
            rows.append({"time": (start + i * md.CANDLE_DURATION).isoformat(), "complete": True,
                         "volume": 100 + i, "mid": {"o": str(opened), "h": str(max(opened, closed) + .0002),
                                                     "l": str(min(opened, closed) - .0002), "c": str(closed)}})
    return {"instrument": "EUR_USD", "granularity": "H4", "candles": rows}


def range_snapshot(start=date(2026, 10, 19), end=date(2026, 10, 23)):
    with patch.object(md, "_fetch_candles", return_value=range_payload(end)), patch.object(dr, "datetime", RangeClock):
        return dr.get_range_market_data(start, end)


class RangeMarketTests(unittest.TestCase):
    def test_inclusive_week_and_continuous_indicators(self):
        snapshot = range_snapshot()
        self.assertEqual(snapshot["session"]["start"], "2026-10-18T17:00:00-04:00")
        self.assertEqual(snapshot["session"]["end"], "2026-10-23T17:00:00-04:00")
        self.assertEqual((snapshot["range"]["trading_day_count"], len(snapshot["candles"])), (5, 30))
        self.assertEqual(snapshot["warmup"]["candle_count"], 300)
        self.assertEqual(len(dr.build_range_evidence_catalog(snapshot)), 30)
        self.assertNotIn("journal_date", snapshot)
        # Extending the end date never changes earlier indicator values.
        # Use exactly the same price history: the synthetic fixture depends on its end date.
        with patch.object(md, "_fetch_candles", return_value=range_payload()), patch.object(dr, "datetime", RangeClock):
            short = dr.get_range_market_data(date(2026, 10, 19), date(2026, 10, 20))
        self.assertEqual(short["candles"], snapshot["candles"][:12])
        self.assertAlmostEqual(snapshot["summary"]["change_percent"],
                               (snapshot["candles"][-1]["close"] / snapshot["candles"][0]["open"] - 1) * 100)

    def test_weekends_skipped_including_endpoints(self):
        snapshot = range_snapshot(date(2026, 10, 17), date(2026, 10, 25))
        self.assertEqual(snapshot["range"]["trading_dates"], [f"2026-10-{i}" for i in range(19, 24)])
        self.assertEqual(snapshot["range"]["calendar_day_count"], 9)
        self.assertEqual(snapshot["session"]["end"], "2026-10-23T17:00:00-04:00")

    def test_dst_weekend_is_not_missing_data(self):
        for start, end, gap in ((date(2026, 3, 6), date(2026, 3, 9), 47),
                                (date(2026, 10, 30), date(2026, 11, 2), 49)):
            snapshot = range_snapshot(start, end)
            self.assertEqual(len(snapshot["candles"]), 12)
            actual_gap = datetime.fromisoformat(snapshot["candles"][6]["open_time"]) - datetime.fromisoformat(snapshot["candles"][5]["close_time"])
            self.assertEqual(actual_gap, timedelta(hours=gap))
            self.assertEqual(len(dr.build_range_evidence_catalog(snapshot)), 12)
            results = dr.evaluate_range_strategy(snapshot)
            self.assertNotEqual(results["candles"][6]["factors"][0]["outcome"], "unavailable")

    def test_single_day_matches_daily_market_and_scores(self):
        with patch.object(md, "_fetch_candles", return_value=range_payload()), patch.object(md, "datetime", RangeClock):
            daily = md.get_market_data(date(2026, 10, 23))
        custom = range_snapshot(date(2026, 10, 23), date(2026, 10, 23))
        self.assertEqual(daily["candles"], custom["candles"])
        self.assertEqual(evaluate_strategy(daily)["candles"], dr.evaluate_range_strategy(custom)["candles"])

    def test_invalid_unfinished_and_oversized_dates_do_not_fetch(self):
        with patch.object(md, "_fetch_candles") as fetch, patch.object(dr, "datetime", RangeClock):
            for start, end in ((date(2026, 10, 23), date(2026, 10, 19)), (date.min, date.min),
                               (date(2026, 10, 1), date(2026, 11, 1)),
                               (date(2026, 10, 17), date(2026, 10, 18)),
                               (date(2026, 11, 19), date(2026, 11, 20))):
                with self.subTest(start=start, end=end), self.assertRaises(md.MarketDataError) as error:
                    dr.get_range_market_data(start, end)
                self.assertEqual(error.exception.status_code, 422)
            fetch.assert_not_called()

    def test_maximum_range_uses_one_bounded_provider_request(self):
        body = io.BytesIO(json.dumps(range_payload(date(2026, 10, 31))).encode())
        with patch.dict(os.environ, ENVIRONMENT), patch.object(md, "urlopen", return_value=body) as request:
            snapshot = dr.get_range_market_data(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(len(snapshot["candles"]), 132)
        request.assert_called_once()
        params = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
        self.assertEqual(params["count"], ["482"])
        self.assertEqual(params["granularity"], ["H4"])
        self.assertEqual(params["alignmentTimezone"], ["America/New_York"])
        self.assertEqual(params["dailyAlignment"], ["17"])
        self.assertEqual(params["to"], ["2026-10-30T21:00:00+00:00"])

    def test_missing_partial_or_duplicate_candles_are_not_skipped(self):
        base = range_payload()
        for kind in ("missing", "incomplete", "duplicate"):
            data = copy.deepcopy(base)
            if kind == "missing":
                data["candles"].pop(-10)
            elif kind == "incomplete":
                data["candles"][-10]["complete"] = False
            else:
                data["candles"].append(copy.deepcopy(data["candles"][-10]))
            with self.subTest(kind=kind), patch.object(md, "_fetch_candles", return_value=data), self.assertRaises(md.MarketDataError):
                dr.get_range_market_data(date(2026, 10, 19), date(2026, 10, 23))

    def test_short_warmup_and_extra_weekend_candle_fail(self):
        for kind in ("warmup", "weekend"):
            data = range_payload()
            if kind == "warmup":
                data["candles"] = data["candles"][-329:]
            else:
                extra = copy.deepcopy(data["candles"][-1])
                extra["time"] = "2026-10-17T21:00:00+00:00"
                data["candles"].append(extra)
            with patch.object(md, "_fetch_candles", return_value=data), self.assertRaises(md.MarketDataError):
                dr.get_range_market_data(date(2026, 10, 16) if kind == "weekend" else date(2026, 10, 19), date(2026, 10, 23))

    def test_future_prices_never_influence_requested_range(self):
        base = range_payload()
        with patch.object(md, "_fetch_candles", return_value=base):
            before = dr.get_range_market_data(date(2026, 10, 19), date(2026, 10, 23))
        extra = copy.deepcopy(base["candles"][-1]); extra["time"] = "2026-10-23T21:00:00+00:00"; extra["mid"] = {k: "999" for k in "ohlc"}
        base["candles"].append(extra)
        with patch.object(md, "_fetch_candles", return_value=base):
            after = dr.get_range_market_data(date(2026, 10, 19), date(2026, 10, 23))
        self.assertEqual(before["candles"], after["candles"])


class RangeScoringTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = range_snapshot(date(2026, 10, 16), date(2026, 10, 19))
        for i, candle in enumerate([*self.snapshot["previous_candles"], *self.snapshot["candles"]]):
            candle["indicators"].update(ema20=1, sma190=.9, rsi14=30, rsi14_sma14=30)
            candle["indicators"]["squeeze"]["momentum"] = .001 * (i + 1)
        self.snapshot["previous_candle"] = self.snapshot["previous_candles"][-1]

    def test_whole_range_average_and_end_bias_are_distinct(self):
        for i, candle in enumerate(self.snapshot["candles"][-6:]):
            candle["indicators"].update(ema20=1.3, sma190=1.4, rsi14=70, rsi14_sma14=70)
            candle["indicators"]["squeeze"]["momentum"] = -.001 * (i + 1)
        original = copy.deepcopy(self.snapshot)
        result = dr.evaluate_range_strategy(self.snapshot)
        self.assertEqual(self.snapshot, original)
        self.assertEqual(result["summary"]["method"], "range_average")
        self.assertEqual(result["summary"]["bullish_points"], 30 / 12)
        self.assertEqual(result["summary"]["bearish_points"], 29 / 12)
        self.assertEqual(result["summary"]["direction"], "bullish")
        self.assertEqual((result["session_end"]["candle_id"], result["session_end"]["direction"]), ("C12", "bearish"))
        self.assertEqual(result["summary"]["expected_factors"], 48)
        self.assertEqual(result["summary"]["bullish_points"], sum(s["bullish_points"] for s in result["daily_summaries"]) / 2)

    def test_cross_day_and_weekend_references_use_global_ids(self):
        result = dr.evaluate_range_strategy(self.snapshot)
        momentum = result["candles"][6]["factors"][-1]
        self.assertEqual([e["candle_id"] for e in momentum["evidence"]], ["C5", "C6", "C7"])
        self.assertEqual(result["daily_summaries"][1]["candle_ids"], [f"C{i}" for i in range(7, 13)])
        catalog = dr.build_range_evidence_catalog(self.snapshot)
        self.assertEqual(catalog["C7"]["open_time_local"], "2026-10-18T17:00:00-04:00")

    def test_slowdown_across_weekend_keeps_half_points(self):
        for candle, momentum in zip(self.snapshot["candles"][4:7], [.001, .0018, .0023]):
            candle["indicators"]["squeeze"]["momentum"] = momentum
        result = dr.evaluate_range_strategy(self.snapshot)
        momentum = result["candles"][6]["factors"][-1]
        self.assertEqual((momentum["momentum_change"]["pace"], momentum["bullish_points"]), ("slowing", .5))
        self.assertEqual(result["summary"]["bullish_points"], sum(c["bullish_points"] for c in result["candles"]) / 12)

    def test_missing_indicator_anywhere_withholds_overall_average(self):
        self.snapshot["candles"][2]["indicators"]["rsi14"] = None
        self.snapshot["candles"][2]["indicators"]["rsi14_sma14"] = None
        result = dr.evaluate_range_strategy(self.snapshot)
        self.assertEqual(result["summary"]["evaluated_factors"], 47)
        self.assertEqual(result["summary"]["direction"], "insufficient_data")
        self.assertIsNone(result["summary"]["bullish_points"])
        self.assertIsNone(result["summary"]["bearish_alignment_percent"])
        self.assertEqual(result["session_end"]["direction"], "bullish")

    def test_candle_ids_above_six_render_and_unknown_ids_fail(self):
        evaluation = dr.evaluate_range_strategy(self.snapshot)
        value = valid_scored_commentary(build_summary_context(self.snapshot, evaluation))
        value["consensus"]["results"] = [{"candle_id": "C12", "factor_id": "ema_sma"}]
        text = render_scored_journal(json.dumps(value), self.snapshot, evaluation)
        self.assertIn("## Range recap", text)
        self.assertIn("Range-average bias: Bullish", text)
        self.assertIn("Range-end bias: Bullish", text)
        self.assertNotIn("Session-average", text)
        value["consensus"]["results"][0]["candle_id"] = "C13"
        with self.assertRaises(InvalidJournalEvidence):
            render_scored_journal(json.dumps(value), self.snapshot, evaluation)

    def test_tampered_coverage_and_session_gaps_fail(self):
        variants = []
        for key, value in (("trading_day_count", 1), ("calendar_day_count", 1), ("start_date", "2026-10-15")):
            item = copy.deepcopy(self.snapshot); item["range"][key] = value; variants.append(item)
        item = copy.deepcopy(self.snapshot); item["candles"].pop(); variants.append(item)
        item = copy.deepcopy(self.snapshot); item["candles"][6], item["candles"][7] = item["candles"][7], item["candles"][6]; variants.append(item)
        for item in variants:
            with self.assertRaises(InvalidJournalEvidence):
                dr.evaluate_range_strategy(item)


class RangeJournalTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "journal.db"))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        self.snapshot = range_snapshot()
        self.market = self.enterContext(patch.object(main, "get_range_market_data", return_value=self.snapshot))
        self.evaluation = dr.evaluate_range_strategy(self.snapshot)
        value = valid_scored_commentary(build_summary_context(self.snapshot, self.evaluation))
        value["consensus"]["results"] = [{"candle_id": "C30", "factor_id": "ema_sma"}]
        self.ai = self.enterContext(patch.object(main.client.responses, "create", return_value=SimpleNamespace(status="completed", output_text=json.dumps(value))))
        self.client = self.enterContext(TestClient(main.app))
        self.entry = {"start_date": "2026-10-19", "end_date": "2026-10-23", "notes": "Review this period."}

    def generate(self):
        response = self.client.post("/range-journal/generate", json=self.entry)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_full_range_input_and_fixed_scoring_reach_ai(self):
        draft = self.generate()
        sent = json.loads(self.ai.call_args.kwargs["input"])
        self.assertEqual(len(sent["market_data"]["candles"]), 30)
        self.assertEqual(len(sent["evidence_catalog"]), 30)
        self.assertEqual(sent["rule_evaluation"], draft["rule_evaluation"])
        self.assertEqual(sent["summary_context"]["method"], "range_average")
        self.assertEqual(draft["entry"]["strategy"], dr.range_rule_definition()["rules"])
        self.assertIn("range_average", self.ai.call_args.kwargs["instructions"])

    def test_invalid_inputs_and_wrong_rule_versions_rejected(self):
        for entry in ({**self.entry, "timeframe": "1h"}, {**self.entry, "pair": "GBPUSD"},
                      {**self.entry, "rule_set_id": "four_factor_v3"}, {**self.entry, "strategy": "Fake rules"},
                      {**self.entry, "rule_evaluation": {}}, {**self.entry, "end_date": "bad"}):
            self.assertEqual(self.client.post("/range-journal/generate", json=entry).status_code, 422)
        self.market.assert_not_called(); self.ai.assert_not_called()

    def test_provider_or_evidence_errors_never_call_ai_or_stage(self):
        self.market.side_effect = md.MarketDataError("Missing candles", 422)
        self.assertEqual(self.client.post("/range-journal/generate", json=self.entry).status_code, 422)
        self.market.side_effect = None
        self.snapshot["candles"].pop()
        self.assertEqual(self.client.post("/range-journal/generate", json=self.entry).status_code, 502)
        self.ai.assert_not_called()
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM range_generated_drafts").fetchone()[0], 0)

    def test_ai_wrong_method_unknown_reference_and_incomplete_response_not_saved(self):
        original = json.loads(self.ai.return_value.output_text)
        for kind in ("method", "reference", "status"):
            value = copy.deepcopy(original)
            if kind == "method": value["consensus"]["method"] = "session_average"
            if kind == "reference": value["consensus"]["results"][0]["candle_id"] = "C31"
            self.ai.return_value.output_text = json.dumps(value)
            self.ai.return_value.status = "incomplete" if kind == "status" else "completed"
            self.assertEqual(self.client.post("/range-journal/generate", json=self.entry).status_code, 502)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM range_generated_drafts").fetchone()[0], 0)

    def test_save_reopen_edit_idempotency_and_immutable_evidence(self):
        draft = self.generate()
        request = {"generation_id": draft["generation_id"], "edited_draft": draft["draft"]}
        response = self.client.post("/range-journals", json=request)
        self.assertEqual(response.status_code, 201, response.text)
        journal = response.json()
        self.assertEqual(self.client.post("/range-journals", json=request).json()["id"], journal["id"])
        self.assertEqual(self.client.post("/range-journals", json={**request, "edited_draft": "changed"}).status_code, 409)
        self.market.reset_mock(); self.ai.reset_mock()
        rd.init_range_db()
        for response in (self.client.get(f"/range-journals/{journal['id']}"),
                         self.client.patch(f"/range-journals/{journal['id']}", json={"edited_draft": "My review"})):
            self.assertEqual(response.status_code, 200)
            saved = response.json()
            self.assertEqual(saved["market_data"], self.snapshot)
            self.assertEqual(saved["rule_evaluation"], self.evaluation)
            self.assertEqual(saved["original_draft"], draft["draft"])
            self.assertEqual((saved["start_date"], saved["end_date"]), ("2026-10-19", "2026-10-23"))
        self.market.assert_not_called(); self.ai.assert_not_called()
        self.assertEqual(self.client.patch(f"/range-journals/{journal['id']}", json={"edited_draft": "x", "start_date": "2026-10-01"}).status_code, 422)
        self.assertEqual(self.client.patch(f"/range-journals/{journal['id']}", json={"edited_draft": "x", "rule_evaluation": {}}).status_code, 422)

    def test_daily_and_range_ids_saves_lists_and_deletions_are_isolated(self):
        daily_entry = {"pair": "EURUSD", "timeframe": "4h", "journal_date": "2026-10-20", "strategy": "Old rules", "notes": ""}
        daily_id = db.store_generated_draft(daily_entry, "Daily text", None)
        custom = self.generate()
        self.assertEqual(self.client.post("/journals", json={"generation_id": custom["generation_id"], "edited_draft": "x"}).status_code, 404)
        self.assertEqual(self.client.post("/range-journals", json={"generation_id": daily_id, "edited_draft": "x"}).status_code, 404)
        daily = db.save_generated_journal(daily_id, "Daily text")
        saved = rd.save_range_journal(custom["generation_id"], custom["draft"])
        self.assertEqual(daily["id"], saved["id"])
        self.assertEqual(self.client.get("/journals").json()["total"], 1)
        self.assertEqual(self.client.get("/journals/calendar?month=2026-10").json()["journal_count"], 1)
        self.assertEqual(self.client.get("/range-journals").json()["total"], 1)
        self.assertEqual(self.client.delete(f"/range-journals/{saved['id']}").status_code, 204)
        self.assertEqual(self.client.delete(f"/range-journals/{saved['id']}").status_code, 404)
        self.assertEqual(self.client.get("/range-journals").json()["total"], 0)
        self.assertEqual(self.client.get(f"/journals/{daily['id']}").json()["edited_draft"], "Daily text")
        for response in (self.client.get(f"/range-journals/{saved['id']}"), self.client.patch(f"/range-journals/{saved['id']}", json={"edited_draft": "x"})):
            self.assertEqual(response.status_code, 404)

    def test_list_pagination_and_options_need_no_providers(self):
        for _ in range(21):
            pending = rd.store_range_draft({**self.entry, "pair": "EURUSD", "timeframe": "4h"}, "Draft", self.snapshot, self.evaluation)
            rd.save_range_journal(pending, "Saved")
        first = self.client.get("/range-journals").json()
        second = self.client.get("/range-journals?limit=20&offset=20").json()
        self.assertEqual((first["total"], len(first["items"]), len(second["items"])), (21, 20, 1))
        self.assertGreater(first["items"][0]["id"], second["items"][0]["id"])
        self.assertNotIn("market_data", first["items"][0])
        self.assertIsInstance(first["items"][0]["change_percent"], float)
        options = self.client.get("/range-journal/options").json()
        self.assertEqual((options["max_calendar_days"], options["rule_set"]["summary_method"]), (31, "range_average"))
        for query in ("limit=0", "limit=101", "offset=-1"):
            self.assertEqual(self.client.get(f"/range-journals?{query}").status_code, 422)
        self.market.assert_not_called(); self.ai.assert_not_called()

    def test_range_tables_survive_restart_and_leave_old_daily_records_intact(self):
        daily_entry = {"pair": "EURUSD", "timeframe": "4h", "journal_date": "2026-10-20", "strategy": "Old", "notes": ""}
        pending = db.store_generated_draft(daily_entry, "Pending", None)
        profile = db.insert_strategy_profile("Existing", "Old")
        db.init_db(); rd.init_range_db(); rd.init_range_db()
        self.assertEqual(db.fetch_strategy_profile(profile["id"]), profile)
        self.assertEqual(db.save_generated_journal(pending, "Pending")["original_draft"], "Pending")
