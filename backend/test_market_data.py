"""Offline market-data regression tests using simulated OANDA responses.

Run all tests from backend: python -m unittest discover -v
Uses dummy credentials; no live provider requests or saved journal data.
"""

import copy
import io
import json
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

ENVIRONMENT = {
    "OPENAI_API_KEY": "dummy-openai-token",
    "OANDA_API_TOKEN": "dummy-oanda-token",
    "OANDA_ACCOUNT_ID": "dummy-account",
    "OANDA_API_URL": "https://api-fxpractice.oanda.com",
}

with patch.dict(os.environ, ENVIRONMENT, clear=True), patch("dotenv.load_dotenv"):
    import main
import market_data as md


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 22, 12, tzinfo=timezone.utc).astimezone(tz)


def payload(journal_date=date(2026, 10, 20)):
    candles = []
    for days_before in range(120, -1, -1):
        label = journal_date - timedelta(days=days_before)
        if label.weekday() in (5, 6):
            continue
        start, _ = md.session_bounds(label)
        for index in range(6):
            stamp = start + index * timedelta(hours=4)
            close = [1.2, 1.205, 1.201, 1.203, 1.202, 1.21][index] if days_before == 0 else 1.2
            candles.append({
                "time": stamp.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                "complete": True,
                "volume": 100 + index,
                "mid": {"o": "1.2", "h": str(max(1.2, close) + 0.002),
                        "l": str(min(1.2, close) - 0.002), "c": str(close)},
            })
    return {"instrument": "EUR_USD", "granularity": "H4", "candles": candles[-350:]}


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENVIRONMENT, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.clock = patch.object(md, "datetime", FixedDateTime)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        # No lifespan context: database initialization is not needed for these GET requests.
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def request(self, data=None, day="2026-10-20"):
        with patch.object(md, "_fetch_candles", return_value=payload() if data is None else data):
            return self.client.get("/market-data", params={"journal_date": day})

    def test_successful_session_and_summary(self):
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["session"]["start"], "2026-10-19T17:00:00-04:00")
        self.assertEqual(data["session"]["end"], "2026-10-20T17:00:00-04:00")
        self.assertEqual(data["session"]["candle_count"], 6)
        self.assertEqual(data["warmup"]["candle_count"], 300)
        self.assertEqual(len(data["candles"]), 6)
        self.assertEqual(data["indicator_settings"]["sma"]["period"], 190)
        self.assertEqual(data["candles"][0]["close_time_local"], "2026-10-19T21:00:00-04:00")
        self.assertEqual(data["candles"][-1]["close_time_local"], "2026-10-20T17:00:00-04:00")
        self.assertAlmostEqual(data["summary"]["change_pips"], 100)
        self.assertAlmostEqual(data["summary"]["change_percent"], 100 * 0.01 / 1.2)
        self.assertAlmostEqual(data["summary"]["high"], 1.212)
        self.assertAlmostEqual(data["summary"]["low"], 1.198)
        self.assertEqual(data["summary"]["price_direction"], "up")
        self.assertIsNone(data["candles"][0]["indicators"]["rsi14"])
        self.assertEqual(data["candles"][0]["indicators"]["rsi_status"], "undefined_no_price_changes")
        self.assertNotIn("MACD", response.text.upper())
        self.assertNotIn("dummy", response.text)
        json.dumps(data, allow_nan=False)

    def test_query_validation(self):
        with patch.object(md, "_fetch_candles") as fetch:
            for params in ({}, {"journal_date": "not-a-date"}, {"journal_date": "2026-02-30"}):
                self.assertEqual(self.client.get("/market-data", params=params).status_code, 422)
            fetch.assert_not_called()

    def test_unfinished_and_weekend_sessions(self):
        with patch.object(md, "_fetch_candles") as fetch:
            for day in ("2026-10-22", "2026-10-23", "2026-10-17", "2026-10-18", "0001-01-01"):
                response = self.client.get("/market-data", params={"journal_date": day})
                self.assertEqual(response.status_code, 422, response.text)
            fetch.assert_not_called()

    def test_dst_boundaries(self):
        for day, hour in ((date(2026, 3, 6), 22), (date(2026, 3, 9), 21),
                          (date(2026, 10, 30), 21), (date(2026, 11, 2), 22)):
            start, end = md.session_bounds(day)
            self.assertEqual(start.hour, hour)
            self.assertEqual(end.hour, hour)
            self.assertEqual(end-start, timedelta(hours=24))
            self.assertEqual(start.astimezone(md.NY).hour, 17)
            self.assertEqual(end.astimezone(md.NY).hour, 17)

    def test_session_after_spring_clock_change(self):
        response = self.request(payload(date(2026, 3, 9)), "2026-03-09")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["session"]["end_utc"], "2026-03-09T21:00:00+00:00")

    def test_missing_or_unfinished_session_candles(self):
        missing = payload()
        missing["candles"].pop(-3)
        incomplete = payload()
        incomplete["candles"][-1]["complete"] = False
        for data in (missing, incomplete):
            response = self.request(data)
            self.assertEqual(response.status_code, 422)
            self.assertIn("six completed", response.json()["detail"])

    def test_no_session_or_insufficient_history(self):
        no_session = payload()
        no_session["candles"] = no_session["candles"][:-6]
        short_history = payload()
        short_history["candles"] = short_history["candles"][-305:]
        for data in (no_session, short_history):
            self.assertEqual(self.request(data).status_code, 422)

    def test_bad_upstream_data(self):
        variants = []
        duplicate = payload()
        duplicate["candles"].append(copy.deepcopy(duplicate["candles"][-1]))
        variants.append(duplicate)
        for key, value in (("h", "0"), ("c", "NaN"), ("o", "999")):
            malformed = payload()
            malformed["candles"][-1]["mid"][key] = value
            variants.append(malformed)
        malformed = payload()
        malformed["candles"][-1]["complete"] = "true"
        variants.append(malformed)
        malformed = payload()
        malformed["candles"][-1]["time"] = "2026-10-20T14:00:00+00:00"
        variants.append(malformed)
        malformed = payload()
        malformed["candles"][-1]["time"] = "2026-10-20T17:00:00"
        variants.append(malformed)
        for malformed in variants + [{}, [], None]:
            with patch.object(md, "_fetch_candles", return_value=malformed):
                response = self.client.get("/market-data?journal_date=2026-10-20")
                self.assertEqual(response.status_code, 502, response.text)

    def test_cutoff_and_chronological_order(self):
        baseline = self.request().json()
        data = payload()
        future = copy.deepcopy(data["candles"][-1])
        future["time"] = "2026-10-20T21:00:00Z"
        future["mid"]["c"] = "500"
        data["candles"].append(future)
        data["candles"].reverse()
        result = self.request(data)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), baseline)

    def test_no_future_influence(self):
        baseline = self.request().json()
        data = payload()
        data["candles"][-1]["mid"]["c"] = "1.5"
        data["candles"][-1]["mid"]["h"] = "1.6"
        changed = self.request(data).json()
        self.assertEqual(changed["candles"][:-1], baseline["candles"][:-1])
        self.assertNotEqual(changed["candles"][-1], baseline["candles"][-1])

    def test_request_parameters(self):
        response_body = io.BytesIO(json.dumps(payload()).encode())
        with patch.object(md, "urlopen", return_value=response_body) as fetch:
            response = self.client.get("/market-data?journal_date=2026-10-20")
        self.assertEqual(response.status_code, 200, response.text)
        request = fetch.call_args.args[0]
        params = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(params["count"], ["350"])
        self.assertEqual(params["granularity"], ["H4"])
        self.assertEqual(params["to"], ["2026-10-20T21:00:00+00:00"])
        self.assertEqual(params["dailyAlignment"], ["17"])
        self.assertEqual(params["alignmentTimezone"], ["America/New_York"])
        self.assertNotIn("from", params)
        self.assertEqual(request.get_method(), "GET")

    def test_upstream_errors_are_safe(self):
        for code, expected_status in ((401,502),(403,502),(404,502),(429,503),(500,503)):
            failure = HTTPError("https://example.invalid/dummy-account", code, "dummy-secret", {}, None)
            with patch.object(md, "urlopen", side_effect=failure):
                response = self.client.get("/market-data?journal_date=2026-10-20")
            self.assertEqual(response.status_code, expected_status)
            self.assertNotIn("dummy", response.text)
        with patch.object(md, "urlopen", side_effect=URLError("dummy-secret")):
            response = self.client.get("/market-data?journal_date=2026-10-20")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("dummy", response.text)
        with patch.object(md, "urlopen", return_value=io.BytesIO(b"not json")):
            self.assertEqual(self.client.get("/market-data?journal_date=2026-10-20").status_code, 502)

    def test_bad_config_never_sends_credentials(self):
        for change in ({"OANDA_API_TOKEN":""}, {"OANDA_API_URL":"https://example.invalid"}):
            with patch.dict(os.environ, change), patch.object(md, "urlopen") as fetch:
                response = self.client.get("/market-data?journal_date=2026-10-20")
                self.assertEqual(response.status_code, 503)
                fetch.assert_not_called()

    def test_existing_home_and_preview(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        entry = {"pair":"EUR/USD", "journal_date":"2026-10-20", "timeframe":"4h",
                 "strategy":"Example rule", "notes":"Example notes"}
        response = self.client.post("/journal/preview", json=entry)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), entry)


if __name__ == "__main__":
    unittest.main()
