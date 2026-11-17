"""Explicit setup removal, durable retries, migration and assessment races; offline only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from tests.test_setup_evaluator import inputs, snapshot, valid_assessment, main, ENVIRONMENT
import database as db
import setup_database as sd
import setup_ai as ai


class SetupDeletionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db, 'DB_PATH', self.root/'journal.db'))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        db.init_db(); sd.init_setup_db()
        self.client = self.enterContext(TestClient(main.app))
        self.snap = snapshot()
        self.builder = self.enterContext(patch('setup_api.build_setup_snapshot', return_value=self.snap))
        self.provider = self.enterContext(patch.object(main.client.responses, 'create'))
        self.provider.return_value = SimpleNamespace(status='completed', output_text=json.dumps(valid_assessment(self.snap)), model='offline', id='offline')

    def capture(self, body=None):
        response = self.client.post('/setup-snapshots', json=body or inputs())
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def url(self, record):
        return '/setup-snapshots/'+record['id']

    def test_removes_snapshot_and_all_assessments_preserving_other_records(self):
        record = self.capture()
        other = self.capture()
        db.insert_strategy_profile('Keep this profile', 'Keep these rules')
        before_profiles = db.fetch_strategy_profiles()
        self.client.post(self.url(record)+'/evaluate', json={'request_id':str(uuid4())})
        failed, _ = sd.begin_evaluation(record['id'], uuid4(), 'offline', ai.PROMPT_VERSION)
        sd.finish_evaluation(failed['id'], error='Offline failure')
        with db.get_connection(write=True) as connection:
            connection.execute("""INSERT INTO journals (pair,journal_date,timeframe,strategy,notes,original_draft,edited_draft,created_at,updated_at)
                VALUES ('EURUSD','2026-10-20','4h','strategy','notes','draft','draft','now','now')""")
            before_journals = [tuple(row) for row in connection.execute('SELECT * FROM journals')]
        self.provider.reset_mock(); self.builder.reset_mock()
        response = self.client.delete(self.url(record))
        self.assertEqual((response.status_code,response.content),(204,b''))
        self.assertEqual(self.client.get(self.url(record)).status_code,404)
        self.assertEqual(sd.list_evaluations(record['id']),[])
        self.assertEqual(self.client.get(self.url(other)).json(),other)
        self.assertEqual(self.client.get('/setup-snapshots').json()['total'],1)
        with db.get_connection() as connection:
            self.assertEqual([tuple(row) for row in connection.execute('SELECT * FROM journals')],before_journals)
            marker=dict(connection.execute('SELECT * FROM setup_deletions').fetchone())
            self.assertEqual(set(marker),{'snapshot_id','request_id','deleted_at'})
        self.assertEqual(db.fetch_strategy_profiles(), before_profiles)
        self.provider.assert_not_called(); self.builder.assert_not_called()

    def test_retry_restart_and_delayed_capture_never_restore_deleted_evidence(self):
        body=inputs(); record=self.capture(body)
        self.assertEqual(self.client.delete(self.url(record)).status_code,204)
        sd.init_setup_db()
        self.assertEqual(self.client.delete(self.url(record)).status_code,204)
        self.builder.reset_mock()
        self.assertEqual(self.client.post('/setup-snapshots',json=body).status_code,409)
        self.builder.assert_not_called()
        with self.assertRaises(sd.SetupConflict): sd.store_snapshot(body['request_id'],{},self.snap)
        self.assertEqual(self.client.post(self.url(record)+'/evaluate',json={'request_id':str(uuid4())}).status_code,404)
        self.provider.assert_not_called()
        replacement=self.capture({**body,'request_id':str(uuid4())})
        self.assertNotEqual(replacement['id'],record['id'])

    def test_active_assessment_blocks_delete_then_completion_allows_it(self):
        record=self.capture()
        attempt,_=sd.begin_evaluation(record['id'],uuid4(),'offline',ai.PROMPT_VERSION)
        self.assertEqual(self.client.delete(self.url(record)).status_code,409)
        self.assertIsNotNone(sd.fetch_snapshot(record['id']))
        self.assertEqual(sd.list_evaluations(record['id'])[0]['status'],'pending')
        sd.finish_evaluation(attempt['id'],error='Finished')
        self.assertEqual(self.client.delete(self.url(record)).status_code,204)

    def test_interrupted_attempt_can_be_deleted_and_late_result_cannot_recreate_it(self):
        record=self.capture()
        attempt,_=sd.begin_evaluation(record['id'],uuid4(),'offline',ai.PROMPT_VERSION)
        with db.get_connection(write=True) as connection:
            connection.execute('UPDATE setup_evaluations SET created_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),attempt['id']))
        self.assertEqual(self.client.delete(self.url(record)).status_code,204)
        with self.assertRaises(sd.SetupNotFound): sd.finish_evaluation(attempt['id'],result=valid_assessment(self.snap))
        self.assertEqual(sd.list_evaluations(record['id']),[])

    def test_delete_is_atomic_even_when_final_row_removal_fails(self):
        record=self.capture()
        attempt,_=sd.begin_evaluation(record['id'],uuid4(),'offline',ai.PROMPT_VERSION)
        sd.finish_evaluation(attempt['id'],error='Finished')
        with db.get_connection(write=True) as connection:
            connection.execute("CREATE TRIGGER test_stop_delete BEFORE DELETE ON setup_snapshots BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError): sd.delete_snapshot(record['id'])
        self.assertIsNotNone(sd.fetch_snapshot(record['id']))
        self.assertEqual(len(sd.list_evaluations(record['id'])),1)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM setup_deletions').fetchone()[0],0)

    def test_missing_invalid_ids_and_deleting_corrupt_evidence(self):
        self.assertEqual(self.client.delete('/setup-snapshots/'+str(uuid4())).status_code,404)
        self.assertEqual(self.client.delete('/setup-snapshots/not-a-uuid').status_code,422)
        record=self.capture()
        with db.get_connection(write=True) as connection:
            connection.execute('DROP TRIGGER setup_snapshot_no_update')
            connection.execute("UPDATE setup_snapshots SET snapshot_hash='corrupt' WHERE id=?",(record['id'],))
        self.assertEqual(self.client.get(self.url(record)).status_code,409)
        self.assertEqual(self.client.delete(self.url(record)).status_code,204)

    def test_raw_mutations_still_blocked_and_deleted_capture_id_cannot_be_reinserted(self):
        record=self.capture()
        with db.get_connection() as connection:
            row=tuple(connection.execute('SELECT * FROM setup_snapshots').fetchone())
        for statement in ('DELETE FROM setup_snapshots',"UPDATE setup_snapshots SET snapshot_json='{}'"):
            with self.assertRaises(sqlite3.IntegrityError), db.get_connection(write=True) as connection:
                connection.execute(statement)
        sd.delete_snapshot(record['id'])
        for statement in ('DELETE FROM setup_deletions',"UPDATE setup_deletions SET deleted_at='changed'"):
            with self.assertRaises(sqlite3.IntegrityError), db.get_connection(write=True) as connection:
                connection.execute(statement)
        with self.assertRaises(sqlite3.IntegrityError), db.get_connection(write=True) as connection:
            connection.execute('INSERT INTO setup_snapshots VALUES (?,?,?,?,?,?)',row)

    def test_migration_from_v2_preserves_existing_evidence_and_is_repeatable(self):
        record=self.capture()
        self.client.post(self.url(record)+'/evaluate',json={'request_id':str(uuid4())})
        before=self.client.get(self.url(record)).json()
        with db.get_connection(write=True) as connection:
            connection.execute('DROP TRIGGER setup_snapshot_no_recreate')
            connection.execute('DROP TABLE setup_deletions')
            connection.execute('DELETE FROM setup_schema_migrations WHERE version=3')
            for table,trigger in [('setup_snapshots','setup_snapshot_no_delete'),('setup_evaluations','setup_evaluation_no_delete')]:
                connection.execute('DROP TRIGGER '+trigger)
                connection.execute(f"CREATE TRIGGER {trigger} BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'Immutable'); END")
        sd.init_setup_db(); sd.init_setup_db()
        self.assertEqual(self.client.get(self.url(record)).json(),before)
        with db.get_connection() as connection:
            self.assertEqual([row[0] for row in connection.execute('SELECT version FROM setup_schema_migrations ORDER BY version')],[1,2,3])
        self.assertEqual(self.client.delete(self.url(record)).status_code,204)

    def test_concurrent_assessment_reservation_and_deletion_serialize(self):
        record=self.capture(); barrier=Barrier(2)
        def begin():
            barrier.wait(timeout=5)
            try: return sd.begin_evaluation(record['id'],uuid4(),'offline',ai.PROMPT_VERSION)
            except sd.SetupNotFound: return 'missing'
        def delete():
            barrier.wait(timeout=5)
            try: return sd.delete_snapshot(record['id'])
            except sd.SetupConflict: return 'pending'
        with ThreadPoolExecutor(max_workers=2) as pool:
            a,b=pool.submit(begin),pool.submit(delete)
            started,deleted=a.result(timeout=10),b.result(timeout=10)
        if deleted is True:
            self.assertEqual(started,'missing')
            self.assertEqual(sd.list_evaluations(record['id']),[])
        else:
            self.assertEqual(deleted,'pending')
            self.assertEqual(started[0]['status'],'pending')
            self.assertIsNotNone(sd.fetch_snapshot(record['id']))

    def test_deleted_between_api_read_and_attempt_reservation_returns_404(self):
        record=self.capture(); original=sd.begin_evaluation
        def remove_then_begin(*args):
            sd.delete_snapshot(record['id'])
            return original(*args)
        with patch.object(sd,'begin_evaluation',side_effect=remove_then_begin):
            response=self.client.post(self.url(record)+'/evaluate',json={'request_id':str(uuid4())})
        self.assertEqual(response.status_code,404)
        self.provider.assert_not_called()

    def test_late_provider_response_after_stale_delete_returns_404_without_resurrection(self):
        record=self.capture(); completion=self.provider.return_value
        def delete_during_provider(**kwargs):
            with db.get_connection(write=True) as connection:
                connection.execute('UPDATE setup_evaluations SET created_at=? WHERE snapshot_id=?',((datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),record['id']))
            sd.delete_snapshot(record['id'])
            return completion
        self.provider.side_effect=delete_during_provider
        response=self.client.post(self.url(record)+'/evaluate',json={'request_id':str(uuid4())})
        self.assertEqual(response.status_code,404,response.text)
        self.assertIsNone(sd.fetch_snapshot(record['id']))
        self.assertEqual(sd.list_evaluations(record['id']),[])
