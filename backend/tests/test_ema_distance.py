"""EMA/SMA distance weighting, shared session modes and immutable saved revisions."""

import copy
import json
import unittest
from unittest.mock import patch

import database as db
import date_range as dr
import strategy_rules as rules
from tests.test_strategy_rules import scoring_snapshot
from tests.test_scored_journal import ScoredJournalTestCase, ENTRY
from tests.test_custom_range import range_snapshot
from tests.test_today import view_at


class EmaDistanceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = scoring_snapshot()

    def factor(self, ema, sma=1.1, rule_id=rules.RULE_SET_ID):
        self.snapshot['candles'][0]['indicators'].update(ema20=ema, sma190=sma)
        return rules.evaluate_strategy(self.snapshot, rule_id)['candles'][0]['factors'][1]

    def test_both_directions_use_inclusive_unrounded_sixty_pip_boundary(self):
        for ema, direction, points in [(1.10001, 'bullish', 1), (1.10599999999, 'bullish', 1),
                                       (1.106, 'bullish', 1), (1.10600000001, 'bullish', 2),
                                       (1.12, 'bullish', 2), (1.09999, 'bearish', 1),
                                       (1.09400000001, 'bearish', 1), (1.094, 'bearish', 1),
                                       (1.09399999999, 'bearish', 2), (1.08, 'bearish', 2)]:
            with self.subTest(ema=ema):
                result = self.factor(ema)
                self.assertEqual(result['outcome'], direction)
                self.assertEqual(result[f'{direction}_points'], points)
                other = 'bearish' if direction == 'bullish' else 'bullish'
                self.assertEqual(result[f'{other}_points'], 0)
                self.assertEqual(result['ema_sma_distance']['reduced'], points == 1)
                self.assertEqual(result['evidence'][0]['values'], {'ema20': ema, 'sma190': 1.1})
        self.assertEqual(self.factor(1.106)['ema_sma_distance']['gap_pips'], 60)
        # These prices display identically to five decimals but lie on opposite sides.
        self.assertEqual(f'{1.106:.5f}', f'{1.10600000001:.5f}')

    def test_equal_values_are_neutral_not_reduced_directional_support(self):
        result = self.factor(1.1)
        self.assertEqual((result['outcome'], result['bullish_points'], result['bearish_points']), ('neutral', 0, 0))
        self.assertEqual(result['ema_sma_distance'], {'gap_pips': 0, 'threshold_pips': 60, 'reduced': False})

    def test_missing_or_invalid_inputs_are_unavailable_and_json_safe(self):
        # The public evidence validator rejects invalid required indicator data;
        # the factor also handles unavailable values defensively without scoring them.
        candle = self.snapshot['candles'][0]
        for field in ('ema20', 'sma190'):
            for value in (None, float('nan'), float('inf'), '1.1', True):
                with self.subTest(field=field, value=value):
                    candle['indicators'].update(ema20=1.105, sma190=1.1)
                    candle['indicators'][field] = value
                    result = rules._ema_sma(rules.rule_set_definition()['factors'][1], candle, 'C1')
                    self.assertEqual((result['outcome'], result['bullish_points'], result['bearish_points']), ('unavailable', 0, 0))
                    self.assertIsNone(result['ema_sma_distance']['gap_pips'])
                    json.dumps(result, allow_nan=False)

    def test_reduction_keeps_five_point_denominator_and_equal_session_weights(self):
        # Only the first candle loses a point; all other conditions stay unchanged.
        self.snapshot['candles'][0]['indicators'].update(ema20=1.106, sma190=1.1)
        result = rules.evaluate_strategy(self.snapshot)
        self.assertEqual([row['bullish_points'] for row in result['candles']], [4, 5, 5, 5, 5, 5])
        self.assertEqual(result['candles'][0]['bullish_alignment_percent'], 80)
        self.assertEqual(result['summary']['bullish_points'], 29 / 6)
        self.assertAlmostEqual(result['summary']['bullish_alignment_percent'], 29 / 30 * 100)
        self.assertEqual(result['summary']['max_points'], 5)
        self.assertEqual(result['summary']['reduced_factors'], 1)
        self.assertEqual(result['session_end']['bullish_points'], 5)

    def test_ema_and_momentum_reductions_combine_without_opposite_points(self):
        for candle, momentum in zip(self.snapshot['candles'][-3:], [0.001, 0.0018, 0.0023]):
            candle['indicators']['squeeze']['momentum'] = momentum
        self.snapshot['candles'][-1]['indicators'].update(ema20=1.106, sma190=1.1, rsi14=50)
        last = rules.evaluate_strategy(self.snapshot)['candles'][-1]
        self.assertEqual((last['bullish_points'], last['bearish_points'], last['reduced_factors']), (2.5, 0, 2))
        self.assertEqual(last['bullish_alignment_percent'], 50)
        self.assertEqual(last['direction'], 'bullish')

    def test_legacy_rules_remain_unchanged_and_definition_records_revision(self):
        for rule_id, expected in [('four_factor_v1', 1), ('four_factor_v2', 2), ('four_factor_v3', 2)]:
            result = self.factor(1.106, rule_id=rule_id)
            self.assertEqual(result['bullish_points'], expected)
            self.assertNotIn('ema_sma_distance', result)
            self.assertNotIn('distance_weighting', rules.rule_set_definition(rule_id)['factors'][1])
        definition = rules.rule_set_definition()
        self.assertEqual((definition['id'], definition['version'], definition['revision']), ('four_factor_v4', 4, 2))
        self.assertEqual(definition['factors'][1]['distance_weighting']['pip_size'], 0.0001)
        self.assertIn('do not shrink the alignment denominator', definition['rules'])
        definition['factors'][1]['distance_weighting']['within_points'] = 99
        self.assertEqual(self.factor(1.106)['bullish_points'], 1)

    def test_custom_range_reuses_reduction_for_every_candle_and_daily_summary(self):
        snapshot = range_snapshot()
        for candle in snapshot['candles']:
            candle['indicators'].update(ema20=1.106, sma190=1.1)
        result = dr.evaluate_range_strategy(snapshot)
        self.assertEqual(result['rule_set']['revision'], 2)
        self.assertEqual(len(result['candles']), 30)
        for row in result['candles']:
            self.assertEqual(row['factors'][1]['bullish_points'], 1)
        self.assertEqual(result['summary']['max_points'], 5)
        self.assertEqual(result['summary']['bullish_points'], sum(row['bullish_points'] for row in result['candles']) / 30)

    def test_today_uses_same_revision_and_only_completed_candles(self):
        view = view_at()
        result = view['rule_evaluation']
        self.assertEqual(result['rule_set']['revision'], 2)
        self.assertEqual(result['summary']['method'], 'session_to_date')
        self.assertEqual(len(result['candles']), 3)
        for row in result['candles']:
            self.assertEqual(row['factors'][1]['bullish_points'], 1)
            self.assertTrue(row['factors'][1]['ema_sma_distance']['reduced'])
        self.assertEqual(result['summary']['max_points'], 5)
        self.assertEqual(result['summary']['expected_factors'], 12)


