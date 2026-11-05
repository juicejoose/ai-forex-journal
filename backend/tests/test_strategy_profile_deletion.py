"""Offline profile deletion checks; all data lives in temporary SQLite files.

Run from backend: python -m unittest -v tests.test_strategy_profile_deletion
"""

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

# Imports main with dummy credentials and dotenv disabled.
from tests.test_market_data import ENVIRONMENT
import database as db
import main


class StrategyProfileDeletionTests(unittest.TestCase):
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

    def tearDown(self):
        self.market.assert_not_called()
        self.ai.assert_not_called()

    def profile(self, name="EMA continuation"):
        return db.insert_strategy_profile(name, "Close above EMA20.")

    def test_delete_preserves_other_profiles_journals_and_staged_drafts(self):
        target = self.profile()
        other = self.profile("Keep this profile")
        entry = {
            "pair": "EURUSD", "journal_date": "2026-10-20", "timeframe": "4h",
            "strategy": target["rules"], "notes": "Deletion test fixture.",
        }
        generation_id = db.store_generated_draft(entry, "Original", {"fixture": True})
        journal = db.save_generated_journal(generation_id, "Saved edits")
        staged_id = db.store_generated_draft(entry, "Unsaved draft", {"fixture": True})
        with db.get_connection() as connection:
            staged = dict(connection.execute(
                "SELECT * FROM generated_drafts WHERE id = ?", (staged_id,),
            ).fetchone())

        response = self.client.delete(f'/strategy-profiles/{target["id"]}')

        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get(f'/strategy-profiles/{target["id"]}').status_code, 404)
        self.assertEqual(self.client.get("/strategy-profiles").json(), {"items": [other], "total": 1})
        self.assertEqual(db.fetch_journal(journal["id"]), journal)
        with db.get_connection() as connection:
            self.assertEqual(dict(connection.execute(
                "SELECT * FROM generated_drafts WHERE id = ?", (staged_id,),
            ).fetchone()), staged)
        # A previously generated draft can still be saved with the copied strategy.
        saved_later = db.save_generated_journal(staged_id, "Saved after deleting profile")
        self.assertEqual(saved_later["strategy"], target["rules"])

    def test_deletion_persists_after_restart(self):
        target = self.profile()
        self.assertEqual(self.client.delete(f'/strategy-profiles/{target["id"]}').status_code, 204)
        with TestClient(main.app) as restarted:
            self.assertEqual(restarted.get(f'/strategy-profiles/{target["id"]}').status_code, 404)
            self.assertEqual(restarted.get("/strategy-profiles").json(), {"items": [], "total": 0})

    def test_repeat_delete_and_stale_edit_cannot_restore_profile(self):
        target = self.profile()
        url = f'/strategy-profiles/{target["id"]}'
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(self.client.patch(url, json={
            "name": target["name"], "rules": "Stale edits",
        }).status_code, 404)
        self.assertEqual(self.client.get("/strategy-profiles").json()["total"], 0)

    def test_deleted_name_can_be_reused_without_reusing_id(self):
        target = self.profile()
        url = f'/strategy-profiles/{target["id"]}'
        self.assertEqual(self.client.delete(url).status_code, 204)
        response = self.client.post("/strategy-profiles", json={
            "name": target["name"].upper(), "rules": "New rules",
        })
        self.assertEqual(response.status_code, 201, response.text)
        replacement = response.json()
        self.assertGreater(replacement["id"], target["id"])
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(db.fetch_strategy_profile(replacement["id"]), replacement)

    def test_missing_invalid_and_injection_ids_leave_profiles_intact(self):
        target = self.profile()
        for profile_id in (0, -1, 99999):
            response = self.client.delete(f"/strategy-profiles/{profile_id}")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "Strategy profile not found.")
        for profile_id in ("not-an-id", "1%20OR%201=1"):
            self.assertEqual(self.client.delete(f"/strategy-profiles/{profile_id}").status_code, 422)
        self.assertEqual(db.fetch_strategy_profile(target["id"]), target)

    def test_simultaneous_deletes_remove_only_target_once(self):
        target = self.profile()
        other = self.profile("Keep this profile")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: db.delete_strategy_profile(target["id"]), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(db.fetch_strategy_profiles(), {"items": [other], "total": 1})

    def test_storage_failure_rolls_back_deletion(self):
        target = self.profile()
        other = self.profile("Keep this profile")
        with db.get_connection(write=True) as connection:
            connection.execute("""
                CREATE TRIGGER fail_profile_delete AFTER DELETE ON strategy_profiles
                BEGIN
                    SELECT RAISE(ABORT, 'Simulated storage failure');
                END
            """)
        with TestClient(main.app, raise_server_exceptions=False) as client:
            response = client.delete(f'/strategy-profiles/{target["id"]}')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(db.fetch_strategy_profile(target["id"]), target)
        self.assertEqual(db.fetch_strategy_profile(other["id"]), other)

    def test_browser_preflight_allows_profile_deletion(self):
        for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
            response = self.client.options("/strategy-profiles/1", headers={
                "Origin": origin, "Access-Control-Request-Method": "DELETE",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], origin)
            self.assertIn("DELETE", response.headers["access-control-allow-methods"])

    def test_deleting_last_profile_returns_empty_list_and_allows_new_profile(self):
        target = self.profile()
        self.assertEqual(self.client.delete(f'/strategy-profiles/{target["id"]}').status_code, 204)
        self.assertEqual(self.client.get("/strategy-profiles").json(), {"items": [], "total": 0})
        response = self.client.post("/strategy-profiles", json={"name": "New profile", "rules": "New rules"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.get("/strategy-profiles").json()["items"], [response.json()])


if __name__ == "__main__":
    unittest.main()
