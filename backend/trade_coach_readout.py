"""Summarize already-scored, completed H4 candles for an open-trade review."""

DIRECTIONAL_EVENTS = {'rejection', 'breakout', 'retest_held'}


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
