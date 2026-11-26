"""Append-only corrections. Saved analyses and final scores belong to one trade version."""
import json
from datetime import datetime, timezone
from uuid import uuid4

import database as db
import trade_database as trades
from setup_database import canonical
from trade_calculations import TradeInputError, entry_context, past_time, trade_outcome, utc, validate_entry_zone_times


def migrate(con):
    if con.execute('SELECT 1 FROM trade_schema_migrations WHERE version=6').fetchone():
        return
    con.execute('''CREATE TABLE trade_edits (
        id TEXT PRIMARY KEY, trade_id TEXT NOT NULL REFERENCES trades(id), revision INTEGER NOT NULL,
        request_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL, entry_json TEXT NOT NULL,
        exit_json TEXT, entry_at TEXT NOT NULL, timing TEXT NOT NULL, evidence_hash TEXT NOT NULL,
        changes_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(trade_id,revision))''')
    # Same storage format as revision zero. Each foreign key here identifies an edit.
    con.execute('''CREATE TABLE edited_trade_analyses (
        id TEXT PRIMARY KEY, trade_id TEXT NOT NULL REFERENCES trade_edits(id),
        source TEXT NOT NULL, request_id TEXT UNIQUE, analysis_json TEXT NOT NULL,
        analysis_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(trade_id,source))''')
    con.execute('''CREATE TABLE edited_trade_scores (
        trade_id TEXT PRIMARY KEY REFERENCES trade_edits(id),
        entry_analysis_id TEXT NOT NULL REFERENCES edited_trade_analyses(id),
        exit_hash TEXT NOT NULL, score_json TEXT NOT NULL, score_hash TEXT NOT NULL, created_at TEXT NOT NULL)''')
    for table in ('trade_edits','edited_trade_analyses','edited_trade_scores'):
        owner = 'OLD.trade_id' if table=='trade_edits' else '(SELECT trade_id FROM trade_edits WHERE id=OLD.trade_id)'
        con.execute(f"""CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table}
                        BEGIN SELECT RAISE(ABORT,'Trade revisions are immutable'); END""")
        con.execute(f"""CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
                        WHEN NOT EXISTS (SELECT 1 FROM trade_deletions WHERE trade_id={owner})
                        BEGIN SELECT RAISE(ABORT,'Use explicit trade deletion'); END""")
    con.execute('INSERT INTO trade_schema_migrations VALUES (6,?)',(datetime.now(timezone.utc).isoformat(),))


def apply_latest(con, record, context, detail):
    row = con.execute('SELECT * FROM trade_edits WHERE trade_id=? ORDER BY revision DESC LIMIT 1',
                      (record['id'],)).fetchone()
    record.update(revision=0, edit_id=None, original_evidence_hash=record['evidence_hash'])
    if detail:
        record['edits'] = []
    if row is None:
        return
    entry = json.loads(row['entry_json'])
    context['timing'] = row['timing']
    if trades._hash(entry,context) != row['evidence_hash']:
        raise trades.TradeConflict('The corrected trade evidence failed its integrity check.')
    exit_values = json.loads(row['exit_json']) if row['exit_json'] else record['exit']
    record.update(entry=entry, exit=exit_values, context_timing=row['timing'], evidence_hash=row['evidence_hash'],
                  revision=row['revision'], edit_id=row['id'], edited_at=row['created_at'],
                  result=trade_outcome(entry,exit_values) if exit_values else None)
    if detail:
        history = con.execute('SELECT revision,created_at,changes_json,evidence_hash FROM trade_edits WHERE trade_id=? ORDER BY revision DESC',
                              (record['id'],))
        record['edits'] = [dict(revision=r['revision'],at=r['created_at'],changes=json.loads(r['changes_json']),
                                evidence_hash=r['evidence_hash']) for r in history]


