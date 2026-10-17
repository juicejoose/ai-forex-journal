import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "journal.db"


@contextmanager
def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=10, autocommit=False)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
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


def insert_journal(entry, original_draft, edited_draft):
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO journals (
                pair, journal_date, timeframe, strategy, notes,
                original_draft, edited_draft, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["pair"], entry["journal_date"], entry["timeframe"],
                entry["strategy"], entry["notes"],
                original_draft, edited_draft, now, now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM journals WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)


def fetch_journal(journal_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM journals WHERE id = ?",
            (journal_id,),
        ).fetchone()
        return dict(row) if row is not None else None


def update_journal_text(journal_id, edited_draft):
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE journals SET edited_draft = ?, updated_at = ? WHERE id = ?",
            (edited_draft, now, journal_id),
        )

        if cursor.rowcount == 0:
            return None

        row = connection.execute(
            "SELECT * FROM journals WHERE id = ?",
            (journal_id,),
        ).fetchone()

        return dict(row)


def fetch_journals(limit=20, offset=0):
    with get_connection() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM journals"
        ).fetchone()[0]

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