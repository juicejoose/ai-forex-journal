"""Calendar and date filtering use saved snapshots and temporary databases only."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.test_market_data import ENVIRONMENT
import database as db
import main


def saved_score(net, *, method="session_average", complete=True, revision=2):
    return {"schema_version": 1, "rule_set": {"id": "four_factor_v4", "version": 4, "revision": revision},
            "summary": {"method": method, "complete": complete, "candle_count": 6,
                        "net_score": net, "max_points": 5}}


class JournalCalendarTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "journal.db"))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        self.market = self.enterContext(patch.object(main, "get_market_data", side_effect=AssertionError("No live market requests")))
        self.ai = self.enterContext(patch.object(main.client.responses, "create", side_effect=AssertionError("No AI requests")))
        self.client = self.enterContext(TestClient(main.app))

    def tearDown(self):
        self.market.assert_not_called()
        self.ai.assert_not_called()

    def save(self, day="2026-10-20", opened=100, closed=101, snapshot="default", pair="EURUSD", timeframe="4h", evaluation=None):
        entry = {"pair": pair, "journal_date": day, "timeframe": timeframe,
                 "strategy": "Private strategy", "notes": "Private notes"}
        if snapshot == "default":
            snapshot = {"instrument": "EUR_USD", "timeframe": "H4", "journal_date": day,
                        "session": {"complete": True}, "summary": {"open": opened, "close": closed, "change_percent": 999}}
        generation = db.store_generated_draft(entry, "Private original draft", snapshot, evaluation)
        return db.save_generated_journal(generation, "Private saved edits")

    def calendar(self, month="2026-10"):
        response = self.client.get("/journals/calendar", params={"month": month})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_calendar_groups_by_session_date_and_counts_every_entry(self):
        first = self.save()
        latest = self.save()
        self.save("2026-10-21", closed=99)
        self.save("2026-09-30")
        # Saving later must not move a journal to a different calendar date.
        with db.get_connection(write=True) as connection:
            connection.execute("UPDATE journals SET created_at = '2027-01-01T00:00:00Z' WHERE id = ?", (latest["id"],))
        data = self.calendar()
        self.assertEqual(data["journal_count"], 3)
        self.assertEqual(data["total_journals"], 4)
        self.assertEqual(data["latest_journal_date"], "2026-10-21")
        self.assertEqual(data["days"], [
            {"date": "2026-10-20", "journal_count": 2, "change_percent": 1.0, "average_net_score": None, "source_journal_id": latest["id"]},
            {"date": "2026-10-21", "journal_count": 1, "change_percent": -1.0, "average_net_score": None, "source_journal_id": latest["id"] + 1},
        ])
        # The repeated session is 1%, not 2%; cached summary percentages and AI prose are not used.
        self.assertEqual(db.fetch_journal(first["id"]), first)

    def test_latest_usable_snapshot_wins_and_zero_is_preserved(self):
        self.save(closed=102)
        zero = self.save(closed=100)
        self.save(snapshot=None)
        day = self.calendar()["days"][0]
        self.assertEqual(day["change_percent"], 0)
        self.assertEqual(day["source_journal_id"], zero["id"])
        self.assertEqual(day["journal_count"], 3)

    def test_missing_invalid_or_unrelated_snapshots_have_no_color(self):
        valid = {"instrument": "EUR_USD", "timeframe": "H4", "journal_date": "2026-10-20",
                 "session": {"complete": True}, "summary": {"open": 100, "close": 101}}
        invalid = [None, {}, [], {**valid, "instrument": "GBP_USD"}, {**valid, "timeframe": "H1"},
                   {**valid, "journal_date": "2026-10-19"}, {**valid, "session": {"complete": False}},
                   {**valid, "session": None}, {**valid, "summary": None}]
        for opened, closed in [(0, 1), (-1, 1), (1, 0), (True, 101), (100, False), ("100", 101), (1e-308, 1e308)]:
            snapshot = copy.deepcopy(valid)
            snapshot["summary"] = {"open": opened, "close": closed}
            invalid.append(snapshot)
        for snapshot in invalid:
            saved = self.save(snapshot=snapshot)
            data = self.client.get("/journals", params={"journal_date": "2026-10-20"}).json()
            self.assertIsNone(data["items"][0]["change_percent"])
            self.assertIsNone(self.calendar()["days"][0]["change_percent"])
            db.delete_journal(saved["id"])
        for raw in ('not-json', '{"summary": NaN}', '{"instrument":"EUR_USD","timeframe":"H4","journal_date":"2026-10-20","session":{"complete":true},"summary":{"open":100,"close":1e999}}'):
            saved = self.save()
            with db.get_connection(write=True) as connection:
                connection.execute("UPDATE journals SET market_data_json = ? WHERE id = ?", (raw, saved["id"]))
            self.assertIsNone(self.calendar()["days"][0]["change_percent"])
            db.delete_journal(saved["id"])
        self.save(pair="GBPUSD")
        self.save(timeframe="1h")
        self.assertIsNone(self.calendar()["days"][0]["change_percent"])

    def test_legacy_journal_is_visible_without_market_data(self):
        saved = self.save(snapshot=None, pair="GBPUSD", timeframe="1h")
        day = self.calendar()["days"][0]
        self.assertEqual(day["journal_count"], 1)
        self.assertIsNone(day["change_percent"])
        self.assertIsNone(day["source_journal_id"])
        page = self.client.get("/journals", params={"journal_date": "2026-10-20"}).json()
        self.assertEqual(page["items"][0]["id"], saved["id"])
        self.assertIsNone(page["items"][0]["change_percent"])

    def test_month_boundaries_leap_day_and_supported_year_limits(self):
        for day in ("2024-02-01", "2024-02-29", "2024-03-01", "2026-12-31", "2027-01-01", "0001-01-01", "9999-12-31"):
            self.save(day)
        for month, dates in [("2024-02", ["2024-02-01", "2024-02-29"]),
                             ("2026-12", ["2026-12-31"]), ("2027-01", ["2027-01-01"]),
                             ("0001-01", ["0001-01-01"]), ("9999-12", ["9999-12-31"])]:
            self.assertEqual([day["date"] for day in self.calendar(month)["days"]], dates)

    def test_day_filter_is_paginated_without_truncating_calendar_counts(self):
        saved = [self.save() for _ in range(25)]
        self.save("2026-10-21")
        first = self.client.get("/journals?journal_date=2026-10-20&limit=20&offset=0").json()
        second = self.client.get("/journals?journal_date=2026-10-20&limit=20&offset=20").json()
        self.assertEqual(first["total"], 25)
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(len(second["items"]), 5)
        self.assertEqual([item["id"] for item in first["items"] + second["items"]], [row["id"] for row in reversed(saved)])
        self.assertEqual(self.calendar()["days"][0]["journal_count"], 25)
        self.assertEqual(self.client.get("/journals").json()["total"], 26)
        for item in first["items"]:
            self.assertEqual(set(item), {"id", "pair", "journal_date", "timeframe", "created_at", "updated_at", "change_percent"})
            self.assertEqual(item["change_percent"], 1.0)

    def test_invalid_month_queries_are_rejected(self):
        for month in ("2026-13", "2026-00", "2026-1", "2026-10-20", "0000-01", "10000-01", "2026-10' OR 1=1--", ""):
            self.assertEqual(self.client.get("/journals/calendar", params={"month": month}).status_code, 422, month)
        self.assertEqual(self.client.get("/journals/calendar").status_code, 422)

    def test_invalid_date_filters_are_rejected_and_empty_date_is_empty(self):
        self.save()
        for day in ("2026-02-30", "2026-10-20' OR 1=1--", "bad-date"):
            self.assertEqual(self.client.get("/journals", params={"journal_date": day}).status_code, 422)
        self.assertEqual(self.client.get("/journals?journal_date=2026-10-22").json()["items"], [])

    def test_deletion_updates_counts_and_falls_back_to_remaining_snapshot(self):
        first = self.save(closed=101)
        newest = self.save(closed=99)
        self.assertEqual(self.calendar()["days"][0]["change_percent"], -1)
        self.assertEqual(self.client.delete(f'/journals/{newest["id"]}').status_code, 204)
        day = self.calendar()["days"][0]
        self.assertEqual(day["change_percent"], 1)
        self.assertEqual(day["journal_count"], 1)
        self.assertEqual(self.client.delete(f'/journals/{first["id"]}').status_code, 204)
        self.assertEqual(self.calendar()["days"], [])
        self.assertEqual(self.client.get("/journals?journal_date=2026-10-20").json()["total"], 0)

    def test_empty_calendar_and_other_month_metadata(self):
        self.assertEqual(self.calendar(), {"month": "2026-10", "days": [], "journal_count": 0,
                                          "total_journals": 0, "latest_journal_date": None})
        self.save("2026-09-30")
        data = self.calendar()
        self.assertEqual(data["days"], [])
        self.assertEqual(data["total_journals"], 1)
        self.assertEqual(data["latest_journal_date"], "2026-09-30")

    def test_average_net_uses_same_journal_as_percent_never_combines_strategies(self):
        self.save(closed=102, evaluation=saved_score(4))
        selected = self.save(closed=99, evaluation=saved_score(-1.5))
        day = self.calendar()["days"][0]
        self.assertEqual((day["change_percent"], day["average_net_score"], day["source_journal_id"]), (-1, -1.5, selected["id"]))
        # A newer written-only journal supplies prices, but must not borrow an older score.
        written = self.save(closed=103)
        day = self.calendar()["days"][0]
        self.assertEqual((day["change_percent"], day["source_journal_id"]), (3, written["id"]))
        self.assertIsNone(day["average_net_score"])

    def test_saved_average_keeps_zero_sign_and_full_precision_without_mutation(self):
        for value in (0, 11 / 6, -11 / 6, -5, 5):
            with self.subTest(value=value):
                journal = self.save(evaluation=saved_score(value))
                day = self.calendar()["days"][0]
                self.assertEqual(day["average_net_score"], value)
                self.assertEqual(db.fetch_journal(journal["id"]), journal)
                self.assertNotIn("rule_evaluation", day)
                self.assertNotIn("market_data", day)

    def test_incomplete_final_candle_or_missing_scores_are_unavailable(self):
        cases = [None, {}, [], saved_score(None), saved_score(2, complete=False),
                 saved_score(2, method="final_candle"), saved_score(2, method="session_to_date"),
                 saved_score(2, method="range_average")]
        for key, value in (("rule_set", None), ("rule_set", {"id": "four_factor_v3"}), ("summary", None)):
            cases.append({**saved_score(2), key: value})
        wrong_count = saved_score(2)
        wrong_count["summary"]["candle_count"] = 3
        cases.append(wrong_count)
        for evaluation in cases:
            with self.subTest(evaluation=evaluation):
                self.save(evaluation=evaluation)
                self.assertIsNone(self.calendar()["days"][0]["average_net_score"])

    def test_malformed_saved_scores_do_not_break_the_calendar_or_become_zero(self):
        journal = self.save(evaluation=saved_score(2))
        raw_values = ['not-json', 'null', '[]']
        for value in (True, '2', float('nan'), float('inf'), -float('inf'), 6, -6):
            raw_values.append(json.dumps(saved_score(value)))
        for raw in raw_values:
            with db.get_connection(write=True) as connection:
                connection.execute('UPDATE journals SET rule_evaluation_json = ? WHERE id = ?', (raw, journal['id']))
            day = self.calendar()["days"][0]
            self.assertEqual(day["change_percent"], 1)
            self.assertIsNone(day["average_net_score"])

    def test_partial_snapshot_cannot_replace_full_session_average(self):
        full = self.save(evaluation=saved_score(1.5))
        partial = {"instrument": "EUR_USD", "timeframe": "H4", "journal_date": "2026-10-20",
                   "session": {"complete": False}, "summary": {"open": 100, "close": 102}}
        self.save(snapshot=partial, evaluation=saved_score(4, method="session_to_date"))
        day = self.calendar()["days"][0]
        self.assertEqual((day["source_journal_id"], day["average_net_score"]), (full["id"], 1.5))
        db.delete_journal(full["id"])
        day = self.calendar()["days"][0]
        self.assertIsNone(day["change_percent"])
        self.assertIsNone(day["average_net_score"])

    def test_older_v4_revision_is_preserved_and_deletion_restores_its_saved_score(self):
        original_evaluation = saved_score(3.5)
        original_evaluation['rule_set'].pop('revision')
        original = self.save(evaluation=original_evaluation)
        latest = self.save(evaluation=saved_score(2.5))
        # Editing older journal text does not move its score ahead of a newer save.
        db.update_journal_text(original['id'], 'My edited notes')
        self.assertEqual(self.calendar()["days"][0]["average_net_score"], 2.5)
        db.delete_journal(latest['id'])
        day = self.calendar()["days"][0]
        self.assertEqual((day["source_journal_id"], day["average_net_score"]), (original['id'], 3.5))
        self.assertEqual(db.fetch_journal(original['id'])['rule_evaluation'], original_evaluation)


if __name__ == "__main__":
    unittest.main()
