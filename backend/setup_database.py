"""Durable setup evidence and independent, idempotent AI attempts in SQLite."""
from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
import sqlite3
from uuid import uuid4

import database as db


class SetupConflict(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def init_setup_db():
    # SQLite's backup API gives a consistent copy before the first additive migration.
    with db.get_connection() as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='setup_schema_migrations'").fetchone()
    if not exists:
        backup = db.DB_PATH.with_name(f"{db.DB_PATH.stem}.before-setup-v1-{uuid4().hex[:8]}.db")
        with closing(sqlite3.connect(db.DB_PATH)) as source, closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
    with db.get_connection(write=True) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS setup_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        if not connection.execute("SELECT 1 FROM setup_schema_migrations WHERE version=1").fetchone():
            connection.execute("""CREATE TABLE setup_snapshots (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, created_at TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE setup_evaluations (
                id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES setup_snapshots(id) ON DELETE RESTRICT,
                request_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL CHECK(status IN ('pending','completed','failed')),
                created_at TEXT NOT NULL, completed_at TEXT, requested_model TEXT NOT NULL,
                provider_model TEXT, provider_response_id TEXT, prompt_version TEXT NOT NULL,
                schema_version INTEGER NOT NULL, result_json TEXT, error_message TEXT)""")
            connection.execute("CREATE INDEX setup_created ON setup_snapshots(created_at DESC, id DESC)")
            connection.execute("CREATE INDEX setup_evaluation_history ON setup_evaluations(snapshot_id, created_at DESC)")
            connection.execute("CREATE UNIQUE INDEX setup_pending ON setup_evaluations(snapshot_id) WHERE status='pending'")
            for action in ("UPDATE", "DELETE"):
                connection.execute(f"""CREATE TRIGGER setup_snapshot_no_{action.lower()} BEFORE {action} ON setup_snapshots
                    BEGIN SELECT RAISE(ABORT, 'Setup snapshots are immutable'); END""")
            connection.execute("""CREATE TRIGGER setup_evaluation_final BEFORE UPDATE ON setup_evaluations
                WHEN OLD.status != 'pending' BEGIN SELECT RAISE(ABORT, 'Final evaluations are immutable'); END""")
            connection.execute("""CREATE TRIGGER setup_evaluation_no_delete BEFORE DELETE ON setup_evaluations
                BEGIN SELECT RAISE(ABORT, 'Evaluation records are immutable'); END""")
            connection.execute("INSERT INTO setup_schema_migrations VALUES (1, ?)", (datetime.now(timezone.utc).isoformat(),))
        if not connection.execute("SELECT 1 FROM setup_schema_migrations WHERE version=2").fetchone():
            connection.execute("""CREATE TABLE setup_previews (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL)""")
            connection.execute("""CREATE TRIGGER setup_preview_no_update BEFORE UPDATE ON setup_previews
                BEGIN SELECT RAISE(ABORT, 'Preview evidence is fixed'); END""")
            connection.execute("INSERT INTO setup_schema_migrations VALUES (2, ?)", (datetime.now(timezone.utc).isoformat(),))



def _snapshot(row):
    if row is None:
        return None
    raw = row["snapshot_json"]
    if hashlib.sha256(raw.encode()).hexdigest() != row["snapshot_hash"]:
        raise SetupConflict("Stored evidence failed its integrity check.")
    return {"id": row["id"], "created_at": row["created_at"], "snapshot_hash": row["snapshot_hash"],
            "snapshot": json.loads(raw)}


def find_snapshot_request(request_id, request):
    with db.get_connection() as connection:
        row = connection.execute("SELECT * FROM setup_snapshots WHERE request_id=?", (str(request_id),)).fetchone()
    if row and row["request_json"] != canonical(request):
        raise SetupConflict("This request ID already belongs to different setup inputs.")
    return _snapshot(row)


def store_snapshot(request_id, request, snapshot):
    raw = canonical(snapshot)
    with db.get_connection(write=True) as connection:
        row = connection.execute("SELECT * FROM setup_snapshots WHERE request_id=?", (str(request_id),)).fetchone()
        if row:
            if row["request_json"] != canonical(request):
                raise SetupConflict("This request ID already belongs to different setup inputs.")
            return _snapshot(row)
        identifier = str(uuid4())
        connection.execute("INSERT INTO setup_snapshots VALUES (?,?,?,?,?,?)", (identifier, str(request_id),
            canonical(request), raw, hashlib.sha256(raw.encode()).hexdigest(), datetime.now(timezone.utc).isoformat()))
        return _snapshot(connection.execute("SELECT * FROM setup_snapshots WHERE id=?", (identifier,)).fetchone())


def fetch_snapshot(identifier):
    with db.get_connection() as connection:
        return _snapshot(connection.execute("SELECT * FROM setup_snapshots WHERE id=?", (str(identifier),)).fetchone())


def list_snapshots(limit=20, offset=0):
    with db.get_connection() as connection:
        rows = connection.execute("SELECT * FROM setup_snapshots ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        count = connection.execute("SELECT COUNT(*) FROM setup_snapshots").fetchone()[0]
    items = []
    for row in rows:
        stored = _snapshot(row)
        snap = stored.pop("snapshot")
        items.append({**stored, "title": snap["entry"]["title"], "direction": snap["entry"]["direction"],
                      "mode": snap["mode"], "cutoff_at": snap["cutoff_at"]})
    return {"items": items, "total": count, "limit": limit, "offset": offset}


def _evaluation(row):
    if row is None:
        return None
    result = dict(row)
    raw = result.pop("result_json")
    result["result"] = json.loads(raw) if raw else None
    return result


def list_evaluations(snapshot_id):
    with db.get_connection() as connection:
        rows = connection.execute("SELECT * FROM setup_evaluations WHERE snapshot_id=? ORDER BY created_at DESC,id DESC", (str(snapshot_id),)).fetchall()
    return [_evaluation(row) for row in rows]


def begin_evaluation(snapshot_id, request_id, model, prompt_version):
    now = datetime.now(timezone.utc)
    with db.get_connection(write=True) as connection:
        # Expire before looking up an idempotency key so retrying a lost response
        # also recovers a request whose process stopped before finalization.
        connection.execute("""UPDATE setup_evaluations SET status='failed',completed_at=?,error_message=?
            WHERE snapshot_id=? AND status='pending' AND created_at<?""", (now.isoformat(),
            "The previous request was interrupted. Its evidence is still saved.", str(snapshot_id), (now-timedelta(minutes=5)).isoformat()))
        row = connection.execute("SELECT * FROM setup_evaluations WHERE request_id=?", (str(request_id),)).fetchone()
        if row:
            if row["snapshot_id"] != str(snapshot_id):
                raise SetupConflict("This AI request ID belongs to a different snapshot.")
            return _evaluation(row), False
        if connection.execute("SELECT 1 FROM setup_evaluations WHERE snapshot_id=? AND status='pending'", (str(snapshot_id),)).fetchone():
            raise SetupConflict("An assessment for this snapshot is already running. Reopen it shortly.")
        identifier = str(uuid4())
        connection.execute("""INSERT INTO setup_evaluations
            (id,snapshot_id,request_id,status,created_at,requested_model,prompt_version,schema_version)
            VALUES (?,?,?,'pending',?,?,?,1)""", (identifier,str(snapshot_id),str(request_id),now.isoformat(),model,prompt_version))
        return _evaluation(connection.execute("SELECT * FROM setup_evaluations WHERE id=?", (identifier,)).fetchone()), True


def finish_evaluation(identifier, *, result=None, error=None, provider_model=None, response_id=None):
    with db.get_connection(write=True) as connection:
        connection.execute("""UPDATE setup_evaluations SET status=?,completed_at=?,result_json=?,error_message=?,
            provider_model=?,provider_response_id=? WHERE id=? AND status='pending'""", (
            "failed" if error else "completed",datetime.now(timezone.utc).isoformat(),canonical(result) if result else None,
            error,provider_model,response_id,str(identifier)))
        return _evaluation(connection.execute("SELECT * FROM setup_evaluations WHERE id=?", (str(identifier),)).fetchone())


def _preview(row):
    if row is None or row["expires_at"] <= datetime.now(timezone.utc).isoformat():
        raise SetupConflict("This chart preview is no longer available. Reload the chart; your draft zones can be kept.")
    return {**_snapshot(row), "expires_at": row["expires_at"], "selection": json.loads(row["request_json"])}


def find_preview_request(request_id, request):
    with db.get_connection() as connection:
        row = connection.execute("SELECT * FROM setup_previews WHERE request_id=?", (str(request_id),)).fetchone()
    if row is None:
        return None
    if row["request_json"] != canonical(request):
        raise SetupConflict("This preview request ID belongs to different time settings.")
    return _preview(row)


def store_preview(request_id, request, snapshot):
    now = datetime.now(timezone.utc)
    raw = canonical(snapshot)
    with db.get_connection(write=True) as connection:
        row = connection.execute("SELECT * FROM setup_previews WHERE request_id=?", (str(request_id),)).fetchone()
        if row:
            if row["request_json"] != canonical(request):
                raise SetupConflict("This preview request ID belongs to different time settings.")
            return _preview(row)
        # Temporary market evidence only; captured setups never depend on this table.
        connection.execute("DELETE FROM setup_previews WHERE expires_at<=?", (now.isoformat(),))
        connection.execute("DELETE FROM setup_previews WHERE id IN (SELECT id FROM setup_previews ORDER BY created_at DESC,id DESC LIMIT -1 OFFSET 49)")
        identifier = str(uuid4())
        connection.execute("INSERT INTO setup_previews VALUES (?,?,?,?,?,?,?)", (identifier, str(request_id),
            canonical(request), raw, hashlib.sha256(raw.encode()).hexdigest(), now.isoformat(),
            (now+timedelta(hours=24)).isoformat()))
        return _preview(connection.execute("SELECT * FROM setup_previews WHERE id=?", (identifier,)).fetchone())


def fetch_preview(identifier):
    with db.get_connection() as connection:
        return _preview(connection.execute("SELECT * FROM setup_previews WHERE id=?", (str(identifier),)).fetchone())
