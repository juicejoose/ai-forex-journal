"""Offline strategy-profile regression tests using a temporary SQLite database.

Run all tests from backend: python -m unittest discover -v
Uses dummy credentials; no live provider requests or saved journal data.
"""

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

# Imports main with dummy credentials and dotenv disabled.
from test_market_data import ENVIRONMENT
import database as db
import main


class StrategyProfileTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "journal.db"))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        self.market = self.enterContext(patch.object(
            main, "get_market_data", side_effect=AssertionError("No market requests"),
        ))
        self.ai = self.enterContext(patch.object(
            main.client.responses, "create", side_effect=AssertionError("No AI requests"),
        ))
        self.client = self.enterContext(TestClient(main.app))

    def create(self, name="H4 trend", rules="Bullish when close > EMA20 and RSI14 > 50."):
        response = self.client.post("/strategy-profiles", json={"name": name, "rules": rules})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_read_sorted_list_and_trim(self):
        self.assertEqual(self.client.get("/strategy-profiles").json(), {"items": [], "total": 0})
        second = self.create("  Z trend  ", "  First rule.\nSecond rule.  ")
        first = self.create("a trend")
        self.assertEqual(second["name"], "Z trend")
        self.assertEqual(second["rules"], "First rule.\nSecond rule.")
        self.assertEqual(second["created_at"], second["updated_at"])
        self.assertEqual(self.client.get(f'/strategy-profiles/{first["id"]}').json(), first)
        self.assertEqual(self.client.get("/strategy-profiles").json(), {
            "items": [first, second], "total": 2,
        })
        self.market.assert_not_called()
        self.ai.assert_not_called()

    def test_profiles_survive_application_restart(self):
        saved = self.create()
        # A fresh application lifespan reopens the same on-disk database.
        with TestClient(main.app) as restarted:
            self.assertEqual(restarted.get(f'/strategy-profiles/{saved["id"]}').json(), saved)
            self.assertEqual(restarted.get("/strategy-profiles").json()["items"], [saved])

    def test_duplicate_name_rejected_case_insensitively(self):
        original = self.create()
        response = self.client.post("/strategy-profiles", json={
            "name": "  h4 TREND  ", "rules": "Different strategy",
        })
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("already exists", response.json()["detail"])
        self.assertEqual(self.client.get("/strategy-profiles").json()["items"], [original])

    def test_edit_keeps_identity_and_created_at(self):
        original = self.create()
        response = self.client.patch(f'/strategy-profiles/{original["id"]}', json={
            "name": "  Revised trend  ", "rules": "  New rules.  ",
        })
        self.assertEqual(response.status_code, 200, response.text)
        edited = response.json()
        self.assertEqual(edited["id"], original["id"])
        self.assertEqual(edited["created_at"], original["created_at"])
        self.assertGreater(edited["updated_at"], original["updated_at"])
        self.assertEqual((edited["name"], edited["rules"]), ("Revised trend", "New rules."))
        self.assertEqual(self.client.get(f'/strategy-profiles/{original["id"]}').json(), edited)

    def test_conflicting_rename_rolls_back_entire_edit(self):
        first = self.create("First")
        second = self.create("Second")
        response = self.client.patch(f'/strategy-profiles/{second["id"]}', json={
            "name": "FIRST", "rules": "This change must also roll back.",
        })
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get("/strategy-profiles").json()["items"], [first, second])

    def test_missing_profile(self):
        self.assertEqual(self.client.get("/strategy-profiles/999").status_code, 404)
        response = self.client.patch("/strategy-profiles/999", json={"name": "Missing", "rules": "Rules"})
        self.assertEqual(response.status_code, 404)

    def test_invalid_fields_rejected_for_create_and_edit(self):
        original = self.create()
        valid = {"name": "Valid", "rules": "Valid rules"}
        invalid = [
            {}, {"name": "Missing rules"}, {"rules": "Missing name"},
            {**valid, "name": "  "}, {**valid, "rules": "\n\t"},
            {**valid, "name": "x" * 101}, {**valid, "rules": "x" * 10001},
            {**valid, "name": 123}, {**valid, "rules": None},
            {**valid, "id": 7}, {**valid, "created_at": "forged"},
        ]
        for body in invalid:
            for method, path in (("POST", "/strategy-profiles"),
                                 ("PATCH", f'/strategy-profiles/{original["id"]}')):
                with self.subTest(method=method, body=repr(body)[:100]):
                    self.assertEqual(self.client.request(method, path, json=body).status_code, 422)
        self.assertEqual(self.client.get("/strategy-profiles").json()["items"], [original])

    def test_quotes_and_unicode_are_stored_as_text(self):
        name = "Trader's strategy — 日誌"
        rules = "Price > SMA190; '); DROP TABLE journals; --\nRSI14 > 50"
        saved = self.create(name, rules)
        self.assertEqual(saved["name"], name)
        self.assertEqual(saved["rules"], rules)
        self.assertEqual(self.client.get("/journals").json()["total"], 0)

    def test_profile_edits_do_not_change_journals_or_staged_drafts(self):
        profile = self.create()
        entry = {
            "pair": "EURUSD", "journal_date": "2026-10-20", "timeframe": "4h",
            "strategy": profile["rules"], "notes": "",
        }
        generation_one = db.store_generated_draft(entry, "Original draft", {"fixture": True})
        journal_one = db.save_generated_journal(generation_one, "Edited draft")
        generation_two = db.store_generated_draft(entry, "Another draft", {"fixture": True})
        response = self.client.patch(f'/strategy-profiles/{profile["id"]}', json={
            "name": "Updated profile", "rules": "Entirely different rules",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.fetch_journal(journal_one["id"]), journal_one)
        journal_two = db.save_generated_journal(generation_two, "Another edited draft")
        self.assertEqual(journal_two["strategy"], profile["rules"])

    def test_simultaneous_duplicate_creates_keep_one_record(self):
        def save(_):
            try:
                return db.insert_strategy_profile("Same name", "Rules")
            except db.DuplicateStrategyProfileError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(db.fetch_strategy_profiles()["total"], 1)


if __name__ == "__main__":
    unittest.main()
