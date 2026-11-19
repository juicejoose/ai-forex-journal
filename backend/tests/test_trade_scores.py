"""Trade scores use immutable entry evidence and only closes occurring during the hold."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timedelta
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from tests.test_setup_evaluator import main, ENVIRONMENT
from tests.test_trade_log import trade,full_exit
from tests.test_trade_timeline import provider,at,NOW,ENTERED
import database as db
import trade_database as td
import trade_scores as ts
import trade_timeline as tl
import market_data as md
from trade_models import TradeCloseInput

EXIT='2026-11-09T14:30:00-05:00'

class Clock(datetime):
    value=NOW
    @classmethod
    def now(cls,tz=None): return cls.value.astimezone(tz)


class TradeScoreTests(unittest.TestCase):
    def setUp(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db,'DB_PATH',root/'test.db'))
        self.enterContext(patch.dict(os.environ,ENVIRONMENT,clear=True))
        self.client=self.enterContext(TestClient(main.app))
        self.ai=self.enterContext(patch.object(main.client.responses,'create',side_effect=AssertionError('No AI call')))
        self.enterContext(patch.object(ts,'datetime',Clock)); Clock.value=NOW
        self.market=self.enterContext(patch.object(md,'_fetch_candles',side_effect=provider(NOW)))

    def create(self,entry_at=ENTERED,exit_at=None,direction='long'):
        body=trade(entry_at=entry_at,direction=direction,initial_stop_loss=None,initial_take_profit=None)
        response=self.client.post('/trades',json=body)
        self.assertEqual(response.status_code,201,response.text)
        record=response.json()
        if exit_at:
            response=self.client.post('/trades/'+record['id']+'/close',json=full_exit(exit_at=exit_at))
            self.assertEqual(response.status_code,200,response.text)
            record=response.json()
        return record

    def scores(self,record):
        response=self.client.post('/trades/'+record['id']+'/scores',json={})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_entry_uses_latest_completed_candle_not_session_average_or_entry_bar(self):
        record=self.create(exit_at=EXIT); result=self.scores(record)
        original=result['entry_analysis']['analysis']['reconstructed_snapshot']['rule_evaluation']
        score=result['entry_score']
        self.assertEqual(score['candle'],original['candles'][-1])
        self.assertEqual(score['summary']['method'],'latest_completed_at_entry')
        self.assertEqual(score['data_through'],at('2026-11-09T09:00:00-05:00').isoformat())
        self.assertEqual(score['summary']['bullish_points'],original['session_end']['bullish_points'])
        self.assertEqual(score['summary']['bearish_points'],original['session_end']['bearish_points'])
        self.assertEqual(score['summary']['max_points'],5)
        self.assertIsNotNone(result['saved_at'])
        self.assertEqual(td.fetch_trade(record['id'])['entry'],record['entry'])

    def test_full_average_only_includes_closes_after_entry_and_by_exit(self):
        Clock.value=at('2026-11-10T18:00:00-05:00'); self.market.side_effect=provider(Clock.value)
        record=self.create(exit_at='2026-11-10T14:30:00-05:00'); result=self.scores(record)
        full=result['full_trade']; rows=full['candles']
        self.assertEqual(len(rows),7)
        self.assertEqual(rows[0]['close_time'],at('2026-11-09T13:00:00-05:00').isoformat())
        self.assertEqual(rows[-1]['close_time'],at('2026-11-10T13:00:00-05:00').isoformat())
        self.assertTrue(full['exit_candle_excluded']);self.assertTrue(full['entry_candle_includes_pre_entry_prices'])
        for side in ('bullish','bearish'):
            self.assertEqual(full['summary'][side+'_points'],sum(row[side+'_points'] for row in rows)/7)
        self.assertEqual(full['summary']['net_score'],sum(row['net_score'] for row in rows)/7)
        self.assertTrue(all(at(c['close_time'])<=at(record['exit']['exit_at']) for c in full['source_candles']))
        self.assertTrue(all('start' not in call.kwargs for call in self.market.call_args_list))
        self.assertEqual(self.market.call_args.args[0],at(record['exit']['exit_at']))

    def test_exact_entry_and_exit_boundaries_are_not_double_counted(self):
        result=self.scores(self.create(entry_at='2026-11-09T13:00:00-05:00',exit_at='2026-11-09T17:00:00-05:00'))
        self.assertEqual(result['entry_score']['data_through'],at('2026-11-09T13:00:00-05:00').isoformat())
        self.assertEqual(len(result['full_trade']['candles']),1)
        self.assertEqual(result['full_trade']['candles'][0]['close_time'],at('2026-11-09T17:00:00-05:00').isoformat())
        self.assertFalse(result['full_trade']['entry_candle_includes_pre_entry_prices'])
        self.assertFalse(result['full_trade']['exit_candle_excluded'])

    def test_no_completed_close_is_unavailable_not_zero(self):
        record=self.create(exit_at='2026-11-09T10:30:00-05:00'); result=self.scores(record)
        self.assertEqual(result['full_trade']['summary']['candle_count'],0)
        self.assertIsNone(result['full_trade']['summary']['net_score'])
        self.assertEqual(result['full_trade']['source_candles'],[])
        self.assertIsNotNone(result['entry_score']['summary']['net_score'])
        self.assertEqual(self.market.call_count,1)  # Entry reconstruction only.

    def test_long_and_short_support_swap_but_market_direction_does_not(self):
        a=self.scores(self.create(exit_at=EXIT,direction='long'))
        b=self.scores(self.create(exit_at=EXIT,direction='short'))
        for section in ('entry_score','full_trade'):
            left,right=a[section]['summary'],b[section]['summary']
            self.assertEqual(left['supporting_points'],right['conflicting_points'])
            self.assertEqual(left['direction'],right['direction'])
            self.assertEqual(left['net_score'],right['net_score'])

    def test_open_average_grows_only_when_candles_close_and_entry_stays_fixed(self):
        record=self.create(); first=self.scores(record)
        self.assertIsNone(first['saved_at']);self.assertEqual(first['full_trade']['summary']['method'],'trade_to_date_average')
        self.assertEqual(first['full_trade']['summary']['candle_count'],6)
        original_entry=deepcopy(first['entry_score'])
        Clock.value=NOW+timedelta(hours=4)
        self.market.side_effect=provider(Clock.value)
        later=self.scores(record)
        self.assertEqual(later['full_trade']['summary']['candle_count'],7)
        self.assertEqual(later['entry_score'],original_entry)
        with db.get_connection() as con:self.assertEqual(con.execute('SELECT count(*) FROM trade_score_snapshots').fetchone()[0],0)

    def test_missing_period_data_preserves_entry_and_retry_can_complete(self):
        Clock.value=at('2026-11-10T18:00:00-05:00')
        record=self.create(exit_at='2026-11-10T14:30:00-05:00')
        fetch=provider(Clock.value); missing=at('2026-11-09T13:00:00-05:00')
        def gap(end,count=350,*,start=None):
            raw=fetch(end,count,start=start)
            raw['candles']=[r for r in raw['candles'] if at(r['time'])!=missing]
            return raw
        self.market.side_effect=gap
        failed=self.scores(record)
        self.assertIn('missing',failed['full_trade']['error'])
        self.assertIsNone(failed['full_trade']['summary'])
        self.assertIsNotNone(failed['entry_score'])
        self.assertIsNone(failed['saved_at'])
        self.market.side_effect=provider(at('2026-11-10T18:00:00-05:00'))
        self.assertIsNotNone(self.scores(record)['saved_at'])

    def test_forming_and_post_exit_prices_never_change_scores(self):
        record=self.create(exit_at=EXIT)
        entry=td.analyze_trade(record['id'],ts.TradeAnalysisInput(request_id=uuid4(),source='entry_time'))
        saved=entry['strategy_analyses'][0]
        baseline=ts.build_scores(entry,saved,NOW)
        fetch=provider(NOW)
        def changed(end,count=350,*,start=None):
            raw=fetch(end,count,start=start)
            for row in raw['candles']:
                if at(row['time'])>=at('2026-11-09T13:00:00-05:00'):row['mid'].update(c='1.5',h='1.6')
            return raw
        self.market.side_effect=changed
        self.assertEqual(ts.build_scores(entry,saved,NOW),baseline)

    def test_closed_score_survives_restart_without_provider_calls(self):
        record=self.create(exit_at=EXIT); first=self.scores(record)
        td.init_trade_db();self.market.side_effect=AssertionError('Frozen scores must not refresh')
        self.assertEqual(self.scores(record),first)
        self.ai.assert_not_called()

    def test_closed_score_guards_hash_and_atomic_storage(self):
        record=self.create(exit_at=EXIT);self.scores(record)
        for statement in ('DELETE FROM trade_score_snapshots',"UPDATE trade_score_snapshots SET score_hash='bad'"):
            with self.assertRaises(sqlite3.IntegrityError),db.get_connection(write=True) as con:con.execute(statement)
        with db.get_connection(write=True) as con:
            con.execute('DROP TRIGGER trade_score_snapshots_no_update');con.execute("UPDATE trade_score_snapshots SET score_hash='bad'")
        self.assertEqual(self.client.post('/trades/'+record['id']+'/scores',json={}).status_code,409)

    def test_deletion_removes_scores_and_delayed_work_cannot_restore_them(self):
        record=self.create(exit_at=EXIT);self.scores(record)
        self.assertEqual(self.client.delete('/trades/'+record['id']).status_code,204)
        with db.get_connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM trade_score_snapshots').fetchone()[0],0)
            self.assertEqual(list(con.execute('PRAGMA foreign_key_check')),[])
        self.assertEqual(self.client.post('/trades/'+record['id']+'/scores',json={}).status_code,404)
        record=self.create(exit_at=EXIT); original=ts.build_scores
        def deleting(*args):
            result=original(*args);td.delete_trade(record['id']);return result
        with patch.object(ts,'build_scores',side_effect=deleting):
            self.assertEqual(self.client.post('/trades/'+record['id']+'/scores',json={}).status_code,404)

    def test_exit_saved_during_calculation_rebuilds_with_exit_cutoff(self):
        record=self.create();original=ts.build_scores;calls=[]
        def closing(*args):
            result=original(*args);calls.append(result)
            if len(calls)==1:td.close_trade(record['id'],TradeCloseInput(**full_exit(exit_at=EXIT)))
            return result
        with patch.object(ts,'build_scores',side_effect=closing):result=self.scores(record)
        self.assertEqual(len(calls),2)
        self.assertEqual(result['status'],'closed')
        self.assertEqual(result['full_trade']['summary']['candle_count'],1)
        self.assertIsNotNone(result['saved_at'])

    def test_concurrent_closed_calculations_keep_one_snapshot(self):
        record=self.create(exit_at=EXIT)
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:ts.calculate_scores(record['id']),range(2)))
        self.assertEqual(results[0],results[1])
        with db.get_connection() as con:self.assertEqual(con.execute('SELECT count(*) FROM trade_score_snapshots').fetchone()[0],1)

    def test_failed_final_storage_rolls_back_and_keeps_entry_evidence(self):
        record=self.create(exit_at=EXIT)
        with db.get_connection(write=True) as con:
            con.execute("CREATE TRIGGER fail_score AFTER INSERT ON trade_score_snapshots BEGIN SELECT RAISE(ABORT,'rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):ts.calculate_scores(record['id'])
        with db.get_connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM trade_score_snapshots').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT count(*) FROM trade_strategy_analyses').fetchone()[0],1)

    def test_weekend_dst_and_multi_session_closes_are_counted_equally(self):
        record=self.create(entry_at='2026-10-30T13:30:00-04:00',exit_at='2026-11-02T10:30:00-05:00')
        result=self.scores(record);rows=result['full_trade']['candles']
        self.assertEqual(len(rows),5)
        self.assertEqual(rows[0]['close_time'],at('2026-10-30T17:00:00-04:00').isoformat())
        self.assertEqual(rows[1]['open_time'],at('2026-11-01T17:00:00-05:00').isoformat())
        self.assertEqual(result['full_trade']['summary']['net_score'],sum(row['net_score'] for row in rows)/5)

    def test_unavailable_factor_withholds_average_and_never_becomes_zero(self):
        record=self.create(exit_at=EXIT); original=md._indicator_rows
        def missing(*args,**kwargs):
            rows=original(*args,**kwargs)
            # Affect only the first in-trade close, after entry reconstruction.
            for row in rows:
                if at(row['close_time'])==at('2026-11-09T13:00:00-05:00'):row['indicators']['rsi14_sma14']=None
            return rows
        with patch.object(md,'_indicator_rows',side_effect=missing):result=self.scores(record)
        self.assertEqual(result['full_trade']['summary']['direction'],'insufficient_data')
        self.assertIsNone(result['full_trade']['summary']['net_score'])
        self.assertIsNotNone(result['entry_score']['summary']['net_score'])

    def test_unknown_ids_and_client_scores_are_rejected(self):
        self.assertEqual(self.client.post('/trades/'+str(uuid4())+'/scores',json={}).status_code,404)
        self.assertEqual(self.client.post('/trades/bad/scores',json={}).status_code,422)
        record=self.create()
        self.assertEqual(self.client.post('/trades/'+record['id']+'/scores',json={'net_score':5}).status_code,422)
        self.market.assert_not_called()

    def test_v3_upgrade_preserves_records_and_adds_score_storage(self):
        record=self.create()
        with db.get_connection(write=True) as con:
            con.execute('DROP TABLE trade_score_snapshots');con.execute('DELETE FROM trade_schema_migrations WHERE version=4')
        td.init_trade_db();td.init_trade_db()
        self.assertEqual(td.fetch_trade(record['id']),record)
        self.assertIsNotNone(self.scores(record)['entry_score'])
