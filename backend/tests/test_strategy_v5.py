"""RSI threshold priority, three-reading trends and momentum in all quadrants."""
import copy
import json
import unittest
from datetime import date
from unittest.mock import patch
from uuid import uuid4

from tests.test_strategy_rules import scoring_snapshot
from tests.test_scored_journal import ScoredJournalTestCase, ENTRY, valid_scored_commentary
from tests.test_custom_range import range_snapshot
from tests.test_today import view_at
from strategy_rules import (RULE_SET_ID, TREND_RULE_SET_ID, SESSION_RULE_SET_ID, rule_set_definition, evaluate_strategy as _evaluate_strategy,
                            _rsi_with_trend)
from scored_journal import build_summary_context
import date_range as dr
import database as db
import main


def evaluate_strategy(snapshot, rule_set_id=TREND_RULE_SET_ID, **kwargs):
    return _evaluate_strategy(snapshot, rule_set_id, **kwargs)

def set_values(snapshot, key, values):
    candles = [*snapshot['previous_candles'], *snapshot['candles']]
    for candle, value in zip(candles, values):
        if key == 'momentum':
            candle['indicators']['squeeze']['momentum'] = value
        else:
            candle['indicators'][key] = value


class StrategyV5Tests(unittest.TestCase):
    def setUp(self):
        self.snapshot = scoring_snapshot()

    def first(self, key, values):
        set_values(self.snapshot, key, values)
        return evaluate_strategy(self.snapshot)['candles'][0]['factors'][2 if key == 'rsi14' else 3]

    def test_rsi_thresholds_are_inclusive_and_override_opposing_trends(self):
        for values, outcome in [([20, 30, 40], 'bullish'), ([80, 70, 60], 'bearish'),
                                ([5, 10, 39.9999], 'bullish'), ([95, 90, 60.0001], 'bearish'),
                                ([50, 45, 0], 'bullish'), ([50, 55, 100], 'bearish')]:
            with self.subTest(values=values):
                factor = self.first('rsi14', values)
                self.assertEqual(factor['outcome'], outcome)
                self.assertEqual(factor[outcome + '_points'], 1)
                self.assertEqual(len(factor['evidence']), 1)
                self.assertEqual(factor['rsi_signal']['basis'], 'oversold' if outcome == 'bullish' else 'overbought')

    def test_rsi_in_band_trend_uses_three_strict_readings_and_current_band_only(self):
        for values, outcome in [([42, 48, 55], 'bullish'), ([58, 52, 45], 'bearish'),
                                ([20, 35, 50], 'bullish'), ([80, 65, 50], 'bearish'),
                                ([40, 40.0000001, 40.0000002], 'bullish')]:
            with self.subTest(values=values):
                factor = self.first('rsi14', values)
                self.assertEqual(factor['outcome'], outcome)
                self.assertEqual(factor[outcome + '_points'], 1)
                self.assertEqual(factor['rsi_signal']['basis'], 'rising' if outcome == 'bullish' else 'falling')
                self.assertEqual([r['candle_id'] for r in factor['evidence']], ['P-1', 'P0', 'C1'])
                self.assertEqual([r['values']['rsi14'] for r in factor['evidence']], values)

    def test_rsi_flat_or_mixed_values_are_neutral(self):
        for values in ([45, 45, 50], [45, 50, 50], [50, 50, 50], [55, 45, 50], [45, 55, 50]):
            factor = self.first('rsi14', values)
            self.assertEqual((factor['outcome'], factor['bullish_points'], factor['bearish_points']), ('neutral', 0, 0))
            self.assertEqual(factor['rsi_signal']['basis'], 'mixed_or_flat')

    def test_rsi_threshold_does_not_require_history_but_in_band_does(self):
        self.snapshot.pop('previous_candles')
        for value, outcome in [(40, 'bullish'), (60, 'bearish'), (50, 'unavailable')]:
            self.snapshot['candles'][0]['indicators']['rsi14'] = value
            factor = evaluate_strategy(self.snapshot)['candles'][0]['factors'][2]
            self.assertEqual(factor['outcome'], outcome)

    def test_rsi_invalid_history_is_unavailable_and_never_zero_filled(self):
        for invalid in (None, float('nan'), float('inf'), -1, 101, True, '45'):
            with self.subTest(invalid=invalid):
                factor = self.first('rsi14', [invalid, 48, 55])
                self.assertEqual(factor['outcome'], 'unavailable')
                json.dumps(factor, allow_nan=False)
        self.snapshot = scoring_snapshot()
        self.first('rsi14', [42, 48, 55])
        self.snapshot['previous_candles'][0]['close_time'] = self.snapshot['candles'][0]['close_time']
        self.assertEqual(evaluate_strategy(self.snapshot)['candles'][0]['factors'][2]['outcome'], 'unavailable')

    def test_rsi_invalid_current_reading_never_earns_a_threshold_point(self):
        factor_def = rule_set_definition(TREND_RULE_SET_ID)['factors'][2]
        for value in (None, float('nan'), float('inf'), -1, 101, True, '45'):
            self.snapshot['candles'][0]['indicators']['rsi14'] = value
            result = _rsi_with_trend(factor_def, *self.snapshot['previous_candles'], self.snapshot['candles'][0], 'P-1', 'P0', 'C1')
            self.assertEqual(result['outcome'], 'unavailable')
            json.dumps(result, allow_nan=False)

    def test_rsi_lookback_rolls_without_future_influence_or_input_mutation(self):
        set_values(self.snapshot, 'rsi14', [42, 44, 46, 48, 47, 46, 46, 50])
        original = copy.deepcopy(self.snapshot)
        result = evaluate_strategy(self.snapshot)
        self.assertEqual(self.snapshot, original)
        self.assertEqual([c['factors'][2]['outcome'] for c in result['candles']],
                         ['bullish', 'bullish', 'neutral', 'bearish', 'neutral', 'neutral'])
        self.snapshot['candles'][-1]['indicators']['rsi14'] = 70
        after = evaluate_strategy(self.snapshot)
        self.assertEqual(result['candles'][:-1], after['candles'][:-1])
        self.assertNotEqual(result['summary'], after['summary'])

    def test_momentum_all_four_sign_direction_combinations_keep_full_points(self):
        for values, outcome in [([.001, .002, .003], 'bullish'), ([.003, .002, .001], 'bearish'),
                                ([-.001, -.002, -.003], 'bearish'), ([-.003, -.002, -.001], 'bullish')]:
            factor = self.first('momentum', values)
            self.assertEqual((factor['outcome'], factor[outcome + '_points']), (outcome, 1))
            self.assertEqual(factor['momentum_change']['pace'], 'steady')

    def test_momentum_slowdown_reduces_all_four_combinations_without_opposite_points(self):
        for values, outcome in [([.001, .0018, .0023], 'bullish'), ([.003, .002, .0015], 'bearish'),
                                ([-.001, -.0018, -.0023], 'bearish'), ([-.003, -.002, -.0015], 'bullish')]:
            factor = self.first('momentum', values)
            self.assertEqual((factor['outcome'], factor[outcome + '_points']), (outcome, .5))
            self.assertEqual(factor['bullish_points'] + factor['bearish_points'], .5)
            self.assertEqual(factor['momentum_change']['pace'], 'slowing')

    def test_momentum_acceleration_new_moves_and_equal_deltas(self):
        for values, outcome, pace in [([.004, .0035, .002], 'bearish', 'accelerating'),
                                      ([-.004, -.0035, -.002], 'bullish', 'accelerating'),
                                      ([.002, .003, .0025], 'bearish', 'new_move'),
                                      ([-.002, -.003, -.0025], 'bullish', 'new_move'),
                                      ([.007, .006, .005 + 1e-13], 'bearish', 'steady')]:
            factor = self.first('momentum', values)
            self.assertEqual((factor['outcome'], factor[outcome + '_points'], factor['momentum_change']['pace']), (outcome, 1, pace))

    def test_momentum_zero_crossing_or_touch_keeps_direction_and_resets_slowdown(self):
        for values, outcome in [([.001, .0005, 0], 'bearish'), ([-.001, -.0005, 0], 'bullish'),
                                ([.001, -.001, -.0015], 'bearish'), ([-.001, .001, .0015], 'bullish')]:
            factor = self.first('momentum', values)
            self.assertEqual((factor['outcome'], factor[outcome + '_points'], factor['momentum_change']['pace']), (outcome, 1, 'transition'))
        for values in ([.003, .002, .002], [-.003, -.002, -.002], [0, 0, 0]):
            factor = self.first('momentum', values)
            self.assertEqual((factor['outcome'], factor['momentum_change']['movement']), ('neutral', 'unchanged'))

    def test_missing_momentum_history_withholds_score_and_full_average(self):
        self.snapshot.pop('previous_candles')
        result = evaluate_strategy(self.snapshot)
        self.assertEqual(result['candles'][0]['factors'][3]['outcome'], 'unavailable')
        self.assertIsNone(result['summary']['net_score'])
        self.assertEqual(result['summary']['expected_factors'], 24)

    def test_v4_and_earlier_keep_threshold_only_rsi_and_sign_dependent_momentum(self):
        set_values(self.snapshot, 'rsi14', [42, 45, 50])
        set_values(self.snapshot, 'momentum', [.003, .002, .0015])
        for version in range(1, 5):
            old = evaluate_strategy(self.snapshot, f'four_factor_v{version}')
            factors = old['candles'][0]['factors']
            self.assertEqual([f['outcome'] for f in factors[2:]], ['neutral', 'neutral'])
            self.assertNotIn('rsi_signal', factors[2])
            self.assertNotIn('movement', factors[3].get('momentum_change', {}))
        self.assertEqual(evaluate_strategy(self.snapshot, SESSION_RULE_SET_ID)['summary']['method'], 'session_average')
        definition = rule_set_definition(SESSION_RULE_SET_ID)
        self.assertEqual((definition['version'], definition['revision']), (4, 2))
        self.assertNotIn('three consecutive strictly rising RSI14', definition['rules'])

    def test_range_uses_global_rsi_history_across_weekend_and_fixed_denominator(self):
        snapshot = range_snapshot(date(2026, 10, 16), date(2026, 10, 19))
        for candle, value in zip(snapshot['candles'][4:7], [44, 48, 52]):
            candle['indicators']['rsi14_sma14'] = value
        result = dr.evaluate_range_strategy(snapshot)
        factor = result['candles'][6]['factors'][2]
        self.assertEqual(factor['outcome'], 'bullish')
        self.assertEqual([r['candle_id'] for r in factor['evidence']], ['C5', 'C6', 'C7'])
        self.assertEqual(result['rule_set']['id'], RULE_SET_ID)
        self.assertEqual(result['summary']['max_points'], 5)
        self.assertEqual(result['summary']['net_score'], sum(c['net_score'] for c in result['candles']) / 12)


