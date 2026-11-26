"""Offline coach contracts, causal evidence, immutability and request lifecycle."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from tests.test_setup_evaluator import main, ENVIRONMENT, quote_at, snapshot
from tests.test_trade_log import trade, full_exit
from tests.test_trade_timeline import provider, at, NOW, ENTERED
import database as db
import trade_database as td
import trade_coach_database as cd
import trade_coach_market as cm
import trade_coach_ai as ai
import market_data as md
import setup_market as sm
import setup_database as sd
from trade_coach_models import CoachRequest
from journal_grounding import InvalidJournalEvidence

class Clock(datetime):
    value=NOW
    @classmethod
    def now(cls,tz=None):return cls.value.astimezone(tz)


def assessment(catalog):
    facts=catalog['facts']
    support=[f['id'] for f in facts if f['role']=='supports'][:12]
    conflict=[f['id'] for f in facts if f['role']=='conflicts'][:12]
    return {'summary':'The completed factor readings provide a technical view of support and conflict for the recorded trade direction. Further confirmation remains uncertain.',
            'main_concern':'Initial management levels may differ from the current plan.',
            'supporting_facts':support,'conflicting_facts':conflict,
            'change_facts':[f['id'] for f in facts if f['role']=='change'],
            'context_facts':[f['id'] for f in facts if f['role'] in ('context','missing') and f['required']],
            'watch_conditions':[c['id'] for c in catalog['conditions'] if c['kind']=='watch'][:2],
            'invalidation_conditions':[c['id'] for c in catalog['conditions'] if c['kind']=='invalidation'][:2]}


class CoachTests(unittest.TestCase):
    def setUp(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db,'DB_PATH',root/'test.db'))
        self.enterContext(patch.dict(os.environ,ENVIRONMENT,clear=True))
        self.client=self.enterContext(TestClient(main.app))
        Clock.value=NOW
        self.enterContext(patch.object(cm,'datetime',Clock))
        self.enterContext(patch.object(cd,'datetime',Clock))
        self.market=self.enterContext(patch.object(md,'_fetch_candles',side_effect=provider(NOW)))
        self.quote=self.enterContext(patch.object(sm,'fetch_quote',return_value=quote_at(NOW)))
        self.ai=self.enterContext(patch.object(main.client.responses,'create',side_effect=self.fake_ai))

    def fake_ai(self,**kwargs):
        payload=json.loads(kwargs['input'])
        return SimpleNamespace(status='completed',output_text=json.dumps(assessment(payload)),model='test-model',id='test-response')

    def create(self,**overrides):
        response=self.client.post('/trades',json=trade(**{'entry_at':ENTERED,**overrides}))
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def url(self,record):return '/trades/'+record['id']+'/coach-reviews'

    def review(self,record,body=None):
        response=self.client.post(self.url(record),json=body or {'request_id':str(uuid4())})
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()
        self.assertEqual(result['status'],'completed',result.get('error_message'))
        return result

    def test_manual_review_freezes_before_ai_and_retains_entry_rule_version(self):
        record=self.create();original=deepcopy(record)
        def checked(**kwargs):
            running=cd.listing(record['id'])['items'][0]
            self.assertEqual(running['status'],'pending');self.assertIsNotNone(running['snapshot_hash'])
            self.assertEqual(kwargs['reasoning'],{'effort':'medium'});self.assertFalse(kwargs['store'])
            self.assertTrue(kwargs['text']['format']['strict'])
            return self.fake_ai(**kwargs)
        self.ai.side_effect=checked
        review=self.review(record);snap=review['snapshot']
        current=td.fetch_trade(record['id'])
        for key in ('entry','context','evidence_hash','review'):self.assertEqual(current[key],original[key])
        self.assertEqual(snap['rule_set']['id'],'four_factor_v7')
        self.assertEqual(snap['rule_set'],current['strategy_analyses'][0]['analysis']['rule_set'])
        self.assertEqual(len(snap['calculation_version']),64)
        self.assertEqual(snap['entry_score']['candle'],current['strategy_analyses'][0]['analysis']['reconstructed_snapshot']['rule_evaluation']['candles'][-1])
        self.assertEqual(snap['full_trade']['summary']['candle_count'],6)
        self.assertEqual(snap['latest'],snap['full_trade']['candles'][-1])
        self.assertEqual(snap['data_through'],at('2026-11-10T09:00:00-05:00').isoformat())
        self.assertEqual(snap['reference_price']['basis'],'quote_midpoint')
        payload=json.loads(self.ai.call_args.kwargs['input'])
        self.assertNotIn('source_candles',payload);self.assertNotIn('exit',payload);self.assertNotIn('review',payload)
        self.assertTrue(all(at(c['close_time'])<=NOW for c in snap['source_candles']))
        self.assertTrue(all(at(ENTERED)<at(c['close_time'])<=NOW for c in snap['full_trade']['candles']))
        self.assertTrue(any('external news' in text for text in snap['catalog']['limitations']))

    def test_same_uuid_replays_without_network_and_mismatched_inputs_conflict(self):
        record=self.create();body={'request_id':str(uuid4()),'observations':'Current note'}
        first=self.review(record,body);calls=self.market.call_count
        self.assertEqual(self.review(record,body),first)
        self.assertEqual(self.market.call_count,calls);self.ai.assert_called_once()
        self.assertEqual(self.client.post(self.url(record),json={**body,'observations':'Changed'}).status_code,409)
        other=self.create()
        self.assertEqual(self.client.post(self.url(other),json=body).status_code,409)

    def test_read_only_history_is_paginated_and_survives_restart(self):
        record=self.create();a=self.review(record);Clock.value+=timedelta(seconds=1);b=self.review(record)
        self.market.reset_mock();self.ai.reset_mock();self.quote.reset_mock()
        td.init_trade_db()
        listing=self.client.get(self.url(record)+'?limit=1').json()
        self.assertEqual(listing['total'],2);self.assertEqual(listing['items'][0]['id'],b['id'])
        self.assertNotIn('snapshot',listing['items'][0])
        self.assertEqual(self.client.get(self.url(record)+'?limit=1&offset=1').json()['items'][0]['id'],a['id'])
        self.assertEqual(self.client.get(self.url(record)+'/'+a['id']).json(),a)
        self.market.assert_not_called();self.ai.assert_not_called();self.quote.assert_not_called()
        other=self.create();self.assertEqual(self.client.get(self.url(other)+'/'+a['id']).status_code,404)

    def test_new_candles_change_review_not_prior_assessment(self):
        record=self.create();a=self.review(record)
        Clock.value=NOW+timedelta(hours=4);self.market.side_effect=provider(Clock.value)
        b=self.review(record)
        self.assertNotEqual(a['snapshot_hash'],b['snapshot_hash']);self.assertNotEqual(a['data_through'],b['data_through'])
        self.assertEqual(a['snapshot']['entry_score'],b['snapshot']['entry_score'])
        self.assertEqual(self.client.get(self.url(record)+'/'+a['id']).json(),a)

    def test_forming_prices_never_enter_factors_and_future_quotes_fall_back(self):
        record=self.create();a=self.review(record)
        fetch=provider(NOW)
        def forming(end,count=350,*,start=None):
            raw=fetch(end,count,start=start)
            for candle in raw['candles']:
                if at(candle['time'])+md.CANDLE_DURATION>NOW:candle['mid'].update(c='1.9',h='2')
            return raw
        self.market.side_effect=forming;self.quote.return_value=quote_at(NOW+timedelta(seconds=1))
        b=self.review(record)
        for key in ('entry_score','latest','full_trade','source_candles'):self.assertEqual(a['snapshot'][key],b['snapshot'][key])
        self.assertEqual(b['snapshot']['quote']['status'],'unavailable')
        self.assertEqual(b['snapshot']['reference_price']['basis'],'last_completed_close')
        self.assertEqual(b['snapshot']['reference_price']['time'],b['data_through'])

    def test_no_close_during_hold_does_not_claim_zero_average(self):
        record=self.create(entry_at='2026-11-10T10:00:00-05:00');result=self.review(record)
        snap=result['snapshot'];self.assertEqual(snap['full_trade']['summary']['candle_count'],0)
        self.assertIsNone(snap['full_trade']['summary']['net_score']);self.assertEqual(snap['recent_candles'],[])
        self.assertTrue(any('No H4 candle' in text for text in snap['catalog']['limitations']))

    def test_long_short_roles_reverse_without_changing_strategy(self):
        a=self.review(self.create())['snapshot']
        b=self.review(self.create(direction='short',initial_stop_loss=None,initial_take_profit=None))['snapshot']
        self.assertEqual(a['latest'],b['latest']);self.assertEqual(a['directional_net_change'],-b['directional_net_change'])
        left=[f for f in a['catalog']['facts'] if f['evidence'].get('scope')=='current_factor']
        right=[f for f in b['catalog']['facts'] if f['evidence'].get('scope')=='current_factor']
        for x,y in zip(left,right):self.assertEqual(y['role'],{'supports':'conflicts','conflicts':'supports'}.get(x['role'],x['role']))

    def test_coach_inherits_drawn_trade_zones_with_or_without_a_linked_setup(self):
        zone = {'label':'Logged floor','kind':'support','lower':'1.105','upper':'1.106'}
        saved = sd.store_snapshot(uuid4(),{},snapshot())
        for setup_id,source in ((None,'trade_entry_zones'),(saved['id'],'setup_and_trade_entry_zones')):
            record = self.create(entry_zones=[zone],setup_id=setup_id)
            inherited = self.review(record)['snapshot']
            self.assertEqual(inherited['zone_source'],source)
            expected = [z['label'] for z in saved['snapshot']['zones']] if setup_id else []
            self.assertEqual([z['label'] for z in inherited['zones']], [*expected,zone['label']])
            override = self.review(record,{'request_id':str(uuid4()),'zones':[]})['snapshot']
            self.assertEqual(override['zones'],[])
            self.assertEqual(override['entry_score'],inherited['entry_score'])
            self.assertEqual(override['full_trade'],inherited['full_trade'])

    def test_manual_zones_are_review_only_and_inherited_zones_stay_fixed(self):
        saved=sd.store_snapshot(uuid4(),{},snapshot())
        record=self.create(setup_id=saved['id']);inherited=self.review(record)['snapshot']
        self.assertEqual(inherited['zone_source'],'saved_entry_setup');self.assertEqual(len(inherited['zones']),1)
        zone={'label':'Current ceiling','kind':'resistance','lower':'1.126','upper':'1.127','timeframe':'H4','origin_at':'2026-11-06T14:00:00Z'}
        edited=self.review(record,{'request_id':str(uuid4()),'zones':[zone],'observations':'Watch rejection'})['snapshot']
        self.assertEqual(edited['zone_source'],'review_annotations');self.assertEqual(edited['zones'][0]['label'],'Current ceiling')
        self.assertEqual(edited['zones'][0]['patterns']['version'],inherited['zones'][0]['patterns']['version'])
        self.assertEqual(td.fetch_trade(record['id'])['context'],record['context'])
        empty=self.review(record,{'request_id':str(uuid4()),'zones':[]})
        self.assertEqual(empty['snapshot']['zones'],[])

    def test_future_origin_fails_without_ai_and_client_cannot_supply_scores(self):
        record=self.create()
        body={'request_id':str(uuid4()),'zones':[{'label':'Future','kind':'support','lower':'1.1','upper':'1.2','origin_at':(NOW+timedelta(hours=1)).isoformat()}]}
        result=self.client.post(self.url(record),json=body).json()
        self.assertEqual(result['status'],'failed');self.ai.assert_not_called()
        for key,value in [('scores',{}),('cutoff_at',NOW.isoformat()),('assessment','supported')]:
            self.assertEqual(self.client.post(self.url(record),json={'request_id':str(uuid4()),key:value}).status_code,422)

    def test_missing_candle_stops_ai_instead_of_zero_filling(self):
        record=self.create();fetch=provider(NOW);missing=at('2026-11-09T13:00:00-05:00')
        def gap(end,count=350,*,start=None):
            raw=fetch(end,count,start=start);raw['candles']=[r for r in raw['candles'] if at(r['time'])!=missing];return raw
        self.market.side_effect=gap
        result=self.client.post(self.url(record),json={'request_id':str(uuid4())}).json()
        self.assertEqual(result['status'],'failed');self.assertIn('missing',result['error_message']);self.ai.assert_not_called()

    def test_failed_ai_retains_snapshot_and_retry_does_not_repeat_paid_call(self):
        record=self.create();body={'request_id':str(uuid4())}
        self.ai.side_effect=lambda **kwargs:SimpleNamespace(status='completed',output_text='{"assessment":"guaranteed"}')
        failed=self.client.post(self.url(record),json=body).json()
        self.assertEqual(failed['status'],'failed');self.assertIsNotNone(failed['snapshot']);self.assertIsNone(failed['result'])
        self.assertEqual(self.client.post(self.url(record),json=body).json(),failed);self.ai.assert_called_once()
        self.ai.side_effect=self.fake_ai;self.review(record)
        self.assertEqual(cd.listing(record['id'])['total'],2)

    def test_pending_request_replay_other_requests_block_and_expiry_cannot_be_overwritten(self):
        record=self.create();request=CoachRequest(request_id=uuid4())
        reserved,_=cd.reserve(record['id'],request,'test','test')
        snap=cm.build_snapshot(record['id'],request);snap['catalog']=ai.build_catalog(snap)
        cd.freeze(reserved['id'],snap)
        self.assertEqual(self.client.post(self.url(record),json=request.model_dump(mode='json')).json()['status'],'pending')
        self.assertEqual(self.client.post(self.url(record),json={'request_id':str(uuid4())}).status_code,409);self.ai.assert_not_called()
        Clock.value=NOW+timedelta(minutes=6)
        self.review(record)
        late=cd.finish(reserved['id'],result=assessment(snap['catalog']))
        self.assertEqual(late['status'],'failed');self.assertIn('expired',late['error_message'])

    def test_closed_trade_retains_history_and_rejects_new_reviews(self):
        record=self.create();body={'request_id':str(uuid4())};review=self.review(record,body)
        self.client.post('/trades/'+record['id']+'/close',json=full_exit(exit_at=NOW.isoformat()))
        self.assertEqual(self.client.post(self.url(record),json={'request_id':str(uuid4())}).status_code,409)
        self.assertEqual(self.client.post(self.url(record),json=body).json(),review)
        self.assertEqual(self.client.get(self.url(record)+'/'+review['id']).json(),review)

    def test_trade_closing_during_ai_retains_evidence_but_not_active_opinion(self):
        record=self.create()
        def close(**kwargs):
            self.client.post('/trades/'+record['id']+'/close',json=full_exit(exit_at=NOW.isoformat()))
            return self.fake_ai(**kwargs)
        self.ai.side_effect=close
        result=self.client.post(self.url(record),json={'request_id':str(uuid4())}).json()
        self.assertEqual(result['status'],'failed');self.assertIsNotNone(result['snapshot']);self.assertIsNone(result['result'])
        self.assertIn('closed',result['error_message'])

    def test_close_during_capture_never_calls_ai(self):
        record=self.create();build=cm.build_snapshot
        def close(identifier,request):
            snap=build(identifier,request)
            self.client.post('/trades/'+record['id']+'/close',json=full_exit(exit_at=NOW.isoformat()))
            return snap
        with patch('trade_coach_api.build_snapshot',side_effect=close):
            result=self.client.post(self.url(record),json={'request_id':str(uuid4())}).json()
        self.assertEqual(result['status'],'failed');self.ai.assert_not_called()

    def test_unavailable_quote_does_not_prevent_completed_candle_review(self):
        record=self.create();self.quote.side_effect=md.MarketDataError('No fresh quote',503)
        result=self.review(record)
        self.assertEqual(result['snapshot']['reference_price']['basis'],'last_completed_close')
        self.assertTrue(any('Fresh quote unavailable' in text for text in result['snapshot']['catalog']['limitations']))

    def test_delete_cascades_reviews_and_late_response_cannot_resurrect(self):
        record=self.create();self.review(record)
        def delete(**kwargs):
            self.assertEqual(self.client.delete('/trades/'+record['id']).status_code,204)
            return self.fake_ai(**kwargs)
        self.ai.side_effect=delete
        self.assertEqual(self.client.post(self.url(record),json={'request_id':str(uuid4())}).status_code,404)
        with db.get_connection() as con:self.assertEqual(con.execute('SELECT count(*) FROM trade_coach_reviews').fetchone()[0],0)
        self.assertEqual(self.client.get(self.url(record)).status_code,404)

    def test_frozen_evidence_result_and_direct_deletion_are_protected(self):
        record=self.create();result=self.review(record)
        for sql in ("UPDATE trade_coach_reviews SET snapshot_json='{}'","UPDATE trade_coach_reviews SET result_json='{}'","DELETE FROM trade_coach_reviews"):
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError),db.get_connection(write=True) as con:con.execute(sql)
        with db.get_connection(write=True) as con:
            con.execute('DROP TRIGGER trade_coach_fixed');con.execute("UPDATE trade_coach_reviews SET result_json='{}'")
        self.assertEqual(self.client.get(self.url(record)+'/'+result['id']).status_code,409)

    def test_ai_rejects_invented_numbers_ids_roles_omissions_and_unavailable_verdict(self):
        snap=self.review(self.create())['snapshot'];good=assessment(snap['catalog'])
        mutations=[{'summary':'The net score is 99.'},{'summary':'A confirmed breakout guarantees profit.'},{'supporting_facts':['FAKE']},{'context_facts':[]},{'watch_conditions':['BAD']},{'main_concern':'Buy now.'}]
        for changes in mutations:
            with self.subTest(changes=changes),self.assertRaises(InvalidJournalEvidence):ai.parse(json.dumps({**good,**changes}),snap)
        directional=next(f for f in snap['catalog']['facts'] if f['role'] in ('supports','conflicts'))
        with self.assertRaises(InvalidJournalEvidence):ai.parse(json.dumps({**good,'context_facts':good['context_facts']+[directional['id']]}),snap)
        snap['catalog']['readout']['strategy_alignment']='insufficient_evidence'
        with self.assertRaises(InvalidJournalEvidence):ai.parse(json.dumps({**good,'assessment':'supported'}),snap)
        self.assertEqual(ai.parse(json.dumps(good),snap)['assessment'],'insufficient_evidence')
