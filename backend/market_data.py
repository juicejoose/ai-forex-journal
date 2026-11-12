"""Completed EUR/USD H4 sessions for the journal. main.py loads the .env file."""

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from indicators import ema, rsi, sma, sma_nullable, squeeze_momentum


NY = ZoneInfo("America/New_York")
UTC = timezone.utc
CANDLE_DURATION = timedelta(hours=4)
WARMUP_COUNT = 300
CHART_HISTORY_COUNT = 60
EMA_PERIOD = 20
SMA_PERIOD = 190
RSI_PERIOD = 14
RSI_MA_PERIOD = 14
BB_PERIOD = 20
BB_MULTIPLIER = 2.0
KC_PERIOD = 20
KC_MULTIPLIER = 1.5
USE_TRUE_RANGE = True


class MarketDataError(Exception):
    """A safe public error message, without credentials or upstream bodies."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    price_updates: int

    @property
    def close_time(self) -> datetime:
        return self.open_time + CANDLE_DURATION


def session_bounds(journal_date: date) -> tuple[datetime, datetime]:
    """Return UTC bounds; create both 5 p.m. boundaries in New York first."""
    if journal_date == date.min:
        raise MarketDataError("Choose a later journal date.", 422)
    previous_date = journal_date - timedelta(days=1)
    start = datetime.combine(previous_date, time(17), tzinfo=NY)
    end = datetime.combine(journal_date, time(17), tzinfo=NY)
    return start.astimezone(UTC), end.astimezone(UTC)


def _fetch_candles(end: datetime, count: int = WARMUP_COUNT + 50) -> dict:
    token = os.getenv("OANDA_API_TOKEN", "").strip()
    account_id = os.getenv("OANDA_ACCOUNT_ID", "").strip()
    base_url = os.getenv("OANDA_API_URL", "").strip().rstrip("/")
    if not token or not account_id:
        raise MarketDataError("OANDA credentials are missing from the backend configuration.", 503)
    if base_url != "https://api-fxpractice.oanda.com":
        raise MarketDataError("OANDA_API_URL must use the OANDA practice server.", 503)

    params = urlencode({
        "granularity": "H4",
        "price": "M",
        "count": count,
        "to": end.isoformat(),
        "dailyAlignment": 17,
        "alignmentTimezone": "America/New_York",
        "smooth": "false",
    })
    url = (
        f"{base_url}/v3/accounts/{quote(account_id, safe='')}"
        f"/instruments/EUR_USD/candles?{params}"
    )
    request = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Accept-Datetime-Format": "RFC3339",
    })
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
    except HTTPError as exc:
        if exc.code in (401, 403):
            message = "OANDA rejected access. Check the practice credentials and account access."
        elif exc.code == 429:
            message = "OANDA's request limit was reached. Please try again shortly."
        else:
            message = f"OANDA could not provide candles (HTTP {exc.code})."
        raise MarketDataError(message, 503 if exc.code == 429 or exc.code >= 500 else 502) from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Could not reach OANDA. Please try again shortly.", 503) from None
    except (ValueError, UnicodeDecodeError):
        raise MarketDataError("OANDA returned an unreadable response.") from None
    return data


def _parse_candles(data: dict, cutoff: datetime) -> list[Candle]:
    """Use only completed, well-formed candles that finish by the cutoff."""
    try:
        if (not isinstance(data, dict) or data.get("instrument") != "EUR_USD"
                or data.get("granularity") != "H4" or not isinstance(data.get("candles"), list)):
            raise ValueError("Unexpected response schema")
        candles = []
        for item in data["candles"]:
            if type(item["complete"]) is not bool:
                raise ValueError("Invalid completion flag")
            if not item["complete"]:
                continue
            opened_at = datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
            if opened_at.tzinfo is None:
                raise ValueError("Missing timestamp timezone")
            opened_at = opened_at.astimezone(UTC)
            if opened_at + CANDLE_DURATION > cutoff:
                continue
            local = opened_at.astimezone(NY)
            if (local.hour not in (1, 5, 9, 13, 17, 21)
                    or local.minute or local.second or local.microsecond):
                raise ValueError("Misaligned H4 candle")

            prices = [float(item["mid"][key]) for key in ("o", "h", "l", "c")]
            opened, high, low, closed = prices
            if (any(not isfinite(value) or value <= 0 for value in prices)
                    or not low <= opened <= high or not low <= closed <= high):
                raise ValueError("Invalid OHLC prices")
            volume = item["volume"]
            if type(volume) is not int or volume < 0:
                raise ValueError("Invalid price-update count")
            candles.append(Candle(opened_at, opened, high, low, closed, volume))

        candles.sort(key=lambda candle: candle.open_time)
        if len({candle.open_time for candle in candles}) != len(candles):
            raise ValueError("Duplicate timestamps")
        return candles
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise MarketDataError("OANDA returned malformed, duplicate, or misaligned candle data.") from None


def get_market_data(journal_date: date) -> dict:
    """Fetch history and calculate indicators; return the requested session only."""
    start, end = session_bounds(journal_date)
    if end > datetime.now(UTC):
        raise MarketDataError(
            "This session has not finished. Choose a date whose 5 p.m. New York cutoff has passed.", 422
        )
    if journal_date.weekday() in (5, 6):
        raise MarketDataError(
            "This weekend date has no full EUR/USD session ending at 5 p.m. New York time. Choose a weekday.", 422
        )

    raw = _fetch_candles(end)
    retrieved_at = datetime.now(UTC)
    candles = _parse_candles(raw, end)
    session = [candle for candle in candles if start <= candle.open_time < end]
    expected = [start + index * CANDLE_DURATION for index in range(6)]
    if not session:
        raise MarketDataError("No completed candles are available for this session. Choose another date.", 422)
    if [candle.open_time for candle in session] != expected:
        raise MarketDataError(
            "This session does not have all six completed H4 candles. Data may be missing or trading may have closed early.", 422
        )
    warmup = [candle for candle in candles if candle.close_time <= start][-WARMUP_COUNT:]
    if len(warmup) < WARMUP_COUNT:
        raise MarketDataError("Not enough earlier candles are available to initialize the indicators.", 422)

    return _build_snapshot(journal_date, start, end, session, warmup, retrieved_at)


def _build_snapshot(journal_date, start, end, session, warmup, retrieved_at):
    """Calculate indicators once over the complete history and requested candles."""
    series = warmup + session
    closes = [candle.close for candle in series]
    highs = [candle.high for candle in series]
    lows = [candle.low for candle in series]
    ema_values = ema(closes, EMA_PERIOD)
    sma_values = sma(closes, SMA_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)
    rsi_ma_values = sma_nullable(rsi_values, RSI_MA_PERIOD)
    squeeze = squeeze_momentum(
        highs, lows, closes, bb_period=BB_PERIOD, bb_multiplier=BB_MULTIPLIER,
        kc_period=KC_PERIOD, kc_multiplier=KC_MULTIPLIER, use_true_range=USE_TRUE_RANGE,
    )

    rows = []
    # Save a bounded part of the existing warmup for chart context. Calculate it
    # in the same pass so displayed indicators agree with the analyzed candles.
    history_count = min(CHART_HISTORY_COUNT, len(warmup))
    for index in range(len(warmup) - history_count, len(series)):
        candle = series[index]
        squeeze_values = {key: values[index] for key, values in squeeze.items()}
        if (ema_values[index] is None or sma_values[index] is None
                or any(value is None for value in squeeze_values.values())):
            raise MarketDataError("Indicator calculations did not have enough valid history.")
        rows.append({
            "open_time": candle.open_time.isoformat(),
            "close_time": candle.close_time.isoformat(),
            "open_time_local": candle.open_time.astimezone(NY).isoformat(),
            "close_time_local": candle.close_time.astimezone(NY).isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            # OANDA volume counts price updates, not global traded volume.
            "price_updates": candle.price_updates,
            "indicators": {
                "ema20": ema_values[index],
                "sma190": sma_values[index],
                "rsi14": rsi_values[index],
                "rsi14_sma14": rsi_ma_values[index],
                "rsi_status": "ready" if rsi_values[index] is not None else "undefined_no_price_changes",
                "squeeze": squeeze_values,
            },
        })

    change = session[-1].close - session[0].open
    return {
        "schema_version": 4,
        "source": "OANDA",
        "environment": "practice",
        "instrument": "EUR_USD",
        "timeframe": "H4",
        "price_basis": "midpoint",
        "smoothed_candles": False,
        "journal_date": journal_date.isoformat(),
        "retrieved_at": retrieved_at.isoformat(),
        "session": {
            "timezone": "America/New_York",
            "start": start.astimezone(NY).isoformat(),
            "end": end.astimezone(NY).isoformat(),
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "complete": True,
            "candle_count": len(session),
        },
        "warmup": {
            "candle_count": len(warmup),
            "first_open_time": warmup[0].open_time.isoformat(),
            "last_close_time": warmup[-1].close_time.isoformat(),
        },
        "indicator_settings": {
            "source": "close",
            "ema": {"period": EMA_PERIOD, "seed": "sma"},
            "sma": {"period": SMA_PERIOD},
            "rsi": {"period": RSI_PERIOD, "smoothing": "wilder", "flat_value": None},
            "rsi_ma": {"source": "rsi14", "type": "sma", "period": RSI_MA_PERIOD},
            "squeeze": {
                "formula": "LazyBear corrected 2014-09-29",
                "bb_period": BB_PERIOD, "bb_multiplier": BB_MULTIPLIER,
                "kc_period": KC_PERIOD, "kc_multiplier": KC_MULTIPLIER,
                "use_true_range": USE_TRUE_RANGE,
            },
        },
        "summary": {
            "open": session[0].open,
            "high": max(candle.high for candle in session),
            "low": min(candle.low for candle in session),
            "close": session[-1].close,
            "change": change,
            "change_pips": change / 0.0001,
            "change_percent": 100 * change / session[0].open,
            "price_direction": "up" if change > 0 else "down" if change < 0 else "unchanged",
        },
        "chart_context": {"purpose": "display_only", "candles": rows[:history_count]},
        "previous_candle": rows[history_count - 1],
        "previous_candles": rows[history_count - 2:history_count],  # P-1 then P0.
        "candles": rows[history_count:],
    }
