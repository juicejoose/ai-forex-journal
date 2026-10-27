import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DB_PATH = Path(__file__).resolve().parent / "data" / "journal.db"


class DraftAlreadySavedError(Exception):
    pass


class DuplicateStrategyProfileError(Exception):
    pass


@contextmanager
def get_connection(*, write=False):
    # Explicit transactions make the save check and insertion atomic.
    connection = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
    finally:
        connection.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(write=True) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS journals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                journal_date TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                strategy TEXT NOT NULL,
                notes TEXT NOT NULL,
                original_draft TEXT NOT NULL,
                edited_draft TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Existing journals remain intact; they have no historical snapshot.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(journals)")}
        if "market_data_json" not in columns:
            connection.execute("ALTER TABLE journals ADD COLUMN market_data_json TEXT")
        if "generation_id" not in columns:
            connection.execute("ALTER TABLE journals ADD COLUMN generation_id TEXT")
        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS journals_generation_id
            ON journals(generation_id)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS generated_drafts (
                id TEXT PRIMARY KEY,
                entry_json TEXT NOT NULL,
                original_draft TEXT NOT NULL,
                market_data_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS strategy_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                rules TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)


def _journal_from_row(row):
    if row is None:
        return None
    journal = dict(row)
    snapshot = journal.pop("market_data_json")
    journal["market_data"] = json.loads(snapshot) if snapshot is not None else None
    return journal


def store_generated_draft(entry, original_draft, market_data):
    """Keep the server's original evidence until the user saves the journal."""
    generation_id = str(uuid4())
    with get_connection(write=True) as connection:
        connection.execute(
            """
            INSERT INTO generated_drafts
                (id, entry_json, original_draft, market_data_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                generation_id, json.dumps(entry, allow_nan=False), original_draft,
                json.dumps(market_data, allow_nan=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return generation_id


def save_generated_journal(generation_id, edited_draft):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(write=True) as connection:
        existing = connection.execute(
            "SELECT * FROM journals WHERE generation_id = ?", (generation_id,),
        ).fetchone()
        if existing is not None:
            if existing["edited_draft"] != edited_draft:
                raise DraftAlreadySavedError
            return _journal_from_row(existing)

        draft = connection.execute(
            "SELECT * FROM generated_drafts WHERE id = ?", (generation_id,),
        ).fetchone()
        if draft is None:
            return None

        entry = json.loads(draft["entry_json"])
        cursor = connection.execute(
            """
            INSERT INTO journals (
                pair, journal_date, timeframe, strategy, notes,
                original_draft, edited_draft, created_at, updated_at,
                market_data_json, generation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["pair"], entry["journal_date"], entry["timeframe"],
                entry["strategy"], entry["notes"], draft["original_draft"],
                edited_draft, now, now, draft["market_data_json"], generation_id,
            ),
        )
        connection.execute("DELETE FROM generated_drafts WHERE id = ?", (generation_id,))
        row = connection.execute(
            "SELECT * FROM journals WHERE id = ?", (cursor.lastrowid,),
        ).fetchone()
        return _journal_from_row(row)


def fetch_journal(journal_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM journals WHERE id = ?", (journal_id,),
        ).fetchone()
        return _journal_from_row(row)


def update_journal_text(journal_id, edited_draft):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(write=True) as connection:
        cursor = connection.execute(
            "UPDATE journals SET edited_draft = ?, updated_at = ? WHERE id = ?",
            (edited_draft, now, journal_id),
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            "SELECT * FROM journals WHERE id = ?", (journal_id,),
        ).fetchone()
        return _journal_from_row(row)


def delete_journal(journal_id):
    """Permanently remove one saved journal, including its stored evidence."""
    with get_connection(write=True) as connection:
        cursor = connection.execute("DELETE FROM journals WHERE id = ?", (journal_id,))
        return cursor.rowcount == 1


def fetch_journals(limit=20, offset=0):
    with get_connection() as connection:
        total = connection.execute("SELECT COUNT(*) FROM journals").fetchone()[0]
        rows = connection.execute(
            """
            SELECT id, pair, journal_date, timeframe, created_at, updated_at
            FROM journals
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def fetch_strategy_profiles():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM strategy_profiles ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": len(rows)}


def fetch_strategy_profile(profile_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM strategy_profiles WHERE id = ?", (profile_id,),
        ).fetchone()
        return dict(row) if row is not None else None


def delete_strategy_profile(profile_id):
    """Remove one profile; journals and generated drafts keep their copied rules."""
    with get_connection(write=True) as connection:
        cursor = connection.execute(
            "DELETE FROM strategy_profiles WHERE id = ?", (profile_id,),
        )
        return cursor.rowcount == 1


def insert_strategy_profile(name, rules):
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection(write=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO strategy_profiles (name, rules, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, rules, now, now),
            )
            return dict(connection.execute(
                "SELECT * FROM strategy_profiles WHERE id = ?", (cursor.lastrowid,),
            ).fetchone())
    except sqlite3.IntegrityError as exc:
        if exc.sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE":
            raise DuplicateStrategyProfileError from None
        raise


def update_strategy_profile(profile_id, name, rules):
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE strategy_profiles SET name = ?, rules = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, rules, now, profile_id),
            )
            if cursor.rowcount == 0:
                return None
            return dict(connection.execute(
                "SELECT * FROM strategy_profiles WHERE id = ?", (profile_id,),
            ).fetchone())
    except sqlite3.IntegrityError as exc:
        if exc.sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE":
            raise DuplicateStrategyProfileError from None
        raise
