import json
import math
import os
import sqlite3
from calendar import monthrange
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

DB_PATH = Path(os.environ.get("JOURNAL_DB_PATH", Path(__file__).resolve().parent / "data" / "journal.db"))


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
        if "title" not in columns:
            connection.execute("ALTER TABLE journals ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS journals_generation_id
            ON journals(generation_id)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS journals_session_date
            ON journals(journal_date, created_at DESC, id DESC)
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
        for table in ("journals", "generated_drafts"):
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "rule_evaluation_json" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN rule_evaluation_json TEXT")
        profile_columns = {row["name"] for row in connection.execute("PRAGMA table_info(strategy_profiles)")}
        if "rule_set_id" not in profile_columns:
            connection.execute("ALTER TABLE strategy_profiles ADD COLUMN rule_set_id TEXT")


def _journal_from_row(row):
    if row is None:
        return None
    journal = dict(row)
    snapshot = journal.pop("market_data_json")
    journal["market_data"] = json.loads(snapshot) if snapshot is not None else None
    evaluation = journal.pop("rule_evaluation_json")
    journal["rule_evaluation"] = json.loads(evaluation) if evaluation is not None else None
    return journal


def store_generated_draft(entry, original_draft, market_data, rule_evaluation=None):
    """Keep the server's original evidence until the user saves the journal."""
    generation_id = str(uuid4())
    with get_connection(write=True) as connection:
        connection.execute(
            """
            INSERT INTO generated_drafts
                (id, entry_json, original_draft, market_data_json, created_at, rule_evaluation_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id, json.dumps(entry, allow_nan=False), original_draft,
                json.dumps(market_data, allow_nan=False),
                datetime.now(timezone.utc).isoformat(),
                json.dumps(rule_evaluation, allow_nan=False) if rule_evaluation is not None else None,
            ),
        )
    return generation_id


def save_generated_journal(generation_id, edited_draft, *, title=""):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(write=True) as connection:
        existing = connection.execute(
            "SELECT * FROM journals WHERE generation_id = ?", (generation_id,),
        ).fetchone()
        if existing is not None:
            if existing["edited_draft"] != edited_draft or existing["title"] != title:
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
                market_data_json, generation_id, rule_evaluation_json, title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["pair"], entry["journal_date"], entry["timeframe"],
                entry["strategy"], entry["notes"], draft["original_draft"],
                edited_draft, now, now, draft["market_data_json"], generation_id, draft["rule_evaluation_json"], title,
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


def update_journal_text(journal_id, edited_draft, *, title=None):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(write=True) as connection:
        cursor = connection.execute(
            "UPDATE journals SET edited_draft = ?, updated_at = ?, title = COALESCE(?, title) WHERE id = ?",
            (edited_draft, now, title, journal_id),
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


def _session_change_percent(row):
    """Read a saved EUR/USD H4 session's return, never a journal's AI prose."""
    if row["pair"].upper().replace("/", "").replace("_", "") != "EURUSD" or row["timeframe"] != "4h":
        return None
    try:
        snapshot = json.loads(row["market_data_json"])
        if (not isinstance(snapshot, dict) or snapshot.get("instrument") != "EUR_USD"
                or snapshot.get("timeframe") != "H4"
                or snapshot.get("journal_date") != row["journal_date"]
                or not isinstance(snapshot.get("session"), dict)
                or snapshot["session"].get("complete") is not True):
            return None
        summary = snapshot["summary"]
        opened, closed = summary["open"], summary["close"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value <= 0 for value in (opened, closed)):
            return None
        change = (closed - opened) / opened * 100
        return change if math.isfinite(change) else None
    except (TypeError, ValueError, KeyError, OverflowError):
        return None


def fetch_journals(limit=20, offset=0, journal_date=None):
    where = " WHERE journal_date = ?" if journal_date is not None else ""
    parameters = (journal_date,) if journal_date is not None else ()
    with get_connection() as connection:
        total = connection.execute("SELECT COUNT(*) FROM journals" + where, parameters).fetchone()[0]
        rows = connection.execute(
            """SELECT id, title, pair, journal_date, timeframe, created_at, updated_at, market_data_json, rule_evaluation_json
            FROM journals""" + where + """
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item.pop("market_data_json")
            item.pop("rule_evaluation_json")
            item["change_percent"] = _session_change_percent(row)
            item["average_net_score"] = _session_average_net_score(row, allow_partial=True)
            try:
                snapshot = json.loads(row["market_data_json"])
                if snapshot.get("analysis_kind") == "intraday":
                    item["session_complete"] = snapshot["session"]["complete"]
                    item["completed_candles"] = len(snapshot["candles"])
                    item["data_through"] = snapshot["data_through"]
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            items.append(item)
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def _session_average_net_score(row, *, allow_partial=False):
    """Read stored averages; only entry cards may include a provisional average."""
    try:
        evaluation = json.loads(row["rule_evaluation_json"])
        if not isinstance(evaluation, dict) or evaluation.get("schema_version") != 1:
            return None
        definition, summary = evaluation.get("rule_set"), evaluation.get("summary")
        if (not isinstance(definition, dict) or definition.get("id") not in ("four_factor_v4", "four_factor_v5", "four_factor_v6", "four_factor_v7")
                or not isinstance(summary, dict) or summary.get("complete") is not True):
            return None
        method, count = summary.get("method"), summary.get("candle_count")
        full = method == "session_average" and count == 6
        partial = (allow_partial and method == "session_to_date" and evaluation.get("analysis_kind") == "intraday"
                   and type(count) is int and 1 <= count < 6)
        if not full and not partial:
            return None
        if allow_partial:
            # Entry cards must agree with their own market snapshot's identity and coverage.
            snapshot = json.loads(row["market_data_json"])
            if (not isinstance(snapshot, dict) or snapshot.get("instrument") != "EUR_USD"
                    or snapshot.get("timeframe") != "H4" or row["timeframe"] != "4h"
                    or row["pair"].upper().replace("/", "").replace("_", "") != "EURUSD"
                    or snapshot.get("journal_date") != row["journal_date"]
                    or not isinstance(snapshot.get("session"), dict)
                    or snapshot["session"].get("complete") is not full):
                return None
            if partial and (snapshot.get("analysis_kind") != "intraday" or len(snapshot.get("candles", [])) != count):
                return None
        value, maximum = summary.get("net_score"), summary.get("max_points")
        if (any(type(number) not in (int, float) or not math.isfinite(number) for number in (value, maximum))
                or maximum <= 0 or abs(value) > maximum):
            return None
        return value
    except (TypeError, ValueError, KeyError, OverflowError):
        return None


def fetch_journal_calendar(month):
    first = date.fromisoformat(f"{month}-01")
    last = first.replace(day=monthrange(first.year, first.month)[1])
    with get_connection() as connection:
        overall = connection.execute(
            "SELECT COUNT(*) AS total, MAX(journal_date) AS latest FROM journals"
        ).fetchone()
        rows = connection.execute("""
            SELECT id, pair, journal_date, timeframe, market_data_json, rule_evaluation_json
            FROM journals WHERE journal_date >= ? AND journal_date <= ?
            ORDER BY journal_date, created_at DESC, id DESC
        """, (first.isoformat(), last.isoformat()))
        days = {}
        for row in rows:
            day = days.setdefault(row["journal_date"], {
                "date": row["journal_date"], "journal_count": 0,
                "change_percent": None, "average_net_score": None, "source_journal_id": None,
            })
            day["journal_count"] += 1
            # Several strategies can share a session. Do not add their returns.
            # The first usable snapshot is the most recently saved one for this date.
            if day["source_journal_id"] is None:
                change = _session_change_percent(row)
                if change is not None:
                    day["change_percent"] = change
                    # Keep both values tied to one journal; never combine strategies
                    # or substitute a final-candle/provisional score for a daily mean.
                    day["average_net_score"] = _session_average_net_score(row)
                    day["source_journal_id"] = row["id"]
        return {
            "month": month, "days": list(days.values()),
            "journal_count": sum(day["journal_count"] for day in days.values()),
            "total_journals": overall["total"], "latest_journal_date": overall["latest"],
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


def insert_strategy_profile(name, rules, rule_set_id=None):
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection(write=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO strategy_profiles (name, rules, created_at, updated_at, rule_set_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, rules, now, now, rule_set_id),
            )
            return dict(connection.execute(
                "SELECT * FROM strategy_profiles WHERE id = ?", (cursor.lastrowid,),
            ).fetchone())
    except sqlite3.IntegrityError as exc:
        if exc.sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE":
            raise DuplicateStrategyProfileError from None
        raise


def update_strategy_profile(profile_id, name, rules, rule_set_id=None):
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE strategy_profiles SET name = ?, rules = ?, updated_at = ?, rule_set_id = ?
                WHERE id = ?
                """,
                (name, rules, now, rule_set_id, profile_id),
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
