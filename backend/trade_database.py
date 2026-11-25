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
        if not con.execute('SELECT 1 FROM trade_schema_migrations WHERE version=1').fetchone():
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
        if not con.execute('SELECT 1 FROM trade_schema_migrations WHERE version=2').fetchone():
            con.execute("""CREATE TABLE trade_strategy_analyses (
                id TEXT PRIMARY KEY, trade_id TEXT NOT NULL REFERENCES trades(id) ON DELETE RESTRICT,
                source TEXT NOT NULL CHECK (source IN ('saved_setup','entry_time')), request_id TEXT UNIQUE,
                analysis_json TEXT NOT NULL, analysis_hash TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(trade_id,source))""")
            for action in ('UPDATE','DELETE'):
                con.execute(f"""CREATE TRIGGER trade_strategy_analyses_no_{action.lower()}
                    BEFORE {action} ON trade_strategy_analyses BEGIN
                    SELECT RAISE(ABORT,'Trade strategy evidence is immutable'); END""")
            con.execute('INSERT INTO trade_schema_migrations VALUES (2,?)',(datetime.now(timezone.utc).isoformat(),))

        if not con.execute('SELECT 1 FROM trade_schema_migrations WHERE version=3').fetchone():
            con.execute('CREATE TABLE trade_deletions (trade_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, deleted_at TEXT NOT NULL)')
            for table in ('trades','trade_exits','trade_reviews','trade_strategy_analyses'):
                con.execute(f'DROP TRIGGER {table}_no_delete')
                key = 'OLD.id' if table == 'trades' else 'OLD.trade_id'
                con.execute(f"""CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
                    WHEN NOT EXISTS (SELECT 1 FROM trade_deletions WHERE trade_id={key})
                    BEGIN SELECT RAISE(ABORT,'Use explicit trade deletion'); END""")
            con.execute("""CREATE TRIGGER trades_no_recreate BEFORE INSERT ON trades
                WHEN EXISTS (SELECT 1 FROM trade_deletions WHERE trade_id=NEW.id OR request_id=NEW.request_id)
                BEGIN SELECT RAISE(ABORT,'Deleted trade request cannot be reused'); END""")
            for action in ('UPDATE','DELETE'):
                con.execute(f"""CREATE TRIGGER trade_deletions_no_{action.lower()} BEFORE {action} ON trade_deletions
                    BEGIN SELECT RAISE(ABORT,'Deletion identifiers are fixed'); END""")
            con.execute('INSERT INTO trade_schema_migrations VALUES (3,?)',(datetime.now(timezone.utc).isoformat(),))

        if not con.execute('SELECT 1 FROM trade_schema_migrations WHERE version=4').fetchone():
            con.execute("""CREATE TABLE trade_score_snapshots (
                trade_id TEXT PRIMARY KEY REFERENCES trades(id) ON DELETE RESTRICT,
                entry_analysis_id TEXT NOT NULL REFERENCES trade_strategy_analyses(id) ON DELETE RESTRICT,
                exit_hash TEXT NOT NULL, score_json TEXT NOT NULL, score_hash TEXT NOT NULL, created_at TEXT NOT NULL)""")
            con.execute("""CREATE TRIGGER trade_score_snapshots_no_update BEFORE UPDATE ON trade_score_snapshots
                BEGIN SELECT RAISE(ABORT,'Closed trade scores are fixed'); END""")
            con.execute("""CREATE TRIGGER trade_score_snapshots_no_delete BEFORE DELETE ON trade_score_snapshots
                WHEN NOT EXISTS (SELECT 1 FROM trade_deletions WHERE trade_id=OLD.trade_id)
                BEGIN SELECT RAISE(ABORT,'Use explicit trade deletion'); END""")
            con.execute('INSERT INTO trade_schema_migrations VALUES (4,?)',(datetime.now(timezone.utc).isoformat(),))

        from trade_coach_database import migrate
        migrate(con)
        from trade_edits import migrate as migrate_edits
        migrate_edits(con)


