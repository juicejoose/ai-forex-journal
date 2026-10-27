"""Offline deletion checks using simulated providers and temporary SQLite only.

Run from backend: python -m unittest -v test_journal_deletion
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


ENTRY = {
    "pair": "EURUSD", "journal_date": "2026-10-20", "timeframe": "4h",
    "strategy": "Close above EMA20.", "notes": "Deletion test fixture.",
}


class JournalDeletionTests(unittest.TestCase):
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

    def save(self, text="Saved test journal"):
        generation_id = db.store_generated_draft(ENTRY, "Original test draft", {"fixture": True})
        return db.save_generated_journal(generation_id, text)

    def test_delete_removes_only_target_and_its_evidence(self):
        target = self.save()
        other = self.save("Keep this journal")
        profile = db.insert_strategy_profile("Keep this profile", "Close above EMA20.")
        staged_id = db.store_generated_draft(ENTRY, "Keep this unsaved draft", {"fixture": True})

        response = self.client.delete(f'/journals/{target["id"]}')

        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get(f'/journals/{target["id"]}').status_code, 404)
        self.assertEqual(db.fetch_journal(other["id"]), other)
        self.assertEqual(db.fetch_strategy_profile(profile["id"]), profile)
        self.assertEqual(self.client.get("/journals").json()["total"], 1)
        with db.get_connection() as connection:
            self.assertIsNone(connection.execute(
                "SELECT * FROM journals WHERE id = ?", (target["id"],),
            ).fetchone())
            self.assertEqual(connection.execute(
                "SELECT original_draft FROM generated_drafts WHERE id = ?", (staged_id,),
            ).fetchone()[0], "Keep this unsaved draft")

    def test_deletion_persists_after_database_reinitialization(self):
        target = self.save()
        self.assertEqual(self.client.delete(f'/journals/{target["id"]}').status_code, 204)
        with TestClient(main.app) as restarted:
            self.assertEqual(restarted.get(f'/journals/{target["id"]}').status_code, 404)
            self.assertEqual(restarted.get("/journals").json()["total"], 0)

    def test_stale_save_edit_and_repeat_delete_cannot_restore_journal(self):
        target = self.save()
        url = f'/journals/{target["id"]}'
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(self.client.patch(url, json={"edited_draft": "Stale edit"}).status_code, 404)
        self.assertEqual(self.client.post("/journals", json={
            "generation_id": target["generation_id"], "edited_draft": target["edited_draft"],
        }).status_code, 404)
        self.assertEqual(self.client.get("/journals").json()["total"], 0)
        replacement = self.save()
        self.assertGreater(replacement["id"], target["id"])

    def test_missing_or_invalid_id_does_not_delete_other_entries(self):
        saved = self.save()
        for journal_id in (0, -1, 99999):
            response = self.client.delete(f"/journals/{journal_id}")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "Journal not found.")
        self.assertEqual(self.client.delete("/journals/not-an-id").status_code, 422)
        self.assertEqual(self.client.delete("/journals/1%20OR%201=1").status_code, 422)
        self.assertEqual(db.fetch_journal(saved["id"]), saved)

    def test_legacy_journal_without_market_snapshot_can_be_deleted(self):
        with db.get_connection(write=True) as connection:
            cursor = connection.execute("""
                INSERT INTO journals (
                    pair, journal_date, timeframe, strategy, notes,
                    original_draft, edited_draft, created_at, updated_at
                ) VALUES ('GBPUSD', '2026-09-01', '1h', 'Rules', '', 'Original', 'Edited', 'before', 'before')
            """)
            journal_id = cursor.lastrowid
        self.assertIsNone(db.fetch_journal(journal_id)["market_data"])
        self.assertEqual(self.client.delete(f"/journals/{journal_id}").status_code, 204)
        self.assertIsNone(db.fetch_journal(journal_id))

    def test_simultaneous_deletes_remove_one_journal_once(self):
        target = self.save()
        other = self.save("Keep this journal")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: db.delete_journal(target["id"]), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(db.fetch_journal(other["id"]), other)

    def test_browser_preflight_allows_delete_for_development_frontend(self):
        for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
            response = self.client.options("/journals/1", headers={
                "Origin": origin,
                "Access-Control-Request-Method": "DELETE",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], origin)
            self.assertIn("DELETE", response.headers["access-control-allow-methods"])

    def test_storage_failure_rolls_back_deletion(self):
        target = self.save()
        other = self.save("Keep this journal")
        with db.get_connection(write=True) as connection:
            # Simulate a database failure after the target row is removed.
            connection.execute("""
                CREATE TRIGGER fail_delete AFTER DELETE ON journals
                BEGIN
                    SELECT RAISE(ABORT, 'Simulated storage failure');
                END
            """)
        with TestClient(main.app, raise_server_exceptions=False) as client:
            response = client.delete(f'/journals/{target["id"]}')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(db.fetch_journal(target["id"]), target)
        self.assertEqual(db.fetch_journal(other["id"]), other)

    def test_deleting_last_entry_on_last_page_updates_count(self):
        journals = [self.save(f"Journal {index}") for index in range(21)]
        last_page = self.client.get("/journals?limit=20&offset=20").json()
        self.assertEqual(last_page["total"], 21)
        self.assertEqual(len(last_page["items"]), 1)
        journal_id = last_page["items"][0]["id"]
        self.assertEqual(self.client.delete(f"/journals/{journal_id}").status_code, 204)
        first_page = self.client.get("/journals?limit=20&offset=0").json()
        self.assertEqual(first_page["total"], 20)
        self.assertEqual(len(first_page["items"]), 20)
        self.assertEqual({row["id"] for row in first_page["items"]},
                         {row["id"] for row in journals} - {journal_id})


if __name__ == "__main__":
    unittest.main()
