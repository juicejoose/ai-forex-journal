"""Offline journal-saving regression tests using a temporary SQLite database.

Run all tests from backend: python -m unittest discover -v
Uses dummy credentials; no live provider requests or saved journal data.
"""

import copy
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from openai import APIError

# This helper imports main with dummy credentials and dotenv disabled.
from test_market_data import ENVIRONMENT, FixedDateTime, payload
from test_journal_grounding import valid_analysis
from journal_grounding import render_journal
import database as db
import main
import market_data as md

ENTRY = {
    "pair": "EUR/USD", "journal_date": "2026-10-20", "timeframe": "4h",
    "strategy": "At each candle close, bullish when close > EMA20 and RSI14 > 50.",
    "notes": "User observation, not verified price evidence.",
}


class JournalEvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "journal.db"))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        self.enterContext(patch.object(md, "datetime", FixedDateTime))
        self.enterContext(patch.object(md, "urlopen", side_effect=AssertionError("No live requests")))
        with patch.object(md, "_fetch_candles", return_value=payload()):
            self.snapshot = md.get_market_data(date(2026, 10, 20))
        self.market = self.enterContext(patch.object(main, "get_market_data", return_value=self.snapshot))
        response_text = json.dumps(valid_analysis(ENTRY["strategy"]))
        self.expected_draft = render_journal(response_text, self.snapshot, ENTRY["strategy"])
        self.ai = self.enterContext(patch.object(
            main.client.responses, "create",
            return_value=SimpleNamespace(status="completed", output_text=response_text),
        ))
        self.client = self.enterContext(TestClient(main.app))

    def generate(self, entry=None):
        response = self.client.post("/journal/generate", json=ENTRY if entry is None else entry)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save(self, draft, text="Edited journal."):
        response = self.client.post("/journals", json={
            "generation_id": draft["generation_id"], "edited_draft": text,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_full_evidence_sent_to_ai_and_original_held_on_server(self):
        draft = self.generate()
        sent = json.loads(self.ai.call_args.kwargs["input"])
        self.assertEqual(sent["market_data"], self.snapshot)
        self.assertEqual(sent["entry"], draft["entry"])
        self.assertEqual(sent["entry"]["pair"], "EURUSD")
        self.assertEqual(len(sent["market_data"]["candles"]), 6)
        self.assertEqual(draft["market_data"], self.snapshot)
        self.assertFalse(self.ai.call_args.kwargs["store"])
        self.assertEqual(self.client.get("/journals").json()["total"], 0)
        # Mutating the returned draft cannot replace the server's evidence.
        draft["entry"]["strategy"] = "Tampered"
        draft["market_data"]["summary"]["close"] = 999
        saved = self.save(draft)
        self.assertEqual(saved["strategy"], ENTRY["strategy"])
        self.assertEqual(saved["original_draft"], self.expected_draft)
        self.assertEqual(saved["market_data"], self.snapshot)

    def test_save_reopen_edit_and_restore_keep_snapshot(self):
        draft = self.generate()
        saved = self.save(draft)
        journal_id = saved["id"]
        self.market.reset_mock()
        self.ai.reset_mock()
        reopened = self.client.get(f"/journals/{journal_id}").json()
        self.assertEqual(reopened, saved)
        edited = self.client.patch(f"/journals/{journal_id}", json={"edited_draft": "New edit."}).json()
        for key in ("market_data", "original_draft", "strategy", "notes", "generation_id", "created_at"):
            self.assertEqual(edited[key], saved[key])
        self.assertEqual(edited["edited_draft"], "New edit.")
        restored = self.client.patch(f"/journals/{journal_id}", json={
            "edited_draft": saved["original_draft"],
        }).json()
        self.assertEqual(restored["edited_draft"], self.expected_draft)
        self.market.assert_not_called()
        self.ai.assert_not_called()
        self.assertEqual(self.client.get("/journals").json()["total"], 1)

    def test_draft_survives_database_reinitialization(self):
        draft = self.generate()
        db.init_db()
        self.assertEqual(self.save(draft)["market_data"], self.snapshot)

    def test_retry_and_concurrent_save_create_only_one_journal(self):
        draft = self.generate()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: db.save_generated_journal(
                draft["generation_id"], "Edited journal.",
            ), range(2)))
        self.assertEqual(results[0]["id"], results[1]["id"])
        retried = self.save(draft)
        self.assertEqual(retried["id"], results[0]["id"])
        self.assertEqual(self.client.get("/journals").json()["total"], 1)
        changed_retry = self.client.post("/journals", json={
            "generation_id": draft["generation_id"], "edited_draft": "Different text",
        })
        self.assertEqual(changed_retry.status_code, 409)
        self.assertEqual(db.fetch_journal(retried["id"])["edited_draft"], "Edited journal.")

    def test_save_and_patch_reject_replacement_evidence(self):
        draft = self.generate()
        for extra in ({"market_data": {}}, {"entry": ENTRY}, {"original_draft": "Fake"}):
            result = self.client.post("/journals", json={
                "generation_id": draft["generation_id"], "edited_draft": "Text", **extra,
            })
            self.assertEqual(result.status_code, 422)
        saved = self.save(draft)
        result = self.client.patch(f'/journals/{saved["id"]}', json={
            "edited_draft": "Text", "market_data": {},
        })
        self.assertEqual(result.status_code, 422)

    def test_unknown_draft_and_invalid_inputs(self):
        response = self.client.post("/journals", json={
            "generation_id": str(uuid4()), "edited_draft": "Text",
        })
        self.assertEqual(response.status_code, 404)
        for body in ({"generation_id": "invalid", "edited_draft": "Text"},
                     {"generation_id": str(uuid4()), "edited_draft": " "},
                     {"generation_id": str(uuid4()), "edited_draft": "x" * 20001}):
            self.assertEqual(self.client.post("/journals", json=body).status_code, 422)
        self.assertEqual(self.client.get("/journals/99999").status_code, 404)
        self.assertEqual(self.client.patch("/journals/99999", json={"edited_draft": "Text"}).status_code, 404)

    def test_supported_pair_aliases_and_optional_notes(self):
        for pair in ("EURUSD", "eur/usd", "EUR_USD"):
            entry = {**ENTRY, "pair": pair}
            del entry["notes"]
            draft = self.generate(entry)
            self.assertEqual(draft["entry"]["pair"], "EURUSD")
            self.assertEqual(self.save(draft)["notes"], "")

    def test_wrong_pair_timeframe_and_invalid_entry_never_call_providers(self):
        for changes in ({"pair": "GBPUSD"}, {"timeframe": "1h"}, {"strategy": " "},
                        {"journal_date": "bad-date"}, {"strategy": "x" * 10001}):
            response = self.client.post("/journal/generate", json={**ENTRY, **changes})
            self.assertEqual(response.status_code, 422)
        self.market.assert_not_called()
        self.ai.assert_not_called()

    def test_market_errors_stop_ai_and_storage(self):
        for status in (422, 502, 503):
            self.market.side_effect = md.MarketDataError("Market request rejected.", status)
            response = self.client.post("/journal/generate", json=ENTRY)
            self.assertEqual(response.status_code, status)
        self.ai.assert_not_called()
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_drafts").fetchone()[0], 0)

    def test_weekend_and_unfinished_session_do_not_call_ai(self):
        self.market.side_effect = md.get_market_data
        for day in ("2026-10-17", "2026-10-18", "2026-10-22", "2026-10-23"):
            response = self.client.post("/journal/generate", json={**ENTRY, "journal_date": day})
            self.assertEqual(response.status_code, 422, response.text)
        self.ai.assert_not_called()

    def test_failed_empty_incomplete_or_oversized_ai_results_do_not_store(self):
        for status, text in (("incomplete", "Partial text"), ("completed", "  "), ("completed", "x" * 20001)):
            self.ai.return_value = SimpleNamespace(status=status, output_text=text)
            self.assertEqual(self.client.post("/journal/generate", json=ENTRY).status_code, 502)
        self.ai.side_effect = APIError("private error", request=SimpleNamespace(), body=None)
        response = self.client.post("/journal/generate", json=ENTRY)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private error", response.text)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_drafts").fetchone()[0], 0)

    def test_write_transaction_rolls_back_on_error(self):
        with self.assertRaises(RuntimeError):
            with db.get_connection(write=True) as connection:
                connection.execute("INSERT INTO generated_drafts VALUES ('test', '{}', 'draft', '{}', 'today')")
                raise RuntimeError("rollback")
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_drafts").fetchone()[0], 0)


