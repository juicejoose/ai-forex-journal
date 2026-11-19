"""Offline timeline coverage, provisional prices and immutable entry evidence."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
import os
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from tests.test_setup_evaluator import main, snapshot, ENVIRONMENT
from tests.test_custom_range import range_payload
from tests.test_trade_log import trade, full_exit
import database as db
import setup_database as sd
import trade_database as td
import trade_timeline as tl
import market_data as md


def at(value):
    return datetime.fromisoformat(value).astimezone(md.UTC)


NOW = at('2026-11-10T11:00:00-05:00')
ENTERED = '2026-11-09T10:00:00-05:00'


def record(exit_at=None, entry_at=ENTERED):
    return {'id': 'test-trade', 'entry': trade(entry_at=entry_at), 'status': 'closed' if exit_at else 'open',
            'exit': full_exit(exit_at=exit_at) if exit_at else None}


def provider(now=NOW):
    source = range_payload(date(2026, 11, 20))
    tail = source['candles'][-1]['time']
    source['candles'].extend(row for row in range_payload(date(2026, 12, 10))['candles'] if row['time'] > tail)
    def fetch(end, count=350, *, start=None):
        if start is not None:
            rows = deepcopy([r for r in source['candles'] if start <= at(r['time']) < now])[:count]
        else:
            rows = deepcopy([r for r in source['candles'] if at(r['time']) < min(end, now)])[-count:]
        for row in rows:
            row['complete'] = at(row['time']) + md.CANDLE_DURATION <= now
        return {**source, 'candles': rows}
    return fetch


class TimelineTests(unittest.TestCase):
    def build(self, rec=None, now=NOW):
        with patch.object(md, '_fetch_candles', side_effect=provider(now)):
            return tl.build_timeline(rec or record(), now)

    def test_open_trade_includes_post_entry_and_current_forming_candle(self):
        view = self.build()
        self.assertEqual(len(view['chart_context']['candles']), 160)
        self.assertEqual(len(view['candles']), 7)
        self.assertEqual(view['candles'][0]['open_time'], at('2026-11-09T09:00:00-05:00').isoformat())
        self.assertEqual(view['candles'][-1]['open_time'], at('2026-11-10T09:00:00-05:00').isoformat())
        self.assertFalse(view['candles'][-1]['complete'])
        self.assertEqual(view['coverage']['forming_count'], 1)
        self.assertEqual(view['coverage']['missing_candle_count'], 0)
        self.assertEqual(view['events'][0]['at'], at(ENTERED).isoformat())
        self.assertNotIn('rule_evaluation', view)

    def test_live_pips_use_latest_midpoint_with_long_short_and_fractional_precision(self):
        latest=Decimal(str(self.build()['candles'][-1]['close']))
        for direction,delta,expected in [('long','0.00125','+12.5'),('short','0.00125','-12.5'),('short','-0.00125','+12.5'),('long','0','0.0')]:
            rec=record();rec['entry'].update(direction=direction,entry_price=str(latest-Decimal(delta)),initial_stop_loss=None)
            result=self.build(rec)['price_result']
            self.assertEqual(result['pips'],expected)
            self.assertEqual(result['price_basis'],'midpoint')
            self.assertEqual(result['reference_kind'],'forming')
            self.assertEqual(result['reference_at'],NOW.isoformat())
            self.assertEqual(Decimal(result['reference_price']),latest)

    def test_no_forming_price_labels_completed_close_with_its_actual_timestamp(self):
        fetch=provider()
        def missing_forming(end,count=350,*,start=None):
            raw=fetch(end,count,start=start)
            raw['candles']=[c for c in raw['candles'] if c['complete']]
            return raw
        with patch.object(md,'_fetch_candles',side_effect=missing_forming):view=tl.build_timeline(record(),NOW)
        self.assertEqual(view['price_result']['reference_kind'],'completed')
        self.assertEqual(view['price_result']['reference_at'],view['candles'][-1]['close_time'])
        self.assertLess(at(view['price_result']['reference_at']),NOW)

    def test_weekend_price_stays_completed_and_no_post_entry_price_stays_missing(self):
        now=at('2026-11-07T12:00:00-05:00')
        weekend=self.build(record(entry_at='2026-11-06T10:00:00-05:00'),now)
        self.assertEqual(weekend['price_result']['reference_kind'],'completed')
        self.assertEqual(weekend['price_result']['reference_at'],at('2026-11-06T17:00:00-05:00').isoformat())
        empty=self.build(record(entry_at='2026-11-07T10:00:00-05:00'),now)
        self.assertIsNone(empty['price_result'])

    def test_closed_timeline_never_supplies_live_result_even_with_after_exit_prices(self):
        rec=record('2026-11-09T14:30:00-05:00')
        original=deepcopy(rec)
        self.assertIsNone(self.build(rec)['price_result'])
        self.assertIsNone(self.build(rec,NOW+timedelta(days=4))['price_result'])
        self.assertEqual(rec,original)

    def test_forming_data_is_opt_in_and_never_changes_default_parser(self):
        raw = provider()(NOW)
        normal = md._parse_candles(raw, NOW)
        display = md._parse_candles(raw, NOW, include_forming=True)
        self.assertEqual(display[:-1], normal)
        self.assertTrue(all(c.complete for c in normal))
        self.assertFalse(display[-1].complete)

    def test_malformed_forming_prices_fail_validation_and_old_incomplete_is_omitted(self):
        raw = provider()(NOW)
        raw['candles'][-1]['mid']['c'] = 'NaN'
        with self.assertRaises(md.MarketDataError): md._parse_candles(raw, NOW, include_forming=True)
        self.assertTrue(md._parse_candles(raw, NOW))
        raw = provider()(NOW)
        raw['candles'][-2]['complete'] = False
        values = md._parse_candles(raw, NOW, include_forming=True)
        self.assertEqual(len(values), len(raw['candles']) - 1)

    def test_completed_future_bar_is_never_accepted_as_forming(self):
        raw = range_payload(date(2026, 11, 20))
        rows = md._parse_candles(raw, NOW, include_forming=True)
        self.assertTrue(all(c.close_time <= NOW for c in rows))

    def test_closed_trade_keeps_exit_candle_separate_from_after_exit_context(self):
        rec = record('2026-11-09T14:30:00-05:00')
        view = self.build(rec)
        self.assertEqual(view['coverage']['trade_candle_count'], 2)
        self.assertEqual(view['coverage']['after_exit_count'], 5)
        last = view['candles'][1]
        self.assertTrue(all(c['timeline_phase'] == 'after_exit' for c in view['candles'][2:]))
        self.assertEqual(last['close_time'], at('2026-11-09T17:00:00-05:00').isoformat())
        self.assertTrue(last['contains_post_exit_prices'])
        self.assertTrue(view['coverage']['contains_post_exit_prices'])
        self.assertFalse(view['coverage']['exit_candle_pending'])
        self.assertEqual(view['events'][1]['candle_open_time'], last['open_time'])
        self.assertEqual(view['events'][1]['at'], at(rec['exit']['exit_at']).isoformat())

    def test_exit_exactly_at_close_places_next_bar_in_after_exit_context(self):
        view = self.build(record('2026-11-09T13:00:00-05:00'))
        self.assertEqual(view['coverage']['trade_candle_count'], 1)
        self.assertFalse(view['coverage']['contains_post_exit_prices'])
        self.assertEqual(view['events'][1]['candle_open_time'], view['candles'][0]['open_time'])

    def test_entry_and_exit_in_same_bar_preserve_both_events(self):
        view = self.build(record('2026-11-09T10:30:00-05:00'))
        self.assertEqual(view['coverage']['trade_candle_count'], 1)
        self.assertEqual(len(view['events']), 2)
        self.assertEqual(view['events'][0]['candle_open_time'], view['events'][1]['candle_open_time'])

    def test_recent_closed_trade_has_pending_exit_bar_and_never_fetches_future(self):
        with patch.object(md, '_fetch_candles', side_effect=provider()) as fetch:
            view = tl.build_timeline(record('2026-11-10T10:30:00-05:00'), NOW)
        self.assertEqual(fetch.call_args.args[0], NOW)
        self.assertTrue(view['coverage']['exit_candle_pending'])
        self.assertFalse(view['candles'][-1]['complete'])
        self.assertTrue(view['coverage']['contains_post_exit_prices'])

    def test_after_exit_context_grows_without_changing_trade_candles_or_events(self):
        rec = record('2026-11-09T14:30:00-05:00')
        a, b = self.build(rec), self.build(rec, NOW + timedelta(days=4))
        self.assertEqual(a['candles'][:2], b['candles'][:2])
        self.assertLess(a['coverage']['after_exit_count'], b['coverage']['after_exit_count'])
        self.assertEqual(a['events'], b['events'])

    def test_future_forming_changes_do_not_change_prior_indicators(self):
        baseline = self.build()
        fetch = provider()
        def changed(end, count=350):
            raw = fetch(end, count)
            if end == NOW: raw['candles'][-1]['mid'].update(c='1.5', h='1.6')
            return raw
        with patch.object(md, '_fetch_candles', side_effect=changed): later = tl.build_timeline(record(), NOW)
        self.assertEqual(baseline['candles'][:-1], later['candles'][:-1])
        self.assertNotEqual(baseline['candles'][-1]['indicators'], later['candles'][-1]['indicators'])
        self.assertNotEqual(baseline['price_result']['pips'],later['price_result']['pips'])

    def test_weekend_entry_without_market_candles_still_returns_context(self):
        now = at('2026-11-07T12:00:00-05:00')
        view = self.build(record(entry_at='2026-11-07T10:00:00-05:00'), now)
        self.assertEqual(view['candles'], [])
        self.assertEqual(len(view['chart_context']['candles']), 160)
        self.assertIsNone(view['events'][0]['candle_open_time'])
        self.assertEqual(view['coverage']['missing_candle_count'], 0)

    def test_weekend_and_dst_are_not_reported_as_missing_candles(self):
        view = self.build(record(entry_at='2026-10-30T13:30:00-04:00'))
        self.assertEqual(view['coverage']['missing_candle_count'], 0)
        times = [at(c['open_time']) for c in view['candles']]
        self.assertIn(at('2026-10-30T13:00:00-04:00'), times)
        self.assertIn(at('2026-11-01T17:00:00-05:00'), times)
        self.assertNotIn(at('2026-11-01T16:00:00-05:00'), times)

    def test_missing_candle_is_explicit_and_never_synthesized(self):
        fetch = provider()
        missing = at('2026-11-09T13:00:00-05:00')
        def gap(end, count=350):
            raw = fetch(end, count); raw['candles'] = [c for c in raw['candles'] if at(c['time']) != missing]
            return raw
        with patch.object(md, '_fetch_candles', side_effect=gap): view = tl.build_timeline(record(), NOW)
        self.assertEqual(view['coverage']['missing_candle_count'], 1)
        self.assertEqual(view['coverage']['first_missing_open'], missing.isoformat())
        self.assertNotIn(missing.isoformat(), [c['open_time'] for c in view['candles']])

    def test_backward_pages_retain_whole_trade_and_no_duplicate_candles(self):
        baseline = self.build(record(entry_at='2026-10-19T10:00:00-04:00'))
        with patch.object(tl, 'PAGE_SIZE', 100), patch.object(md, '_fetch_candles', side_effect=provider()) as fetch:
            view = tl.build_timeline(record(entry_at='2026-10-19T10:00:00-04:00'), NOW)
        self.assertGreater(fetch.call_count, 1)
        self.assertEqual(view, baseline)

    def test_oversized_history_fails_instead_of_truncating(self):
        with patch.object(tl, 'MAX_CANDLES', 3), patch.object(md, '_fetch_candles', side_effect=provider()):
            with self.assertRaisesRegex(md.MarketDataError, 'too long'): tl.build_timeline(record(), NOW)

    def test_insufficient_history_and_provider_errors_are_explicit(self):
        with patch.object(md, '_fetch_candles', return_value={'instrument':'EUR_USD','granularity':'H4','candles':[]}):
            with self.assertRaisesRegex(md.MarketDataError, 'Not enough'): tl.build_timeline(record(), NOW)
        with patch.object(md, '_fetch_candles', side_effect=md.MarketDataError('Unavailable',503)):
            with self.assertRaisesRegex(md.MarketDataError, 'Unavailable'): tl.build_timeline(record(), NOW)


    def test_old_trade_gets_first_160_after_exit_not_most_recent_160(self):
        rec = record('2026-10-20T14:30:00-04:00', entry_at='2026-10-19T10:00:00-04:00')
        now = at('2026-12-01T11:00:00-05:00')
        view = self.build(rec, now)
        after = [c for c in view['candles'] if c['timeline_phase'] == 'after_exit']
        self.assertEqual(len(after), 160)
        self.assertEqual(after[0]['open_time'], at('2026-10-20T17:00:00-04:00').isoformat())
        self.assertEqual(after[-1]['close_time'], at('2026-11-26T09:00:00-05:00').isoformat())
        self.assertEqual(view['display_through'], after[-1]['close_time'])
        self.assertEqual(view['coverage']['after_exit_complete_count'], 160)
        self.assertEqual(view['coverage']['missing_candle_count'], 0)
        later = self.build(rec, now+timedelta(days=4))
        self.assertEqual(view['candles'], later['candles'])
        self.assertEqual(view['events'], later['events'])

    def test_160th_forming_bar_is_included_but_161st_is_not(self):
        now = at('2026-11-26T07:00:00-05:00')
        rec = record('2026-10-20T14:30:00-04:00', entry_at='2026-10-19T10:00:00-04:00')
        view = self.build(rec, now)
        self.assertEqual(view['coverage']['after_exit_count'], 160)
        self.assertEqual(view['coverage']['after_exit_complete_count'], 159)
        self.assertFalse(view['candles'][-1]['complete'])
        self.assertEqual(view['candles'][-1]['timeline_phase'], 'after_exit')
        later = self.build(rec, now+timedelta(hours=4))
        self.assertEqual(later['coverage']['after_exit_count'], 160)
        self.assertEqual(later['coverage']['after_exit_complete_count'], 160)

    def test_forward_context_skips_weekend_and_dst_and_excludes_future_prices(self):
        now = at('2026-11-02T10:00:00-05:00')
        rec = record('2026-10-30T17:00:00-04:00', entry_at='2026-10-30T13:30:00-04:00')
        view = self.build(rec, now)
        after = [c for c in view['candles'] if c['timeline_phase'] == 'after_exit']
        self.assertEqual(len(after),5)
        self.assertEqual(after[0]['open_time'], at('2026-11-01T17:00:00-05:00').isoformat())
        self.assertTrue(all(at(c['open_time']) < now for c in after))
        self.assertEqual(view['coverage']['missing_candle_count'],0)
        self.assertEqual(view['coverage']['trade_candle_count'],1)

    def test_post_exit_gap_is_reported_and_does_not_shorten_160_available_candles(self):
        now = at('2026-12-01T11:00:00-05:00'); fetch = provider(now)
        gap = at('2026-10-20T21:00:00-04:00')
        def missing(end,count=350,*,start=None):
            raw = fetch(end,count,start=start)
            if start is not None: raw['candles'] = [c for c in raw['candles'] if at(c['time']) != gap]
            return raw
        rec = record('2026-10-20T14:30:00-04:00', entry_at='2026-10-19T10:00:00-04:00')
        with patch.object(md,'_fetch_candles',side_effect=missing): view = tl.build_timeline(rec,now)
        self.assertEqual(view['coverage']['after_exit_count'],160)
        self.assertEqual(view['coverage']['missing_candle_count'],1)
        self.assertEqual(view['coverage']['first_missing_open'],gap.isoformat())
        self.assertNotIn(gap.isoformat(),[c['open_time'] for c in view['candles']])

    def test_pending_exit_bar_does_not_request_future_context(self):
        with patch.object(md,'_fetch_candles',side_effect=provider()) as fetch:
            view = tl.build_timeline(record('2026-11-10T10:30:00-05:00'),NOW)
        self.assertTrue(view['coverage']['exit_candle_pending'])
        self.assertEqual(view['coverage']['after_exit_count'],0)
        self.assertEqual(fetch.call_count,1)
        self.assertNotIn('start',fetch.call_args.kwargs)

    def test_after_exit_prices_cannot_change_trade_indicators(self):
        rec = record('2026-11-09T14:30:00-05:00'); baseline = self.build(rec)
        fetch = provider()
        def changed(end,count=350,*,start=None):
            raw = fetch(end,count,start=start)
            if start is not None:
                for row in raw['candles']: row['mid'].update(c='1.5',h='1.6')
            return raw
        with patch.object(md,'_fetch_candles',side_effect=changed): view = tl.build_timeline(rec,NOW)
        self.assertEqual(view['candles'][:2],baseline['candles'][:2])
        self.assertNotEqual(view['candles'][2]['indicators'],baseline['candles'][2]['indicators'])

    def test_forward_request_uses_from_and_count_without_to(self):
        raw = {'instrument':'EUR_USD','granularity':'H4','candles':[]}
        with patch.dict(os.environ,ENVIRONMENT,clear=True), patch.object(md,'urlopen',return_value=io.BytesIO(json.dumps(raw).encode())) as request:
            md._fetch_candles(None,count=161,start=NOW)
        params = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
        self.assertEqual(params['from'],[NOW.isoformat()])
        self.assertEqual(params['count'],['161'])
        self.assertNotIn('to',params)
        self.assertEqual(params['granularity'],['H4'])
        self.assertEqual(params['dailyAlignment'],['17'])
        self.assertEqual(params['alignmentTimezone'],['America/New_York'])
        with self.assertRaises(ValueError): md._fetch_candles(NOW,start=NOW)


class TimelineAPITests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db, 'DB_PATH', root/'test.db'))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        self.client = self.enterContext(TestClient(main.app))
        self.ai = self.enterContext(patch.object(main.client.responses, 'create', side_effect=AssertionError('No AI call')))

    def tearDown(self):
        self.ai.assert_not_called()

    def test_chart_reads_never_mutate_entry_snapshots_strategy_or_reviews(self):
        setup = sd.store_snapshot(uuid4(), {}, snapshot())
        rec = self.client.post('/trades', json=trade(setup_id=setup['id'],entry_at=ENTERED)).json()
        original = deepcopy(td.fetch_trade(rec['id']))
        with patch.object(md, '_fetch_candles', side_effect=provider()):
            result = self.client.get('/trades/'+rec['id']+'/timeline')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(td.fetch_trade(rec['id']),original)

    def test_after_exit_context_does_not_change_saved_scores_or_outcome(self):
        setup = sd.store_snapshot(uuid4(), {}, snapshot())
        rec = self.client.post('/trades', json=trade(setup_id=setup['id'],entry_at=ENTERED)).json()
        closed = self.client.post('/trades/'+rec['id']+'/close',json=full_exit(exit_at='2026-11-09T14:30:00-05:00')).json()
        before = deepcopy(td.fetch_trade(closed['id']))
        with patch.object(md,'_fetch_candles',side_effect=provider()):
            response = self.client.get('/trades/'+closed['id']+'/timeline')
        self.assertEqual(response.status_code,200,response.text)
        self.assertGreater(response.json()['coverage']['after_exit_count'],0)
        self.assertEqual(td.fetch_trade(closed['id']),before)
        self.assertEqual(before['strategy_analyses'],rec['strategy_analyses'])

    def test_saved_exit_during_fetch_rebuilds_with_closed_boundary(self):
        rec = self.client.post('/trades', json=trade(entry_at=ENTERED)).json()
        original = tl.build_timeline
        calls = []
        def closing(record, now):
            calls.append(record['status'])
            view = original(record, NOW)
            if len(calls) == 1:
                result = self.client.post('/trades/'+rec['id']+'/close', json=full_exit(exit_at='2026-11-09T14:30:00-05:00'))
                self.assertEqual(result.status_code,200,result.text)
            return view
        with patch.object(md,'_fetch_candles',side_effect=provider()), patch.object(tl,'build_timeline',side_effect=closing):
            response = self.client.get('/trades/'+rec['id']+'/timeline')
        self.assertEqual(calls,['open','closed'])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['coverage']['trade_candle_count'],2)
        self.assertEqual(response.json()['coverage']['after_exit_count'],5)

    def test_missing_trade_invalid_id_and_provider_failure_do_not_write(self):
        self.assertEqual(self.client.get('/trades/'+str(uuid4())+'/timeline').status_code,404)
        self.assertEqual(self.client.get('/trades/not-a-uuid/timeline').status_code,422)
        rec = self.client.post('/trades', json=trade(entry_at=ENTERED)).json()
        with patch.object(md,'_fetch_candles',side_effect=md.MarketDataError('Unavailable',503)):
            self.assertEqual(self.client.get('/trades/'+rec['id']+'/timeline').status_code,503)
        self.assertEqual(td.fetch_trade(rec['id']),rec)
