"""Offline intraday checks: no live providers and no user database writes."""
import copy
import json
import os
import tempfile
import unittest
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from tests.test_custom_range import range_payload
from tests.test_market_data import ENVIRONMENT
from tests.test_scored_journal import valid_scored_commentary
from journal_grounding import InvalidJournalEvidence, build_evidence_catalog
from scored_journal import build_summary_context, render_scored_journal
from strategy_rules import evaluate_strategy
import today
import market_data as md
import database as db
import main


def instant(value):
    return datetime.fromisoformat(value).replace(tzinfo=md.NY).astimezone(md.UTC)


NOW = instant('2026-10-23T06:00:00')  # Three closed candles, fourth forming.


class Clock(datetime):
    value = NOW
    @classmethod
    def now(cls, tz=None):
        return cls.value.astimezone(tz)


def view_at(now=NOW):
    with patch.object(md, '_fetch_candles', return_value=range_payload()):
        return today.build_today_view(now)


def commentary(view):
    value = valid_scored_commentary(build_summary_context(view['market_data'], view['rule_evaluation']))
    for section in value.values():
        for reference in section['results']:
            reference['candle_id'] = f"C{view['session']['candle_count']}"
    value['session_review']['explanation'] = 'The session so far shows movement supported by the supplied completed candles.'
    value['limitations']['explanation'] = 'The remaining candles are pending, so the provisional balance may change.'
    return value


class TodayMarketTests(unittest.TestCase):
    def test_zero_candles_has_six_slots_and_makes_no_provider_request(self):
        with patch.object(md, '_fetch_candles') as fetch:
            view = today.build_today_view(instant('2026-10-22T18:00:00'))
        self.assertIsNone(view['market_data']); self.assertIsNone(view['snapshot_id'])
        self.assertEqual([s['status'] for s in view['slots']], ['forming'] + ['upcoming'] * 5)
        fetch.assert_not_called()

    def test_three_closed_candles_have_correct_coverage_and_equal_average(self):
        view = view_at()
        result = view['rule_evaluation']
        self.assertEqual([s['status'] for s in view['slots']], ['completed'] * 3 + ['forming', 'upcoming', 'upcoming'])
        self.assertFalse(view['market_data']['session']['complete'])
        self.assertEqual(result['summary']['method'], 'session_to_date')
        self.assertEqual(result['session_end']['candle_id'], 'C3')
        self.assertEqual(result['summary']['expected_factors'], 12)
        for side in ('bullish', 'bearish'):
            self.assertEqual(result['summary'][f'{side}_points'], sum(c[f'{side}_points'] for c in result['candles']) / 3)
        self.assertEqual(view['market_data']['data_through'], '2026-10-23T09:00:00+00:00')

    def test_every_close_boundary_advances_only_after_close(self):
        start, _ = md.session_bounds(date(2026, 10, 23))
        for count in range(1, 7):
            at = start + timedelta(hours=4 * count)
            with self.subTest(count=count):
                self.assertEqual(view_at(at - timedelta(microseconds=1))['session']['candle_count'], count - 1)
                self.assertEqual(view_at(at)['session']['candle_count'], count)

    def test_rollover_and_weekend_follow_new_york_not_calendar_midnight(self):
        cases = [('2026-10-22T16:59:59', '2026-10-22', False), ('2026-10-22T17:00:00', '2026-10-23', False),
                 ('2026-10-23T17:00:00', '2026-10-23', True), ('2026-10-24T12:00:00', '2026-10-23', True),
                 ('2026-10-25T16:59:59', '2026-10-23', True), ('2026-10-25T17:00:00', '2026-10-26', False),
                 ('2026-10-26T00:00:00', '2026-10-26', False)]
        for value, expected, closed in cases:
            context = today.session_context(instant(value))
            self.assertEqual((context[0].isoformat(), context[4]), (expected, closed))

    def test_dst_weekends_and_monday_predecessors(self):
        for value, offset in [('2026-03-08T17:00:00', '-04:00'), ('2026-11-01T17:00:00', '-05:00')]:
            context = today.session_context(instant(value))
            self.assertEqual(context[3], 0)
            self.assertTrue(context[1].astimezone(md.NY).isoformat().endswith(offset))
            with patch.object(md, '_fetch_candles', return_value=range_payload(context[0])):
                view = today.build_today_view(instant(value) + timedelta(hours=5))
            self.assertEqual(view['session']['candle_count'], 1)
            self.assertEqual(view['rule_evaluation']['summary']['unavailable_factors'], 0)

    def test_forming_future_values_cannot_change_indicators_or_scores(self):
        raw = range_payload()
        before = view_at()
        for candle in raw['candles'][-3:]:
            candle['mid'] = {key: '999' for key in 'ohlc'}
        with patch.object(md, '_fetch_candles', return_value=raw):
            after = today.build_today_view(NOW)
        self.assertEqual(before['market_data']['candles'], after['market_data']['candles'])
        self.assertEqual(before['rule_evaluation'], after['rule_evaluation'])

    def test_missing_overdue_incomplete_duplicate_and_short_history_fail(self):
        for kind in ('gap', 'incomplete', 'duplicate', 'warmup'):
            raw = range_payload()
            if kind == 'gap': raw['candles'].pop(-5)
            if kind == 'incomplete': raw['candles'][-4]['complete'] = False
            if kind == 'duplicate': raw['candles'].append(copy.deepcopy(raw['candles'][-4]))
            if kind == 'warmup': raw['candles'] = raw['candles'][-100:]
            with self.subTest(kind=kind), patch.object(md, '_fetch_candles', return_value=raw), self.assertRaises(md.MarketDataError):
                today.build_today_view(NOW)

    def test_history_stays_anchored_as_session_grows_and_final_matches_daily(self):
        first = view_at()
        second = view_at(instant('2026-10-23T14:00:00'))
        full = view_at(instant('2026-10-23T17:00:00'))
        with patch.object(md, '_fetch_candles', return_value=range_payload()):
            daily = md.get_market_data(date(2026, 10, 23))
        self.assertEqual(first['market_data']['candles'], second['market_data']['candles'][:3])
        self.assertEqual(full['market_data']['candles'], daily['candles'])
        self.assertEqual(full['rule_evaluation']['summary'], evaluate_strategy(daily)['summary'])

    def test_default_grounding_still_rejects_partial_and_partial_rejects_tampering(self):
        snapshot = view_at()['market_data']
        with self.assertRaises(InvalidJournalEvidence): build_evidence_catalog(snapshot)
        self.assertEqual(list(build_evidence_catalog(snapshot, allow_partial=True)), ['C1', 'C2', 'C3'])
        for kind in ('count', 'as_of', 'complete', 'date', 'cutoff', 'order'):
            bad = copy.deepcopy(snapshot)
            if kind == 'count': bad['session']['candle_count'] = 6
            if kind == 'as_of': bad['as_of'] = bad['candles'][1]['close_time']
            if kind == 'complete': bad['session']['complete'] = True
            if kind == 'date': bad['journal_date'] = '2026-10-24'
            if kind == 'cutoff': bad['data_through'] = bad['session']['end_utc']
            if kind == 'order': bad['candles'][1], bad['candles'][2] = bad['candles'][2], bad['candles'][1]
            with self.subTest(kind=kind), self.assertRaises(InvalidJournalEvidence): build_evidence_catalog(bad, allow_partial=True)

    def test_missing_factor_withholds_to_date_average_not_pending_zero_points(self):
        snapshot = view_at()['market_data']
        snapshot['candles'][1]['indicators']['rsi14'] = None
        result = evaluate_strategy(snapshot, allow_partial=True)
        self.assertIsNone(result['summary']['bullish_points'])
        self.assertEqual(result['summary']['evaluated_factors'], 11)

    def test_partial_canonical_rules_do_not_require_future_candles(self):
        rules = view_at()['rule_evaluation']['rule_set']['rules']
        self.assertNotIn('all six', rules)
        self.assertNotIn('twenty-four', rules)
        self.assertNotIn('or average fewer candles', rules)
        self.assertIn('Pending candles have no points', rules)