def delete_trade(identifier):
    """Explicit, atomic removal; retain only retry IDs to prevent resurrection."""
    identifier = str(identifier)
    with db.get_connection(write=True) as con:
        row = con.execute('SELECT request_id FROM trades WHERE id=?',(identifier,)).fetchone()
        if row is None:
            if con.execute('SELECT 1 FROM trade_deletions WHERE trade_id=?',(identifier,)).fetchone(): return
            raise TradeNotFound('Trade not found.')
        con.execute('INSERT INTO trade_deletions VALUES (?,?,?)',(identifier,row['request_id'],datetime.now(timezone.utc).isoformat()))
        for table in ('edited_trade_scores','edited_trade_analyses'):
            con.execute(f'DELETE FROM {table} WHERE trade_id IN (SELECT id FROM trade_edits WHERE trade_id=?)',(identifier,))
        for table in ('trade_edits','trade_coach_reviews','trade_score_snapshots','trade_strategy_analyses','trade_reviews','trade_exits'):
            con.execute(f'DELETE FROM {table} WHERE trade_id=?',(identifier,))
        con.execute('DELETE FROM trades WHERE id=?',(identifier,))



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
    from trade_edits import apply_latest
    apply_latest(con, record, context, detail)
    if detail: record.update(context=context, reviews=history, strategy_analyses=_analyses(con,record))
    return record


def create_trade(entry):
    now=datetime.now(timezone.utc)
    values=entry.model_dump(mode='json',exclude={'request_id'})
    values['entry_at']=utc(entry.entry_at)
    request=sd.canonical(values)
    with db.get_connection(write=True) as con:
        if con.execute('SELECT 1 FROM trade_deletions WHERE request_id=?',(str(entry.request_id),)).fetchone():
            raise TradeConflict('This trade was deleted. Start a new entry with a new save request.')
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
        record = _record(con,identifier)
        if source is not None:
            from trade_analysis import build_analysis
            analysis = build_analysis(values, source['snapshot'], 'saved_setup', record['evidence_hash'], context['timing'])
            _store_analysis(con, identifier, 'saved_setup', analysis)
        return _record(con,identifier)


def close_trade(identifier, entry):
    now=datetime.now(timezone.utc)
    values=entry.model_dump(mode='json',exclude={'request_id','expected_revision'}); values['exit_at']=utc(entry.exit_at)
    request=sd.canonical(values)
    with db.get_connection(write=True) as con:
        record=_record(con,identifier)
        found=con.execute('SELECT * FROM trade_exits WHERE request_id=?',(str(entry.request_id),)).fetchone()
        if found:
            if found['trade_id']!=str(identifier) or found['request_json']!=request:
                raise TradeConflict('This exit request belongs to different inputs.')
            return record
        if record['status']=='closed': raise TradeConflict('This trade already has a full exit. Reopen it to see the saved result.')
        if entry.expected_revision is not None and entry.expected_revision != record['revision']:
            raise TradeConflict('The entry changed. Reopen the trade before recording its exit.')
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
        rows=con.execute('SELECT t.id'+source+' ORDER BY COALESCE((SELECT entry_at FROM trade_edits WHERE trade_id=t.id ORDER BY revision DESC LIMIT 1),t.entry_at) DESC,t.id DESC LIMIT ? OFFSET ?',(limit,offset)).fetchall()
        return {'items':[_record(con,row['id'],detail=False) for row in rows], 'total':total,'limit':limit,'offset':offset}


def _analyses(con, trade_row):
    table = 'edited_trade_analyses' if trade_row['edit_id'] else 'trade_strategy_analyses'
    rows=con.execute(f'SELECT * FROM {table} WHERE trade_id=? ORDER BY created_at,id',(trade_row['edit_id'] or trade_row['id'],)).fetchall()
    results=[]
    for row in rows:
        payload=json.loads(row['analysis_json'])
        if (hashlib.sha256(sd.canonical(payload).encode()).hexdigest()!=row['analysis_hash'] or
                payload['entry_evidence_hash']!=trade_row['evidence_hash'] or payload['source']!=row['source']):
            raise TradeConflict('The saved strategy comparison failed its integrity check.')
        results.append({'id':row['id'],'source':row['source'],'created_at':row['created_at'],
                        'analysis_hash':row['analysis_hash'],'analysis':payload})
    return results


