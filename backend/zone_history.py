"""Descriptive H4 zone history, independent of strategy points and AI wording."""
from datetime import datetime, time, timedelta
from decimal import Decimal
from math import isfinite

from market_data import NY, UTC, CANDLE_DURATION, MarketDataError

VERSION = "zone_history_v1"
FOLLOWUP_CANDLES = 3


def _stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Timezone required")
    return stamp.astimezone(UTC)


def _next_open(close):
    local = close.astimezone(NY)
    if local.weekday() == 4 and local.time().replace(tzinfo=None) == time(17):
        return datetime.combine(local.date() + timedelta(days=2), time(17), tzinfo=NY).astimezone(UTC)
    return close


def _position(value, lower, upper):
    return "below" if value < lower else "above" if value > upper else "inside"


def _first_open_at_or_after(origin):
    local = origin.astimezone(NY)
    for offset in range(4):
        day = local.date() + timedelta(days=offset)
        for hour in (1, 5, 9, 13, 17, 21):
            if day.weekday() == 5 or day.weekday() == 4 and hour >= 17 or day.weekday() == 6 and hour < 17:
                continue
            candidate = datetime.combine(day, time(hour), tzinfo=NY).astimezone(UTC)
            if candidate >= origin:
                return candidate
    raise ValueError("No scheduled H4 opening found")


def _pips(value):
    return float(value / Decimal("0.0001"))


def _source_rows(source, cutoff):
    rows = []
    try:
        for original in source:
            closed = _stamp(original["close_time"])
            # Do not even inspect prices of candles that were not complete at cutoff.
            if closed > cutoff:
                continue
            opened = _stamp(original["open_time"])
            values = {key: Decimal(str(original[key])) for key in ("open", "high", "low", "close")}
            if (closed - opened != CANDLE_DURATION or
                any(not isfinite(value) or value <= 0 for value in values.values()) or
                values["low"] > min(values["open"], values["close"]) or
                values["high"] < max(values["open"], values["close"])):
                raise ValueError("Invalid source candle")
            rows.append({"opened": opened, "closed": closed, **values,
                         "candle_id": f"H4-{opened.strftime('%Y%m%dT%H%MZ')}"})
        rows.sort(key=lambda row: row["opened"])
        if any(a["closed"] > b["opened"] for a, b in zip(rows, rows[1:])):
            raise ValueError("Overlapping or duplicate source candles")
    except (KeyError, TypeError, ValueError, ArithmeticError, OverflowError):
        raise MarketDataError("The saved candles cannot support validated zone history.", 502) from None
    return rows


def _reference(row):
    return {"candle_id": row["candle_id"], "open_time": row["opened"].isoformat(),
            "close_time": row["closed"].isoformat(), "close": float(row["close"])}


