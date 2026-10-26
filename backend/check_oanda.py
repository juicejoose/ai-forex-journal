import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from indicators import ema, rsi, sma, squeeze_momentum


def main():
    load_dotenv(Path(__file__).with_name(".env"))

    token = os.getenv("OANDA_API_TOKEN", "").strip()
    account_id = os.getenv("OANDA_ACCOUNT_ID", "").strip()
    base_url = os.getenv("OANDA_API_URL", "").strip().rstrip("/")

    if not token or not account_id:
        raise SystemExit("Missing OANDA_API_TOKEN or OANDA_ACCOUNT_ID in .env.")
    if base_url != "https://api-fxpractice.oanda.com":
        raise SystemExit("Set OANDA_API_URL to https://api-fxpractice.oanda.com.")

    ny = ZoneInfo("America/New_York")
    journal_date = date(2026, 10, 20)
    warmup_count = 300
    ema_period = 20
    sma_period = 190
    rsi_period = 14
    bb_period = 20
    bb_multiplier = 2.0
    kc_period = 20
    kc_multiplier = 1.5
    use_true_range = True
    session_start = datetime.combine(
        journal_date - timedelta(days=1), time(17), tzinfo=ny
    )
    session_end = datetime.combine(journal_date, time(17), tzinfo=ny)
    start_utc = session_start.astimezone(timezone.utc)
    end_utc = session_end.astimezone(timezone.utc)

    if end_utc > datetime.now(timezone.utc):
        raise SystemExit("This session has not finished yet.")

    params = urlencode({
        "granularity": "H4",
        "price": "M",
        # Fetch extra history, then select the warmup and session separately.
        "count": warmup_count + 50,
        "to": end_utc.isoformat(),
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
            status = response.status
            data = json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"OANDA request failed: HTTP {exc.code}.") from None
    except (URLError, TimeoutError):
        raise SystemExit("Network, timeout, or certificate error reaching OANDA.") from None

    if data.get("instrument") != "EUR_USD" or data.get("granularity") != "H4":
        raise SystemExit("OANDA returned an unexpected instrument or timeframe.")

    candles = []
    for candle in data["candles"]:
        opened_at = datetime.fromisoformat(candle["time"].replace("Z", "+00:00"))
        closed_at = opened_at + timedelta(hours=4)
        if candle["complete"] and closed_at <= end_utc:
            candles.append((opened_at, candle["mid"]))

    candles.sort(key=lambda item: item[0])
    if len({opened_at for opened_at, _ in candles}) != len(candles):
        raise SystemExit("OANDA returned duplicate candle timestamps.")

    # These earlier candles initialize indicators; they are not today's session.
    warmup_candles = [
        candle for candle in candles
        if candle[0] + timedelta(hours=4) <= start_utc
    ][-warmup_count:]
    session_candles = [
        candle for candle in candles if start_utc <= candle[0] < end_utc
    ]

    print("HTTP status:", status)
    print("Instrument: EUR_USD | Timeframe: H4")
    print("Session start:", session_start.isoformat())
    print("Session end:  ", session_end.isoformat())
    print("Warmup candles:", len(warmup_candles))
    print("Completed session candles:", len(session_candles))

    if len(warmup_candles) < warmup_count:
        raise SystemExit("Not enough earlier candles to initialize indicators.")

    # This fixed weekday test should contain six consecutive H4 candles.
    expected = [start_utc + timedelta(hours=4 * i) for i in range(6)]
    if [opened_at for opened_at, _ in session_candles] != expected:
        raise SystemExit("Session data is missing, incomplete, or misaligned.")

    # Compute over the full history, then display only the session's results.
    calculation_candles = warmup_candles + session_candles
    print("Total candles for calculations:", len(calculation_candles))
    print("First warmup candle:", warmup_candles[0][0].astimezone(ny).isoformat())
    last_warmup_close = warmup_candles[-1][0] + timedelta(hours=4)
    print("Last warmup candle closes:", last_warmup_close.astimezone(ny).isoformat())

    closes = [float(prices["c"]) for _, prices in calculation_candles]
    highs = [float(prices["h"]) for _, prices in calculation_candles]
    lows = [float(prices["l"]) for _, prices in calculation_candles]
    ema_values = ema(closes, ema_period)
    sma_values = sma(closes, sma_period)
    rsi_values = rsi(closes, rsi_period)
    squeeze = squeeze_momentum(
        highs, lows, closes,
        bb_period=bb_period, bb_multiplier=bb_multiplier,
        kc_period=kc_period, kc_multiplier=kc_multiplier,
        use_true_range=use_true_range,
    )

    print(
        f"Indicators: EMA({ema_period}), SMA({sma_period}), RSI({rsi_period}), Squeeze "
        "| Source: midpoint close"
    )
    print("EMA initialization: SMA of the first period of closes")
    print("RSI smoothing: Wilder (alpha=1/period); undefined flat RSI displays N/A")
    print(
        f"LazyBear corrected formula: BB({bb_period}, {bb_multiplier}), "
        f"KC({kc_period}, {kc_multiplier}), True Range={use_true_range}"
    )
    print("Squeeze ON=BB inside KC; OFF=BB outside KC; NEUTRAL=neither")
    print("Release=YES only on an ON-to-OFF transition")
    print("Session values below are available at each candle's CLOSE time:")

    for index in range(len(warmup_candles), len(calculation_candles)):
        opened_at, prices = calculation_candles[index]
        closed_at = opened_at + timedelta(hours=4)
        opened_label = opened_at.astimezone(ny).strftime("%Y-%m-%d %H:%M %Z")
        closed_label = closed_at.astimezone(ny).strftime("%Y-%m-%d %H:%M %Z")
        ema_value = ema_values[index]
        sma_value = sma_values[index]
        rsi_value = rsi_values[index]
        momentum = squeeze["momentum"][index]
        squeeze_state = squeeze["state"][index]
        histogram_color = squeeze["histogram_color"][index]
        released = squeeze["released"][index]
        if (ema_value is None or sma_value is None or index < rsi_period
                or momentum is None or squeeze_state is None or histogram_color is None):
            raise SystemExit("An indicator is not ready for a session candle.")

        rsi_text = "N/A" if rsi_value is None else f"{rsi_value:.2f}"
        release_text = "N/A" if released is None else ("YES" if released else "NO")
        print(
            f"OPEN {opened_label} -> CLOSE {closed_label} | "
            f"O={prices['o']} H={prices['h']} L={prices['l']} C={prices['c']} | "
            f"EMA{ema_period}={ema_value:.6f} SMA{sma_period}={sma_value:.6f} | "
            f"RSI{rsi_period}={rsi_text} | Squeeze={squeeze_state} "
            f"Momentum={momentum:.6f} Color={histogram_color} Release={release_text}"
        )


if __name__ == "__main__":
    main()