class EmaDistanceJournalTests(ScoredJournalTestCase):
    entry = {**ENTRY, 'rule_set_id': rules.RULE_SET_ID}

    def test_revised_weight_and_gap_reach_ai_and_persist_through_editing(self):
        for candle in self.snapshot['candles']:
            candle['indicators'].update(ema20=1.106, sma190=1.1)
        draft = self.generate()
        expected = copy.deepcopy(draft['rule_evaluation'])
        sent = json.loads(self.ai.call_args.kwargs['input'])
        self.assertEqual(sent['rule_evaluation'], expected)
        self.assertEqual(expected['summary']['bullish_points'], 4)
        self.assertEqual(expected['summary']['bullish_alignment_percent'], 80)
        self.assertEqual(expected['rule_set']['revision'], 2)
        self.assertIn('ema_sma_distance is authoritative', self.ai.call_args.kwargs['instructions'])
        saved = self.client.post('/journals', json={'generation_id': draft['generation_id'], 'edited_draft': draft['draft']})
        self.assertEqual(saved.status_code, 201, saved.text)
        for response in [self.client.get(f"/journals/{saved.json()['id']}"),
                         self.client.patch(f"/journals/{saved.json()['id']}", json={'edited_draft': 'My notes'})]:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['rule_evaluation'], expected)

    def test_old_v4_saved_and_pending_results_are_never_recalculated(self):
        for candle in self.snapshot['candles']:
            candle['indicators'].update(ema20=1.106, sma190=1.1)
        old_definition = rules.rule_set_definition()
        old_definition.pop('revision')
        old_definition['factors'] = copy.deepcopy(list(rules.FACTORS))
        old_definition['rules'] = 'Previously saved v4 rules: EMA/SMA always earns two points.'
        with patch.object(rules, 'rule_set_definition', return_value=old_definition):
            old_result = rules.evaluate_strategy(self.snapshot)
        self.assertEqual(old_result['summary']['bullish_points'], 5)
        entry = {**self.entry, 'strategy': old_definition['rules']}
        pending = db.store_generated_draft(entry, 'Old draft', self.snapshot, old_result)
        original = db.save_generated_journal(db.store_generated_draft(entry, 'Already saved', self.snapshot, old_result), 'Already saved')
        new = self.generate()
        self.assertEqual(new['rule_evaluation']['summary']['bullish_points'], 4)
        db.init_db()
        saved_pending = db.save_generated_journal(pending, 'Old draft')
        for journal in (original, saved_pending):
            fetched = self.client.get(f"/journals/{journal['id']}").json()
            self.assertEqual(fetched['rule_evaluation'], old_result)
            self.assertEqual(fetched['strategy'], entry['strategy'])

    def test_current_catalog_does_not_delete_retired_profiles(self):
        profile = self.client.post('/strategy-profiles', json={'name': 'Existing v3', 'rules': 'ignored', 'rule_set_id': 'four_factor_v3'}).json()
        before = copy.deepcopy(profile)
        catalog = self.client.get('/strategy-rule-sets').json()
        self.assertEqual([item['id'] for item in catalog['items']], ['four_factor_v4'])
        self.assertEqual(catalog['items'][0]['revision'], 2)
        self.assertEqual(db.fetch_strategy_profile(profile['id']), before)
        changed = self.client.patch(f"/strategy-profiles/{profile['id']}", json={'name': 'Existing v3', 'rules': 'ignored', 'rule_set_id': rules.RULE_SET_ID})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()['id'], profile['id'])
        self.assertEqual(changed.json()['rules'], rules.RULES_TEXT)
        self.market.assert_not_called()
        self.ai.assert_not_called()


if __name__ == '__main__':
    unittest.main()
