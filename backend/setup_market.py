"""Freeze only evidence available at an explicit cutoff; never change scoring."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import market_data as md
from strategy_rules import evaluate_strategy
import today
from zone_history import analyze_zone_history, VERSION as ZONE_HISTORY_VERSION
from zone_patterns import analyze_zone_patterns, VERSION as ZONE_PATTERN_VERSION
from trade_plan import calculate_trade_plan


def fetch_quote():
    """Read-only practice pricing. No trading endpoints are used."""
    base = os.getenv("OANDA_API_URL", "").rstrip("/")
    token, account = os.getenv("OANDA_API_TOKEN", ""), os.getenv("OANDA_ACCOUNT_ID", "")
    if base != "https://api-fxpractice.oanda.com" or not token or not account:
        raise md.MarketDataError("Practice pricing is not configured.", 503)
    request = Request(f"{base}/v3/accounts/{quote(account, safe='')}/pricing?instruments=EUR_USD",
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, OSError, ValueError):
        raise md.MarketDataError("A fresh practice quote could not be retrieved.", 503) from None


def validated_quote(raw, cutoff):
    try:
        items = [p for p in raw["prices"] if p["instrument"] == "EUR_USD"]
        if len(items) != 1 or items[0]["status"] != "tradeable":
            raise ValueError()
        price = items[0]
        timestamp = datetime.fromisoformat(price["time"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or not 0 <= (cutoff - timestamp).total_seconds() <= 120:
            raise ValueError()
        bid, ask = float(price["bids"][0]["price"]), float(price["asks"][0]["price"])
        if not all(isfinite(n) and n > 0 for n in (bid, ask)) or bid > ask:
            raise ValueError()
        return {"status": "available", "source": "OANDA practice", "time": timestamp.isoformat(),
                "bid": bid, "ask": ask, "midpoint": (bid + ask) / 2}
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, AttributeError):
        return {"status": "unavailable", "reason": "The quote is stale, not tradeable, malformed, or after the cutoff."}


def _version_hash():
    root = Path(__file__).parent
    names = ("indicators.py", "market_data.py", "strategy_rules.py", "today.py", "setup_market.py", "zone_history.py", "zone_patterns.py", "trade_plan.py")
    return hashlib.sha256(b"".join((root / name).read_bytes() for name in names)).hexdigest()


def _relation(value, lower, upper):
    return "below" if value < lower else "above" if value > upper else "inside"


def zone_evidence(zones, reference, last_candle):
    results = []
    for index, zone in enumerate(zones, 1):
        low, high = zone.lower, zone.upper
        price = Decimal(str(reference["value"]))
        distance = low - price if price < low else price - high if price > high else Decimal(0)
        close = Decimal(str(last_candle["close"]))
        results.append({"id": f"Z{index}", **zone.model_dump(mode="json"),
            "source": "user_entered", "price_position": _relation(price, low, high),
            "distance_pips": float(distance / Decimal("0.0001")),
            "last_close_position": _relation(close, low, high),
            "last_candle_overlaps": Decimal(str(last_candle["low"])) <= high and Decimal(str(last_candle["high"])) >= low})
    return results


def build_setup_snapshot(entry):
    received = datetime.now(md.UTC)
    if entry.mode == "historical" and (entry.as_of > received or entry.as_of.year < 2000):
        raise md.MarketDataError("Choose a historical cutoff from 2000 through the present, including its timezone.", 422)
    raw_quote = None
    quote_error = None
    if entry.include_quote:
        try:
            raw_quote = fetch_quote()
        except md.MarketDataError as exc:
            quote_error = str(exc)
    cutoff = entry.as_of.astimezone(md.UTC) if entry.mode == "historical" else datetime.now(md.UTC)
    if any(zone.observed_at and zone.observed_at > cutoff for zone in entry.zones):
        raise md.MarketDataError("A zone's observation time cannot be after the evaluation cutoff.", 422)
    if any(zone.origin_at and zone.origin_at > cutoff for zone in entry.zones):
        raise md.MarketDataError("A zone's origin cannot be after the evaluation cutoff.", 422)
    quote_data = (validated_quote(raw_quote, cutoff) if raw_quote is not None else
                  {"status": "unavailable", "reason": quote_error} if quote_error else {"status": "not_requested"})
    view = today.build_today_view(cutoff, include_source=True)
    prior_session = view["market_data"] is None
    if prior_session:
        # Before this session's first close, show the previous completed session explicitly.
        previous_date = datetime.fromisoformat(view["session"]["start"]).astimezone(md.NY).date()
        while previous_date.weekday() >= 5:
            previous_date -= timedelta(days=1)
        market = md.get_market_data(previous_date, include_source=True)
        evaluation = evaluate_strategy(market)
    else:
        market, evaluation = view["market_data"], view["rule_evaluation"]
    source = market.pop("calculation_inputs")
    if any(datetime.fromisoformat(row["close_time"]) > cutoff for row in source):
        raise md.MarketDataError("The source history contains data after the cutoff.", 502)
    last = market["candles"][-1]
    reference = ({"basis": "quote_midpoint", "value": quote_data["midpoint"], "time": quote_data["time"]}
                 if quote_data["status"] == "available" else
                 {"basis": "last_completed_close", "value": last["close"], "time": last["close_time"]})
    zones = zone_evidence(entry.zones, reference, last)
    for zone in zones:
        zone["history"] = analyze_zone_history(zone, source, cutoff)
        zone["patterns"] = analyze_zone_patterns(zone, source, cutoff, zone["history"])
    snapshot = {"schema_version": 4, "mode": entry.mode, "cutoff_at": cutoff.isoformat(),
        "received_at": received.isoformat(), "captured_at": datetime.now(md.UTC).isoformat(),
        "data_through": last["close_time"], "calculation_version": _version_hash(),
        "price_action_version": ZONE_HISTORY_VERSION, "instrument": "EUR_USD", "timeframe": "H4",
        "zone_pattern_version": ZONE_PATTERN_VERSION,
        "entry": entry.model_dump(mode="json", exclude={"request_id"}),
        "observation_provenance": "retrospective_user_input" if entry.mode == "historical" else "user_input_at_capture",
        "prior_session_context": prior_session, "market_state": view["market_state"],
        "source_candles": source, "market_data": market, "rule_evaluation": evaluation,
        "quote": quote_data, "reference_price": reference,
        "zones": zones, "trade_plan": calculate_trade_plan(entry.trade_plan, entry.direction, zones)}
    return snapshot


def capture_preview(entry, preview):
    """Finalize user annotations against server-owned evidence; no provider requests."""
    selection = dict(preview["selection"])
    supplied = entry.model_dump(mode="json", include={"mode", "as_of", "include_quote"})
    # Compare aware datetimes rather than their equivalent timezone spellings.
    for values in (selection, supplied):
        if values.get("as_of"):
            values["as_of"] = datetime.fromisoformat(values["as_of"]).astimezone(md.UTC).isoformat()
    if selection != supplied:
        raise md.MarketDataError("The time settings differ from the chart preview. Reload the chart first.", 409)
    snapshot = deepcopy(preview["snapshot"])
    if snapshot["calculation_version"] != _version_hash():
        raise md.MarketDataError("The calculation code changed since this preview. Reload the chart first.", 409)
    cutoff = datetime.fromisoformat(snapshot["cutoff_at"])
    if any((zone.origin_at and zone.origin_at > cutoff) or
           (zone.observed_at and zone.observed_at > cutoff) for zone in entry.zones):
        raise md.MarketDataError("Zone times cannot be after the preview cutoff.", 422)
    zones = zone_evidence(entry.zones, snapshot["reference_price"], snapshot["market_data"]["candles"][-1])
    for zone in zones:
        zone["history"] = analyze_zone_history(zone, snapshot["source_candles"], cutoff)
        zone["patterns"] = analyze_zone_patterns(zone, snapshot["source_candles"], cutoff, zone["history"])
    snapshot.update(entry=entry.model_dump(mode="json", exclude={"request_id"}), zones=zones,
        trade_plan=calculate_trade_plan(entry.trade_plan, entry.direction, zones),
        finalized_at=datetime.now(md.UTC).isoformat(), preview_id=preview["id"],
        observation_provenance="retrospective_user_input" if entry.mode == "historical" else "user_input_after_preview")
    return snapshot
