"""Summarize already-scored, completed H4 candles for an open-trade review."""

from collections import deque
from math import isfinite

DIRECTIONAL_EVENTS = {'rejection', 'breakout', 'retest_held'}


def hold_alignment(snapshot):
    """Describe the hold using only the scores frozen in this review."""
    hold = snapshot.get('full_trade') or {}
    rows = hold.get('candles')
    direction = snapshot.get('trade', {}).get('direction')
    if not rows or direction not in ('long', 'short'):
        return None

    counts = dict(supportive=0, opposing=0, balanced=0, unavailable=0)
    latest_run = previous_run = None
    recent_nets = deque(maxlen=2)
    for row in rows:
        net = row.get('net_score')
        if row.get('direction') == 'insufficient_data' or type(net) not in (int, float) or not isfinite(net):
            net = None
            status = 'unavailable'
        elif net == 0:
            status = 'balanced'
        else:
            status = 'supportive' if (net > 0) == (direction == 'long') else 'opposing'
        if latest_run is None or latest_run['status'] != status:
            previous_run, latest_run = latest_run, {'status': status, 'count': 0}
        latest_run['count'] += 1
        counts[status] += 1
        recent_nets.append(net)
    return {'total': len(rows), 'counts': counts, 'latest_run': latest_run, 'previous_run': previous_run,
            'recent_nets': list(recent_nets),
            'average_net': None if counts['unavailable'] else (hold.get('summary') or {}).get('net_score')}


def current_zone_events(zone, through):
    return [event for event in zone['patterns']['events']
            if event['close_time'] == through and event['kind'] in DIRECTIONAL_EVENTS]


def _price_action(snapshot, count):
    zones = snapshot['zones']
    matches = []
    desired = 'bullish' if snapshot['trade']['direction'] == 'long' else 'bearish'
    for zone in zones:
        for event in current_zone_events(zone, snapshot['data_through']):
            matches.append({'zone_id': zone['id'], 'zone_label': zone['label'], 'event_id': event['id'],
                            'kind': event['kind'], 'direction': event['direction']})
    directions = {event['direction'] for event in matches}
    partial = any(zone['patterns']['status'] != 'covered' for zone in zones)
    if not count:
        status = 'awaiting_close'
    elif not zones:
        status = 'no_zones'
    elif not snapshot['covers_latest_close']:
        status = 'unavailable'
    elif len(directions) > 1:
        status = 'mixed'
    elif directions:
        status = 'supports' if desired in directions else 'opposes'
    else:
        status = 'limited_history' if partial else 'no_match'
    return {'status': status, 'partial_coverage': partial,
            'matches': matches if count and snapshot['covers_latest_close'] else []}


def _state(factor):
    return {key: factor[key] for key in ('outcome', 'bullish_points', 'bearish_points')}


def _factor_history(entry, rows):
    history = {}
    for factor in entry['factors']:
        initial = _state(factor)
        history[factor['factor_id']] = {'factor_id': factor['factor_id'], 'name': factor['name'],
            'entry': initial, 'latest': initial, 'previous': None, 'changed_at': None, 'consecutive_closes': 0}
    for candle in rows:
        for factor in candle['factors']:
            item = history[factor['factor_id']]
            current = _state(factor)
            if current != item['latest']:
                item.update(previous=item['latest'], latest=current, changed_at=candle['close_time'],
                            consecutive_closes=0)
            item['consecutive_closes'] += 1
    return list(history.values())


def build_readout(snapshot):
    rows = snapshot['full_trade']['candles']
    latest = snapshot['latest_summary']
    count = len(rows)
    available = snapshot['covers_latest_close'] and latest['net_score'] is not None
    alignment = 'insufficient_evidence'
    if available:
        relative_net = latest['net_score'] * (1 if snapshot['trade']['direction'] == 'long' else -1)
        alignment = 'supported' if relative_net > 0 else 'contradicted' if relative_net < 0 else 'balanced'
    return {'strategy_alignment': alignment, 'market_net_score': latest['net_score'] if available else None,
            'hold_closes': count, 'price_action': _price_action(snapshot, count),
            'factor_history': _factor_history(snapshot['entry_score']['candle'], rows)}
