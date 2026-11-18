"""Display-only extended context: indicator warmup, exact bounds and no AI/storage."""
from copy import deepcopy
from datetime import timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.test_setup_evaluator import main, ENVIRONMENT
from tests.test_trade_timeline import provider, at, NOW
import chart_context as cc
import market_data as md
import database as db

BEFORE = at('2026-10-19T17:00:00-04:00')
AFTER = at('2026-10-20T17:00:00-04:00')
LATER = at('2026-12-01T11:00:00-05:00')


class ChartContextTests(unittest.TestCase):
    def build(self, after=AFTER, now=LATER):
        with patch.object(md,'_fetch_candles',side_effect=provider(now)):
            return cc.build_context(BEFORE,after,now)

    def test_160_preceding_and_first_160_following_all_have_initialized_indicators(self):
        view=self.build()
        self.assertEqual((len(view['preceding']),len(view['following'])),(160,160))
        self.assertEqual(view['preceding'][-1]['close_time'],BEFORE.isoformat())
        self.assertEqual(view['following'][0]['open_time'],AFTER.isoformat())
        self.assertEqual(view['following'][-1]['close_time'],at('2026-11-26T09:00:00-05:00').isoformat())
        for row in view['preceding']+view['following']:
            for key in ('sma190','ema20','rsi14','rsi14_sma14'):
                self.assertIsNotNone(row['indicators'][key])
            self.assertIsNotNone(row['indicators']['squeeze']['momentum'])
        self.assertEqual(view['purpose'],'display_only')
        self.assertNotIn('rule_evaluation',view)
        self.assertEqual(self.build(now=LATER+timedelta(days=3))['following'],view['following'])

    def test_live_preview_only_requests_earlier_data(self):
        with patch.object(md,'_fetch_candles',side_effect=provider(NOW)) as fetch:
            view=cc.build_context(BEFORE,None,NOW)
        self.assertEqual(view['following'],[])
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(fetch.call_args.args,(BEFORE,))
        self.assertEqual(fetch.call_args.kwargs,{'count':480})

    def test_recent_context_includes_forming_bar_but_never_future(self):
        now=at('2026-10-20T23:00:00-04:00')
        view=self.build(now=now)
        self.assertEqual(len(view['following']),2)
        self.assertTrue(view['following'][0]['complete'])
        self.assertFalse(view['following'][-1]['complete'])
        self.assertTrue(all(at(row['open_time']) < now for row in view['following']))
        self.assertEqual(self.build(now=AFTER)['following'],[])

    def test_weekends_and_dst_keep_real_times_without_synthetic_candles(self):
        end=at('2026-10-30T17:00:00-04:00')
        now=at('2026-11-02T10:00:00-05:00')
        with patch.object(md,'_fetch_candles',side_effect=provider(now)):
            view=cc.build_context(BEFORE,end,now)
        self.assertEqual(len(view['following']),5)
        self.assertEqual(view['following'][0]['open_time'],at('2026-11-01T17:00:00-05:00').isoformat())

    def test_future_prices_never_change_preceding_rows(self):
        original=self.build(); fetch=provider(LATER)
        def changed(end,count=350,*,start=None):
            raw=deepcopy(fetch(end,count,start=start))
            if start is not None:
                for row in raw['candles']: row['mid'].update(c='1.5',h='1.6')
            return raw
        with patch.object(md,'_fetch_candles',side_effect=changed): view=cc.build_context(BEFORE,AFTER,LATER)
        self.assertEqual(view['preceding'],original['preceding'])
        self.assertNotEqual(view['following'],original['following'])

    def test_invalid_boundaries_and_insufficient_data_fail_visibly(self):
        with patch.object(md,'_fetch_candles',side_effect=AssertionError('Invalid boundary must not fetch')):
            for before,after in ((NOW+timedelta(days=1),None),(BEFORE,BEFORE-timedelta(hours=4)),(BEFORE,NOW+timedelta(days=1)),(at('1999-12-31T00:00:00+00:00'),None)):
                with self.assertRaises(md.MarketDataError): cc.build_context(before,after,NOW)
        with patch.object(md,'_fetch_candles',return_value={'instrument':'EUR_USD','granularity':'H4','candles':[]}):
            with self.assertRaisesRegex(md.MarketDataError,'Not enough'): cc.build_context(BEFORE,None,NOW)

    def test_endpoint_validates_timezone_and_does_not_write_or_call_ai(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db,'DB_PATH',root/'test.db'))
        self.enterContext(patch.dict(os.environ,ENVIRONMENT,clear=True))
        client=self.enterContext(TestClient(main.app))
        self.enterContext(patch.object(main.client.responses,'create',side_effect=AssertionError('No AI call')))
        with db.get_connection() as con: original=list(con.iterdump())
        self.assertEqual(client.get('/chart-context',params={'before_at':'2026-10-20T10:00:00'}).status_code,422)
        with patch.object(md,'_fetch_candles',side_effect=provider()):
            response=client.get('/chart-context',params={'before_at':BEFORE.isoformat(),'after_at':AFTER.isoformat()})
        self.assertEqual(response.status_code,200,response.text)
        with db.get_connection() as con: self.assertEqual(list(con.iterdump()),original)
        with patch.object(md,'_fetch_candles',side_effect=md.MarketDataError('Provider unavailable',503)):
            self.assertEqual(client.get('/chart-context',params={'before_at':BEFORE.isoformat()}).status_code,503)