def save_edit(identifier, edit):
    now = datetime.now(timezone.utc)
    trade_id = str(identifier)
    request = canonical(edit.model_dump(mode='json',exclude={'request_id'}))
    with db.get_connection(write=True) as con:
        record = trades._record(con,trade_id)
        previous = con.execute('SELECT trade_id,request_json FROM trade_edits WHERE request_id=?',
                               (str(edit.request_id),)).fetchone()
        if previous:
            if previous['trade_id'] != trade_id or previous['request_json'] != request:
                raise trades.TradeConflict('This edit request already belongs to different trade details.')
            return record
        if edit.expected_revision != record['revision'] or bool(edit.exit) != bool(record['exit']):
            raise trades.TradeConflict('The trade changed while you were editing. Reopen it to load the latest details.')
        past_time(edit.entry.entry_at,'Entry time',now)
        entry = edit.entry.model_dump(mode='json')
        entry.update(entry_at=utc(edit.entry.entry_at),setup_id=record['entry']['setup_id'])
        exit_values = None
        if edit.exit:
            past_time(edit.exit.exit_at,'Exit time',now)
            if edit.exit.exit_at < edit.entry.entry_at:
                raise TradeInputError('Exit time cannot be before entry time.')
            exit_values = edit.exit.model_dump(mode='json')
            exit_values['exit_at'] = utc(edit.exit.exit_at)
        changes = {key:{'before':old.get(key),'after':value}
                   for old,new in [(record['entry'],entry),(record['exit'] or {},exit_values or {})]
                   for key,value in new.items() if old.get(key)!=value}
        if not changes:
            raise TradeInputError('No trade details changed.')
        source = record['context']['setup']
        context = dict(record['context'])
        if 'entry_at' in changes:
            validate_entry_zone_times(context.get('entry_zones', []), edit.entry.entry_at)
            if source:
                context['timing'] = entry_context(edit.entry,source,now)['timing']
        evidence_hash = trades._hash(entry,context)
        edit_id = str(uuid4())
        con.execute('INSERT INTO trade_edits VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (edit_id,trade_id,record['revision']+1,str(edit.request_id),request,canonical(entry),
                     canonical(exit_values) if exit_values else None,entry['entry_at'],context['timing'],
                     evidence_hash,canonical(changes),now.isoformat()))
        con.execute("""UPDATE trade_coach_reviews SET status='failed',updated_at=?,error_message=?
                       WHERE trade_id=? AND status IN ('capturing','pending')""",
                    (now.isoformat(),'The trade was edited during this review. Request a review of the corrected trade.',trade_id))
        # Reuse the original market observation if the cutoff did not move.
        from trade_analysis import build_analysis
        for prior in record['strategy_analyses']:
            source_kind = prior['source']
            if source_kind == 'entry_time' and 'entry_at' in changes:
                continue
            snapshot = source['snapshot'] if source_kind=='saved_setup' else prior['analysis']['reconstructed_snapshot']
            timing = context['timing'] if source_kind=='saved_setup' else 'retrospective'
            analysis = build_analysis(entry,snapshot,source_kind,evidence_hash,timing)
            trades._store_analysis(con,trade_id,source_kind,analysis,edit_id=edit_id)
        corrected = trades._record(con,trade_id)
        if exit_values and 'entry_at' not in changes and 'exit_at' not in changes:
            _retain_period_scores(con, record, corrected)
        return corrected


def _retain_period_scores(con, previous, corrected):
    """The trade period is identical. Reinterpret its frozen market scores for the corrected direction."""
    from trade_scores import directional_summary, entry_score
    prior = next((a for a in previous['strategy_analyses'] if a['source'] == 'entry_time'), None)
    if prior is None:
        return
    value = trades._score_snapshot(con, previous['id'], previous, prior)
    if value is None:
        return
    value.pop('saved_at')
    current = next(a for a in corrected['strategy_analyses'] if a['source'] == 'entry_time')
    direction = corrected['entry']['direction']
    value.update(trade_revision=corrected['revision'], trade_direction=direction,
                 entry_analysis_id=current['id'], entry_analysis_hash=current['analysis_hash'],
                 entry_evidence_hash=corrected['evidence_hash'], entry_score=entry_score(corrected, current))
    value['full_trade']['summary'] = directional_summary(value['full_trade']['summary'], direction)
    trades._store_final_score(con, corrected, current, value)
