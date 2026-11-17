"""Immutable entries/exits and append-only self-reviews; independent setup copies."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4
import database as db
import setup_database as sd
from trade_calculations import entry_context, past_time, utc, trade_outcome, TradeInputError


class TradeConflict(ValueError):
    pass


class TradeNotFound(ValueError):
    pass


def init_trade_db():
    with db.get_connection(write=True) as con:
        con.execute('CREATE TABLE IF NOT EXISTS trade_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
        if con.execute('SELECT 1 FROM trade_schema_migrations WHERE version=1').fetchone():
            return
        con.execute('''CREATE TABLE trades (
            id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL,
            entry_json TEXT NOT NULL, context_json TEXT NOT NULL, evidence_hash TEXT NOT NULL,
            entry_at TEXT NOT NULL, created_at TEXT NOT NULL)''')
        con.execute('''CREATE TABLE trade_exits (
            trade_id TEXT PRIMARY KEY REFERENCES trades(id) ON DELETE RESTRICT,
            request_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL, exit_json TEXT NOT NULL,
            result_json TEXT NOT NULL, created_at TEXT NOT NULL)''')
        con.execute('''CREATE TABLE trade_reviews (
            id TEXT PRIMARY KEY, trade_id TEXT NOT NULL REFERENCES trades(id) ON DELETE RESTRICT,
            request_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL,
            review_json TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(trade_id,revision))''')
        con.execute('CREATE INDEX trades_by_entry ON trades(entry_at DESC,id DESC)')
        for table in ('trades','trade_exits','trade_reviews'):
            for action in ('UPDATE','DELETE'):
                con.execute(f'''CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table}
                    BEGIN SELECT RAISE(ABORT,'Trade records are fixed; reviews are appended'); END''')
        con.execute('INSERT INTO trade_schema_migrations VALUES (1,?)',(datetime.now(timezone.utc).isoformat(),))


def _hash(entry, context):
    return hashlib.sha256(sd.canonical({'entry':entry,'context':context}).encode()).hexdigest()


def _record(con, identifier, *, detail=True):
    row=con.execute('SELECT * FROM trades WHERE id=?',(str(identifier),)).fetchone()
    if row is None:
        raise TradeNotFound('Trade not found.')
    entry,context=json.loads(row['entry_json']),json.loads(row['context_json'])
    if _hash(entry,context)!=row['evidence_hash']:
        raise TradeConflict('The saved trade evidence failed its integrity check.')
    closed=con.execute('SELECT * FROM trade_exits WHERE trade_id=?',(row['id'],)).fetchone()
    reviews=con.execute('SELECT review_json,revision,created_at FROM trade_reviews WHERE trade_id=? ORDER BY revision DESC',(row['id'],)).fetchall()
    history=[{**json.loads(r['review_json']),'revision':r['revision'],'recorded_at':r['created_at']} for r in reviews]
    record={'id':row['id'],'entry':entry,'created_at':row['created_at'],
        'status':'closed' if closed else 'open','exit':json.loads(closed['exit_json']) if closed else None,
        'result':json.loads(closed['result_json']) if closed else None,
        'review':history[0] if history else {'discipline':'not_reviewed','notes':'','revision':0},
        'context_timing':context['timing'], 'evidence_hash':row['evidence_hash']}
    if detail: record.update(context=context, reviews=history)
    return record


def create_trade(entry):
    now=datetime.now(timezone.utc)
    values=entry.model_dump(mode='json',exclude={'request_id'})
    values['entry_at']=utc(entry.entry_at)
    request=sd.canonical(values)
    with db.get_connection(write=True) as con:
        found=con.execute('SELECT id,request_json FROM trades WHERE request_id=?',(str(entry.request_id),)).fetchone()
        if found:
            if found['request_json']!=request: raise TradeConflict('This save request belongs to different trade inputs.')
            return _record(con,found['id'])
        past_time(entry.entry_at,'Entry time',now)
        source=None
        if entry.setup_id is not None:
            # Read and copy within the same transaction that serializes setup deletion.
            row=con.execute('SELECT * FROM setup_snapshots WHERE id=?',(str(entry.setup_id),)).fetchone()
            if row is None: raise TradeNotFound('The linked setup no longer exists. Choose another setup or record a manual trade.')
            try: source=sd._snapshot(row)
            except sd.SetupConflict as exc: raise TradeConflict(str(exc)) from None
        context=entry_context(entry,source,now)
        identifier=str(uuid4())
        con.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?,?)',(identifier,str(entry.request_id),request,
            sd.canonical(values),sd.canonical(context),_hash(values,context),values['entry_at'],now.isoformat()))
        return _record(con,identifier)


def close_trade(identifier, entry):
    now=datetime.now(timezone.utc)
    values=entry.model_dump(mode='json',exclude={'request_id'}); values['exit_at']=utc(entry.exit_at)
    request=sd.canonical(values)
    with db.get_connection(write=True) as con:
        record=_record(con,identifier)
        found=con.execute('SELECT * FROM trade_exits WHERE request_id=?',(str(entry.request_id),)).fetchone()
        if found:
            if found['trade_id']!=str(identifier) or found['request_json']!=request:
                raise TradeConflict('This exit request belongs to different inputs.')
            return record
        if record['status']=='closed': raise TradeConflict('This trade already has a full exit. Reopen it to see the saved result.')
        past_time(entry.exit_at,'Exit time',now)
        if entry.exit_at < datetime.fromisoformat(record['entry']['entry_at']):
            raise TradeInputError('Exit time cannot be before entry time.')
        result=trade_outcome(record['entry'],values)
        con.execute('INSERT INTO trade_exits VALUES (?,?,?,?,?,?)',(str(identifier),str(entry.request_id),request,
            sd.canonical(values),sd.canonical(result),now.isoformat()))
        return _record(con,identifier)


def review_trade(identifier, entry):
    values=entry.model_dump(mode='json',exclude={'request_id'})
    request=sd.canonical(values)
    with db.get_connection(write=True) as con:
        record=_record(con,identifier)
        found=con.execute('SELECT trade_id,request_json FROM trade_reviews WHERE request_id=?',(str(entry.request_id),)).fetchone()
        if found:
            if found['trade_id']!=str(identifier) or found['request_json']!=request:
                raise TradeConflict('This review request belongs to different inputs.')
            return record
        if entry.expected_revision!=record['review']['revision']:
            raise TradeConflict('A newer self-review was saved. Reopen this trade before changing its review.')
        review={'discipline':entry.discipline,'notes':entry.notes}
        con.execute('INSERT INTO trade_reviews VALUES (?,?,?,?,?,?,?)',(str(uuid4()),str(identifier),str(entry.request_id),request,
            sd.canonical(review),entry.expected_revision+1,datetime.now(timezone.utc).isoformat()))
        return _record(con,identifier)


def fetch_trade(identifier):
    with db.get_connection() as con: return _record(con,identifier)


def list_trades(status='all',limit=20,offset=0):
    clause={'all':'','open':' WHERE e.trade_id IS NULL','closed':' WHERE e.trade_id IS NOT NULL'}[status]
    source=' FROM trades t LEFT JOIN trade_exits e ON e.trade_id=t.id'+clause
    with db.get_connection() as con:
        total=con.execute('SELECT COUNT(*)'+source).fetchone()[0]
        rows=con.execute('SELECT t.id'+source+' ORDER BY t.entry_at DESC,t.id DESC LIMIT ? OFFSET ?',(limit,offset)).fetchall()
        return {'items':[_record(con,row['id'],detail=False) for row in rows], 'total':total,'limit':limit,'offset':offset}
