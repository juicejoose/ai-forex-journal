"""Map frozen four-factor results to an actual trade; never change strategy scores."""
from copy import deepcopy
from datetime import datetime, timedelta
from math import isfinite
from uuid import uuid4

import market_data as md
import today
from setup_market import build_setup_snapshot
from setup_models import SetupInput
from trade_calculations import TradeInputError

VERSION = 'trade_alignment_v1'
RELATIONS = ('supporting', 'conflicting', 'neutral', 'unavailable')


def _time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(md.UTC)


def latest_scheduled_close(at):
    """Scheduled H4 boundary only, not a claim that a provider supplied a candle."""
    _, start, _, count, _, _ = today.session_context(at)
    if count:
        return start + count * md.CANDLE_DURATION
    previous = start.astimezone(md.NY).date()
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return md.session_bounds(previous)[1]


def relation(outcome, direction):
    if outcome in ('unavailable', 'insufficient_data'):
        return 'unavailable'
    if outcome in ('neutral', 'mixed'):
        return outcome
    return 'supporting' if outcome == ('bullish' if direction == 'long' else 'bearish') else 'conflicting'


def _points(value):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError('Invalid points')
    return value


def _validate(entry, snapshot):
    """Fail closed on malformed/future evidence without rerunning old strategy versions."""
    try:
        entered, cutoff, through = _time(entry['entry_at']), _time(snapshot['cutoff_at']), _time(snapshot['data_through'])
        if entry['direction'] not in ('long', 'short') or not through <= cutoff <= entered:
            raise ValueError('Invalid cutoff')
        if snapshot['instrument'] != 'EUR_USD' or snapshot['timeframe'] != 'H4':
            raise ValueError('Different market')
        market, evaluation = snapshot['market_data'], snapshot['rule_evaluation']
        raw = [*snapshot['source_candles'], *market.get('chart_context', {}).get('candles', []),
               *market.get('previous_candles', []), *market['candles']]
        if market.get('previous_candle'):
            raw.append(market['previous_candle'])
        for candle in raw:
            if (candle.get('complete') is False or _time(candle['close_time']) - _time(candle['open_time']) != md.CANDLE_DURATION or _time(candle['close_time']) > cutoff):
                raise ValueError('Future or incomplete candle')
        if _time(snapshot['reference_price']['time']) > cutoff:
            raise ValueError('Future reference')
        definition, rows = evaluation['rule_set'], evaluation['candles']
        definitions = {factor['id']: factor for factor in definition['factors']}
        if (len(definitions) != 4 or len(definition['factors']) != 4 or
                not definition['id'].startswith('four_factor_v') or not definition['version'] or
                not 1 <= len(rows) <= 6 or len(rows) != len(market['candles'])):
            raise ValueError('Missing four-factor results')
        last_close = None
        for row, candle in zip(rows, market['candles']):
            closed = _time(row['close_time'])
            if (closed != _time(candle['close_time']) or row['open_time'] != candle['open_time'] or
                    closed > cutoff or (last_close is not None and closed <= last_close)):
                raise ValueError('Mismatched candle results')
            last_close = closed
            factors = row['factors']
            if len(factors) != 4 or {f['factor_id'] for f in factors} != set(definitions):
                raise ValueError('Missing factors')
            for factor in factors:
                outcome = factor['outcome']
                bull, bear = _points(factor['bullish_points']), _points(factor['bearish_points'])
                maximum = _points(definitions[factor['factor_id']]['points'])
                if outcome not in ('bullish', 'bearish', 'neutral', 'unavailable') or bull + bear > maximum:
                    raise ValueError('Invalid factor outcome')
                if (outcome == 'bullish' and not (bull > 0 and bear == 0) or
                        outcome == 'bearish' and not (bear > 0 and bull == 0) or
                        outcome in ('neutral', 'unavailable') and (bull != 0 or bear != 0)):
                    raise ValueError('Inconsistent factor points')
                if any(_time(item['close_time']) > closed for item in factor['evidence']):
                    raise ValueError('Future factor evidence')
        if last_close != through or not snapshot['source_candles']:
            raise ValueError('Inconsistent data-through time')
        summary = evaluation['summary']
        if summary['method'] not in ('session_average', 'session_to_date', 'final_candle'):
            raise ValueError('Unsupported summary method')
        selected = rows[-1:] if summary['method'] == 'final_candle' else rows
        missing = any(f['outcome'] == 'unavailable' for row in selected for f in row['factors'])
        expected = {side: sum(f[side + '_points'] for row in selected for f in row['factors']) / len(selected)
                    for side in ('bullish', 'bearish')}
        if missing:
            if summary['direction'] != 'insufficient_data':
                raise ValueError('Missing inputs presented as complete')
        else:
            for side in expected:
                if abs(_points(summary[side + '_points']) - expected[side]) > 1e-9:
                    raise ValueError('Inconsistent saved summary')
            bull, bear = expected['bullish'], expected['bearish']
            expected_direction = 'bullish' if bull > bear else 'bearish' if bear > bull else 'neutral' if bull == 0 else 'mixed'
            if summary['direction'] != expected_direction:
                raise ValueError('Inconsistent direction')
        return entered, cutoff, through
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, OverflowError):
        raise TradeInputError('The four-factor evidence is incomplete, inconsistent, or contains data after its cutoff. The original trade is unchanged.') from None


