"""MA-based threshold/trend scoring and immutable evidence across journal modes."""
import copy
import json
import unittest
from tests.test_strategy_rules import scoring_snapshot
from tests.test_strategy_v5 import set_values
from tests.test_scored_journal import ScoredJournalTestCase, ENTRY
from tests.test_journal_grounding import valid_analysis, STRATEGY
from strategy_rules import RSI_MA_RULE_SET_ID as RULE_SET_ID, TREND_RULE_SET_ID, evaluate_strategy as _evaluate_strategy, rule_set_definition
from journal_grounding import InvalidJournalEvidence, render_journal, build_evidence_catalog, _check_explanation
import database as db


def evaluate_strategy(snapshot, rule_set_id=RULE_SET_ID, **kwargs):
    return _evaluate_strategy(snapshot, rule_set_id, **kwargs)


class StrategyV6Tests(unittest.TestCase):
    def setUp(self): self.snapshot = scoring_snapshot()

    def factor(self, ma, raw=None):
        set_values(self.snapshot, 'rsi14_sma14', ma)
        if raw is not None: set_values(self.snapshot, 'rsi14', raw)
        return evaluate_strategy(self.snapshot)['candles'][0]['factors'][2]

    def test_threshold_boundaries_use_ma_even_when_raw_points_opposite_way(self):
        for ma, raw, outcome in [(40,70,'bullish'), (60,30,'bearish'), (0,100,'bullish'), (100,0,'bearish')]:
            factor = self.factor([50,50,ma], [50,50,raw])
            self.assertEqual(factor['outcome'], outcome)
            self.assertEqual(factor['rsi_signal']['source'], 'rsi14_sma14')
            self.assertEqual(factor['evidence'][-1]['values'], {'rsi14_sma14':ma})
            self.assertEqual(factor['bullish_points'] + factor['bearish_points'], 1)

    def test_three_ma_readings_control_trend_not_raw_readings(self):
        for ma, raw, outcome in [([42,48,55],[58,52,45],'bullish'), ([58,52,45],[42,48,55],'bearish'),
                                  ([45,45,50],[42,48,55],'neutral'), ([45,55,50],[42,48,55],'neutral')]:
            factor = self.factor(ma, raw)
            self.assertEqual(factor['outcome'], outcome)
            self.assertEqual([e['values']['rsi14_sma14'] for e in factor['evidence']], ma)

    def test_threshold_priority_and_in_band_precision(self):
        self.assertEqual(self.factor([30,35,40])['outcome'], 'bullish')
        self.assertEqual(self.factor([70,65,60])['outcome'], 'bearish')
        self.assertEqual(self.factor([45,40.000002,40.000001])['outcome'], 'bearish')
        self.assertEqual(self.factor([55,59.999998,59.999999])['outcome'], 'bullish')

    def test_missing_ma_never_falls_back_to_raw_and_withholds_average(self):
        self.factor([45,48,None], [30,30,30])
        result = evaluate_strategy(self.snapshot)
        self.assertEqual(result['candles'][0]['factors'][2]['outcome'], 'unavailable')
        self.assertIsNone(result['summary']['net_score'])
        del self.snapshot['candles'][0]['indicators']['rsi14_sma14']
        self.assertEqual(evaluate_strategy(self.snapshot)['candles'][0]['factors'][2]['outcome'], 'unavailable')

    def test_threshold_needs_current_ma_but_trend_needs_valid_consecutive_history(self):
        self.assertEqual(self.factor([None,None,40])['outcome'], 'bullish')
        self.assertEqual(self.factor([None,None,50])['outcome'], 'unavailable')
        self.factor([42,48,55])
        self.snapshot['previous_candles'][0]['close_time'] = self.snapshot['candles'][0]['close_time']
        self.assertEqual(evaluate_strategy(self.snapshot)['candles'][0]['factors'][2]['outcome'], 'unavailable')

    def test_settings_cannot_silently_use_another_ma(self):
        for settings in ({}, {'type':'ema','period':14,'source':'rsi14'}, {'type':'sma','period':7,'source':'rsi14'},
                         {'type':'sma','period':14,'source':'close'}):
            self.snapshot['indicator_settings']['rsi_ma'] = settings
            with self.assertRaises(InvalidJournalEvidence): evaluate_strategy(self.snapshot)
            evaluate_strategy(self.snapshot, TREND_RULE_SET_ID)

    def test_future_readings_do_not_change_earlier_scores_and_all_candles_count(self):
        set_values(self.snapshot, 'rsi14_sma14', [42,44,46,48,47,46,46,50])
        before = evaluate_strategy(self.snapshot)
        self.snapshot['candles'][-1]['indicators']['rsi14_sma14'] = 70
        after = evaluate_strategy(self.snapshot)
        self.assertEqual(before['candles'][:-1], after['candles'][:-1])
        self.assertAlmostEqual(after['summary']['net_score'], sum(c['net_score'] for c in after['candles']) / 6)

    def test_v5_keeps_raw_source_and_original_definition(self):
        self.factor([42,48,55], [58,52,45])
        old = evaluate_strategy(self.snapshot, TREND_RULE_SET_ID)
        self.assertEqual(old['candles'][0]['factors'][2]['outcome'], 'bearish')
        self.assertNotIn('source', old['candles'][0]['factors'][2]['rsi_signal'])
        self.assertNotIn('rsi14_sma14', json.dumps(rule_set_definition(TREND_RULE_SET_ID)))

    def test_written_review_can_cite_ma_but_not_invent_it_on_old_snapshot(self):
        analysis = valid_analysis()
        analysis['bullish_factors'][0]['evidence'] = [{'candle_id':'C2','fields':['rsi14_sma14']}]
        analysis['bullish_factors'][0]['explanation'] = 'The cited RSI14 SMA14 supports the smoothed factor.'
        text = render_journal(json.dumps(analysis), self.snapshot, STRATEGY)
        self.assertIn('RSI14 SMA14 30.00', text)
        for candle in self.snapshot['candles']: del candle['indicators']['rsi14_sma14']
        self.assertNotIn('rsi14_sma14', build_evidence_catalog(self.snapshot)['C2']['values'])
        with self.assertRaises(InvalidJournalEvidence): render_journal(json.dumps(analysis),self.snapshot,STRATEGY)
        with self.assertRaises(InvalidJournalEvidence): _check_explanation('RSI14 SMA14 was 61.')