class MigrationTests(unittest.TestCase):
    def test_legacy_database_migrates_without_changing_saved_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(path)
            connection.execute("""CREATE TABLE journals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, pair TEXT NOT NULL,
                journal_date TEXT NOT NULL, timeframe TEXT NOT NULL, strategy TEXT NOT NULL,
                notes TEXT NOT NULL, original_draft TEXT NOT NULL, edited_draft TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            connection.execute("INSERT INTO journals VALUES (7, 'GBPUSD', '2026-09-01', '1h', 'Rules', 'Notes', 'Original', 'Edited', 'before', 'before')")
            connection.commit()
            connection.close()
            with patch.object(db, "DB_PATH", path), TestClient(main.app) as client:
                db.init_db()
                old = client.get("/journals/7").json()
                self.assertEqual(old["edited_draft"], "Edited")
                self.assertEqual(old["timeframe"], "1h")
                self.assertEqual(old["pair"], "GBPUSD")
                self.assertIsNone(old["market_data"])
                self.assertIsNone(old["generation_id"])
                updated = client.patch("/journals/7", json={"edited_draft": "Legacy edit"}).json()
                self.assertEqual(updated["edited_draft"], "Legacy edit")
                self.assertEqual(updated["original_draft"], "Original")
                self.assertEqual(updated["created_at"], "before")
                self.assertIsNone(updated["market_data"])
                page = client.get("/journals?limit=1&offset=0").json()
                self.assertEqual(page["total"], 1)
                self.assertEqual(page["items"][0]["id"], 7)


if __name__ == "__main__":
    unittest.main()
