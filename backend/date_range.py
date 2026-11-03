"""Bounded multi-session market snapshots and deterministic H4 range scores."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import market_data as md
from journal_grounding import InvalidJournalEvidence, build_evidence_catalog, _utc
from strategy_rules import RULE_SET_ID, rule_set_definition, evaluate_strategy, _session_average

MAX_RANGE_DAYS = 31


def trading_dates(start_date, end_date):
    if start_date == date.min or end_date < start_date:
        raise md.MarketDataError("Choose a valid start date on or before the end date.", 422)
    days = (end_date - start_date).days + 1
    if days > MAX_RANGE_DAYS:
        raise md.MarketDataError(f"Choose a range of at most {MAX_RANGE_DAYS} calendar days, including both dates.", 422)
    dates = [start_date + timedelta(days=i) for i in range(days)]
    dates = [day for day in dates if day.weekday() < 5]
    if not dates:
        raise md.MarketDataError("This range has no weekday trading sessions. Include at least one weekday.", 422)
    return dates


def get_range_market_data(start_date, end_date):
    dates = trading_dates(start_date, end_date)
    # Check the selected end date too, even if it lands on a weekend.
    if md.session_bounds(end_date)[1] > datetime.now(timezone.utc):
        raise md.MarketDataError("Choose an end date whose 5 p.m. New York cutoff has passed.", 422)
    start, end = md.session_bounds(dates[0])[0], md.session_bounds(dates[-1])[1]
    expected = [md.session_bounds(day)[0] + i * md.CANDLE_DURATION for day in dates for i in range(6)]
    raw = md._fetch_candles(end, count=md.WARMUP_COUNT + len(expected) + 50)
    retrieved = datetime.now(timezone.utc)
    candles = md._parse_candles(raw, end)
    selected = [c for c in candles if start <= c.open_time < end]
    if [c.open_time for c in selected] != expected:
        raise md.MarketDataError("The range is missing completed H4 candles. A session may have closed early or data may be missing; choose another range.", 422)
    warmup = [c for c in candles if c.close_time <= start][-md.WARMUP_COUNT:]
    if len(warmup) != md.WARMUP_COUNT:
        raise md.MarketDataError("Not enough earlier candles are available to initialize the range indicators.", 422)
    snapshot = md._build_snapshot(end_date, start, end, selected, warmup, retrieved)
    snapshot.pop("journal_date")
    snapshot.update(analysis_kind="custom_range", range={
        "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        "calendar_day_count": (end_date - start_date).days + 1,
        "trading_dates": [day.isoformat() for day in dates], "trading_day_count": len(dates),
    })
    return snapshot


def range_rule_definition():
    definition = rule_set_definition(RULE_SET_ID)
    definition.update(scope="custom_range", summary_method="range_average")
    definition["rules"] = definition["rules"].replace(
        "For the session summary, average bullish and bearish points separately across all six completed H4 candles,",
        "For the custom range summary, average bullish and bearish points separately across every completed H4 candle in the selected range,",
    ).replace("session bias", "range bias").replace("session-end context", "range-end context").replace(
        "All twenty-four factor checks must be available", "Every factor check across the whole range must be available"
    ).replace("session averages", "range averages")
    return definition


def _daily_snapshots(snapshot):
    """Validate all sessions; never silently omit gaps or partial sessions."""
    try:
        if snapshot["analysis_kind"] != "custom_range" or snapshot["session"]["complete"] is not True:
            raise ValueError("Not a completed range")
        info = snapshot["range"]
        start_date, end_date = date.fromisoformat(info["start_date"]), date.fromisoformat(info["end_date"])
        dates = trading_dates(start_date, end_date)
        if info["trading_dates"] != [day.isoformat() for day in dates] or info["trading_day_count"] != len(dates):
            raise ValueError("Invalid range dates")
        if info["calendar_day_count"] != (end_date - start_date).days + 1:
            raise ValueError("Invalid calendar coverage")
        candles = snapshot["candles"]
        if len(candles) != len(dates) * 6 or snapshot["session"]["candle_count"] != len(candles):
            raise ValueError("Incomplete range")
        if (_utc(snapshot["session"]["start_utc"]) != md.session_bounds(dates[0])[0]
                or _utc(snapshot["session"]["end_utc"]) != md.session_bounds(dates[-1])[1]):
            raise ValueError("Range boundary mismatch")
        days = []
        for day_index, day in enumerate(dates):
            offset = day_index * 6
            start, end = md.session_bounds(day)
            daily = {**snapshot, "journal_date": day.isoformat(), "candles": candles[offset:offset + 6],
                     "session": {**snapshot["session"], "start_utc": start.isoformat(), "end_utc": end.isoformat(), "candle_count": 6}}
            if offset:
                daily.update(previous_candle=candles[offset-1], previous_candles=candles[offset-2:offset])
            build_evidence_catalog(daily)
            days.append(daily)
        return days
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, md.MarketDataError) as exc:
        raise InvalidJournalEvidence("The custom range cannot support complete candle evidence.") from exc


def build_range_evidence_catalog(snapshot):
    catalog = {}
    for day_index, daily in enumerate(_daily_snapshots(snapshot)):
        for index, item in enumerate(build_evidence_catalog(daily).values()):
            catalog[f"C{day_index * 6 + index + 1}"] = item
    return catalog


def evaluate_range_strategy(snapshot):
    rows, daily_summaries = [], []
    for day_index, daily in enumerate(_daily_snapshots(snapshot)):
        offset = day_index * 6
        result = evaluate_strategy(daily, RULE_SET_ID)
        mapping = {f"C{i}": f"C{offset+i}" for i in range(1, 7)}
        mapping.update({"P-1": f"C{offset-1}" if offset else "P-1", "P0": f"C{offset}" if offset else "P0"})
        for row in result["candles"]:
            row["candle_id"] = mapping[row["candle_id"]]
            for factor in row["factors"]:
                for evidence in factor["evidence"]:
                    evidence["candle_id"] = mapping[evidence["candle_id"]]
            rows.append(row)
        daily_summaries.append({"journal_date": daily["journal_date"], **result["summary"],
                                "candle_ids": [mapping[c] for c in result["summary"]["candle_ids"]]})
    definition = range_rule_definition()
    summary = _session_average(rows, definition["max_points"])
    summary["method"] = "range_average"
    end = {**result["session_end"], "candle_id": rows[-1]["candle_id"]}
    return {"schema_version": 1, "analysis_kind": "custom_range", "range": deepcopy(snapshot["range"]),
            "rule_set": definition, "summary": summary, "session_end": end,
            "daily_summaries": daily_summaries, "candles": rows}