class StrategyV6JournalTests(ScoredJournalTestCase):
    entry = {**ENTRY, 'rule_set_id': RULE_SET_ID}

    def test_ai_receives_both_series_and_authoritative_ma_result_then_saves_exactly(self):
        set_values(self.snapshot, 'rsi14', [70] * 8)
        set_values(self.snapshot, 'rsi14_sma14', [30] * 8)
        draft = self.generate()
        sent = json.loads(self.ai.call_args.kwargs['input'])
        self.assertEqual(sent['market_data']['candles'][0]['indicators']['rsi14'], 70)
        self.assertEqual(sent['market_data']['candles'][0]['indicators']['rsi14_sma14'], 30)
        factor = sent['rule_evaluation']['candles'][0]['factors'][2]
        self.assertEqual((factor['outcome'],factor['rsi_signal']['source']),('bullish','rsi14_sma14'))
        self.assertIn('v6 and v7, use RSI14 SMA14', self.ai.call_args.kwargs['instructions'])
        saved = self.client.post('/journals',json={'generation_id':draft['generation_id'],'edited_draft':draft['draft']}).json()
        self.assertEqual(db.fetch_journal(saved['id'])['rule_evaluation'],draft['rule_evaluation'])
        self.assertEqual(self.client.get('/journals').json()['items'][0]['average_net_score'],draft['rule_evaluation']['summary']['net_score'])
        self.assertEqual(self.client.get('/journals/calendar?month=2026-10').json()['days'][0]['average_net_score'],draft['rule_evaluation']['summary']['net_score'])

    def test_saved_v5_and_pending_draft_remain_v5_after_v6_generation(self):
        old = evaluate_strategy(self.snapshot,TREND_RULE_SET_ID)
        pending = db.store_generated_draft({**self.entry,'rule_set_id':TREND_RULE_SET_ID},'Pending v5',self.snapshot,old)
        self.generate()
        saved = db.save_generated_journal(pending,'Pending v5')
        self.assertEqual(db.fetch_journal(saved['id'])['rule_evaluation'],old)
