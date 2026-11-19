"""Offline manual trade records, exact outcomes, snapshot timing and review integrity."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from tests.test_setup_evaluator import snapshot, main, ENVIRONMENT
from tests.test_today import NOW
from trade_models import TradeInput, TradeCloseInput
from trade_calculations import trade_outcome, entry_context
import trade_database as td
import setup_database as sd
import database as db
import market_data as md


def trade(**overrides):
    return {'request_id':str(uuid4()),'title':'Manual fixture','direction':'long','entry_price':'1.10000',
        'entry_at':(NOW+timedelta(minutes=1)).isoformat(),'initial_stop_loss':'1.09800','initial_take_profit':'1.10400',
        'entry_reason':'Followed my entry plan.','entry_observations':'Watched support.',**overrides}


def full_exit(**overrides):
    return {'request_id':str(uuid4()),'exit_price':'1.10400','exit_at':(NOW+timedelta(hours=8)).isoformat(),
        'exit_notes':'Manually exited the whole position.',**overrides}


class TradeLogTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db,'DB_PATH',self.root/'journal.db'))
        self.enterContext(patch.dict(os.environ,ENVIRONMENT,clear=True))
        self.client=self.enterContext(TestClient(main.app))
        self.provider=self.enterContext(patch.object(main.client.responses,'create',side_effect=AssertionError('No AI request')))
        self.market=self.enterContext(patch.object(md,'_fetch_candles',side_effect=AssertionError('No market request')))

    def tearDown(self):
        self.provider.assert_not_called(); self.market.assert_not_called()

    def create(self,body=None):
        result=self.client.post('/trades',json=body or trade())
        self.assertEqual(result.status_code,201,result.text)
        return result.json()

    def setup(self,snap=None):
        return sd.store_snapshot(uuid4(),{},snap or snapshot())

    def url(self,record): return '/trades/'+record['id']

    def test_manual_entry_is_saved_without_inventing_evidence_and_survives_restart(self):
        record=self.create()
        self.assertEqual(record['status'],'open')
        self.assertIsNone(record['context']['setup'])
        self.assertEqual(record['context_timing'],'self_reported')
        self.assertEqual(record['review']['discipline'],'not_reviewed')
        self.assertIsNone(record['result'])
        td.init_trade_db()
        self.assertEqual(self.client.get(self.url(record)).json(),record)

    def test_linked_copy_retains_strategy_plan_and_zones_after_source_deletion(self):
        source=self.setup(snapshot(trade_plan={'entry_price':'1.1','stop_loss':'1.098','take_profit':'1.104'}))
        body=trade(setup_id=source['id']); record=self.create(body)
        context=record['context']
        self.assertEqual(context['setup'],source)
        self.assertEqual(context['setup']['snapshot']['rule_evaluation']['rule_set']['id'],'four_factor_v7')
        self.assertEqual(record['context_timing'],'retrospective')
        self.assertEqual(self.client.delete('/setup-snapshots/'+source['id']).status_code,204)
        self.assertEqual(self.client.get(self.url(record)).json(),record)
        self.assertEqual(self.create(body),record)
        self.assertEqual(self.client.post('/trades',json=trade(setup_id=source['id'])).status_code,404)
        td.init_trade_db(); sd.init_setup_db()
        self.assertEqual(td.fetch_trade(record['id'])['context'],context)

    def test_equivalent_timezone_retry_is_idempotent_and_changed_inputs_conflict(self):
        body=trade(); record=self.create(body)
        equivalent={**body,'entry_at':datetime.fromisoformat(body['entry_at']).astimezone(timezone(timedelta(hours=-4))).isoformat()}
        self.assertEqual(self.create(equivalent),record)
        self.assertEqual(self.client.post('/trades',json={**body,'entry_price':'1.10001'}).status_code,409)
        self.assertEqual(td.list_trades()['total'],1)

    def test_valid_long_short_flat_fractional_and_gap_results(self):
        cases=[('long','1.10400','1.09800','+40.0','2'),('short','1.09600','1.10200','+40.0','2'),
               ('long','1.09600','1.09800','-40.0','-2'),('short','1.10400','1.10200','-40.0','-2'),
               ('long','1.10000','1.09800','0.0','0'),('long','1.10001','1.09997','+0.1','0.3333333333333333333333333333')]
        for direction,closed,stop,pips,multiple in cases:
            result=trade_outcome({'direction':direction,'entry_price':'1.10000','initial_stop_loss':stop},{'exit_price':closed})
            self.assertEqual(result['pips'],pips)
            self.assertEqual(Decimal(result['r_multiple']),Decimal(multiple))
        tiny=trade_outcome({'direction':'long','entry_price':'1.1','initial_stop_loss':'.1'},{'exit_price':'1.10001'})
        self.assertEqual(tiny['r_display'],'+<0.01')

    def test_full_exit_saves_actual_result_independently_of_discipline(self):
        record=self.create(); body=full_exit(exit_price='1.09800')
        closed=self.client.post(self.url(record)+'/close',json=body).json()
        self.assertEqual(closed['status'],'closed')
        self.assertEqual((closed['result']['pips'],closed['result']['r_display']),('-20.0','-1.00'))
        self.assertEqual(closed['review']['discipline'],'not_reviewed')
        reviewed=self.client.post(self.url(record)+'/reviews',json={'request_id':str(uuid4()),'expected_revision':0,'discipline':'followed','notes':'A planned loss; I followed my rules.'}).json()
        self.assertEqual(reviewed['result']['outcome'],'negative')
        self.assertEqual(reviewed['review']['discipline'],'followed')
        self.assertEqual(reviewed['evidence_hash'],record['evidence_hash'])
        self.assertEqual(self.client.post(self.url(record)+'/close',json=body).json(),reviewed)
        self.assertEqual(self.client.post(self.url(record)+'/close',json=full_exit()).status_code,409)

    def test_absent_stop_and_target_are_recorded_honestly_with_no_r(self):
        record=self.create(trade(initial_stop_loss=None,initial_take_profit=None))
        closed=self.client.post(self.url(record)+'/close',json=full_exit()).json()
        self.assertEqual(closed['result']['pips'],'+40.0')
        self.assertIsNone(closed['result']['r_multiple'])
        self.assertIsNone(closed['result']['initial_risk_pips'])
        self.assertIsNone(closed['result']['r_display'])

    def test_input_validation_rejects_forged_values_invalid_prices_and_levels(self):
        for change in ({'entry_price':'NaN'},{'entry_price':'0'},{'entry_price':True},{'entry_price':'1.123456'},
                       {'initial_stop_loss':'1.1'},{'initial_take_profit':'1.1'},{'direction':'short'},
                       {'entry_at':'2026-10-20T12:00:00'},{'entry_reason':' '},{'instrument':'GBP_USD'},
                       {'timeframe':'H1'},{'context':{}},{'result':{'pips':99}},{'rule_evaluation':{}},
                       {'entry_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}):
            with self.subTest(change=change):
                response=self.client.post('/trades',json=trade(**change))
                self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(td.list_trades()['total'],0)

    def test_future_cutoff_candles_reference_and_wrong_pair_are_rejected(self):
        cases=[]
        later=(NOW+timedelta(hours=1)).isoformat()
        snap=snapshot(); snap['cutoff_at']=later; cases.append(snap)
        snap=snapshot(); snap['source_candles'][-1]['close_time']=later; cases.append(snap)
        snap=snapshot(); snap['reference_price']['time']=later; cases.append(snap)
        snap=snapshot(); snap['instrument']='GBP_USD'; cases.append(snap)
        for snap in cases:
            source=self.setup(snap)
            response=self.client.post('/trades',json=trade(setup_id=source['id']))
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(td.list_trades()['total'],0)

    def test_timing_distinguishes_captured_before_entry_from_retrospective_annotations(self):
        source=self.setup(); source=deepcopy(source)
        source['created_at']=NOW.isoformat(); source['snapshot']['captured_at']=NOW.isoformat(); source['snapshot']['mode']='live'
        entry=TradeInput(**trade())
        self.assertEqual(entry_context(entry,source,NOW)['timing'],'captured_before_entry')
        source['snapshot']['finalized_at']=(NOW+timedelta(hours=1)).isoformat()
        self.assertEqual(entry_context(entry,source,NOW)['timing'],'retrospective')
        source['snapshot']['mode']='historical'; source['snapshot']['finalized_at']=NOW.isoformat()
        self.assertEqual(entry_context(entry,source,NOW)['timing'],'retrospective')

    def test_exit_validation_prevents_future_earlier_or_injected_results(self):
        record=self.create()
        for changes in ({'exit_price':'Infinity'},{'exit_price':'-1'},{'result':{}},
                        {'exit_at':NOW.isoformat()}, {'exit_at':'2026-10-22T12:00:00'},
                        {'exit_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}):
            response=self.client.post(self.url(record)+'/close',json=full_exit(**changes))
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(td.fetch_trade(record['id'])['status'],'open')

    def test_reviews_append_and_stale_writers_cannot_overwrite_a_newer_review(self):
        record=self.create(); url=self.url(record)+'/reviews'
        first={'request_id':str(uuid4()),'expected_revision':0,'discipline':'deviated','notes':'Entered early.'}
        one=self.client.post(url,json=first).json()
        self.assertEqual(one['review']['revision'],1)
        self.assertEqual(self.client.post(url,json=first).json(),one)
        self.assertEqual(self.client.post(url,json={**first,'notes':'Changed'}).status_code,409)
        self.assertEqual(self.client.post(url,json={**first,'request_id':str(uuid4())}).status_code,409)
        two=self.client.post(url,json={'request_id':str(uuid4()),'expected_revision':1,'discipline':'followed','notes':'Corrected my self-review after checking my plan.'}).json()
        self.assertEqual([row['discipline'] for row in two['reviews']],['followed','deviated'])
        self.assertEqual(two['entry'],record['entry']); self.assertEqual(two['context'],record['context'])
        self.assertIsNone(two['result'])

    def test_request_ids_cannot_be_reused_for_another_trade_exit_or_review(self):
        a,b=self.create(),self.create()
        closed=full_exit()
        self.assertEqual(self.client.post(self.url(a)+'/close',json=closed).status_code,200)
        self.assertEqual(self.client.post(self.url(b)+'/close',json=closed).status_code,409)
        reviewed={'request_id':str(uuid4()),'expected_revision':0,'discipline':'followed','notes':''}
        self.assertEqual(self.client.post(self.url(a)+'/reviews',json=reviewed).status_code,200)
        self.assertEqual(self.client.post(self.url(b)+'/reviews',json=reviewed).status_code,409)

    def test_raw_entry_exit_and_review_mutations_are_blocked(self):
        record=self.create()
        self.client.post(self.url(record)+'/close',json=full_exit())
        self.client.post(self.url(record)+'/reviews',json={'request_id':str(uuid4()),'expected_revision':0,'discipline':'followed','notes':''})
        for table in ('trades','trade_exits','trade_reviews'):
            for statement in (f'DELETE FROM {table}',f"UPDATE {table} SET created_at='changed'"):
                with self.assertRaises(sqlite3.IntegrityError),db.get_connection(write=True) as con: con.execute(statement)
        self.assertEqual(td.fetch_trade(record['id'])['evidence_hash'],record['evidence_hash'])

    def test_corrupt_entry_evidence_refuses_detail_close_and_review(self):
        record=self.create()
        with db.get_connection(write=True) as con:
            con.execute('DROP TRIGGER trades_no_update'); con.execute("UPDATE trades SET evidence_hash='bad'")
        self.assertEqual(self.client.get(self.url(record)).status_code,409)
        self.assertEqual(self.client.post(self.url(record)+'/close',json=full_exit()).status_code,409)
        self.assertEqual(self.client.post(self.url(record)+'/reviews',json={'request_id':str(uuid4()),'expected_revision':0,'discipline':'followed'}).status_code,409)

    def test_close_storage_failure_rolls_back_and_keeps_entry(self):
        record=self.create()
        with db.get_connection(write=True) as con:
            con.execute("CREATE TRIGGER fail_exit AFTER INSERT ON trade_exits BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError): td.close_trade(record['id'],TradeCloseInput(**full_exit()))
        self.assertEqual(td.fetch_trade(record['id']),record)

    def test_listing_filters_paginates_and_unknown_routes_do_not_mutate(self):
        records=[self.create(trade(title=f'Trade {i}')) for i in range(21)]
        self.client.post(self.url(records[0])+'/close',json=full_exit())
        self.assertEqual(self.client.get('/trades?status=open').json()['total'],20)
        self.assertEqual(self.client.get('/trades?status=closed').json()['total'],1)
        page=self.client.get('/trades?offset=20').json()
        self.assertEqual((page['total'],len(page['items'])),(21,1))
        self.assertNotIn('context',page['items'][0])
        for query in ('status=bad','limit=101','offset=-1'): self.assertEqual(self.client.get('/trades?'+query).status_code,422)
        self.assertEqual(self.client.get('/trades/'+str(uuid4())).status_code,404)
        self.assertEqual(self.client.get('/trades/bad').status_code,422)

    def test_concurrent_setup_delete_either_prevents_capture_or_preserves_copied_evidence(self):
        source=self.setup(); barrier=Barrier(2)
        def create():
            barrier.wait(timeout=5)
            try: return td.create_trade(TradeInput(**trade(setup_id=source['id'])))
            except td.TradeNotFound: return None
        def delete():
            barrier.wait(timeout=5)
            return sd.delete_snapshot(source['id'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            a,b=pool.submit(create),pool.submit(delete)
            record,removed=a.result(timeout=10),b.result(timeout=10)
        self.assertTrue(removed)
        if record: self.assertEqual(td.fetch_trade(record['id'])['context']['setup'],source)
        else: self.assertEqual(td.list_trades()['total'],0)

    def test_migration_preserves_other_tables_and_versions(self):
        source=self.setup(); profile=db.insert_strategy_profile('Keep','Rules')
        td.init_trade_db(); td.init_trade_db()
        self.assertEqual(sd.fetch_snapshot(source['id']),source)
        self.assertEqual(db.fetch_strategy_profile(profile['id']),profile)
        with db.get_connection() as con:
            self.assertEqual([r[0] for r in con.execute('SELECT version FROM trade_schema_migrations ORDER BY version')],[1,2,3,4])
            self.assertEqual([r[0] for r in con.execute('SELECT version FROM setup_schema_migrations ORDER BY version')],[1,2,3])