def build_analysis(entry, snapshot, source, evidence_hash, timing):
    entered, cutoff, through = _validate(entry, snapshot)
    if source not in ('saved_setup', 'entry_time') or (source == 'entry_time' and (cutoff != entered or timing != 'retrospective')):
        raise TradeInputError('Reconstructed evidence must use the exact recorded entry cutoff and be labeled retrospective.')
    direction = entry['direction']
    support_key, conflict_key = ('bullish_points', 'bearish_points') if direction == 'long' else ('bearish_points', 'bullish_points')
    evaluation = snapshot['rule_evaluation']
    rows, definition = evaluation['candles'], evaluation['rule_set']
    factors = []
    for factor_def in definition['factors']:
        observed = []
        for row in rows:
            factor = next(f for f in row['factors'] if f['factor_id'] == factor_def['id'])
            status = relation(factor['outcome'], direction)
            observed.append({'candle_id': row['candle_id'], 'open_time': row['open_time'], 'close_time': row['close_time'],
                'relation': status, 'supporting_points': None if status == 'unavailable' else factor[support_key],
                'conflicting_points': None if status == 'unavailable' else factor[conflict_key], 'result': deepcopy(factor)})
        counts = {key: sum(item['relation'] == key for item in observed) for key in RELATIONS}
        factors.append({'id': factor_def['id'], 'name': factor_def['name'], 'max_points': factor_def['points'],
            'latest': observed[-1], 'candles': observed, 'counts': counts,
            'average_supporting_points': None if counts['unavailable'] else sum(item['supporting_points'] for item in observed) / len(observed),
            'average_conflicting_points': None if counts['unavailable'] else sum(item['conflicting_points'] for item in observed) / len(observed)})
    saved_summary = deepcopy(evaluation['summary'])
    unavailable = saved_summary['direction'] == 'insufficient_data'
    summary = {'method': saved_summary['method'], 'relation': relation(saved_summary['direction'], direction),
        'supporting_points': None if unavailable else saved_summary[support_key],
        'conflicting_points': None if unavailable else saved_summary[conflict_key],
        'max_points': saved_summary['max_points'], 'saved_result': saved_summary}
    scheduled = latest_scheduled_close(entered)
    return {'version': VERSION, 'source': source, 'entry_evidence_hash': evidence_hash, 'trade_direction': direction,
        'rule_set': deepcopy(definition), 'summary': summary, 'factors': factors,
        'coverage': {'entry_at': entry['entry_at'], 'cutoff_at': snapshot['cutoff_at'], 'data_through': snapshot['data_through'],
            'cutoff_age_seconds': (entered - cutoff).total_seconds(), 'last_close_age_seconds': (entered - through).total_seconds(),
            'latest_scheduled_close': scheduled.isoformat(), 'covers_latest_scheduled_close': through == scheduled,
            'timing': timing, 'market_state': snapshot['market_state'], 'journal_date': snapshot['market_data']['journal_date'],
            'earlier_session': snapshot['market_data']['journal_date'] != today.session_context(entered)[0].isoformat(),
            'candle_count': len(rows), 'expected_candle_count': 6, 'session_complete': snapshot['market_data']['session']['complete']},
        # A reconstruction is a separate immutable record, never a replacement of the entry copy.
        'reconstructed_snapshot': deepcopy(snapshot) if source == 'entry_time' else None}


def reconstruct_entry(entry):
    """Only the recorded direction and cutoff are accepted; no exit, outcome, or later notes."""
    return build_setup_snapshot(SetupInput(request_id=uuid4(), mode='historical', as_of=_time(entry['entry_at']),
                                         direction=entry['direction'], include_quote=False))