class FormingContextTests(unittest.TestCase):
    def test_current_forming_candle_has_provisional_indicators_separate_from_evidence(self):
        before=at('2026-11-09T17:00:00-05:00')
        with patch.object(md,'_fetch_candles',side_effect=provider(NOW)):
            view=cc.build_context(before,None,NOW,forming_at=NOW)
        row=view['forming_candle']
        self.assertEqual(row['open_time'],at('2026-11-10T09:00:00-05:00').isoformat())
        self.assertFalse(row['complete'])
        self.assertEqual(row['as_of'],NOW.isoformat())
        self.assertEqual(view['following'],[])
        self.assertNotIn('rule_evaluation',view)
        for key in ('sma190','ema20','rsi14','rsi14_sma14'):
            self.assertIsNotNone(row['indicators'][key])
        self.assertIsNotNone(row['indicators']['squeeze']['momentum'])

    def test_first_session_candle_before_any_close_and_dst_opening(self):
        for start in ('2026-11-08T17:00:00-05:00','2026-11-01T17:00:00-05:00'):
            before=at(start); now=before+timedelta(minutes=30)
            with patch.object(md,'_fetch_candles',side_effect=provider(now)):
                result=cc.build_context(before,None,now,forming_at=now)
            self.assertEqual(result['forming_candle']['open_time'],before.isoformat())
            self.assertEqual(len(result['preceding']),160)
            self.assertTrue(all(at(row['close_time'])<=before for row in result['preceding']))

    def test_old_cutoff_never_receives_full_historical_bar_or_todays_bar(self):
        with patch.object(md,'_fetch_candles',side_effect=AssertionError('No historical forming request')):
            self.assertIsNone(cc.forming_candle(NOW-timedelta(days=1),NOW))
        # Previous bar closed two hours ago; today's partial prices cannot stand in for it.
        with patch.object(md,'_fetch_candles',side_effect=provider(NOW)):
            self.assertIsNone(cc.forming_candle(NOW-timedelta(hours=3),NOW))
        # A full bar returned after the supplied clock time is never accepted as a partial bar.
        fetch=provider(NOW)
        def fully_closed(end,count=350):
            raw=fetch(end,count)
            raw['candles'][-1]['complete']=True
            return raw
        with patch.object(md,'_fetch_candles',side_effect=fully_closed):
            self.assertIsNone(cc.forming_candle(NOW,NOW))

    def test_weekend_does_not_invent_forming_prices(self):
        now=at('2026-11-07T12:00:00-05:00')
        with patch.object(md,'_fetch_candles',side_effect=provider(now)):
            self.assertIsNone(cc.forming_candle(now,now))

    def test_forming_changes_do_not_change_completed_strategy_results(self):
        import today
        fetch=provider(NOW)
        with patch.object(md,'_fetch_candles',side_effect=fetch):
            original=today.build_today_view(NOW)
            initial=cc.forming_candle(NOW,NOW)
        def changed(end,count=350):
            raw=fetch(end,count)
            for row in raw['candles']:
                if not row['complete']: row['mid'].update(c='1.5',h='1.6')
            return raw
        with patch.object(md,'_fetch_candles',side_effect=changed):
            later=today.build_today_view(NOW)
            partial=cc.forming_candle(NOW,NOW)
        self.assertEqual(original['market_data']['candles'],later['market_data']['candles'])
        self.assertEqual(original['rule_evaluation'],later['rule_evaluation'])
        self.assertNotEqual(initial['indicators'],partial['indicators'])
        self.assertNotIn('forming_candle',later['market_data'])

    def test_invalid_live_parameters_are_rejected_before_fetching(self):
        with patch.object(md,'_fetch_candles',side_effect=AssertionError('Invalid parameters must not fetch')):
            for after,forming in ((AFTER,NOW),(None,BEFORE-timedelta(minutes=1)),(None,NOW+timedelta(minutes=1))):
                with self.assertRaises(md.MarketDataError): cc.build_context(BEFORE,after,NOW,forming_at=forming)

    def test_invalid_forming_prices_and_missing_warmup_fail_explicitly(self):
        fetch=provider(NOW)
        malformed=fetch(NOW); malformed['candles'][-1]['mid']['c']='NaN'
        short=fetch(NOW,count=25)
        for raw in (malformed,short):
            with patch.object(md,'_fetch_candles',return_value=raw):
                with self.assertRaises(md.MarketDataError): cc.forming_candle(NOW,NOW)
