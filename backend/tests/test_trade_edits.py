"""Trade corrections and the evidence that belongs to each version."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from types import SimpleNamespace

from fastapi.testclient import TestClient
import database as db
import market_data as md
import setup_database
import trade_coach_database
import trade_coach_market
import trade_database
import trade_scores
from trade_coach_models import CoachRequest
from tests.test_setup_evaluator import ENVIRONMENT, main, snapshot
from tests.test_trade_log import trade, full_exit
from tests.test_trade_timeline import ENTERED, NOW, provider
from tests.test_trade_coach import Clock, assessment


class TradeEditTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db,'DB_PATH',root/'journal.db'))
        self.enterContext(patch.dict(os.environ,ENVIRONMENT,clear=True))
        self.client = self.enterContext(TestClient(main.app))
        Clock.value = NOW
        self.enterContext(patch.object(trade_scores, 'datetime', Clock))
        self.enterContext(patch.object(trade_coach_market, 'datetime', Clock))
        self.market = self.enterContext(patch.object(md, '_fetch_candles', side_effect=provider(NOW)))
        self.enterContext(patch('setup_market.fetch_quote', side_effect=md.MarketDataError('Offline')))
        self.ai = self.enterContext(patch.object(main.client.responses, 'create', side_effect=lambda **args:
            SimpleNamespace(status='completed', output_text=json.dumps(assessment(json.loads(args['input']))),
                            model='fixture',id='response')))

    def create(self, **details):
        response = self.client.post('/trades', json=trade(**{'entry_at':ENTERED, **details}))
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def path(self, record, suffix=''):
        return '/trades/' + record['id'] + suffix

    def body(self, record, entry=None, exit=None):
        values = {k:v for k,v in record['entry'].items() if k!='setup_id'}
        return {'request_id':str(uuid4()), 'expected_revision':record['revision'], 'entry':{**values,**(entry or {})},
                'exit':{**record['exit'],**(exit or {})} if record['exit'] else None}

    def post(self, record, suffix, body, expected=200):
        result = self.client.post(self.path(record,suffix),json=body)
        self.assertEqual(result.status_code,expected,result.text[:800])
        return result.json()

    def close(self, record):
        return self.post(record,'/close',full_exit(exit_at=NOW.isoformat()))

    def test_trade_correction_preserves_drawn_zones_and_checks_original_zone_timing(self):
        zone = {'label':'Ceiling','kind':'resistance','lower':'1.15','upper':'1.16','origin_at':ENTERED}
        record = self.create(entry_zones=[zone])
        updated = self.post(record,'/edits',self.body(record,{'title':'Corrected'}))
        self.assertEqual(updated['context']['entry_zones'],record['context']['entry_zones'])
        before_origin = (datetime.fromisoformat(ENTERED) - timedelta(hours=1)).isoformat()
        self.post(updated,'/edits',self.body(updated,{'entry_at':before_origin}),422)

    def test_edit_open_replay_conflict_list_order_and_close(self):
        first = self.create()
        second = self.create(entry_at='2026-11-09T18:00:00Z')
        change = self.body(first, {'title':'Corrected fill','entry_price':'1.10100','entry_at':'2026-11-10T09:00:00Z'})
        corrected = self.post(first,'/edits',change)
        self.assertEqual(corrected['revision'],1)
        self.assertEqual(corrected['edits'][0]['changes']['entry_price'],{'before':'1.10000','after':'1.10100'})
        self.assertEqual(self.post(first,'/edits',change),corrected)
        self.post(first,'/edits',self.body(first,{'title':'stale'}),409)
        self.post(second,'/edits',change,409)
        self.post(corrected,'/edits',self.body(corrected),422)
        self.post(corrected,'/close',full_exit(exit_at=NOW.isoformat(),expected_revision=0),409)
        listing = self.client.get('/trades').json()
        self.assertEqual([row['id'] for row in listing['items']],[first['id'],second['id']])
        self.assertEqual(self.close(corrected)['result']['pips'],'+30.0')
        self.market.assert_not_called()
        self.ai.assert_not_called()

    def test_closed_correction_reuses_frozen_period_and_adjusts_direction_offline(self):
        record = self.close(self.create())
        scores = self.post(record,'/scores',{})
        self.assertTrue(scores['saved_at'])
        self.market.reset_mock()
        self.market.side_effect = AssertionError('A correction with the same cutoff must reuse its candles')
        record = self.post(record,'/edits',self.body(record,{'direction':'short','initial_stop_loss':'1.10300',
                                          'initial_take_profit':'1.09400'}, {'exit_price':'1.09700'}))
        self.assertEqual(record['result']['pips'],'+30.0')
        self.assertEqual(record['result']['r_display'],'+1.00')
        corrected = self.post(record,'/scores',{})
        self.assertEqual(corrected['trade_revision'],1)
        self.assertEqual(corrected['full_trade']['source_candles'],scores['full_trade']['source_candles'])
        self.assertEqual(corrected['full_trade']['summary']['supporting_points'],scores['full_trade']['summary']['conflicting_points'])
        self.assertNotEqual(corrected['entry_analysis_id'],scores['entry_analysis_id'])
        self.assertEqual(corrected['entry_score']['candle'],scores['entry_score']['candle'])
        trade_database.init_trade_db()
        self.assertEqual(self.client.get(self.path(record)).json(),record)
        with db.get_connection(write=True) as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('UPDATE trade_edits SET timing=timing')
        self.assertEqual(self.client.delete(self.path(record)).status_code,204)
        with db.get_connection() as con:
            for table in ('trade_edits','edited_trade_analyses','edited_trade_scores','trade_score_snapshots'):
                self.assertEqual(con.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.market.assert_not_called()

    def test_changed_cutoffs_reconstruct_at_correct_times(self):
        record = self.close(self.create())
        previous = self.post(record,'/scores',{})
        body = self.body(record,{'entry_at':'2026-11-09T19:00:00Z'},{'exit_at':'2026-11-10T10:00:00Z'})
        corrected = self.post(record,'/edits',body)
        self.assertEqual(corrected['strategy_analyses'],[])
        scores = self.post(corrected,'/scores',{})
        self.assertNotEqual(previous['entry_analysis_hash'],scores['entry_analysis_hash'])
        self.assertEqual(scores['entry_score']['cutoff_at'],corrected['entry']['entry_at'])
        self.assertEqual(scores['full_trade']['cutoff_at'],corrected['exit']['exit_at'])
        self.assertGreater(len(previous['full_trade']['candles']),len(scores['full_trade']['candles']))
        self.assertIsNone(trade_database.finish_scores(record['id'],record,previous['entry_analysis'],previous))

    def test_edit_validation_and_future_linked_evidence(self):
        source = setup_database.store_snapshot(uuid4(),{},snapshot())
        cutoff = datetime.fromisoformat(source['snapshot']['cutoff_at'])
        record = self.create(entry_at=cutoff.isoformat(),setup_id=source['id'])
        self.post(record,'/edits',self.body(record,{'entry_at':(cutoff-timedelta(seconds=1)).isoformat()}),422)
        self.post(record,'/edits',self.body(record,{'entry_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}),422)
        self.post(record,'/edits',self.body(record,{'initial_stop_loss':'1.30000'}),422)
        corrected = self.post(record,'/edits',self.body(record,{'entry_reason':'Corrected note'}))
        self.assertEqual(record['context']['setup'],corrected['context']['setup'])
        self.assertEqual(record['strategy_analyses'][0]['analysis']['rule_set'],corrected['strategy_analyses'][0]['analysis']['rule_set'])
        closed = self.close(corrected)
        self.post(closed,'/edits',{**self.body(closed),'exit':None},409)
        self.post(closed,'/edits',self.body(closed,exit={'exit_at':(cutoff-timedelta(hours=1)).isoformat()}),422)

    def test_prior_coach_evidence_kept_and_pending_review_cancelled(self):
        record = self.create()
        review = self.post(record,'/coach-reviews',{'request_id':str(uuid4())})
        self.assertEqual(review['status'],'completed',review.get('error_message'))
        pending, _ = trade_coach_database.reserve(record['id'],CoachRequest(request_id=uuid4()),'demo','1')
        body = self.body(record,{'direction':'short','initial_stop_loss':None,'initial_take_profit':None})
        corrected = self.post(record,'/edits',body)
        old_review = self.client.get(self.path(record,'/coach-reviews/'+review['id'])).json()
        self.assertEqual(old_review,review)
        self.assertEqual(old_review['direction'],'long')
        self.assertEqual(trade_coach_database.finish(pending['id'],error='Late worker')['status'],'failed')
        new_review = self.post(corrected,'/coach-reviews',{'request_id':str(uuid4())})
        self.assertEqual(new_review['status'],'completed',new_review['error_message'])
        self.assertEqual(new_review['snapshot']['trade_revision'],1)
        self.assertEqual(new_review['direction'],'short')
