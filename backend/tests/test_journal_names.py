"""Journal names and per-entry averages use temporary storage and no live providers."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.test_market_data import ENVIRONMENT
from tests.test_strategy_rules import scoring_snapshot
from tests.test_custom_range import range_snapshot
from tests.test_today import view_at, instant
from strategy_rules import evaluate_strategy
from date_range import evaluate_range_strategy
import database as db
import range_database as rd
import main


class JournalNamesTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, 'DB_PATH', Path(directory) / 'journal.db'))
        self.enterContext(patch.dict(os.environ, ENVIRONMENT, clear=True))
        self.market = self.enterContext(patch.object(main, 'get_market_data', side_effect=AssertionError('No provider calls')))
        self.ai = self.enterContext(patch.object(main.client.responses, 'create', side_effect=AssertionError('No AI calls')))
        self.client = self.enterContext(TestClient(main.app))
        self.snapshot = scoring_snapshot()
        self.entry = {'pair': 'EURUSD', 'timeframe': '4h', 'journal_date': '2026-10-20', 'strategy': 'Saved rules', 'notes': ''}

    def tearDown(self):
        self.market.assert_not_called()
        self.ai.assert_not_called()

    def stage(self, kind='daily', snapshot=None, evaluation=None):
        if kind == 'range':
            snapshot = range_snapshot()
            entry = {**self.entry, 'start_date': '2026-10-19', 'end_date': '2026-10-23', 'rule_set_id': 'four_factor_v4'}
            entry.pop('journal_date')
            return rd.store_range_draft(entry, 'Original range', snapshot, evaluate_range_strategy(snapshot))
        snapshot = snapshot or self.snapshot
        entry = {**self.entry, 'journal_date': snapshot['journal_date']}
        return db.store_generated_draft(entry, 'Original daily', snapshot, evaluation if evaluation is not None else evaluate_strategy(snapshot))

    def save(self, kind='daily', title='', **kwargs):
        endpoint = '/range-journals' if kind == 'range' else '/journals'
        request = {'generation_id': self.stage(kind, **kwargs), 'edited_draft': 'Saved review', 'title': title}
        response = self.client.post(endpoint, json=request)
        self.assertEqual(response.status_code, 201, response.text)
        return endpoint, response.json(), request

    def test_names_create_rename_reopen_and_clear_for_daily_and_range(self):
        for kind in ('daily', 'range'):
            with self.subTest(kind=kind):
                endpoint, original, _ = self.save(kind, '  EUR/USD — session review ✨  ')
                self.assertEqual(original['title'], 'EUR/USD — session review ✨')
                response = self.client.patch(f"{endpoint}/{original['id']}", json={'edited_draft': original['edited_draft'], 'title': 'Renamed review'})
                self.assertEqual(response.status_code, 200, response.text)
                renamed = response.json()
                for key in original:
                    if key not in ('title', 'updated_at'):
                        self.assertEqual(renamed[key], original[key], key)
                self.assertEqual(self.client.get(f"{endpoint}/{original['id']}").json()['title'], 'Renamed review')
                self.assertEqual(self.client.get(endpoint).json()['items'][0]['title'], 'Renamed review')
                cleared = self.client.patch(f"{endpoint}/{original['id']}", json={'edited_draft': original['edited_draft'], 'title': '   '})
                self.assertEqual(cleared.json()['title'], '')

    def test_older_clients_can_omit_title_without_clearing_existing_name(self):
        for kind in ('daily', 'range'):
            endpoint, saved, _ = self.save(kind, 'Keep this name')
            edited = self.client.patch(f"{endpoint}/{saved['id']}", json={'edited_draft': 'Updated text'})
            self.assertEqual(edited.json()['title'], 'Keep this name')
            self.assertEqual(edited.json()['edited_draft'], 'Updated text')
            response = self.client.post(endpoint, json={'generation_id': self.stage(kind), 'edited_draft': 'Untitled'})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()['title'], '')

    def test_title_limit_and_types_are_validated_before_any_write(self):
        for kind in ('daily', 'range'):
            endpoint, saved, request = self.save(kind, 'x' * 120)
            for title in ('x' * 121, None, 123, True, [], {}):
                with self.subTest(kind=kind, title=title):
                    self.assertEqual(self.client.post(endpoint, json={**request, 'title': title}).status_code, 422)
                    self.assertEqual(self.client.patch(f"{endpoint}/{saved['id']}", json={'edited_draft': 'New text', 'title': title}).status_code, 422)
                    self.assertEqual(self.client.get(f"{endpoint}/{saved['id']}").json(), saved)

    def test_retry_is_idempotent_and_cannot_overwrite_a_later_rename(self):
        for kind in ('daily', 'range'):
            endpoint, saved, request = self.save(kind, 'Initial name')
            self.assertEqual(self.client.post(endpoint, json=request).json()['id'], saved['id'])
            self.assertEqual(self.client.post(endpoint, json={**request, 'title': 'Different name'}).status_code, 409)
            self.client.patch(f"{endpoint}/{saved['id']}", json={'edited_draft': saved['edited_draft'], 'title': 'Later name'})
            self.assertEqual(self.client.post(endpoint, json=request).status_code, 409)
            self.assertEqual(self.client.get(f"{endpoint}/{saved['id']}").json()['title'], 'Later name')
            self.assertEqual(self.client.get(endpoint).json()['total'], 1)

    def test_duplicate_names_are_allowed_and_daily_range_ids_stay_isolated(self):
        _, daily, _ = self.save(title='Same name')
        _, custom, _ = self.save('range', 'Same name')
        self.assertEqual(daily['id'], custom['id'])
        self.save(title='Same name')
        self.client.patch(f"/journals/{daily['id']}", json={'edited_draft': daily['edited_draft'], 'title': 'Daily only'})
        self.assertEqual(self.client.get(f"/range-journals/{custom['id']}").json()['title'], 'Same name')
        self.assertEqual(self.client.get('/journals').json()['total'], 2)
        for endpoint in ('/journals', '/range-journals'):
            self.assertEqual(self.client.patch(f'{endpoint}/9999', json={'edited_draft': 'Text', 'title': 'Missing'}).status_code, 404)

    def test_existing_schema_and_pending_drafts_upgrade_without_data_loss(self):
        _, daily, _ = self.save()
        _, custom, _ = self.save('range')
        pending_daily, pending_range = self.stage(), self.stage('range')
        with db.get_connection(write=True) as connection:
            connection.execute('ALTER TABLE journals DROP COLUMN title')
            connection.execute('ALTER TABLE range_journals DROP COLUMN title')
        for _ in range(2):
            db.init_db(); rd.init_range_db()
        self.assertEqual(db.fetch_journal(daily['id']), daily)
        self.assertEqual(rd.fetch_range_journal(custom['id']), custom)
        for endpoint, generation in (('/journals', pending_daily), ('/range-journals', pending_range)):
            response = self.client.post(endpoint, json={'generation_id': generation, 'edited_draft': 'Pending draft', 'title': 'Named after upgrade'})
            self.assertEqual(response.status_code, 201, response.text)
            db.init_db(); rd.init_range_db()
            self.assertEqual(self.client.get(f"{endpoint}/{response.json()['id']}").json()['title'], 'Named after upgrade')

    def test_each_daily_card_uses_its_own_average_and_rename_preserves_order(self):
        _, first, _ = self.save(title='First strategy')
        for candle in self.snapshot['candles']:
            candle['indicators']['rsi14'] = 60
            candle['indicators']['rsi14_sma14'] = 60
        _, second, _ = self.save(title='Second strategy')
        self.client.patch(f"/journals/{first['id']}", json={'edited_draft': first['edited_draft'], 'title': 'First renamed'})
        page = self.client.get('/journals?journal_date=2026-10-20').json()['items']
        self.assertEqual([item['id'] for item in page], [second['id'], first['id']])
        self.assertEqual([item['title'] for item in page], ['Second strategy', 'First renamed'])
        self.assertEqual([item['average_net_score'] for item in page], [second['rule_evaluation']['summary']['net_score'], first['rule_evaluation']['summary']['net_score']])
        self.assertNotEqual(page[0]['average_net_score'], page[1]['average_net_score'])
        day = self.client.get('/journals/calendar?month=2026-10').json()['days'][0]
        self.assertEqual((day['source_journal_id'], day['average_net_score']), (second['id'], page[0]['average_net_score']))
        for item in page:
            self.assertNotIn('rule_evaluation_json', item)
            self.assertNotIn('market_data_json', item)

    def test_today_card_uses_provisional_average_but_calendar_waits_for_full_session(self):
        for now, expected_complete in ((instant('2026-10-23T06:00:00'), False), (instant('2026-10-23T17:00:00'), True)):
            view = view_at(now)
            _, saved, _ = self.save(title='Today review', snapshot=view['market_data'], evaluation=view['rule_evaluation'])
            item = self.client.get('/journals?journal_date=2026-10-23').json()['items'][0]
            self.assertEqual(item['average_net_score'], view['rule_evaluation']['summary']['net_score'])
            self.assertEqual(item['session_complete'], expected_complete)
            day = self.client.get('/journals/calendar?month=2026-10').json()['days'][0]
            self.assertEqual(day['average_net_score'], item['average_net_score'] if expected_complete else None)
            changed = self.client.patch(f"/journals/{saved['id']}", json={'edited_draft': saved['edited_draft'], 'title': 'Today renamed'}).json()
            self.assertEqual(changed['rule_evaluation'], saved['rule_evaluation'])

    def test_missing_incomplete_legacy_and_zero_card_scores_are_distinct(self):
        evaluations = [None, evaluate_strategy(self.snapshot, 'four_factor_v3')]
        incomplete = copy.deepcopy(self.snapshot)
        incomplete['candles'][0]['indicators']['rsi14'] = None
        incomplete['candles'][0]['indicators']['rsi14_sma14'] = None
        evaluations.append(evaluate_strategy(incomplete))
        for evaluation in evaluations:
            generation = db.store_generated_draft(self.entry, 'Original', self.snapshot, evaluation)
            db.save_generated_journal(generation, 'Saved')
            self.assertIsNone(self.client.get('/journals').json()['items'][0]['average_net_score'])
        for candle in [*self.snapshot['previous_candles'], *self.snapshot['candles']]:
            candle['indicators'].update(ema20=candle['close'], sma190=candle['close'], rsi14=50, rsi14_sma14=50)
            candle['indicators']['squeeze']['momentum'] = 0
        self.save(title='Neutral review')
        self.assertEqual(self.client.get('/journals').json()['items'][0]['average_net_score'], 0)


if __name__ == '__main__':
    unittest.main()
