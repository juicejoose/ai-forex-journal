"""Chart preview capture must preserve server-owned evidence without a refetch."""
from datetime import datetime, timedelta, timezone
import copy
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from tests.test_setup_evaluator import snapshot, inputs, ENVIRONMENT, main
import database as db
import setup_database as sd
import setup_market as sm


class SetupPreviewTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'journal.db'
        self.enterContext(patch.object(db, 'DB_PATH', path))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        db.init_db()
        sd.init_setup_db()
        self.client = self.enterContext(TestClient(main.app))
        self.snap = snapshot(zones=[])
        self.builder = self.enterContext(patch('setup_api.build_setup_snapshot', return_value=copy.deepcopy(self.snap)))
        self.provider = self.enterContext(patch.object(main.client.responses, 'create'))

    def preview(self):
        body = {key: value for key, value in inputs(zones=[]).items() if key in ('request_id','mode','as_of','include_quote')}
        response = self.client.post('/setup-previews', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return body, response.json()

    def test_capture_exact_preview_across_restart_without_refetch(self):
        body, preview = self.preview()
        sd.init_setup_db()
        self.builder.reset_mock()
        capture = inputs(preview_id=preview['id'], direction='short', zones=[{
            'label': 'Drawn support', 'kind': 'support', 'lower': '1.12600', 'upper': '1.12700',
            'origin_at': self.snap['source_candles'][-20]['open_time']}])
        response = self.client.post('/setup-snapshots', json=capture)
        self.assertEqual(response.status_code, 201, response.text)
        saved = response.json()['snapshot']
        for key in ('cutoff_at','source_candles','market_data','quote','reference_price','rule_evaluation','calculation_version'):
            self.assertEqual(saved[key], preview['snapshot'][key], key)
        self.assertEqual(saved['entry']['direction'], 'short')
        self.assertGreater(saved['zones'][0]['history']['candle_count'], 0)
        self.assertEqual(saved['preview_id'], preview['id'])
        self.builder.assert_not_called()
        self.provider.assert_not_called()
        self.assertEqual(self.client.post('/setup-snapshots', json=capture).json(), response.json())
        self.assertEqual(self.client.get('/setup-snapshots').json()['total'], 1)
        self.assertTrue(all(datetime.fromisoformat(c['close_time']) <= datetime.fromisoformat(saved['cutoff_at']) for c in saved['source_candles']))

    def test_preview_retry_is_idempotent_and_not_a_saved_setup(self):
        body, preview = self.preview()
        self.assertEqual(self.client.post('/setup-previews', json=body).json(), preview)
        self.builder.assert_called_once()
        self.provider.assert_not_called()
        self.assertEqual(self.client.get('/setup-snapshots').json()['total'], 0)
        changed = {**body, 'as_of': '2020-01-01T00:00:00Z'}
        self.assertEqual(self.client.post('/setup-previews', json=changed).status_code, 409)

    def test_live_capture_keeps_preview_quote_and_cutoff_as_annotations_are_added(self):
        self.snap.update(mode='live', observation_provenance='user_input_at_capture')
        self.snap['quote'] = {'status': 'available', 'source': 'OANDA practice',
            'time': self.snap['cutoff_at'], 'bid': 1.126, 'ask': 1.1262, 'midpoint': 1.1261}
        self.snap['reference_price'] = {'basis': 'quote_midpoint', 'value': 1.1261, 'time': self.snap['cutoff_at']}
        self.builder.return_value = copy.deepcopy(self.snap)
        response = self.client.post('/setup-previews', json={
            'request_id': str(uuid4()), 'mode': 'live', 'include_quote': True})
        self.assertEqual(response.status_code, 201, response.text)
        preview = response.json()
        self.builder.reset_mock()
        with patch.object(sm, 'fetch_quote', side_effect=AssertionError('Must not refresh quote')):
            response = self.client.post('/setup-snapshots', json=inputs(
                mode='live', as_of=None, include_quote=True, preview_id=preview['id']))
        self.assertEqual(response.status_code, 201, response.text)
        saved = response.json()['snapshot']
        for key in ('quote', 'reference_price', 'cutoff_at', 'market_data', 'rule_evaluation'):
            self.assertEqual(saved[key], self.snap[key])
        self.assertEqual(saved['observation_provenance'], 'user_input_after_preview')
        self.assertIn('finalized_at', saved)
        self.assertTrue(any('frozen' in text for text in saved['catalog']['limitations']))
        self.builder.assert_not_called()
        self.provider.assert_not_called()

    def test_time_quote_and_version_mismatches_rejected(self):
        _, preview = self.preview()
        for overrides in ({'as_of':'2020-01-01T00:00:00Z'}, {'mode':'live','as_of':None,'include_quote':True}):
            response = self.client.post('/setup-snapshots', json=inputs(preview_id=preview['id'], **overrides))
            self.assertEqual(response.status_code, 409, response.text)
        with patch.object(sm, '_version_hash', return_value='new code'):
            self.assertEqual(self.client.post('/setup-snapshots', json=inputs(preview_id=preview['id'])).status_code, 409)
        # Equivalent timezone spelling is accepted.
        original = datetime.fromisoformat(self.snap['cutoff_at'])
        equivalent = original.astimezone(timezone(timedelta(hours=-4))).isoformat()
        self.assertEqual(self.client.post('/setup-snapshots', json=inputs(preview_id=preview['id'], as_of=equivalent)).status_code, 201)

    def test_future_origin_and_client_injected_candles_rejected(self):
        _, preview = self.preview()
        zones = inputs()['zones']
        zones[0]['origin_at'] = (datetime.fromisoformat(self.snap['cutoff_at'])+timedelta(seconds=1)).isoformat()
        self.assertEqual(self.client.post('/setup-snapshots', json=inputs(preview_id=preview['id'], zones=zones)).status_code, 422)
        self.assertEqual(self.client.post('/setup-snapshots', json=inputs(preview_id=preview['id'], source_candles=[])).status_code, 422)
        self.assertEqual(self.client.post('/setup-previews', json=inputs()).status_code, 422)

    def test_expired_missing_and_corrupt_previews_cannot_be_captured(self):
        _, preview = self.preview()
        future = datetime.now(timezone.utc)+timedelta(days=2)
        class Later(datetime):
            @classmethod
            def now(cls, tz=None): return future.astimezone(tz)
        with patch.object(sd, 'datetime', Later):
            self.assertEqual(self.client.post('/setup-snapshots', json=inputs(preview_id=preview['id'])).status_code, 409)
        self.assertEqual(self.client.post('/setup-snapshots', json=inputs(preview_id=str(uuid4()))).status_code, 409)
        with db.get_connection(write=True) as connection:
            connection.execute('DROP TRIGGER setup_preview_no_update')
            connection.execute("UPDATE setup_previews SET snapshot_hash='tampered'")
        self.assertEqual(self.client.post('/setup-snapshots', json=inputs(preview_id=preview['id'])).status_code, 409)

    def test_preview_eviction_does_not_remove_saved_evidence_or_break_capture_retry(self):
        _, preview = self.preview()
        body = inputs(preview_id=preview['id'])
        saved = self.client.post('/setup-snapshots', json=body).json()
        for _ in range(51): sd.store_preview(uuid4(), preview['selection'], self.snap)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM setup_previews').fetchone()[0], 50)
        self.assertEqual(self.client.post('/setup-snapshots', json=body).json(), saved)
        self.assertEqual(self.client.get('/setup-snapshots/'+saved['id']).json(), saved)

    def test_additive_migration_from_v1_preserves_existing_snapshot(self):
        saved = sd.store_snapshot(uuid4(), {}, self.snap)
        with db.get_connection(write=True) as connection:
            connection.execute('DROP TABLE setup_previews')
            connection.execute('DELETE FROM setup_schema_migrations WHERE version=2')
        sd.init_setup_db()
        sd.init_setup_db()
        self.assertEqual(sd.fetch_snapshot(saved['id']), saved)
        with db.get_connection(write=True) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE setup_snapshots SET snapshot_json='{}'")
