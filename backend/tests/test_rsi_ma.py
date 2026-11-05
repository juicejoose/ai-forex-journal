"""RSI smoothing math and continuous provider-data wiring (offline)."""
import unittest
from datetime import date
from math import fsum
from unittest.mock import patch
from indicators import rsi, sma_nullable
from tests.test_custom_range import range_payload, RangeClock
from tests.test_today import view_at
import market_data as md
import date_range as dr


class RsiMaTests(unittest.TestCase):
    def test_sma_averages_rsi_values_with_full_precision_and_alignment(self):
        values = [None] * 14 + [30 + i / 7 for i in range(22)]
        actual = sma_nullable(values, 14)
        self.assertEqual(actual[:27], [None] * 27)
        self.assertEqual(len(actual), len(values))
        for i in range(27, len(values)):
            self.assertEqual(actual[i], fsum(values[i-13:i+1]) / 14)
        self.assertNotEqual(actual[-1], round(actual[-1], 2))

    def test_rsi14_ma_first_valid_value_needs_28_closes(self):
        actual = sma_nullable(rsi(list(range(1, 36)), 14), 14)
        self.assertEqual(actual[:27], [None] * 27)
        self.assertEqual(actual[27:], [100] * 8)
        self.assertEqual(sma_nullable(rsi([2] * 50), 14), [None] * 50)

    def test_missing_readings_require_a_new_complete_window(self):
        self.assertEqual(sma_nullable([1, 2, 3, None, 4, 5, 6], 3),
                         [None, None, 2, None, None, None, 5])
        for invalid in (float('nan'), float('inf'), True, '50'):
            with self.assertRaises(ValueError):
                sma_nullable([invalid], 1)
        for period in (0, -1, True, 1.5):
            with self.assertRaises(ValueError): sma_nullable([50], period)

    def test_future_values_never_change_existing_ma(self):
        prices = [1 + (i % 7) / 100 for i in range(50)]
        short = sma_nullable(rsi(prices), 14)
        self.assertEqual(sma_nullable(rsi(prices + [9, 0.2, 10]), 14)[:50], short)

    def test_market_snapshot_matches_independent_warmup_calculation(self):
        data = range_payload()
        label = date(2026, 10, 23)
        start, end = md.session_bounds(label)
        from datetime import datetime
        rows = [row for row in data['candles'] if datetime.fromisoformat(row['time']) < end][-306:]
        expected_raw = rsi([float(row['mid']['c']) for row in rows], 14)
        with patch.object(md, '_fetch_candles', return_value=data), patch.object(md, 'datetime', RangeClock):
            snapshot = md.get_market_data(label)
        self.assertEqual(snapshot['indicator_settings']['rsi_ma'], {'source':'rsi14','type':'sma','period':14})
        for index, candle in enumerate([*snapshot['previous_candles'], *snapshot['candles']], 298):
            self.assertEqual(candle['indicators']['rsi14'], expected_raw[index])
            self.assertEqual(candle['indicators']['rsi14_sma14'], fsum(expected_raw[index-13:index+1]) / 14)
        self.assertEqual(snapshot['candles'][0]['open_time'], start.isoformat())

    def test_today_and_range_share_completed_candle_smoothing(self):
        view = view_at()
        with patch.object(md, '_fetch_candles', return_value=range_payload()), patch.object(dr, 'datetime', RangeClock):
            full = dr.get_range_market_data(date(2026,10,23), date(2026,10,23))
        self.assertEqual(view['market_data']['candles'], full['candles'][:3])
        self.assertEqual(view['rule_evaluation']['candles'], dr.evaluate_range_strategy(full)['candles'][:3])
        self.assertEqual(view['rule_evaluation']['summary']['complete_candles'], 3)
