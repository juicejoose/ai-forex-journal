"""Near-threshold RSI-MA reductions, exact boundaries and persisted evidence."""
import json
import unittest
from datetime import date
from unittest.mock import patch
from uuid import uuid4
from tests.test_strategy_rules import scoring_snapshot
from tests.test_strategy_v5 import set_values
from tests.test_scored_journal import ScoredJournalTestCase, ENTRY, valid_scored_commentary
from tests.test_custom_range import range_snapshot
from tests.test_today import view_at
from strategy_rules import RULE_SET_ID, RSI_MA_RULE_SET_ID, evaluate_strategy, rule_set_definition
from scored_journal import build_summary_context
import date_range as dr
import database as db
import main
import market_data as md


def today_with_reduction():
    original = md._build_snapshot
    def build(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        set_values(snapshot, 'rsi14_sma14', [50,53,56,57,58])
        return snapshot
    with patch.object(md, '_build_snapshot', side_effect=build):
        return view_at()


class StrategyV7Tests(unittest.TestCase):
    def setUp(self): self.snapshot = scoring_snapshot()

    def factor(self, values):
        set_values(self.snapshot, 'rsi14_sma14', values)
        return evaluate_strategy(self.snapshot)['candles'][0]['factors'][2]

    def test_upper_band_includes_56_but_excludes_60(self):
        for value, side, points, proximity in [(55.999999,'bullish',1,None),(56,'bullish',.5,'overbought'),
                (59.999999,'bullish',.5,'overbought'),(60,'bearish',1,None),(61,'bearish',1,None)]:
            with self.subTest(value=value):
                factor=self.factor([50,53,value])
                self.assertEqual((factor['outcome'],factor[side+'_points'],factor['rsi_signal']['proximity']),(side,points,proximity))
                self.assertEqual(factor['rsi_signal']['reduced'],points==.5)

    def test_lower_band_includes_44_but_excludes_40(self):
        for value, side, points, proximity in [(44.000001,'bearish',1,None),(44,'bearish',.5,'oversold'),
                (40.000001,'bearish',.5,'oversold'),(40,'bullish',1,None),(34,'bullish',1,None)]:
            with self.subTest(value=value):
                factor=self.factor([50,47,value])
                self.assertEqual((factor['outcome'],factor[side+'_points'],factor['rsi_signal']['proximity']),(side,points,proximity))
                self.assertEqual(factor['rsi_signal']['reduced'],points==.5)

    def test_moving_away_from_threshold_keeps_full_point(self):
        for values,side in [([59,58,57],'bearish'),([41,42,43],'bullish')]:
            factor=self.factor(values)
            self.assertEqual(factor[side+'_points'],1)
            self.assertFalse(factor['rsi_signal']['reduced'])

    def test_mixed_and_equal_readings_near_threshold_do_not_earn_half_point(self):
        for values in ([54,58,57],[55,55,57],[55,57,57],[46,42,43],[45,45,43],[45,43,43]):
            factor=self.factor(values)
            self.assertEqual((factor['outcome'],factor['bullish_points'],factor['bearish_points']),('neutral',0,0))
            self.assertFalse(factor['rsi_signal']['reduced'])

    def test_missing_history_stays_unavailable_but_extremes_use_threshold(self):
        for values in ([None,53,57],[50,None,57],[50,47,None]):
            factor=self.factor(values)
            self.assertEqual(factor['outcome'],'unavailable')
            self.assertFalse(factor['rsi_signal']['reduced'])
            self.assertIsNone(evaluate_strategy(self.snapshot)['summary']['net_score'])
        self.assertEqual(self.factor([None,None,60])['bearish_points'],1)
        self.assertEqual(self.factor([None,None,40])['bullish_points'],1)

    def test_reduction_has_one_direction_and_cites_three_ma_readings(self):
        for values,side in [([50,53,56],'bullish'),([50,47,44],'bearish')]:
            factor=self.factor(values)
            self.assertEqual(factor[side+'_points'],.5)
            self.assertEqual(factor['bullish_points']+factor['bearish_points'],.5)
            self.assertEqual([e['values']['rsi14_sma14'] for e in factor['evidence']],values)
            self.assertEqual([e['candle_id'] for e in factor['evidence']],['P-1','P0','C1'])
            self.assertIn('reduced to 0.5',factor['reason'])

    def test_daily_average_and_reduced_count_include_all_half_points(self):
        set_values(self.snapshot,'rsi14_sma14',[50,53,56,57,58,59,60,61])
        result=evaluate_strategy(self.snapshot);old=evaluate_strategy(self.snapshot,RSI_MA_RULE_SET_ID)
        self.assertEqual(result['summary']['reduced_factors'],old['summary']['reduced_factors']+4)
        self.assertEqual(result['summary']['max_points'],5)
        self.assertEqual(result['summary']['net_score'],sum(c['net_score'] for c in result['candles'])/6)
        self.assertAlmostEqual(old['summary']['net_score']-result['summary']['net_score'],2/6)
        self.assertAlmostEqual(result['summary']['bullish_alignment_percent'],result['summary']['bullish_points']/5*100)
        self.assertEqual(result['session_end']['net_score'],old['session_end']['net_score'])

    def test_today_averages_only_completed_candles(self):
        result=today_with_reduction()['rule_evaluation']
        self.assertEqual(len(result['candles']),3)
        self.assertEqual(result['summary']['method'],'session_to_date')
        self.assertEqual(result['summary']['expected_factors'],12)
        self.assertEqual(result['summary']['net_score'],sum(c['net_score'] for c in result['candles'])/3)
        self.assertTrue(all(c['factors'][2]['bullish_points']==.5 for c in result['candles']))

    def test_range_uses_history_across_weekend(self):
        snapshot=range_snapshot(date(2026,10,16),date(2026,10,19))
        for candle,value in zip(snapshot['candles'][4:7],[50,53,56]):candle['indicators']['rsi14_sma14']=value
        result=dr.evaluate_range_strategy(snapshot);factor=result['candles'][6]['factors'][2]
        self.assertEqual(factor['bullish_points'],.5)
        self.assertEqual([e['candle_id'] for e in factor['evidence']],['C5','C6','C7'])
        self.assertEqual(result['summary']['net_score'],sum(c['net_score'] for c in result['candles'])/12)

    def test_v6_keeps_full_points_and_future_candles_cannot_change_earlier_rows(self):
        self.factor([50,53,56]);old=evaluate_strategy(self.snapshot,RSI_MA_RULE_SET_ID)
        self.assertEqual(old['candles'][0]['factors'][2]['bullish_points'],1)
        self.assertNotIn('reduced',old['candles'][0]['factors'][2]['rsi_signal'])
        before=evaluate_strategy(self.snapshot)
        self.snapshot['candles'][-1]['indicators']['rsi14_sma14']=57
        self.assertEqual(before['candles'][:-1],evaluate_strategy(self.snapshot)['candles'][:-1])
        self.assertNotIn('trend_reduction',rule_set_definition(RSI_MA_RULE_SET_ID)['factors'][2])


class StrategyV7JournalTests(ScoredJournalTestCase):
    entry={**ENTRY,'rule_set_id':RULE_SET_ID}

    def test_ai_saving_and_calendar_use_reduced_results(self):
        set_values(self.snapshot,'rsi14_sma14',[50,53,56,57,58,59,60,61]);draft=self.generate()
        sent=json.loads(self.ai.call_args.kwargs['input'])
        self.assertEqual(sent['rule_evaluation'],draft['rule_evaluation'])
        self.assertEqual(sent['rule_evaluation']['candles'][0]['factors'][2]['bullish_points'],.5)
        self.assertIn('rsi_signal.proximity',self.ai.call_args.kwargs['instructions'])
        saved=self.client.post('/journals',json={'generation_id':draft['generation_id'],'edited_draft':draft['draft']}).json()
        self.assertEqual(db.fetch_journal(saved['id'])['rule_evaluation'],draft['rule_evaluation'])
        expected=draft['rule_evaluation']['summary']['net_score']
        self.assertEqual(self.client.get('/journals').json()['items'][0]['average_net_score'],expected)
        self.assertEqual(self.client.get('/journals/calendar?month=2026-10').json()['days'][0]['average_net_score'],expected)

    def test_today_and_range_ai_receive_half_point_metadata(self):
        view=today_with_reduction();view['snapshot_id']=str(uuid4())
        custom=range_snapshot();set_values(custom,'rsi14_sma14',[50,53,56,57,58])
        with patch.object(main,'load_today_snapshot',return_value=view),patch.object(main,'get_range_market_data',return_value=custom):
            for endpoint,body,snapshot,evaluation in [
                ('/today/generate',{'snapshot_id':view['snapshot_id']},view['market_data'],view['rule_evaluation']),
                ('/range-journal/generate',{'start_date':'2026-10-19','end_date':'2026-10-23'},custom,dr.evaluate_range_strategy(custom))]:
                commentary=valid_scored_commentary(build_summary_context(snapshot,evaluation))
                for part in commentary.values():
                    for ref in part['results']:ref['candle_id']=evaluation['candles'][-1]['candle_id']
                self.ai.return_value.output_text=json.dumps(commentary)
                response=self.client.post(endpoint,json=body)
                self.assertEqual(response.status_code,200,response.text)
                sent=json.loads(self.ai.call_args.kwargs['input'])
                self.assertEqual(sent['rule_evaluation'],evaluation)
                self.assertEqual(sent['rule_evaluation']['candles'][0]['factors'][2]['bullish_points'],.5)

    def test_pending_v6_draft_keeps_original_points(self):
        set_values(self.snapshot,'rsi14_sma14',[50,53,56]);old=evaluate_strategy(self.snapshot,RSI_MA_RULE_SET_ID)
        pending=db.store_generated_draft({**self.entry,'rule_set_id':RSI_MA_RULE_SET_ID},'Pending v6',self.snapshot,old)
        self.generate();saved=db.save_generated_journal(pending,'Pending v6')
        self.assertEqual(db.fetch_journal(saved['id'])['rule_evaluation'],old)
        self.assertEqual(old['candles'][0]['factors'][2]['bullish_points'],1)
