"""Versioned candle/zone rules. No indicators, score changes, or future data."""
from copy import deepcopy
from decimal import Decimal

from market_data import CANDLE_DURATION
from zone_history import _source_rows, _stamp, _next_open, _position, _reference

VERSION = "zone_patterns_v1"
RETEST_WINDOW = 6
RULES = {
    "version": VERSION, "timeframe": "H4", "close_buffer_pips": 0,
    "breakout_closes": 1, "retest_window_candles": RETEST_WINDOW,
    "rejection": "Previous close outside the original zone; next candle overlaps and closes on that same side. Support is bullish, resistance bearish.",
    "breakout": "Resistance: previous close inside/below and current close above the upper edge. Support: previous close inside/above and current close below the lower edge.",
    "retest": "A later candle approaches from the breakout side, overlaps the zone, and closes back on the breakout side within six subsequent completed H4 candles.",
    "invalidation": "Before a held retest, a completed close beyond the opposite edge ends the retest attempt. An inside/edge close alone does not invalidate it.",
    "boundaries": "Edges count as contact, not as beyond. A held retest records an event at its close, not ongoing validity. No wick/body ratio or candle-colour requirement.",
}


def analyze_zone_patterns(zone, source, cutoff, history):
    result = {"version": VERSION, "rules": deepcopy(RULES), "status": history["status"],
        "origin_at": history["origin_at"], "coverage_start": history["coverage_start"],
        "coverage_end": history["coverage_end"], "cutoff_at": cutoff.isoformat(),
        "events": [], "breakouts": [], "counts": None}
    if history["status"] in ("not_requested", "no_completed_candles"):
        return result
    origin = _stamp(history["origin_at"])
    rows = [row for row in _source_rows(source, cutoff) if row["opened"] >= origin]
    if not any(_next_open(a["closed"]) == b["opened"] for a, b in zip(rows, rows[1:])):
        result["status"] = "insufficient_data"
        return result
    lower, upper = Decimal(zone["lower"]), Decimal(zone["upper"])
    side = "above" if zone["kind"] == "resistance" else "below"
    direction = "bullish" if side == "above" else "bearish"
    opposite = "below" if side == "above" else "above"
    pending = None

    def evidence(row):
        return {**_reference(row), **{name: float(row[name]) for name in ("open", "high", "low")}}

    def event(kind, trend, previous, row, breakout_id=None):
        item = {"id": f"{zone['id']}-P{len(result['events'])+1}", "kind": kind,
            "direction": trend, **_reference(row), "evidence": [evidence(previous), evidence(row)]}
        if breakout_id:
            item["breakout_id"] = breakout_id
        item["description"], item["reason"] = describe_event(item, zone)
        result["events"].append(item)
        return item

    for index, row in enumerate(rows):
        row["position"] = _position(row["close"], lower, upper)
        row["overlap"] = row["low"] <= upper and row["high"] >= lower
        if not index:
            continue  # Never infer the approach from outside the observation window.
        previous = rows[index-1]
        if _next_open(previous["closed"]) != row["opened"]:
            if pending:
                pending.update(status="insufficient_data", reason="data_gap")
                pending = None
            continue
        # Process an existing attempt before considering a new breakout. This
        # prevents the breakout candle itself from qualifying as a retest.
        attempt_was_open = pending is not None
        if pending:
            pending["observed_candles"] += 1
            pending["assessed_through"] = _reference(row)
            if row["overlap"] and pending["first_touch"] is None:
                pending["first_touch"] = _reference(row)
            if row["position"] == opposite:
                failed = event("retest_invalidated", direction, previous, row, pending["id"])
                pending.update(status="invalidated", reason="opposite_edge_close", result_event_id=failed["id"])
                pending = None
            elif previous["position"] == side and row["overlap"] and row["position"] == side:
                held = event("retest_held", direction, previous, row, pending["id"])
                pending.update(status="held", reason="touch_and_close_back", result_event_id=held["id"])
                pending = None
            elif pending["observed_candles"] == RETEST_WINDOW:
                pending.update(status="expired", reason="window_ended_without_hold")
                pending = None
        # Original support/resistance labels do not silently change roles.
        approach = "above" if zone["kind"] == "support" else "below"
        if previous["position"] == approach and row["overlap"] and row["position"] == approach:
            event("rejection", "bullish" if approach == "above" else "bearish", previous, row)
        if previous["position"] != side and row["position"] == side:
            # An inside close followed by a recovery during the same pending
            # attempt is not a fresh breakout and cannot reset the six-bar clock.
            if not attempt_was_open:
                broken = event("breakout", direction, previous, row)
                pending = {"id": broken["id"], "direction": direction, "breakout": _reference(row),
                    "status": "pending", "reason": "awaiting_retest", "observed_candles": 0,
                    "first_touch": None, "assessed_through": _reference(row), "result_event_id": None}
                result["breakouts"].append(pending)
    if pending and _next_open(rows[-1]["closed"]) + CANDLE_DURATION <= cutoff:
        pending.update(status="insufficient_data", reason="data_gap")
    result["counts"] = {kind: sum(item["kind"] == kind for item in result["events"])
        for kind in ("rejection", "breakout", "retest_held", "retest_invalidated")}
    return result


