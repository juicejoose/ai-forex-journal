"""Explicit deletion, atomic cleanup, retry safety and immutable evidence guards."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from tests.test_setup_evaluator import main, snapshot, ENVIRONMENT
from tests.test_trade_log import trade, full_exit
from trade_models import TradeInput, TradeCloseInput
import database as db
import setup_database as sd
import trade_database as td
import market_data as md


class TradeDeletionTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db,'DB_PATH',root/'test.db'))
        self.enterContext(patch.dict(os.environ,ENVIRONMENT,clear=True))
        self.client = self.enterContext(TestClient(main.app))
        self.enterContext(patch.object(main.client.responses,'create',side_effect=AssertionError('No AI call')))
        self.enterContext(patch.object(md,'_fetch_candles',side_effect=AssertionError('No market call')))

    def create(self, **overrides):
        body = trade(**overrides)
        response = self.client.post('/trades',json=body)
        self.assertEqual(response.status_code,201,response.text)
        return body,response.json()

    def test_closed_trade_cleanup_preserves_source_setup_and_other_records(self):
        source = sd.store_snapshot(uuid4(),{},snapshot())
        body,record = self.create(setup_id=source['id'])
        _,other = self.create(setup_id=source['id'])
        url = '/trades/'+record['id']
        self.assertEqual(self.client.post(url+'/close',json=full_exit()).status_code,200)
        self.assertEqual(self.client.post(url+'/reviews',json={'request_id':str(uuid4()),'expected_revision':0,'discipline':'followed','notes':'Planned.'}).status_code,200)
        self.assertEqual(self.client.post(url+'/strategy-analysis',json={'request_id':str(uuid4()),'source':'saved_setup'}).status_code,200)
        with db.get_connection() as con:
            tables=[row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'trade%' AND name NOT LIKE 'sqlite_%'")]
            before={name:[tuple(row) for row in con.execute(f'SELECT * FROM {name}')] for name in tables}
        self.assertEqual(self.client.delete(url).status_code,204)
        self.assertEqual(td.fetch_trade(other['id']),other)
        with db.get_connection() as con:
            for table in ('trade_exits','trade_reviews','trade_strategy_analyses'):
                self.assertEqual(con.execute(f'SELECT count(*) FROM {table} WHERE trade_id=?',(record['id'],)).fetchone()[0],0)
            self.assertEqual({name:[tuple(row) for row in con.execute(f'SELECT * FROM {name}')] for name in tables},before)
            deletion=dict(con.execute('SELECT * FROM trade_deletions').fetchone())
            self.assertEqual(set(deletion),{'trade_id','request_id','deleted_at'})
            self.assertEqual(deletion['request_id'],body['request_id'])
        for suffix in ('','/timeline'):
            self.assertEqual(self.client.get(url+suffix).status_code,404)
        for suffix,payload in (('/close',full_exit()),('/reviews',{'request_id':str(uuid4()),'expected_revision':0,'discipline':'followed'}),('/strategy-analysis',{'request_id':str(uuid4()),'source':'saved_setup'})):
            self.assertEqual(self.client.post(url+suffix,json=payload).status_code,404)

    def test_open_delete_retry_and_restart_prevent_delayed_save_resurrection(self):
        body,record=self.create(); url='/trades/'+record['id']
        self.assertEqual(self.client.delete(url).status_code,204)
        td.init_trade_db()
        self.assertEqual(self.client.delete(url).status_code,204)
        self.assertEqual(self.client.post('/trades',json=body).status_code,409)
        self.assertEqual(td.list_trades()['total'],0)
        self.assertEqual(self.client.delete('/trades/'+str(uuid4())).status_code,404)
        self.assertEqual(self.client.delete('/trades/invalid').status_code,422)
        self.assertEqual(self.client.post('/trades',json={**body,'request_id':str(uuid4())}).status_code,201)

    def test_failed_delete_rolls_back_children_and_retry_marker(self):
        _,record=self.create(); identifier=record['id']
        self.client.post('/trades/'+identifier+'/close',json=full_exit())
        original=deepcopy(td.fetch_trade(identifier))
        with db.get_connection(write=True) as con:
            con.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON trades BEGIN SELECT RAISE(ABORT,'rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError): td.delete_trade(identifier)
        self.assertEqual(td.fetch_trade(identifier),original)
        with db.get_connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM trade_deletions').fetchone()[0],0)

    def test_raw_mutation_guards_and_tombstone_guards_remain(self):
        _,record=self.create()
        for statement in ('DELETE FROM trades',"UPDATE trades SET evidence_hash='bad'"):
            with self.assertRaises(sqlite3.IntegrityError),db.get_connection(write=True) as con: con.execute(statement)
        td.delete_trade(record['id'])
        for statement in ('DELETE FROM trade_deletions',"UPDATE trade_deletions SET deleted_at='bad'"):
            with self.assertRaises(sqlite3.IntegrityError),db.get_connection(write=True) as con: con.execute(statement)

    def test_corrupt_entry_can_still_be_explicitly_deleted(self):
        _,record=self.create()
        with db.get_connection(write=True) as con:
            con.execute('DROP TRIGGER trades_no_update'); con.execute("UPDATE trades SET evidence_hash='bad'")
        self.assertEqual(self.client.delete('/trades/'+record['id']).status_code,204)

    def test_concurrent_retry_and_delete_cannot_resurrect_trade(self):
        body,record=self.create(); barrier=Barrier(2)
        def retry():
            barrier.wait(timeout=5)
            try: td.create_trade(TradeInput(**body))
            except td.TradeConflict: pass
        def delete():
            barrier.wait(timeout=5); td.delete_trade(record['id'])
        with ThreadPoolExecutor(2) as pool:
            tasks=[pool.submit(retry),pool.submit(delete)]
            for task in tasks: task.result(timeout=10)
        self.assertEqual(td.list_trades()['total'],0)

    def test_concurrent_close_and_delete_cannot_leave_orphans(self):
        _,record=self.create(); barrier=Barrier(2)
        def close():
            barrier.wait(timeout=5)
            try: td.close_trade(record['id'],TradeCloseInput(**full_exit()))
            except td.TradeNotFound: pass
        def delete():
            barrier.wait(timeout=5); td.delete_trade(record['id'])
        with ThreadPoolExecutor(2) as pool:
            tasks=[pool.submit(close),pool.submit(delete)]
            for task in tasks: task.result(timeout=10)
        with db.get_connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM trade_exits').fetchone()[0],0)
            self.assertEqual(list(con.execute('PRAGMA foreign_key_check')),[])

    def test_delete_during_reconstruction_or_timeline_discards_inflight_result(self):
        import trade_analysis
        import trade_timeline
        from trade_models import TradeAnalysisInput
        _,record=self.create()
        def reconstruct(entry):
            td.delete_trade(record['id'])
            evidence = snapshot()
            evidence['cutoff_at'] = entry['entry_at']
            return evidence
        with patch.object(trade_analysis,'reconstruct_entry',side_effect=reconstruct):
            with self.assertRaises(td.TradeNotFound):
                td.analyze_trade(record['id'],TradeAnalysisInput(request_id=uuid4(),source='entry_time'))
        _,second=self.create()
        def timeline(*_):
            td.delete_trade(second['id'])
            return {'unreturned':'stale view'}
        with patch.object(trade_timeline,'build_timeline',side_effect=timeline):
            with self.assertRaises(td.TradeNotFound): trade_timeline.fetch_timeline(second['id'])
        with db.get_connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM trade_strategy_analyses').fetchone()[0],0)

    def test_last_page_deletion_updates_filtered_totals_and_retains_other_entries(self):
        records=[self.create(title=f'Entry {i}')[1] for i in range(21)]
        last=td.list_trades(offset=20)['items'][0]
        td.delete_trade(last['id'])
        self.assertEqual(td.list_trades(offset=20)['items'],[])
        self.assertEqual(td.list_trades(status='open')['total'],20)
        self.assertEqual(td.list_trades(status='closed')['total'],0)
        self.assertEqual({r['id'] for r in td.list_trades()['items']},{r['id'] for r in records}-{last['id']})

    def test_v2_upgrade_preserves_records_and_enables_explicit_delete(self):
        _,record=self.create()
        # Recreate the previous schema's guards, without modifying any records.
        with db.get_connection(write=True) as con:
            con.execute('DROP TRIGGER trades_no_recreate')
            con.execute('DROP TABLE trade_deletions')
            for table in ('trades','trade_exits','trade_reviews','trade_strategy_analyses'):
                con.execute(f'DROP TRIGGER {table}_no_delete')
                con.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
            con.execute('DELETE FROM trade_schema_migrations WHERE version=3')
        td.init_trade_db(); td.init_trade_db()
        self.assertEqual(td.fetch_trade(record['id']),record)
        td.delete_trade(record['id'])
        self.assertEqual(td.list_trades()['total'],0)
