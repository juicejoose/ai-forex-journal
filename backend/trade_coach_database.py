"""Idempotent manual coach requests with frozen evidence and immutable final reviews."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4
import database as db
import trade_database as trades
from setup_database import canonical


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def migrate(con):
    if con.execute('SELECT 1 FROM trade_schema_migrations WHERE version=5').fetchone(): return
    con.execute('''CREATE TABLE trade_coach_reviews (
        id TEXT PRIMARY KEY, trade_id TEXT NOT NULL REFERENCES trades(id) ON DELETE RESTRICT,
        request_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('capturing','pending','completed','failed')),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, requested_model TEXT NOT NULL, prompt_version TEXT NOT NULL,
        snapshot_json TEXT, snapshot_hash TEXT, result_json TEXT, result_hash TEXT, error_message TEXT,
        provider_model TEXT, provider_response_id TEXT,
        CHECK((snapshot_json IS NULL) = (snapshot_hash IS NULL)),
        CHECK((result_json IS NULL) = (result_hash IS NULL)),
        CHECK(status NOT IN ('pending','completed') OR snapshot_json IS NOT NULL),
        CHECK((status='completed') = (result_json IS NOT NULL)))''')
    con.execute("CREATE UNIQUE INDEX trade_coach_running ON trade_coach_reviews(trade_id) WHERE status IN ('capturing','pending')")
    con.execute('CREATE INDEX trade_coach_history ON trade_coach_reviews(trade_id,created_at DESC,id DESC)')
    con.execute('''CREATE TRIGGER trade_coach_fixed BEFORE UPDATE ON trade_coach_reviews
        WHEN OLD.status IN ('completed','failed') OR NEW.id IS NOT OLD.id OR NEW.trade_id IS NOT OLD.trade_id
        OR NEW.request_id IS NOT OLD.request_id OR NEW.request_json IS NOT OLD.request_json
        OR NEW.created_at IS NOT OLD.created_at OR NEW.requested_model IS NOT OLD.requested_model
        OR NEW.prompt_version IS NOT OLD.prompt_version
        OR (OLD.snapshot_json IS NOT NULL AND (NEW.snapshot_json IS NOT OLD.snapshot_json OR NEW.snapshot_hash IS NOT OLD.snapshot_hash))
        OR NOT ((OLD.status='capturing' AND NEW.status IN ('pending','failed')) OR (OLD.status='pending' AND NEW.status IN ('completed','failed')))
        BEGIN SELECT RAISE(ABORT,'Coach evidence and final reviews are fixed'); END''')
    con.execute('''CREATE TRIGGER trade_coach_no_delete BEFORE DELETE ON trade_coach_reviews
        WHEN NOT EXISTS (SELECT 1 FROM trade_deletions WHERE trade_id=OLD.trade_id)
        BEGIN SELECT RAISE(ABORT,'Use explicit trade deletion'); END''')
    con.execute('INSERT INTO trade_schema_migrations VALUES (5,?)',(datetime.now(timezone.utc).isoformat(),))


def _read(row, record, detail=True):
    if row is None: raise trades.TradeNotFound('Coach review not found.')
    snap = json.loads(row['snapshot_json']) if row['snapshot_json'] else None
    result = json.loads(row['result_json']) if row['result_json'] else None
    saved_revision = snap.get('trade_revision',0) if snap else None
    hashes = {0:record['original_evidence_hash'], **{edit['revision']:edit['evidence_hash'] for edit in record['edits']}}
    if (snap is not None and (digest(snap) != row['snapshot_hash'] or snap['trade_id'] != record['id'] or
                              snap['entry_evidence_hash'] != hashes.get(saved_revision))) or (result is not None and digest(result) != row['result_hash']):
        raise trades.TradeConflict('The saved coach evidence failed its integrity check.')
    value = {k: row[k] for k in ('id','trade_id','request_id','status','created_at','updated_at','requested_model','prompt_version','provider_model','snapshot_hash','error_message')}
    value.update(result=result, cutoff_at=snap['cutoff_at'] if snap else None,
                 data_through=snap['data_through'] if snap else None,
                 direction=snap['trade']['direction'] if snap else record['entry']['direction'], trade_revision=saved_revision)
    if detail: value.update(snapshot=snap,inputs=json.loads(row['request_json']))
    return value


def _row(con, identifier):
    row = con.execute('SELECT * FROM trade_coach_reviews WHERE id=?',(str(identifier),)).fetchone()
    if row is None: raise trades.TradeNotFound('Coach review no longer exists.')
    return row


def reserve(trade_id, request, model, prompt):
    values = request.model_dump(mode='json',exclude={'request_id'})
    now = datetime.now(timezone.utc)
    with db.get_connection(write=True) as con:
        record = trades._record(con,trade_id)
        found = con.execute('SELECT * FROM trade_coach_reviews WHERE request_id=?',(str(request.request_id),)).fetchone()
        if found:
            if found['trade_id'] != str(trade_id) or found['request_json'] != canonical(values):
                raise trades.TradeConflict('This coach request belongs to different inputs or a different trade.')
            return _read(found,record),False
        if record['status'] != 'open': raise trades.TradeConflict('New coach reviews are available only while a trade is open.')
        con.execute("UPDATE trade_coach_reviews SET status='failed',updated_at=?,error_message=? WHERE trade_id=? AND status IN ('capturing','pending') AND created_at<?",
                    (now.isoformat(),'This interrupted review expired. Start a new review.',str(trade_id),(now-timedelta(minutes=5)).isoformat()))
        if con.execute("SELECT 1 FROM trade_coach_reviews WHERE trade_id=? AND status IN ('capturing','pending')",(str(trade_id),)).fetchone():
            raise trades.TradeConflict('A coach review is already running. Reload its history; an interrupted request expires after five minutes.')
        identifier = str(uuid4())
        con.execute('''INSERT INTO trade_coach_reviews
            (id,trade_id,request_id,request_json,status,created_at,updated_at,requested_model,prompt_version)
            VALUES (?,?,?,?,'capturing',?,?,?,?)''',
            (identifier,str(trade_id),str(request.request_id),canonical(values),now.isoformat(),now.isoformat(),model,prompt))
        return _read(_row(con,identifier),record),True


def freeze(identifier,snapshot):
    with db.get_connection(write=True) as con:
        row = _row(con,identifier); record = trades._record(con,row['trade_id'])
        if row['status'] != 'capturing': raise trades.TradeConflict('This review is no longer capturing evidence. Reload its history.')
        if record['status'] != 'open': raise trades.TradeConflict('The trade closed during capture. Start no further open-trade analysis.')
        if snapshot.get('trade_revision',0) != record['revision'] or snapshot['entry_evidence_hash'] != record['evidence_hash']: raise trades.TradeConflict('The trade evidence changed.')
        con.execute("UPDATE trade_coach_reviews SET status='pending',snapshot_json=?,snapshot_hash=?,updated_at=? WHERE id=?",
                    (canonical(snapshot),digest(snapshot),datetime.now(timezone.utc).isoformat(),str(identifier)))
        return _read(_row(con,identifier),record)


def finish(identifier,*,result=None,error=None,provider_model=None,response_id=None):
    with db.get_connection(write=True) as con:
        row = _row(con,identifier); record = trades._record(con,row['trade_id'])
        if row['status'] in ('completed','failed'): return _read(row,record)
        if record['status'] != 'open': error='The trade closed during this review. Captured evidence is retained; no active-trade opinion was saved.'
        if error is None and (result is None or row['status'] != 'pending'): raise trades.TradeConflict('Coach evidence must be saved before its assessment.')
        status = 'failed' if error else 'completed'
        con.execute('''UPDATE trade_coach_reviews SET status=?,updated_at=?,result_json=?,result_hash=?,error_message=?,provider_model=?,provider_response_id=? WHERE id=?''',
                    (status,datetime.now(timezone.utc).isoformat(),canonical(result) if not error else None,
                     digest(result) if not error else None,error,provider_model,response_id,str(identifier)))
        return _read(_row(con,identifier),record)


def listing(trade_id,limit=10,offset=0):
    with db.get_connection() as con:
        record=trades._record(con,trade_id)
        rows=con.execute('SELECT * FROM trade_coach_reviews WHERE trade_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                         (str(trade_id),limit,offset)).fetchall()
        total=con.execute('SELECT count(*) FROM trade_coach_reviews WHERE trade_id=?',(str(trade_id),)).fetchone()[0]
        return {'items':[_read(row,record,False) for row in rows],'total':total,'limit':limit,'offset':offset}


def fetch(trade_id,identifier):
    with db.get_connection() as con:
        record=trades._record(con,trade_id);row=_row(con,identifier)
        if row['trade_id'] != str(trade_id): raise trades.TradeNotFound('Coach review not found for this trade.')
        return _read(row,record)
