"""Chart context must preserve scored evidence and use only preceding candles."""
import copy
import unittest
from datetime import date
from unittest.mock import patch

import market_data as md
from indicators import ema, sma, rsi, sma_nullable
from strategy_rules import evaluate_strategy
from tests.test_custom_range import range_payload, range_snapshot, RangeClock
from tests.test_today import view_at


class ChartHistoryTests(unittest.TestCase):
    def test_history_uses_the_existing_indicator_pass_without_changing_scores(self):
        day = date(2026, 10, 23)
        raw = range_payload()
        with patch.object(md, "_fetch_candles", return_value=raw), patch.object(md, "datetime", RangeClock):
            snapshot = md.get_market_data(day)
        history = snapshot["chart_context"]["candles"]
        self.assertEqual(len(history), 60)
        self.assertEqual(history[-2:], snapshot["previous_candles"])
        self.assertEqual(history[-1], snapshot["previous_candle"])
        self.assertTrue(all(row["close_time"] <= snapshot["session"]["start_utc"] for row in history))
        self.assertEqual(len(snapshot["candles"]), 6)
        plain = copy.deepcopy(snapshot)
        plain.pop("chart_context")
        self.assertEqual(evaluate_strategy(snapshot), evaluate_strategy(plain))

        start, end = md.session_bounds(day)
        parsed = md._parse_candles(raw, end)
        warmup = [c for c in parsed if c.close_time <= start][-300:]
        selected = [c for c in parsed if c.open_time >= start]
        closes = [c.close for c in warmup + selected]
        expected = {"ema20": ema(closes, 20), "sma190": sma(closes, 190),
                    "rsi14": rsi(closes, 14), "rsi14_sma14": sma_nullable(rsi(closes, 14), 14)}
        for index, row in enumerate(history + snapshot["candles"], 240):
            for key, values in expected.items():
                self.assertEqual(row["indicators"][key], values[index])

    def test_daily_range_and_today_retain_the_same_history(self):
        ranged = range_snapshot(date(2026, 10, 23), date(2026, 10, 23))
        partial = view_at()["market_data"]
        self.assertEqual(partial["chart_context"], ranged["chart_context"])
        self.assertEqual(partial["candles"], ranged["candles"][:3])
        self.assertTrue(all(row["close_time"] <= partial["data_through"]
                            for row in partial["chart_context"]["candles"] + partial["candles"]))

    def test_history_remains_chronological_across_dst_and_weekends(self):
        snapshot = range_snapshot(date(2026, 11, 2), date(2026, 11, 3))
        history = snapshot["chart_context"]["candles"]
        self.assertEqual(history[-1]["close_time_local"], "2026-10-30T17:00:00-04:00")
        self.assertEqual(snapshot["candles"][0]["open_time_local"], "2026-11-01T17:00:00-05:00")
        times = [row["open_time"] for row in history + snapshot["candles"]]
        self.assertEqual(times, sorted(set(times)))
