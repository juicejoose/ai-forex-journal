"""Offline trade alignment: fixed evidence, actual direction, boundaries and storage."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
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
from tests.test_trade_log import trade, full_exit
from tests.test_today import NOW, instant
from tests.test_custom_range import range_payload
from strategy_rules import evaluate_strategy
from trade_models import TradeInput, TradeAnalysisInput
from trade_calculations import TradeInputError
import trade_analysis as analysis
import trade_database as td
import setup_database as sd
import setup_market as sm
import database as db
import market_data as md


def compare(snap=None, direction='long', entry_at=None):
    values=trade(direction=direction, entry_at=(entry_at or NOW).isoformat())
    return analysis.build_analysis(values,snap or snapshot(),'saved_setup','entry-hash','retrospective')


class ComparisonTests(unittest.TestCase):
    def test_actual_short_direction_reverses_support_without_changing_saved_long_setup(self):
        snap=snapshot(); original=deepcopy(snap)
        long,short=compare(snap),compare(snap,'short')
        self.assertEqual(snap,original)
        self.assertEqual(short['trade_direction'],'short')
        self.assertEqual(long['summary']['supporting_points'],short['summary']['conflicting_points'])
        self.assertEqual(long['summary']['conflicting_points'],short['summary']['supporting_points'])
        for a,b in zip(long['factors'],short['factors']):
            self.assertEqual(a['latest']['result'],b['latest']['result'])
            self.assertEqual(a['counts']['supporting'],b['counts']['conflicting'])
        self.assertEqual(long['factors'][0]['latest']['relation'],'supporting')
        self.assertEqual(short['factors'][0]['latest']['relation'],'conflicting')

    def test_mixed_factor_history_keeps_both_averages_and_latest_separate(self):
        result=compare(); momentum=result['factors'][3]
        self.assertEqual(momentum['counts'],dict(supporting=1,conflicting=2,neutral=0,unavailable=0))
        self.assertEqual(momentum['latest']['relation'],'conflicting')
        self.assertAlmostEqual(momentum['average_supporting_points'],1/3)
        self.assertGreater(momentum['average_conflicting_points'],0)
        self.assertEqual(result['coverage']['candle_count'],3)
        self.assertEqual(result['summary']['max_points'],5)

    def test_neutral_is_not_missing_and_reduced_ema_points_keep_original_weight(self):
        result=compare(); ema=result['factors'][1]; rsi=result['factors'][2]
        self.assertEqual(ema['max_points'],2)
        self.assertEqual(ema['latest']['supporting_points'],1)
        self.assertTrue(ema['latest']['result']['ema_sma_distance']['reduced'])
        self.assertEqual(rsi['latest']['relation'],'neutral')
        self.assertEqual(rsi['latest']['supporting_points'],0)

    def test_unavailable_reading_withholds_factor_average_and_overall_summary(self):
        snap=snapshot()
        snap['market_data']['candles'][0]['indicators']['rsi14_sma14']=None
        snap['market_data']['candles'][-1]['indicators']['rsi14_sma14']=65
        snap['rule_evaluation']=evaluate_strategy(snap['market_data'],allow_partial=True)
        snap['rule_evaluation']['summary']['method']='session_to_date'
        result=compare(snap)
        self.assertEqual(result['summary']['relation'],'unavailable')
        self.assertIsNone(result['summary']['supporting_points'])
        factor=result['factors'][2]
        self.assertGreater(factor['counts']['unavailable'],0)
        self.assertIsNone(factor['average_supporting_points'])
        self.assertEqual(factor['latest']['relation'],'conflicting')

    def test_saved_strategy_version_and_half_point_values_are_preserved(self):
        snap=snapshot()
        # V3's sign-based momentum differs from the current strategy. Keep those saved results.
        snap['rule_evaluation']=evaluate_strategy(snap['market_data'],'four_factor_v3',allow_partial=True)
        result=compare(snap)
        self.assertEqual(result['rule_set']['id'],'four_factor_v3')
        self.assertEqual(result['summary']['method'],'final_candle')
        for source,shown in zip(snap['rule_evaluation']['candles'][-1]['factors'],result['factors']):
            self.assertEqual(source,shown['latest']['result'])
        # The existing evaluator remains the source for any fractional result.
        current=snapshot()
        for row in current['rule_evaluation']['candles']:
            for factor in row['factors']:
                if factor['outcome'] in ('bullish','bearish'):
                    factor[factor['outcome']+'_points']=0.5
        from strategy_rules import _session_average
        current['rule_evaluation']['summary']=_session_average(current['rule_evaluation']['candles'],5)
        result=compare(current)
        self.assertEqual(result['factors'][0]['latest']['supporting_points'],0.5)
        self.assertEqual(result['summary']['max_points'],5)

    def test_older_setup_is_flagged_when_another_candle_closed_before_entry(self):
        result=compare(entry_at=NOW+timedelta(hours=4))
        self.assertFalse(result['coverage']['covers_latest_scheduled_close'])
        self.assertEqual(result['coverage']['cutoff_age_seconds'],14400)
        self.assertEqual(result['coverage']['latest_scheduled_close'],(NOW+timedelta(hours=3)).isoformat())

    def test_same_candle_does_not_create_arbitrary_stale_threshold(self):
        result=compare(entry_at=NOW+timedelta(hours=2))
        self.assertTrue(result['coverage']['covers_latest_scheduled_close'])
        self.assertGreater(result['coverage']['last_close_age_seconds'],3600)

    def test_future_cutoff_candle_reference_factor_or_incomplete_candle_is_rejected(self):
        later=(NOW+timedelta(hours=1)).isoformat()
        for change in ('cutoff','raw','reference','factor','incomplete','invalid_points','summary'):
            snap=snapshot()
            if change=='cutoff': snap['cutoff_at']=later
            if change=='raw': snap['source_candles'][-1]['close_time']=later
            if change=='reference': snap['reference_price']['time']=later
            if change=='factor': snap['rule_evaluation']['candles'][0]['factors'][0]['evidence'][0]['close_time']=later
            if change=='incomplete': snap['market_data']['candles'][-1]['complete']=False
            if change=='invalid_points': snap['rule_evaluation']['candles'][0]['factors'][0]['bullish_points']=float('nan')
            if change=='summary': snap['rule_evaluation']['summary']['bullish_points']=99
            with self.subTest(change=change),self.assertRaises(TradeInputError): compare(snap)

    def test_schedule_handles_exact_boundary_weekend_and_both_dst_changes(self):
        cases=[('2026-10-23T08:59:59','2026-10-23T05:00:00'),('2026-10-23T09:00:00','2026-10-23T09:00:00'),
               ('2026-10-23T17:00:00','2026-10-23T17:00:00'),('2026-10-24T12:00:00','2026-10-23T17:00:00'),
               ('2026-10-25T17:00:00','2026-10-23T17:00:00'),('2026-10-26T18:00:00','2026-10-26T17:00:00'),
               ('2026-03-08T17:00:00','2026-03-06T17:00:00'),('2026-11-01T17:00:00','2026-10-30T17:00:00')]
        for entered,expected in cases:
            with self.subTest(entered=entered): self.assertEqual(analysis.latest_scheduled_close(instant(entered)),instant(expected))

    def test_reconstruction_only_uses_closed_candles_at_entry_and_never_requests_quote(self):
        at=instant('2026-10-23T08:59:59')
        with patch.object(md,'_fetch_candles',return_value=range_payload()),patch.object(sm,'fetch_quote') as quote:
            first=analysis.reconstruct_entry(trade(entry_at=at.isoformat()))
        quote.assert_not_called()
        self.assertEqual(len(first['market_data']['candles']),3)
        self.assertTrue(all(analysis._time(c['close_time'])<=at for c in first['source_candles']))
        raw=range_payload()
        for row in raw['candles']:
            if analysis._time(row['time'])+md.CANDLE_DURATION>at: row['mid']={key:'999' for key in 'ohlc'}
        with patch.object(md,'_fetch_candles',return_value=raw): second=analysis.reconstruct_entry(trade(entry_at=at.isoformat()))
        self.assertEqual(first['rule_evaluation'],second['rule_evaluation'])
        with patch.object(md,'_fetch_candles',return_value=range_payload()): exact=analysis.reconstruct_entry(trade(entry_at=instant('2026-10-23T09:00:00').isoformat()))
        self.assertEqual(len(exact['market_data']['candles']),4)

    def test_first_candle_pending_uses_explicit_earlier_session_context(self):
        at=instant('2026-10-22T18:00:00')
        with patch.object(md,'_fetch_candles',return_value=range_payload()): snap=analysis.reconstruct_entry(trade(entry_at=at.isoformat()))
        result=compare(snap,entry_at=at)
        self.assertTrue(result['coverage']['earlier_session'])
        self.assertEqual(result['coverage']['journal_date'],'2026-10-22')
        self.assertEqual(result['coverage']['candle_count'],6)
        self.assertTrue(result['coverage']['covers_latest_scheduled_close'])


class TradeAnalysisStorageTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db,'DB_PATH',self.root/'journal.db'))
        self.enterContext(patch.dict(os.environ,ENVIRONMENT,clear=True))
        self.client=self.enterContext(TestClient(main.app))
        self.ai=self.enterContext(patch.object(main.client.responses,'create',side_effect=AssertionError('No AI call')))
        self.quote=self.enterContext(patch.object(sm,'fetch_quote',side_effect=AssertionError('No live quote')))

    def tearDown(self):
        self.ai.assert_not_called(); self.quote.assert_not_called()

    def create(self,linked=False,**overrides):
        body=trade(**overrides)
        if linked:
            body['setup_id']=sd.store_snapshot(uuid4(),{},snapshot())['id']
        result=self.client.post('/trades',json=body)
        self.assertEqual(result.status_code,201,result.text)
        return result.json()

    def analyze(self,record,source='entry_time',request_id=None):
        return self.client.post('/trades/'+record['id']+'/strategy-analysis',json={'source':source,'request_id':request_id or str(uuid4())})

    def test_linked_entry_automatically_saves_direction_comparison_without_provider(self):
        snap=sd.store_snapshot(uuid4(),{},snapshot())
        with patch.object(md,'_fetch_candles',side_effect=AssertionError('No market fetch')):
            result=self.client.post('/trades',json=trade(setup_id=snap['id'],direction='short',initial_stop_loss='1.102',initial_take_profit='1.096'))
            self.assertEqual(result.status_code,201,result.text)
            record=result.json()
            comparison=record['strategy_analyses'][0]['analysis']
            self.assertEqual(comparison['trade_direction'],'short')
            self.assertEqual(comparison['factors'][0]['latest']['relation'],'conflicting')
            self.assertIsNone(comparison['reconstructed_snapshot'])
            sd.delete_snapshot(snap['id'])
            self.assertEqual(td.fetch_trade(record['id']),record)
            td.init_trade_db()
            self.assertEqual(td.fetch_trade(record['id']),record)

    def test_manual_reconstruction_is_saved_separately_without_replacing_entry(self):
        record=self.create(); original=deepcopy(record); request=str(uuid4())
        with patch.object(md,'_fetch_candles',return_value=range_payload()) as fetch:
            response=self.analyze(record,request_id=request)
            self.assertEqual(response.status_code,200,response.text)
            stored=response.json()
            self.assertEqual(self.analyze(record,request_id=request).json(),stored)
            self.assertEqual(self.analyze(record).json(),stored)
        self.assertEqual(fetch.call_count,1)
        for key in ('entry','context','evidence_hash','review','exit','result'): self.assertEqual(stored[key],original[key])
        payload=stored['strategy_analyses'][0]['analysis']
        self.assertEqual(payload['coverage']['timing'],'retrospective')
        self.assertEqual(payload['coverage']['cutoff_at'],record['entry']['entry_at'])
        self.assertEqual(payload['reconstructed_snapshot']['zones'],[])
        self.assertEqual(self.analyze(record,'saved_setup').status_code,422)

    def test_reconstructing_old_setup_preserves_both_sources(self):
        record=self.create(True,entry_at=(NOW+timedelta(hours=4)).isoformat())
        original=record['strategy_analyses'][0]
        self.assertFalse(original['analysis']['coverage']['covers_latest_scheduled_close'])
        with patch.object(md,'_fetch_candles',return_value=range_payload()): response=self.analyze(record)
        self.assertEqual(response.status_code,200,response.text)
        stored=response.json()
        self.assertEqual(len(stored['strategy_analyses']),2)
        self.assertEqual(stored['strategy_analyses'][0],original)
        self.assertTrue(stored['strategy_analyses'][1]['analysis']['coverage']['covers_latest_scheduled_close'])

    def test_pre_feature_trade_can_compare_its_preserved_setup_without_provider(self):
        record=self.create(True)
        # Simulate a v1 trade, which has immutable entry context but no v2 comparison row.
        with db.get_connection(write=True) as con:
            con.execute('DROP TRIGGER trade_strategy_analyses_no_delete')
            con.execute('DELETE FROM trade_strategy_analyses')
        sd.delete_snapshot(record['entry']['setup_id'])
        with patch.object(md,'_fetch_candles',side_effect=AssertionError('No refetch')):
            response=self.analyze(record,'saved_setup')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['strategy_analyses'][0]['analysis'],record['strategy_analyses'][0]['analysis'])

    def test_exit_and_self_review_do_not_change_or_enter_the_comparison(self):
        record=self.create(True); before=record['strategy_analyses']
        url='/trades/'+record['id']
        self.client.post(url+'/close',json=full_exit(exit_price='1.09800'))
        reviewed=self.client.post(url+'/reviews',json={'request_id':str(uuid4()),'expected_revision':0,'discipline':'followed','notes':'Outcome is not discipline.'}).json()
        self.assertEqual(reviewed['strategy_analyses'],before)
        encoded=json.dumps(before)
        for forbidden in ('exit_price','exit_notes','exit_at','Outcome is not discipline.','r_multiple'): self.assertNotIn(forbidden,encoded)

    def test_failed_provider_request_leaves_trade_unchanged_and_retry_can_succeed(self):
        record=self.create(); request=str(uuid4())
        with patch.object(md,'_fetch_candles',side_effect=md.MarketDataError('Unavailable',503)):
            self.assertEqual(self.analyze(record,request_id=request).status_code,503)
        self.assertEqual(td.fetch_trade(record['id']),record)
        with patch.object(md,'_fetch_candles',return_value=range_payload()): self.assertEqual(self.analyze(record,request_id=request).status_code,200)

    def test_future_reconstruction_is_rejected_before_storage(self):
        record=self.create(); snap=snapshot(); snap['cutoff_at']=(NOW+timedelta(hours=1)).isoformat()
        with patch.object(analysis,'reconstruct_entry',return_value=snap): self.assertEqual(self.analyze(record).status_code,422)
        self.assertEqual(td.fetch_trade(record['id']),record)

    def test_request_conflicts_invalid_inputs_and_missing_trade(self):
        a,b=self.create(),self.create(); request=str(uuid4())
        with patch.object(md,'_fetch_candles',return_value=range_payload()): self.assertEqual(self.analyze(a,request_id=request).status_code,200)
        self.assertEqual(self.analyze(b,request_id=request).status_code,409)
        self.assertEqual(self.analyze(a,'saved_setup',request).status_code,409)
        url='/trades/'+a['id']+'/strategy-analysis'
        for extra in ({'source':'live'},{'as_of':NOW.isoformat()},{'direction':'short'},{'snapshot':{}},{'points':5}):
            self.assertEqual(self.client.post(url,json={'source':'entry_time','request_id':str(uuid4()),**extra}).status_code,422)
        self.assertEqual(self.analyze({'id':str(uuid4())}).status_code,404)

    def test_concurrent_reconstructions_store_one_result(self):
        record=self.create(); snap=snapshot(); snap['cutoff_at']=record['entry']['entry_at']; barrier=Barrier(2)
        def fetch(entry): barrier.wait(timeout=5); return deepcopy(snap)
        def run(): return td.analyze_trade(record['id'],TradeAnalysisInput(source='entry_time',request_id=uuid4()))
        with patch.object(analysis,'reconstruct_entry',side_effect=fetch),ThreadPoolExecutor(max_workers=2) as pool:
            a,b=pool.submit(run),pool.submit(run)
            first,second=a.result(timeout=10),b.result(timeout=10)
        self.assertEqual(first,second)
        self.assertEqual(len(first['strategy_analyses']),1)

    def test_analysis_guards_and_integrity_checks(self):
        record=self.create(True)
        for sql in ('DELETE FROM trade_strategy_analyses',"UPDATE trade_strategy_analyses SET analysis_hash='changed'"):
            with self.assertRaises(sqlite3.IntegrityError),db.get_connection(write=True) as con: con.execute(sql)
        with db.get_connection(write=True) as con:
            con.execute('DROP TRIGGER trade_strategy_analyses_no_update')
            con.execute("UPDATE trade_strategy_analyses SET analysis_hash='changed'")
        self.assertEqual(self.client.get('/trades/'+record['id']).status_code,409)
        self.assertEqual(self.analyze(record).status_code,409)

    def test_v1_database_upgrade_preserves_entries_exits_reviews_and_guards(self):
        record=self.create(True)
        self.client.post('/trades/'+record['id']+'/close',json=full_exit())
        self.client.post('/trades/'+record['id']+'/reviews',json={'request_id':str(uuid4()),'expected_revision':0,'discipline':'followed','notes':'Keep this review.'})
        saved=td.fetch_trade(record['id'])
        with db.get_connection(write=True) as con:
            con.execute('DROP TABLE trade_strategy_analyses')
            con.execute('DELETE FROM trade_schema_migrations WHERE version=2')
        td.init_trade_db(); td.init_trade_db()
        updated=td.fetch_trade(record['id'])
        self.assertEqual(updated,{**saved,'strategy_analyses':[]})
        with self.assertRaises(sqlite3.IntegrityError),db.get_connection(write=True) as con:
            con.execute("UPDATE trades SET entry_at='changed'")
        self.assertEqual(self.analyze(record,'saved_setup').status_code,200)