def _store_analysis(con, identifier, source, payload, request_id=None, *, edit_id=None):
    encoded=sd.canonical(payload)
    table = 'edited_trade_analyses' if edit_id else 'trade_strategy_analyses'
    con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?,?,?)',
        (str(uuid4()),edit_id or str(identifier),source,str(request_id) if request_id else None,encoded,
         hashlib.sha256(encoded.encode()).hexdigest(),datetime.now(timezone.utc).isoformat()))


def _analysis_exists(con, record, entry):
    key = record['edit_id'] or record['id']
    found = con.execute("""SELECT trade_id,source FROM trade_strategy_analyses WHERE request_id=?
                           UNION ALL SELECT trade_id,source FROM edited_trade_analyses WHERE request_id=?""",
                        (str(entry.request_id),str(entry.request_id))).fetchone()
    if found and (found['trade_id'] != key or found['source']!=entry.source):
        raise TradeConflict('This comparison request belongs to another trade version or evidence source.')
    return any(item['source']==entry.source for item in record['strategy_analyses'])


def analyze_trade(identifier, entry):
    from trade_analysis import build_analysis, reconstruct_entry
    # Release the read transaction before a historical provider request.
    with db.get_connection() as con:
        record=_record(con,identifier)
        if _analysis_exists(con,record,entry): return record
    if entry.source=='saved_setup':
        source=record['context']['setup']
        if source is None: raise TradeInputError('This trade has no saved setup evidence. Reconstruct evidence at entry instead.')
        snapshot=source['snapshot']; timing=record['context']['timing']
    else:
        snapshot=reconstruct_entry(record['entry']); timing='retrospective'
    revision = record['revision']
    analysis=build_analysis(record['entry'],snapshot,entry.source,record['evidence_hash'],timing)
    with db.get_connection(write=True) as con:
        record=_record(con,identifier)
        if record['revision'] != revision:
            raise TradeConflict('The trade was edited during analysis. Refresh the trade.')
        if _analysis_exists(con,record,entry): return record
        _store_analysis(con,identifier,entry.source,analysis,entry.request_id,edit_id=record['edit_id'])
        return _record(con,identifier)


def _score_snapshot(con, identifier, record, saved):
    table = 'edited_trade_scores' if record['edit_id'] else 'trade_score_snapshots'
    row = con.execute(f'SELECT * FROM {table} WHERE trade_id=?',(record['edit_id'] or str(identifier),)).fetchone()
    if row is None: return None
    value = json.loads(row['score_json'])
    if (row['score_hash'] != hashlib.sha256(sd.canonical(value).encode()).hexdigest() or
            row['exit_hash'] != hashlib.sha256(sd.canonical(record['exit']).encode()).hexdigest() or
            row['entry_analysis_id'] != saved['id'] or value['entry_analysis_hash'] != saved['analysis_hash'] or
            value['entry_evidence_hash'] != record['evidence_hash']):
        raise TradeConflict('The saved trade scores failed their integrity check.')
    return {**value,'saved_at':row['created_at']}


def fetch_score_snapshot(identifier, record, saved):
    with db.get_connection() as con:
        latest = _record(con,identifier)
        if latest['revision'] != record['revision'] or latest['exit'] != record['exit']: return None
        return _score_snapshot(con,identifier,latest,saved)


def finish_scores(identifier, original, saved, value):
    with db.get_connection(write=True) as con:
        latest = _record(con,identifier)
        if latest['revision'] != original['revision'] or latest['exit'] != original['exit']: return None
        cached = _score_snapshot(con,identifier,latest,saved)
        if cached is not None: return cached
        if latest['status']=='open': return {**value,'saved_at':None}
        _store_final_score(con, latest, saved, value)
        return _score_snapshot(con,identifier,latest,saved)


def _store_final_score(con, record, saved, value):
    table = 'edited_trade_scores' if record['edit_id'] else 'trade_score_snapshots'
    encoded = sd.canonical(value)
    exit_hash = hashlib.sha256(sd.canonical(record['exit']).encode()).hexdigest()
    score_hash = hashlib.sha256(encoded.encode()).hexdigest()
    con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?,?)',
                (record['edit_id'] or record['id'], saved['id'], exit_hash, encoded,
                 score_hash, datetime.now(timezone.utc).isoformat()))