def analyze_zone_history(zone, source, cutoff):
    """Only whole completed candles opening at/after the user-supplied origin."""
    origin = _stamp(zone["origin_at"]) if zone.get("origin_at") else None
    if origin and origin > cutoff:
        raise MarketDataError("A zone's origin cannot be after the evaluation cutoff.", 422)
    result = {"version": VERSION, "timeframe": "H4", "origin_at": origin.isoformat() if origin else None,
              "origin_is_user_supplied": True, "cutoff_at": cutoff.isoformat(),
              "status": "not_requested", "available_from": None, "coverage_start": None, "coverage_end": None,
              "origin_before_history": False, "gap_count": 0, "candle_count": 0,
              "visit_count": None, "overlap_candles": None, "close_counts": None,
              "visits": [], "events": [], "followup_candles": FOLLOWUP_CANDLES}
    if origin is None:
        return result
    available = _source_rows(source, cutoff)
    if not available:
        result["status"] = "no_completed_candles"
        return result
    result["available_from"] = available[0]["opened"].isoformat()
    result["origin_before_history"] = origin < available[0]["opened"]
    rows = [row for row in available if row["opened"] >= origin]
    if not rows:
        result["status"] = "no_completed_candles"
        return result
    low, high = Decimal(zone["lower"]), Decimal(zone["upper"])
    leading_gap = rows[0]["opened"] > _first_open_at_or_after(max(origin, available[0]["opened"]))
    trailing_gap = _next_open(rows[-1]["closed"]) + CANDLE_DURATION <= cutoff
    for index, row in enumerate(rows):
        row["overlap"] = row["low"] <= high and row["high"] >= low
        row["position"] = _position(row["close"], low, high)
        row["gap_before"] = (index > 0 and _next_open(rows[index-1]["closed"]) != row["opened"]) or (index == 0 and leading_gap)
    result.update(coverage_start=rows[0]["opened"].isoformat(), coverage_end=rows[-1]["closed"].isoformat(),
                  candle_count=len(rows), gap_count=sum(row["gap_before"] for row in rows) + int(trailing_gap),
                  overlap_candles=sum(row["overlap"] for row in rows),
                  close_counts={position: sum(row["position"] == position for row in rows)
                                for position in ("above", "inside", "below")})
    result["status"] = "partial_history" if result["origin_before_history"] or result["gap_count"] else "covered"
    ranges, start = [], None
    for index, row in enumerate(rows):
        if start is not None and (not row["overlap"] or row["gap_before"]):
            ranges.append((start, index - 1))
            start = None
        if row["overlap"] and start is None:
            start = index
        previous = rows[index-1]["position"] if index and not row["gap_before"] else None
        if row["position"] != previous:
            result["events"].append({"id": f"{zone['id']}-C{index+1}", "kind": "close_position",
                "position": row["position"], "previous_position": previous, "after_gap": row["gap_before"],
                **_reference(row)})
    if start is not None:
        ranges.append((start, len(rows)-1))
    for number, (first, last) in enumerate(ranges, 1):
        begin, end = rows[first], rows[last]
        identifier = f"{zone['id']}-V{number}"
        following, stop_reason = [], "cutoff"
        for index in range(last + 1, min(last + 1 + FOLLOWUP_CANDLES, len(rows))):
            row = rows[index]
            if row["gap_before"]:
                stop_reason = "data_gap"
                break
            if row["overlap"]:
                stop_reason = "next_visit"
                break
            following.append(row)
        if len(following) == FOLLOWUP_CANDLES:
            stop_reason = "complete"
        elif stop_reason == "cutoff" and trailing_gap:
            stop_reason = "data_gap"
        followup = {"candle_count": len(following), "stop_reason": stop_reason,
                    "last_candle": _reference(following[-1]) if following else None,
                    "close_change_pips": _pips(following[-1]["close"]-end["close"]) if following else None,
                    "high_above_last_overlap_close_pips": _pips(max(Decimal(0), max(c["high"] for c in following)-end["close"])) if following else None,
                    "low_below_last_overlap_close_pips": _pips(max(Decimal(0), end["close"]-min(c["low"] for c in following))) if following else None}
        end_status = ("unknown_after_gap" if last == len(rows)-1 and trailing_gap else
                      "overlapping_at_cutoff" if last == len(rows)-1 else
                      "unknown_after_gap" if rows[last+1]["gap_before"] else "left_zone")
        visit = {"id": identifier, "first_candle": _reference(begin), "last_candle": _reference(end),
                 "overlap_candles": last-first+1, "boundary_start": first == 0 or begin["gap_before"],
                 "last_close_position": end["position"], "end_status": end_status, "followup": followup}
        result["visits"].append(visit)
        result["events"].append({"id": identifier, "kind": "visit_start", "visit_number": number,
                                 "boundary_start": visit["boundary_start"], **_reference(begin)})
    result["visit_count"] = len(ranges)
    result["events"].sort(key=lambda event: (event["open_time"], event["kind"], event["id"]))
    return result


def history_summary(history):
    """Bounded AI context; full event lists stay in the immutable snapshot."""
    summary = {key: value for key, value in history.items() if key not in ("visits", "events")}
    summary["recent_visits"] = history["visits"][-3:]
    summary["recent_close_changes"] = [event for event in history["events"] if event["kind"] == "close_position"][-3:]
    summary["omitted_visits"] = max(0, len(history["visits"])-3)
    return summary


def history_description(history):
    status = history["status"]
    if status == "not_requested":
        return "Historical zone interactions were not evaluated because no origin time was supplied."
    if status == "no_completed_candles":
        return "No whole completed H4 candle opening at or after the supplied origin is available by the cutoff."
    counts = history["close_counts"]
    text = (f"Observed H4 history {history['coverage_start']} through {history['coverage_end']}: "
            f"{history['visit_count']} overlap groups across {history['overlap_candles']} overlapping candles; "
            f"closes above {counts['above']}, inside {counts['inside']}, below {counts['below']}.")
    if status == "partial_history":
        text += " Coverage is partial; these are observed groups, not a complete count since the origin."
    if history["visits"]:
        visit = history["visits"][-1]
        follow = visit["followup"]
        text += f" Latest group {visit['id']}: {visit['end_status'].replace('_', ' ')}."
        if follow["candle_count"]:
            text += (f" Across {follow['candle_count']} following completed candles, close changed "
                     f"{follow['close_change_pips']:+.1f} pips from the last overlap close; window {follow['stop_reason'].replace('_', ' ')}.")
        else:
            text += " No following candle movement is available for that group."
    return text
