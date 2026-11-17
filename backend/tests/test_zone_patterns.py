"""Synthetic H4 rule matches and saved setup contracts; no external API calls."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests.test_zone_history import candle, START
from tests.test_setup_evaluator import snapshot, inputs, valid_assessment
from tests.test_today import instant
from setup_models import SetupInput
from zone_history import analyze_zone_history
from zone_patterns import analyze_zone_patterns, pattern_summary, VERSION
from journal_grounding import InvalidJournalEvidence
import database as db
import setup_database as sd
import setup_market as sm
import setup_ai as ai


def zone(**changes):
    return {'id':'Z1','kind':'resistance','label':'Test zone','lower':'1.10000',
        'upper':'1.10100','origin_at':START.isoformat(), **changes}


def rows(values):
    return [candle(i, *value) for i, value in enumerate(values)]


def analyze(source, selected=None, cutoff=None):
    selected = selected or zone()
    cutoff = cutoff or (datetime.fromisoformat(source[-1]['close_time']) if source else START)
    history = analyze_zone_history(selected, source, cutoff)
    return analyze_zone_patterns(selected, source, cutoff, history)


def upward():
    return rows([(1.1,1.101,1.1005), (1.1008,1.103,1.102)])


def mirror(source):
    return [{**row, 'open':round(2.201-row['open'],5), 'close':round(2.201-row['close'],5),
        'low':round(2.201-row['high'],5), 'high':round(2.201-row['low'],5)} for row in source]


class PatternCalculationTests(unittest.TestCase):
    def test_up_and_down_breakouts_need_one_new_close_and_never_retest_same_bar(self):
        for source, kind, direction in ((upward(),'resistance','bullish'), (mirror(upward()),'support','bearish')):
            result = analyze(source, zone(kind=kind))
            self.assertEqual([e['kind'] for e in result['events']], ['breakout'])
            self.assertEqual(result['events'][0]['direction'],direction)
            self.assertEqual(result['breakouts'][0]['status'],'pending')
            self.assertEqual(result['breakouts'][0]['observed_candles'],0)
            self.assertEqual(result['events'][0]['evidence'][0]['close'],source[0]['close'])

    def test_wick_and_exact_edge_closes_are_not_breakouts(self):
        for close in (1.1005,1.101):
            result = analyze(rows([(1.1,1.101,1.1005),(1.1002,1.103,close)]))
            self.assertEqual(result['events'],[])
        result = analyze(upward()+[candle(2,1.1015,1.104,1.103)])
        self.assertEqual(result['counts']['breakout'],1)

    def test_rejection_requires_contact_prior_outside_and_close_back_on_original_side(self):
        source = rows([(1.1015,1.103,1.102),(1.101,1.104,1.103)])
        for data, kind, direction in ((source,'support','bullish'),(mirror(source),'resistance','bearish')):
            result = analyze(data,zone(kind=kind))
            self.assertEqual(result['events'][0]['kind'],'rejection')
            self.assertEqual(result['events'][0]['direction'],direction)
        for values in ([(1.1,1.101,1.1005),(1.101,1.104,1.103)],
                       [(1.1015,1.103,1.102),(1.1012,1.104,1.103)],
                       [(1.1015,1.103,1.102),(1.1,1.104,1.101)]):
            self.assertEqual(analyze(rows(values),zone(kind='support'))['counts']['rejection'],0)

    def test_retests_hold_in_either_direction_including_exact_edge_contact(self):
        source = upward()+[candle(2,1.101,1.104,1.102)]
        for data, kind, direction in ((source,'resistance','bullish'),(mirror(source),'support','bearish')):
            result = analyze(data,zone(kind=kind))
            self.assertEqual([e['kind'] for e in result['events']],['breakout','retest_held'])
            self.assertEqual(result['breakouts'][0]['status'],'held')
            self.assertEqual(result['breakouts'][0]['observed_candles'],1)
            self.assertEqual(result['events'][-1]['breakout_id'],result['breakouts'][0]['id'])
            self.assertEqual(result['events'][-1]['direction'],direction)

    def test_inside_close_is_pending_not_hold_and_recovery_does_not_reset_clock(self):
        source = upward()+[candle(2,1.1002,1.103,1.1005),candle(3,1.1005,1.103,1.102)]
        result = analyze(source)
        self.assertEqual(result['breakouts'][0]['status'],'pending')
        self.assertEqual(result['breakouts'][0]['observed_candles'],2)
        self.assertEqual(result['counts']['breakout'],1)
        self.assertEqual(result['counts']['retest_held'],0)
        self.assertIsNotNone(result['breakouts'][0]['first_touch'])

    def test_close_past_opposite_edge_invalidates_but_edge_equality_does_not(self):
        for close, expected in ((1.1,'pending'),(1.0999,'invalidated')):
            source = upward()+[candle(2,1.099,1.103,close)]
            for data,kind in ((source,'resistance'),(mirror(source),'support')):
                self.assertEqual(analyze(data,zone(kind=kind))['breakouts'][0]['status'],expected)
        failed=analyze(upward()+[candle(2,1.099,1.103,1.0999)])
        self.assertEqual(failed['events'][-1]['kind'],'retest_invalidated')

    def test_sixth_candle_can_hold_seventh_cannot_and_expiry_is_not_invalidation(self):
        source = upward()+[candle(i,1.1015,1.104,1.103) for i in range(2,7)]
        sixth=analyze(source+[candle(7,1.101,1.104,1.102)])
        self.assertEqual(sixth['breakouts'][0]['status'],'held')
        self.assertEqual(sixth['breakouts'][0]['observed_candles'],6)
        expired=analyze(source+[candle(7,1.1015,1.104,1.103),candle(8,1.101,1.104,1.102)])
        self.assertEqual(expired['breakouts'][0]['status'],'expired')
        self.assertEqual(expired['counts']['retest_held'],0)
        self.assertEqual(expired['counts']['retest_invalidated'],0)

    def test_recovery_on_last_candle_does_not_create_another_six_candle_attempt(self):
        source=upward()+[candle(i,1.1002,1.101,1.1005) for i in range(2,7)]
        result=analyze(source+[candle(7,1.1005,1.103,1.102)])
        self.assertEqual(len(result['breakouts']),1)
        self.assertEqual(result['breakouts'][0]['status'],'expired')

    def test_future_candles_cannot_change_earlier_events_or_attempt_status(self):
        source=upward()+[candle(2,1.101,1.104,1.102),candle(3,1.099,1.103,1.0999)]
        for length in range(1,len(source)+1):
            cutoff=datetime.fromisoformat(source[length-1]['close_time'])
            expected=analyze(source[:length],cutoff=cutoff)
            altered=copy.deepcopy(source)
            for row in altered[length:]: row.update(close='future must not be read', high=999)
            self.assertEqual(analyze(altered,cutoff=cutoff),expected)
        # A later adverse close does not rewrite the historical hold event.
        self.assertEqual(analyze(source)['breakouts'][0]['status'],'held')

    def test_missing_data_ends_pending_attempt_and_cannot_create_cross_gap_pattern(self):
        result=analyze(upward()+[candle(3,1.101,1.104,1.102)])
        self.assertEqual(result['breakouts'][0]['status'],'insufficient_data')
        self.assertEqual(result['counts']['retest_held'],0)
        self.assertEqual(result['counts']['rejection'],0)
        trailing=analyze(upward(),cutoff=START+timedelta(hours=12))
        self.assertEqual(trailing['breakouts'][0]['status'],'insufficient_data')
        separated=analyze([upward()[0],candle(3,1.101,1.104,1.102)])
        self.assertEqual(separated['status'],'insufficient_data')
        self.assertIsNone(separated['counts'])

    def test_normal_weekend_and_dst_are_consecutive_trading_candles(self):
        for friday,sunday in (('2026-10-30T13:00:00','2026-11-01T17:00:00'),('2026-03-06T13:00:00','2026-03-08T17:00:00')):
            a,b=instant(friday),instant(sunday)
            source=[candle(0,1.1,1.101,1.1005,start=a-timedelta(hours=4)),candle(0,1.1008,1.103,1.102,start=a),candle(0,1.101,1.104,1.102,start=b)]
            result=analyze(source,zone(origin_at=source[0]['open_time']))
            self.assertEqual(result['breakouts'][0]['status'],'held')
            self.assertEqual(result['breakouts'][0]['observed_candles'],1)

    def test_missing_origin_and_short_history_are_unknown_and_do_not_borrow_earlier_closes(self):
        for source,selected in ((upward(),zone(origin_at=None)),([],zone()),(upward(),zone(origin_at=upward()[1]['open_time']))):
            result=analyze(source,selected)
            self.assertIsNone(result['counts'])
            self.assertEqual(result['events'],[])
        result=analyze(upward(),zone(origin_at=(START-timedelta(days=30)).isoformat()))
        self.assertEqual(result['status'],'partial_history')
        self.assertEqual(result['counts']['breakout'],1)

    def test_single_price_zones_use_strict_closes_and_inclusive_contact(self):
        source=rows([(1.099,1.1,1.1),(1.1,1.102,1.101),(1.1,1.102,1.1015)])
        result=analyze(source,zone(upper='1.10000'))
        self.assertEqual(result['counts']['breakout'],1)
        self.assertEqual(result['counts']['retest_held'],1)


class PatternIntegrationTests(unittest.TestCase):
    def test_snapshot_versions_rules_and_preview_capture_preserve_strategy_and_evidence(self):
        base=snapshot()
        selected={**inputs()['zones'][0],'origin_at':base['source_candles'][-12]['open_time']}
        snap=snapshot(zones=[selected])
        self.assertEqual(snap['schema_version'],4)
        self.assertEqual(snap['zone_pattern_version'],VERSION)
        self.assertEqual(snap['rule_evaluation'],base['rule_evaluation'])
        original=copy.deepcopy(snap)
        captured=sm.capture_preview(SetupInput(**inputs(zones=[selected])),{
            'id':str(uuid4()),'selection':{'mode':'historical','as_of':snap['cutoff_at'],'include_quote':False},'snapshot':snap})
        self.assertEqual(captured['zones'],snap['zones'])
        self.assertEqual(snap,original)
        with tempfile.TemporaryDirectory() as tmp, patch.object(db,'DB_PATH',Path(tmp)/'journal.db'):
            db.init_db(); sd.init_setup_db()
            stored=sd.store_snapshot(uuid4(),{},captured)
            self.assertEqual(sd.fetch_snapshot(stored['id'])['snapshot'],captured)

    def test_ai_gets_bounded_dated_rules_and_latest_candle_facts_with_valid_roles(self):
        snap=snapshot()
        pattern=analyze(upward()+[candle(2,1.101,1.104,1.102)])
        snap['zones'][0]['patterns']=pattern
        snap['data_through']=pattern['events'][-1]['close_time']
        snap['catalog']=ai.build_catalog(snap)
        fact=next(f for f in snap['catalog']['facts'] if 'pattern_event' in f['evidence'])
        self.assertEqual(fact['role'],'supports')
        result=valid_assessment(snap)
        result['supporting_facts']=[fact['id']]
        ai.parse_assessment(json.dumps(result),snap)
        result['conflicting_facts']=[fact['id']]
        with self.assertRaises(InvalidJournalEvidence): ai.parse_assessment(json.dumps(result),snap)
        snap['data_through']=(datetime.fromisoformat(snap['data_through'])+timedelta(hours=4)).isoformat()
        snap['catalog']=ai.build_catalog(snap)
        self.assertEqual(next(f for f in snap['catalog']['facts'] if 'pattern_event' in f['evidence'])['role'],'context')
        pattern['events']*=5; pattern['breakouts']*=5
        summary=pattern_summary(pattern)
        self.assertEqual(len(summary['recent_events']),3)
        self.assertEqual(len(summary['recent_breakouts']),3)
        self.assertEqual(summary['omitted_events'],7)
        self.assertNotIn('source_candles',ai.ai_input(snap))

    def test_old_snapshots_are_not_recomputed_and_invalidation_is_context(self):
        snap=snapshot()
        snap.pop('zone_pattern_version')
        for item in snap['zones']: item.pop('patterns')
        snap['catalog']=ai.build_catalog(snap)
        before=copy.deepcopy(snap)
        ai.parse_assessment(json.dumps(valid_assessment(snap)),snap)
        self.assertEqual(snap,before)
        self.assertIsNone(ai.ai_input(snap)['zone_pattern_version'])
        pattern=analyze(upward()+[candle(2,1.099,1.103,1.0999)])
        snap['zones'][0]['patterns']=pattern
        snap['data_through']=pattern['events'][-1]['close_time']
        self.assertEqual(next(f for f in ai.build_catalog(snap)['facts'] if 'pattern_event' in f['evidence'])['role'],'context')
