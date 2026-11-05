"""Custom-range journals use separate tables in the existing local database."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from database import get_connection, DraftAlreadySavedError


def init_range_db():
    with get_connection(write=True) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS range_generated_drafts (
            id TEXT PRIMARY KEY, entry_json TEXT NOT NULL, original_draft TEXT NOT NULL,
            market_data_json TEXT NOT NULL, rule_evaluation_json TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS range_journals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            entry_json TEXT NOT NULL, original_draft TEXT NOT NULL, edited_draft TEXT NOT NULL,
            market_data_json TEXT NOT NULL, rule_evaluation_json TEXT NOT NULL,
            generation_id TEXT NOT NULL UNIQUE, change_percent REAL NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS range_journals_created ON range_journals(created_at DESC, id DESC)")


def _journal(row):
    if row is None:
        return None
    item = dict(row)
    item.update(json.loads(item.pop("entry_json")))
    item["market_data"] = json.loads(item.pop("market_data_json"))
    item["rule_evaluation"] = json.loads(item.pop("rule_evaluation_json"))
    item["analysis_kind"] = "custom_range"
    return item


def store_range_draft(entry, draft, snapshot, evaluation):
    generation_id = str(uuid4())
    with get_connection(write=True) as connection:
        connection.execute("""INSERT INTO range_generated_drafts
            (id, entry_json, original_draft, market_data_json, rule_evaluation_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""", (generation_id, json.dumps(entry, allow_nan=False), draft,
            json.dumps(snapshot, allow_nan=False), json.dumps(evaluation, allow_nan=False),
            datetime.now(timezone.utc).isoformat()))
    return generation_id


def save_range_journal(generation_id, edited_draft):
    with get_connection(write=True) as connection:
        existing = connection.execute("SELECT * FROM range_journals WHERE generation_id = ?", (generation_id,)).fetchone()
        if existing is not None:
            if existing["edited_draft"] != edited_draft:
                raise DraftAlreadySavedError
            return _journal(existing)
        draft = connection.execute("SELECT * FROM range_generated_drafts WHERE id = ?", (generation_id,)).fetchone()
        if draft is None:
            return None
        entry = json.loads(draft["entry_json"])
        candles = json.loads(draft["market_data_json"])["candles"]
        change = (candles[-1]["close"] - candles[0]["open"]) / candles[0]["open"] * 100
        now = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute("""INSERT INTO range_journals
            (start_date, end_date, entry_json, original_draft, edited_draft, market_data_json,
             rule_evaluation_json, generation_id, change_percent, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            entry["start_date"], entry["end_date"], draft["entry_json"], draft["original_draft"], edited_draft,
            draft["market_data_json"], draft["rule_evaluation_json"], generation_id, change, now, now))
        connection.execute("DELETE FROM range_generated_drafts WHERE id = ?", (generation_id,))
        return _journal(connection.execute("SELECT * FROM range_journals WHERE id = ?", (cursor.lastrowid,)).fetchone())


def fetch_range_journal(journal_id):
    with get_connection() as connection:
        return _journal(connection.execute("SELECT * FROM range_journals WHERE id = ?", (journal_id,)).fetchone())


def update_range_journal(journal_id, text):
    with get_connection(write=True) as connection:
        cursor = connection.execute("UPDATE range_journals SET edited_draft = ?, updated_at = ? WHERE id = ?",
                                    (text, datetime.now(timezone.utc).isoformat(), journal_id))
        if not cursor.rowcount:
            return None
        return _journal(connection.execute("SELECT * FROM range_journals WHERE id = ?", (journal_id,)).fetchone())


def delete_range_journal(journal_id):
    with get_connection(write=True) as connection:
        return connection.execute("DELETE FROM range_journals WHERE id = ?", (journal_id,)).rowcount == 1


def fetch_range_journals(limit=20, offset=0):
    with get_connection() as connection:
        total = connection.execute("SELECT COUNT(*) FROM range_journals").fetchone()[0]
        rows = connection.execute("""SELECT id, start_date, end_date, created_at, updated_at, change_percent
            FROM range_journals ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}
