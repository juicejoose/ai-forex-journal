"""Evidence an open-trade coach can cite about the trader's written premise."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from journal_grounding import StrictModel
from zone_history import analyze_zone_history
from zone_patterns import analyze_zone_patterns


class PremiseCheck(StrictModel):
    source: Literal['entry_reason', 'entry_observations']
    excerpt: str = Field(min_length=1, max_length=400)
    window: Literal['at_entry', 'since_entry']
    status: Literal['supported', 'challenged', 'awaiting_confirmation', 'unverifiable']
    explanation: str = Field(min_length=1, max_length=400)
    evidence_ids: list[str] = Field(max_length=4)


def premise_evidence(snapshot, entry_source, entry_zones):
    facts = []
    def add(window, stamp, text):
        facts.append({'id': f'P{len(facts)+1}', 'window': window, 'through': stamp, 'text': text})

    entry_at = datetime.fromisoformat(snapshot['trade']['entry_at'])
    baseline = snapshot['entry_score']
    hold = snapshot['full_trade']['candles']
    windows = []
    if baseline['covers_latest_scheduled_close']:
        windows.append(('at_entry', baseline['candle'], entry_source))
    if hold and snapshot['covers_latest_close']:
        windows.append(('since_entry', hold[-1], snapshot['source_candles']))

    for window, candle, source in windows:
        through = candle['close_time']
        cutoff = datetime.fromisoformat(through)
        rows = [r for r in source if datetime.fromisoformat(r['close_time']) <= cutoff]
        if candle['direction'] != 'insufficient_data' and candle.get('net_score') is not None:
            add(window, through, f"Four-factor H4 bias: {candle['direction']}, net {candle['net_score']:+g}.")
        for factor in candle['factors']:
            if factor['outcome'] != 'unavailable':
                readings = factor['evidence'][-1]['values']
                values = ', '.join(f"{key.replace('_', ' ')} {value:.5f}" for key, value in readings.items()
                                   if isinstance(value, (int, float)) and not isinstance(value, bool))
                add(window, through, f"{factor['name']} on this H4 close: {factor['outcome']}. {factor['reason']} {values}")
        if not rows or datetime.fromisoformat(rows[-1]['close_time']) != cutoff:
            continue
        for index, original in enumerate(entry_zones, 1):
            zone = {'id': f'Z{index}', **original.model_dump(mode='json')}
            name = f"{zone['label']} ({zone['kind']}, {zone['lower']}–{zone['upper']})"
            low, high = original.lower, original.upper
            close = Decimal(str(rows[-1]['close']))
            position = 'below' if close < low else 'above' if close > high else 'inside'
            if original.origin_at and original.origin_at > cutoff:
                continue
            origin_note = '' if original.origin_at else ' No zone origin was supplied for historical pattern checks.'
            add(window, through, f"H4 closed at {close} {position} {name}.{origin_note}")
            if not original.origin_at:
                continue
            if window == 'since_entry':
                closes = [Decimal(str(r['close'])) for r in rows if
                          datetime.fromisoformat(r['close_time']) > entry_at and
                          datetime.fromisoformat(r['open_time']) >= original.origin_at]
                if closes:
                    below, above = sum(c < low for c in closes), sum(c > high for c in closes)
                    add(window, through, f"{name}: {len(closes)} of {len(hold)} in-trade H4 closes covered "
                        f"from the zone origin. {below} below, {above} above, {len(closes)-below-above} inside.")
            if window == 'since_entry' and snapshot['zone_source'] != 'review_annotations':
                patterns = snapshot['zones'][index-1]['patterns']
            else:
                history = analyze_zone_history(zone, rows, cutoff)
                patterns = analyze_zone_patterns(zone, rows, cutoff, history)
            eligible = [event for event in patterns['events'] if window == 'at_entry' or
                        entry_at < datetime.fromisoformat(event['close_time']) <= cutoff]
            if eligible:
                event = eligible[-1]
                add(window, event['close_time'], f"{name}. {event['description']}")
    return facts


def validate_premise(checks, snapshot):
    facts = {f['id']: f for f in snapshot['premise_evidence']}
    seen = set()
    if not any(check.source == 'entry_reason' for check in checks):
        raise ValueError('Missing entry reason.')
    for check in checks:
        if check.excerpt not in snapshot['trade'].get(check.source, ''):
            raise ValueError('The quoted premise must come from the saved entry.')
        key = (check.source, check.excerpt, check.window)
        if key in seen:
            raise ValueError('Duplicate premise check.')
        seen.add(key)
        refs = check.evidence_ids
        if len(refs) != len(set(refs)) or any(i not in facts or facts[i]['window'] != check.window for i in refs):
            raise ValueError('Invalid premise evidence or time window.')
        if check.status in ('supported', 'challenged') and not refs:
            raise ValueError('A finding about the premise needs observed market evidence.')
