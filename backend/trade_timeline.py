"""Read-only post-entry chart. Never used by setup or entry strategy assessment."""
from datetime import datetime, timedelta

import market_data as md
import trade_database as db

MAX_CANDLES = 10000
PAGE_SIZE = 5000
POST_EXIT_CANDLES = 60


def bar_start(at):
    local = at.astimezone(md.NY)
    anchor = local.replace(hour=1, minute=0, second=0, microsecond=0)
    return (anchor + timedelta(hours=((local.hour - 1) // 4) * 4)).astimezone(md.UTC)


def trading_bar(at):
    local = at.astimezone(md.NY)
    return local.weekday() < 4 or (local.weekday() == 4 and local.hour < 17) or (local.weekday() == 6 and local.hour >= 17)


def scheduled_bars(start, end):
    """Build each New York session separately so DST weekends keep their real gap."""
    day = start.astimezone(md.NY).date()
    last = end.astimezone(md.NY).date() + timedelta(days=1)
    while day <= last:
        if day.weekday() < 5:
            session_start, _ = md.session_bounds(day)
            for index in range(6):
                opened = session_start + index * md.CANDLE_DURATION
                if start <= opened < end:
                    yield opened
        day += timedelta(days=1)


def _history(start, cutoff):
    # Backward pages cover the whole trade plus warmup; no silent truncation.
    count = min(PAGE_SIZE, max(md.WARMUP_COUNT + 50, int((cutoff-start) / md.CANDLE_DURATION) + md.WARMUP_COUNT + 50))
    cursor, by_time = cutoff, {}
    for _ in range((MAX_CANDLES + md.WARMUP_COUNT) // PAGE_SIZE + 2):
        page = md._parse_candles(md._fetch_candles(cursor, count=count), cursor, include_forming=cursor == cutoff)
        page = [c for c in page if c.open_time < cursor and trading_bar(c.open_time)]
        if not page:
            break
        for candle in page:
            by_time.setdefault(candle.open_time, candle)
        if len([c for c in by_time.values() if c.open_time >= start]) > MAX_CANDLES:
            raise md.MarketDataError(f'The trade timeline supports up to {MAX_CANDLES:,} H4 candles. This trade is too long to chart in full.', 422)
        earlier = sorted((c for c in by_time.values() if c.close_time <= start and c.complete), key=lambda c: c.open_time)
        if len(earlier) >= md.WARMUP_COUNT:
            selected = sorted((c for c in by_time.values() if start <= c.open_time < cutoff), key=lambda c: c.open_time)
            return earlier[-md.WARMUP_COUNT:], selected
        oldest = min(c.open_time for c in page)
        if oldest >= cursor:
            break
        cursor = oldest
    raise md.MarketDataError('Not enough earlier market data is available to chart this trade with indicators.', 422)


def _after_exit(start, now):
    if start >= now:
        return []
    # Forward retrieval keeps the first candles after exit even for old trades.
    # The extra row tolerates an inclusive boundary overlap; never show >60.
    raw = md._fetch_candles(None, count=POST_EXIT_CANDLES + 1, start=start)
    rows = md._parse_candles(raw, now, include_forming=True)
    return [c for c in rows if start <= c.open_time < now and trading_bar(c.open_time)][:POST_EXIT_CANDLES]


def build_timeline(record, now):
    entry = record['entry']
    entered = datetime.fromisoformat(entry['entry_at']).astimezone(md.UTC)
    exited = datetime.fromisoformat(record['exit']['exit_at']).astimezone(md.UTC) if record['exit'] else None
    start = bar_start(entered)
    end = now
    if exited:
        boundary = bar_start(exited)
        # At an exact close, do not add the next candle unless entry and exit
        # are the same instant. A mid-bar exit includes the whole containing bar.
        end = boundary if exited == boundary and exited > entered else boundary + md.CANDLE_DURATION
    cutoff = min(end, now)
    if entered > now:
        raise md.MarketDataError('The trade entry time is in the future.', 422)
    warmup, selected = _history(start, cutoff)
    trade_count = len(selected)
    after_exit = _after_exit(end, now) if exited else []
    selected += after_exit
    if exited and end < now:
        # Once all 60 are available, later days must not expand the window.
        cutoff = min(now, after_exit[-1].close_time) if len(after_exit) == POST_EXIT_CANDLES else now
    all_candles = warmup + selected
    rows = md._indicator_rows(all_candles, len(warmup) - md.CHART_HISTORY_COUNT)
    for row, candle in zip(rows, all_candles[len(warmup) - md.CHART_HISTORY_COUNT:]):
        row['complete'] = candle.complete
        row['timeline_phase'] = 'before_entry' if candle.close_time <= start else 'after_exit' if exited and candle.open_time >= end else 'trade'
        row['contains_post_exit_prices'] = bool(exited and candle.open_time < exited < min(candle.close_time, cutoff))
    history = rows[:md.CHART_HISTORY_COUNT]
    candles = rows[md.CHART_HISTORY_COUNT:]
    expected = list(scheduled_bars(start, cutoff))
    available = {c.open_time for c in selected}
    missing = [at for at in expected if at not in available]
    events = []
    for kind, at, price in [('entry', entered, entry['entry_price']), ('exit', exited, record['exit']['exit_price'] if exited else None)]:
        if at is None:
            continue
        # An exact exit at a bar close belongs to that closing bar. No made-up
        # marker on a neighboring candle when the event occurs during a gap.
        anchor = next((c for c in reversed(all_candles) if c.open_time < at <= c.close_time), None) if kind == 'exit' and at > entered else None
        if anchor is None:
            anchor = next((c for c in all_candles if c.open_time <= at < c.close_time), None)
        events.append({'kind': kind, 'at': at.isoformat(), 'price': price,
                       'candle_open_time': anchor.open_time.isoformat() if anchor else None})
    return {
        'schema_version': 1, 'analysis_kind': 'trade_timeline', 'trade_id': record['id'],
        'status': record['status'], 'direction': entry['direction'], 'source': 'OANDA',
        'instrument': 'EUR_USD', 'timeframe': 'H4', 'price_basis': 'midpoint',
        'as_of': now.isoformat(), 'entry_at': entered.isoformat(), 'exit_at': exited.isoformat() if exited else None,
        'display_through': cutoff.isoformat(), 'events': events,
        'session': {'start_utc': start.isoformat(), 'end_utc': end.isoformat()},
        'chart_context': {'purpose': 'display_only', 'candles': history}, 'candles': candles,
        'coverage': {'trade_candle_count': trade_count, 'after_exit_count': len(after_exit),
                     'after_exit_target': POST_EXIT_CANDLES, 'after_exit_complete_count': sum(c.complete for c in after_exit),
                     'missing_candle_count': len(missing), 'first_missing_open': missing[0].isoformat() if missing else None,
                     'last_candle_close': rows[-1]['close_time'],
                     'forming_count': sum(not c.complete for c in selected),
                     'exit_candle_pending': bool(exited and end > now),
                     'contains_post_exit_prices': any(row['contains_post_exit_prices'] for row in candles)},
    }


def fetch_timeline(identifier):
    record = db.fetch_trade(identifier)
    view = build_timeline(record, datetime.now(md.UTC))
    # If a full exit was saved during the provider request, discard the open
    # view and honor the exit boundary and bounded after-exit context before returning prices.
    latest = db.fetch_trade(identifier)
    if latest['exit'] != record['exit']:
        view = build_timeline(latest, datetime.now(md.UTC))
    return view