def describe_event(item, zone):
    kind, direction = item["kind"], item["direction"]
    low, high = zone["lower"], zone["upper"]
    close = f"{item['close']:.5f}"
    prefix = f"{direction.capitalize()} {kind.replace('_', ' ')} at {item['close_time']}"
    if kind == "rejection":
        position, edge = ("above", high) if direction == "bullish" else ("below", low)
        detail = f"Previous close was {position} the zone; this candle overlapped it and closed {position} {edge} at {close}."
    elif kind == "breakout":
        position, edge = ("above", high) if direction == "bullish" else ("below", low)
        detail = f"One H4 close crossed from inside/the other side to {position} {edge} at {close}. A wick alone does not meet this rule."
    elif kind == "retest_held":
        position, edge = ("above", high) if direction == "bullish" else ("below", low)
        detail = f"A later candle approached from {position}, overlapped the zone, and closed back {position} {edge} at {close} within the retest window."
    else:
        position, edge = ("below", low) if direction == "bullish" else ("above", high)
        detail = f"Before a held retest, a later candle closed {position} the opposite edge {edge} at {close}. This ends that retest attempt; it is not a trade outcome."
    return f"{prefix}. {detail}", detail


def pattern_summary(patterns):
    """Bound AI context while retaining full evidence and event history in storage."""
    return {**{key: value for key, value in patterns.items() if key not in ("events", "breakouts")},
        "recent_events": patterns["events"][-3:], "recent_breakouts": patterns["breakouts"][-3:],
        "omitted_events": max(0, len(patterns["events"])-3),
        "omitted_breakouts": max(0, len(patterns["breakouts"])-3)}


def pattern_description(patterns):
    if patterns["status"] == "not_requested":
        return "Pattern rules were not evaluated because no zone origin was supplied."
    if patterns["status"] in ("no_completed_candles", "insufficient_data"):
        return "Insufficient completed history to establish a prior close and a pattern candle."
    text = f"Candle rules {patterns['version']} use exact zone edges and six later H4 candles for retests."
    if patterns["status"] == "partial_history":
        text += " Coverage is partial; patterns across missing candles cannot be established."
    if patterns["events"]:
        text += " Latest observed event: " + patterns["events"][-1]["description"]
    else:
        text += " No defined pattern matched in the observed window."
    if patterns["breakouts"]:
        last = patterns["breakouts"][-1]
        text += (f" Latest breakout's retest status: {last['status']}; {last['observed_candles']} of six subsequent candles observed"
                 f" through {last['assessed_through']['close_time']}. Reason: {last['reason'].replace('_', ' ')}.")
    return text + " These are dated rule matches, not ongoing confirmation or a forecast."
