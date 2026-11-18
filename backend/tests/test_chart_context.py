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
