"""Extra chart context only: never persisted as or supplied to AI/strategy evidence."""
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime
import market_data as md

CONTEXT_CANDLES = 160
DISPLAY_WARMUP = md.WARMUP_COUNT + CONTEXT_CANDLES
router = APIRouter(tags=['Chart context'])


def preceding_candles(before):
    """160 plotted bars, with 300 further bars to initialize their indicators."""
    raw = md._fetch_candles(before, count=DISPLAY_WARMUP + 20)
    candles = md._parse_candles(raw, before)[-DISPLAY_WARMUP:]
    if len(candles) < DISPLAY_WARMUP:
        raise md.MarketDataError('Not enough earlier data is available for 160 chart candles with initialized indicators.', 422)
    rows = md._indicator_rows(candles, md.WARMUP_COUNT)
    for row in rows: row['complete'] = True
    return rows


def following_candles(after, now):
    if after >= now: return []
    raw = md._fetch_candles(None, count=CONTEXT_CANDLES + 1, start=after)
    following = [c for c in md._parse_candles(raw, now, include_forming=True) if after <= c.open_time < now][:CONTEXT_CANDLES]
    if not following: return []
    warmup = md._parse_candles(md._fetch_candles(after), after)[-md.WARMUP_COUNT:]
    if len(warmup) < md.WARMUP_COUNT:
        raise md.MarketDataError('Not enough history is available to initialize indicators after this review.', 422)
    rows = md._indicator_rows(warmup + following, len(warmup))
    for row, candle in zip(rows, following):
        row.update(complete=candle.complete, timeline_phase='after_review')
    return rows


def forming_candle(at, now):
    """Current H4 bar containing a live preview time; never rebuild a historical partial bar."""
    if now - at >= md.CANDLE_DURATION:
        return None
    raw = md._fetch_candles(now)
    series = md._parse_candles(raw, now, include_forming=True)
    candidate = next((c for c in series if not c.complete and c.open_time <= at < c.close_time), None)
    if candidate is None:
        return None
    warmup = [c for c in series if c.complete and c.close_time <= candidate.open_time][-md.WARMUP_COUNT:]
    if len(warmup) < md.WARMUP_COUNT:
        raise md.MarketDataError('Not enough history is available for the forming candle indicators.', 422)
    row = md._indicator_rows(warmup + [candidate], len(warmup))[0]
    row.update(complete=False, timeline_phase='forming', as_of=now.isoformat())
    return row


def build_context(before, after=None, now=None, *, forming_at=None):
    now = now or datetime.now(md.UTC)
    if before.year < 2000 or before > now or (after and (after < before or after > now)):
        raise md.MarketDataError('Choose chart boundaries from 2000 through the present, in time order.', 422)
    if forming_at and (after or forming_at < before or forming_at > now):
        raise md.MarketDataError('Live forming context must follow the chart start and cannot be combined with later review context.', 422)
    before = before.astimezone(md.UTC)
    after = after.astimezone(md.UTC) if after else None
    forming_at = forming_at.astimezone(md.UTC) if forming_at else None
    return {
        'schema_version': 1, 'purpose': 'display_only', 'instrument': 'EUR_USD', 'timeframe': 'H4',
        'before_at': before.isoformat(), 'after_at': after.isoformat() if after else None,
        'retrieved_at': now.isoformat(), 'target_count': CONTEXT_CANDLES,
        'preceding': preceding_candles(before), 'following': following_candles(after, now) if after else [],
        'forming_at': forming_at.isoformat() if forming_at else None,
        'forming_candle': forming_candle(forming_at, now) if forming_at else None,
    }


@router.get('/chart-context')
def read_context(before_at: AwareDatetime, after_at: AwareDatetime | None = None,
                 forming_at: AwareDatetime | None = None):
    try:
        return build_context(before_at, after_at, forming_at=forming_at)
    except md.MarketDataError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
