"""Current New York session: completed candles only, with bounded server snapshots."""

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, time
from threading import RLock
from time import monotonic
from uuid import uuid4
import hashlib
import json

import market_data as md
from strategy_rules import evaluate_strategy

POLL_SECONDS = 60
SNAPSHOT_TTL = 1800
MAX_SNAPSHOTS = 64
_lock = RLock()
_latest = None
_snapshots = OrderedDict()


def session_context(now):
    local = now.astimezone(md.NY)
    day = local.date()
    closed = (local.weekday() == 4 and local.hour >= 17) or local.weekday() == 5 or (local.weekday() == 6 and local.hour < 17)
    if closed:
        label = day - timedelta(days=(day.weekday() - 4) % 7)
        next_open = datetime.combine(label + timedelta(days=2), time(17), tzinfo=md.NY)
    else:
        label = day + timedelta(days=local.hour >= 17)
        next_open = None
    start, end = md.session_bounds(label)
    count = max(0, min(6, int((min(now, end) - start).total_seconds() // 14400)))
    return label, start, end, count, closed, next_open


def build_today_view(now):
    label, start, end, count, closed, next_open = session_context(now)
    slots = []
    for index in range(6):
        opened = start + index * md.CANDLE_DURATION
        finished = opened + md.CANDLE_DURATION
        slots.append({"candle_id": f"C{index+1}", "open_time": opened.isoformat(), "close_time": finished.isoformat(),
                      "status": "completed" if index < count else "forming" if opened <= now < finished else "upcoming"})
    view = {"schema_version": 1, "journal_date": label.isoformat(), "as_of": now.isoformat(),
            "poll_seconds": POLL_SECONDS, "market_state": "weekend_closed" if closed else "scheduled_session",
            "next_open": next_open.isoformat() if next_open else None,
            "session": {"start": start.isoformat(), "end": end.isoformat(), "complete": count == 6,
                        "candle_count": count, "expected_candle_count": 6},
            "slots": slots, "snapshot_id": None, "market_data": None, "rule_evaluation": None}
    if count == 0:
        return view
    cutoff = min(now, end)
    raw = md._fetch_candles(cutoff)
    candles = md._parse_candles(raw, cutoff)
    selected = [c for c in candles if start <= c.open_time < end]
    expected = [start + i * md.CANDLE_DURATION for i in range(count)]
    if [c.open_time for c in selected] != expected:
        raise md.MarketDataError("A candle that should have closed is not available yet. Data may be delayed or trading may have closed early. Retry shortly; future candles are not substituted.", 503)
    warmup = [c for c in candles if c.close_time <= start][-md.WARMUP_COUNT:]
    if len(warmup) != md.WARMUP_COUNT:
        raise md.MarketDataError("Not enough earlier candles are available for today's indicators.", 503)
    snapshot = md._build_snapshot(label, start, end, selected, warmup, datetime.now(md.UTC))
    snapshot.update(analysis_kind="intraday", as_of=now.isoformat(), data_through=selected[-1].close_time.isoformat())
    snapshot["session"].update(complete=count == 6, expected_candle_count=6)
    evaluation = evaluate_strategy(snapshot, allow_partial=True)
    evaluation.update(analysis_kind="intraday", as_of=snapshot["as_of"], data_through=snapshot["data_through"],
                      session_complete=count == 6, expected_candle_count=6)
    if count < 6:
        evaluation["summary"]["method"] = "session_to_date"
        definition = evaluation["rule_set"]
        definition.update(scope="intraday", summary_method="session_to_date")
        definition["rules"] = definition["rules"].replace("all six completed H4 candles", "all available completed H4 candles")
        definition["rules"] = definition["rules"].replace("All twenty-four factor checks", "All factor checks on completed candles")
        definition["rules"] = definition["rules"].replace(
            "Keep the final candle's bias separately as session-end context.",
            "Keep the latest completed candle's bias separately as latest-close context.")
        definition["rules"] = definition["rules"].replace(
            "Never treat missing inputs as zero or average fewer candles.",
            "Never treat missing inputs as zero or omit any available completed candle from the average.")
        definition["rules"] += " This is a session-to-date review. Pending candles have no points and are excluded from the denominator. The final available candle is latest-close context, not the session's final candle."
    view.update(market_data=snapshot, rule_evaluation=evaluation)
    snapshot["data_key"] = hashlib.sha256(json.dumps({"date": label.isoformat(), "candles": snapshot["candles"],
        "previous_candles": snapshot["previous_candles"], "evaluation": {k: v for k, v in evaluation.items() if k != "as_of"}},
        sort_keys=True, allow_nan=False).encode()).hexdigest()
    return view


def _prune(tick):
    for key, (expires, _) in list(_snapshots.items()):
        if expires <= tick:
            del _snapshots[key]
    while len(_snapshots) > MAX_SNAPSHOTS:
        _snapshots.popitem(last=False)


def get_today_view():
    """Share one poll across tabs; never return stale cache on provider failure."""
    global _latest
    with _lock:
        now, tick = datetime.now(md.UTC), monotonic()
        label, _, _, count, closed, _ = session_context(now)
        key = label, count, closed
        _prune(tick)
        if _latest and _latest[0] == key and tick < _latest[1]:
            return deepcopy(_latest[2])
        view = build_today_view(now)
        if view["market_data"]:
            view["snapshot_id"] = str(uuid4())
            _snapshots[view["snapshot_id"]] = (monotonic() + SNAPSHOT_TTL, deepcopy(view))
            _prune(monotonic())
        _latest = key, monotonic() + 55, deepcopy(view)
        return view


def load_today_snapshot(snapshot_id):
    with _lock:
        _prune(monotonic())
        stored = _snapshots.get(snapshot_id)
        if stored is None:
            raise md.MarketDataError("This live snapshot expired or the backend restarted. Refresh Today, then generate again.", 409)
        return deepcopy(stored[1])