class TodayAPITests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, 'DB_PATH', Path(directory) / 'journal.db'))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        self.enterContext(patch.object(today, '_latest', None))
        self.enterContext(patch.object(today, '_snapshots', OrderedDict()))
        self.enterContext(patch.object(today, 'datetime', Clock))
        self.enterContext(patch.object(Clock, 'value', NOW))
        self.tick = self.enterContext(patch.object(today, 'monotonic', return_value=1000))
        self.provider = self.enterContext(patch.object(md, '_fetch_candles', return_value=range_payload()))
        self.ai = self.enterContext(patch.object(main.client.responses, 'create'))
        self.client = self.enterContext(TestClient(main.app))

    def current(self):
        response = self.client.get('/today')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def generate(self, view=None):
        view = view or self.current()
        self.ai.return_value = SimpleNamespace(status='completed', output_text=json.dumps(commentary(view)))
        response = self.client.post('/today/generate', json={'snapshot_id': view['snapshot_id'], 'notes': 'Review the session so far.'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_polling_is_cached_without_ai_or_database_drafts(self):
        first, second = self.current(), self.current()
        self.assertEqual(first, second)
        self.provider.assert_called_once(); self.ai.assert_not_called()
        self.assertEqual(self.client.get('/today').headers['cache-control'], 'no-store')
        with db.get_connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM generated_drafts').fetchone()[0], 0)

    def test_boundary_invalidates_cache_and_snapshot_keeps_original_evidence(self):
        first = self.current()
        Clock.value = instant('2026-10-23T09:00:00')
        second = self.current()
        self.assertEqual(second['session']['candle_count'], 4)
        self.assertNotEqual(first['snapshot_id'], second['snapshot_id'])
        draft = self.generate(first)
        self.assertEqual(draft['market_data'], first['market_data'])
        self.assertEqual(len(draft['rule_evaluation']['candles']), 3)

    def test_unchanged_refresh_has_same_data_key_and_new_snapshot_id(self):
        first = self.current()
        self.tick.return_value += 61; Clock.value += timedelta(seconds=61)
        second = self.current()
        self.assertEqual(first['market_data']['data_key'], second['market_data']['data_key'])
        self.assertNotEqual(first['snapshot_id'], second['snapshot_id'])

    def test_expiry_and_cache_limit_are_bounded(self):
        first = self.current()
        self.tick.return_value += today.SNAPSHOT_TTL + 1
        self.assertEqual(self.client.post('/today/generate', json={'snapshot_id': first['snapshot_id']}).status_code, 409)
        self.ai.assert_not_called()
        with patch.object(today, 'MAX_SNAPSHOTS', 2):
            ids = []
            for _ in range(3):
                self.tick.return_value += 61
                ids.append(self.current()['snapshot_id'])
            self.assertEqual(len(today._snapshots), 2)
            self.assertNotIn(ids[0], today._snapshots)

    def test_failure_never_returns_stale_cache_as_fresh(self):
        self.current(); self.tick.return_value += 61
        self.provider.side_effect = md.MarketDataError('Provider delayed', 503)
        self.assertEqual(self.client.get('/today').status_code, 503)
        self.ai.assert_not_called()

    def test_zero_candles_cannot_generate_and_client_cannot_submit_data(self):
        Clock.value = instant('2026-10-22T18:00:00')
        view = self.current()
        self.assertIsNone(view['snapshot_id'])
        for body, status in [({'snapshot_id': None}, 422), ({'snapshot_id': str(uuid4())}, 409),
                             ({'snapshot_id': str(uuid4()), 'market_data': {}}, 422),
                             ({'snapshot_id': str(uuid4()), 'notes': 'x' * 10001}, 422)]:
            self.assertEqual(self.client.post('/today/generate', json=body).status_code, status)
        self.ai.assert_not_called(); self.provider.assert_not_called()

    def test_summary_gets_exact_python_coverage_and_pending_cannot_be_cited(self):
        view = self.current(); draft = self.generate(view)
        sent = json.loads(self.ai.call_args.kwargs['input'])
        self.assertEqual(sent['market_data'], view['market_data'])
        self.assertEqual(sent['summary_context']['coverage']['completed_candles'], 3)
        self.assertEqual(list(sent['evidence_catalog']), ['C1', 'C2', 'C3'])
        self.assertIn('Session in progress: 3 of 6', draft['draft'])
        self.assertIn('Session-to-date bias', draft['draft'])
        self.assertNotIn('Session-end bias:', draft['draft'])
        bad = commentary(view); bad['consensus']['results'][0]['candle_id'] = 'C4'
        with self.assertRaises(InvalidJournalEvidence): render_scored_journal(json.dumps(bad), view['market_data'], view['rule_evaluation'])
        bad = commentary(view); bad['consensus']['method'] = 'session_average'
        self.ai.return_value.output_text = json.dumps(bad)
        self.assertEqual(self.client.post('/today/generate', json={'snapshot_id': view['snapshot_id']}).status_code, 502)

    def test_save_reopen_edit_and_delete_preserve_snapshot_and_calendar_semantics(self):
        view = self.current(); draft = self.generate(view)
        request = {'generation_id': draft['generation_id'], 'edited_draft': draft['draft']}
        saved = self.client.post('/journals', json=request).json()
        self.assertEqual(self.client.post('/journals', json=request).json()['id'], saved['id'])
        self.tick.return_value += 61; Clock.value = instant('2026-10-23T14:00:00')
        self.current()
        self.provider.reset_mock(); self.ai.reset_mock()
        updated = self.client.patch(f"/journals/{saved['id']}", json={'edited_draft': 'My review'}).json()
        reopened = self.client.get(f"/journals/{saved['id']}").json()
        self.assertEqual(updated, reopened)
        self.assertEqual(reopened['market_data'], view['market_data'])
        self.assertEqual(reopened['rule_evaluation'], view['rule_evaluation'])
        self.assertEqual(reopened['original_draft'], draft['draft'])
        item = self.client.get('/journals').json()['items'][0]
        self.assertEqual(item['completed_candles'], 3); self.assertFalse(item['session_complete'])
        self.assertIsNone(item['change_percent'])
        calendar = self.client.get('/journals/calendar?month=2026-10').json()
        self.assertEqual(calendar['journal_count'], 1)
        self.assertIsNone(calendar['days'][0]['change_percent'])
        self.assertEqual(self.client.delete(f"/journals/{saved['id']}").status_code, 204)
        self.assertEqual(self.client.get('/journals').json()['total'], 0)
        self.provider.assert_not_called(); self.ai.assert_not_called()


if __name__ == '__main__':
    unittest.main()