class StrategyV5JournalTests(ScoredJournalTestCase):
    entry = {**ENTRY, 'rule_set_id': TREND_RULE_SET_ID}

    def test_daily_ai_gets_new_outcomes_and_saved_card_calendar_keep_v4_and_v5(self):
        set_values(self.snapshot, 'rsi14', [42, 48, 55])
        set_values(self.snapshot, 'momentum', [.003, .002, .0015])
        old = evaluate_strategy(self.snapshot, SESSION_RULE_SET_ID)
        old_generation = db.store_generated_draft({**self.entry, 'rule_set_id': SESSION_RULE_SET_ID}, 'Old v4', self.snapshot, old)
        saved_old = db.save_generated_journal(old_generation, 'Old v4')
        draft = self.generate()
        sent = json.loads(self.ai.call_args.kwargs['input'])
        factors = sent['rule_evaluation']['candles'][0]['factors']
        self.assertEqual((factors[2]['bullish_points'], factors[3]['bearish_points']), (1, .5))
        self.assertIn('v5, v6 and v7 score any rise as bullish', self.ai.call_args.kwargs['instructions'])
        self.assertIn('rsi_signal.basis', self.ai.call_args.kwargs['instructions'])
        saved = self.client.post('/journals', json={'generation_id': draft['generation_id'], 'edited_draft': draft['draft'], 'title': 'New strategy'}).json()
        self.client.patch(f"/journals/{saved['id']}", json={'edited_draft': 'My review', 'title': 'Renamed'})
        self.assertEqual(self.client.get(f"/journals/{saved['id']}").json()['rule_evaluation'], draft['rule_evaluation'])
        page = self.client.get('/journals').json()['items']
        self.assertEqual([r['average_net_score'] for r in page], [draft['rule_evaluation']['summary']['net_score'], old['summary']['net_score']])
        day = self.client.get('/journals/calendar?month=2026-10').json()['days'][0]
        self.assertEqual((day['source_journal_id'], day['average_net_score']), (saved['id'], page[0]['average_net_score']))
        self.assertEqual(db.fetch_journal(saved_old['id'])['rule_evaluation'], old)

    def test_v4_pending_draft_and_profile_remain_original_until_explicit_upgrade(self):
        old = evaluate_strategy(self.snapshot, SESSION_RULE_SET_ID)
        pending = db.store_generated_draft({**self.entry, 'rule_set_id': SESSION_RULE_SET_ID}, 'Pending v4', self.snapshot, old)
        profile = self.client.post('/strategy-profiles', json={'name': 'Old profile', 'rules': 'ignored', 'rule_set_id': SESSION_RULE_SET_ID}).json()
        catalog = self.client.get('/strategy-rule-sets').json()
        self.assertEqual([r['id'] for r in catalog['items']], [RULE_SET_ID])
        self.assertEqual(db.fetch_strategy_profile(profile['id']), profile)
        saved = self.client.post('/journals', json={'generation_id': pending, 'edited_draft': 'Pending v4'}).json()
        self.assertEqual(saved['rule_evaluation'], old)
        updated = self.client.patch(f"/strategy-profiles/{profile['id']}", json={**{k: profile[k] for k in ('name','rules')}, 'rule_set_id': RULE_SET_ID}).json()
        self.assertEqual(updated['rules'], rule_set_definition()['rules'])
        self.assertEqual(db.fetch_journal(saved['id'])['rule_evaluation'], old)

    def test_today_and_range_generation_send_current_version_with_correct_coverage(self):
        view = view_at(); view['snapshot_id'] = str(uuid4())
        custom = range_snapshot()
        with patch.object(main, 'load_today_snapshot', return_value=view), patch.object(main, 'get_range_market_data', return_value=custom):
            for endpoint, body, snapshot, evaluation in [
                ('/today/generate', {'snapshot_id': view['snapshot_id']}, view['market_data'], view['rule_evaluation']),
                ('/range-journal/generate', {'start_date':'2026-10-19','end_date':'2026-10-23'}, custom, dr.evaluate_range_strategy(custom)),
            ]:
                commentary = valid_scored_commentary(build_summary_context(snapshot,evaluation))
                for part in commentary.values():
                    for ref in part['results']: ref['candle_id'] = evaluation['candles'][-1]['candle_id']
                self.ai.return_value.output_text = json.dumps(commentary)
                response = self.client.post(endpoint, json=body)
                self.assertEqual(response.status_code,200,response.text)
                draft=response.json();sent=json.loads(self.ai.call_args.kwargs['input'])
                self.assertEqual(draft['entry']['rule_set_id'],RULE_SET_ID)
                self.assertEqual(sent['rule_evaluation'],evaluation)
                self.assertEqual(draft['rule_evaluation']['rule_set']['id'],RULE_SET_ID)
                self.assertTrue(all('rsi_signal' in c['factors'][2] for c in evaluation['candles']))
