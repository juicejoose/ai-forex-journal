"""Deterministic price-distance outcomes, independent of self-reported discipline."""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from copy import deepcopy

VERSION = 'trade_outcome_v1'
PIP = Decimal('0.0001')
ASSUMPTIONS = ('Results use your manually entered fill prices. Pips and R describe price movement only; '
    'separate commissions, financing and fees are not deducted. No position size or monetary P&L is calculated. '
    'R uses the original entry-to-stop distance, not a later stop change. Outcome does not grade discipline.')


class TradeInputError(ValueError):
    pass


def utc(value):
    return value.astimezone(timezone.utc).isoformat()


def past_time(value, label, now):
    if value > now:
        raise TradeInputError(f'{label} cannot be in the future.')


def entry_context(entry, source, saved_at):
    if source is None:
        return {'schema_version': 1, 'kind': 'manual', 'timing': 'self_reported',
                'retained_at': saved_at.isoformat(), 'setup': None}
    snap = source['snapshot']
    if snap['instrument'] != entry.instrument or snap['timeframe'] != entry.timeframe:
        raise TradeInputError('The linked setup must use EUR/USD and H4.')
    cutoff = datetime.fromisoformat(snap['cutoff_at'])
    if cutoff > entry.entry_at:
        raise TradeInputError('The setup cutoff is after your entry. Choose an earlier setup or record the trade without a linked setup.')
    # Reject future-dated evidence, even if a saved cutoff was mislabeled.
    rows = [*snap.get('source_candles', []), *snap.get('market_data', {}).get('candles', []),
            *snap.get('market_data', {}).get('chart_context', {}).get('candles', [])]
    if any(datetime.fromisoformat(row['close_time']) > cutoff for row in rows):
        raise TradeInputError('The saved setup contains candles after its cutoff and cannot be attached.')
    if datetime.fromisoformat(snap['data_through']) > cutoff or datetime.fromisoformat(snap['reference_price']['time']) > cutoff:
        raise TradeInputError('The saved setup contains a reference after its cutoff and cannot be attached.')
    stamps = [source['created_at'], snap['captured_at'], snap.get('finalized_at', snap['captured_at'])]
    pre_entry = snap['mode'] == 'live' and all(datetime.fromisoformat(stamp) <= entry.entry_at for stamp in stamps)
    return {'schema_version': 1, 'kind': 'linked_setup', 'retained_at': saved_at.isoformat(),
            'timing': 'captured_before_entry' if pre_entry else 'retrospective',
            # Full server-owned copy, including the applicable strategy version, with no live lookup on reopen.
            'setup': deepcopy(source)}


def trade_outcome(entry, exit_values):
    with localcontext() as context:
        context.prec = 28
        opened, closed = Decimal(entry['entry_price']), Decimal(exit_values['exit_price'])
        delta = (closed-opened) * (1 if entry['direction'] == 'long' else -1)
        pips = delta/PIP
        stop = entry.get('initial_stop_loss')
        risk = abs(opened-Decimal(stop))/PIP if stop is not None else None
        multiple = pips/risk if risk is not None else None
        ratio_display = None if multiple is None else (
            ('+' if multiple > 0 else '−')+'<0.01' if 0 < abs(multiple) < Decimal('0.01') else f'{multiple:+.2f}')
    return {'version': VERSION, 'pips': f'{pips:+.1f}' if pips else '0.0',
            'initial_risk_pips': f'{risk:.1f}' if risk is not None else None,
            'r_multiple': str(multiple) if multiple is not None else None, 'r_display': ratio_display,
            'outcome': 'positive' if delta > 0 else 'negative' if delta < 0 else 'flat',
            'assumptions': ASSUMPTIONS}
