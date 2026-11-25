"""Capture an open-trade review at one cutoff, without changing saved entry evidence."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
import market_data as md
import trade_database as trades
import trade_scores as scores
import setup_market as market
from setup_models import SetupZone
from trade_models import TradeAnalysisInput
from trade_calculations import trade_outcome
from trade_analysis import latest_scheduled_close
from zone_history import analyze_zone_history, VERSION as HISTORY_VERSION
from zone_patterns import analyze_zone_patterns, VERSION as PATTERN_VERSION

VERSION='trade_coach_evidence_v1'


def build_snapshot(identifier,request):
    record=trades.fetch_trade(identifier)
    if record['status']!='open': raise trades.TradeConflict('The coach reviews open trades only.')
    saved=next((a for a in record['strategy_analyses'] if a['source']=='entry_time'),None)
    if saved is None:
        record=trades.analyze_trade(identifier,TradeAnalysisInput(request_id=uuid4(),source='entry_time'))
        saved=next(a for a in record['strategy_analyses'] if a['source']=='entry_time')
    raw_quote=None
    try: raw_quote=market.fetch_quote()
    except md.MarketDataError: pass
    cutoff=datetime.now(md.UTC)
    quote=market.validated_quote(raw_quote,cutoff) if raw_quote is not None else {'status':'unavailable','reason':'A fresh practice quote was unavailable.'}
    calculated=scores.build_scores(record,saved,cutoff)
    rows=calculated['full_trade']['candles']
    source=calculated['full_trade'].pop('source_candles') or saved['analysis']['reconstructed_snapshot']['source_candles']
    if any(datetime.fromisoformat(c['close_time'])>cutoff for c in source):
        raise md.MarketDataError('Coach evidence contains a candle beyond its cutoff.',502)
    latest=deepcopy(rows[-1] if rows else calculated['entry_score']['candle'])
    last=source[-1]
    reference=({'basis':'quote_midpoint','value':quote['midpoint'],'time':quote['time']} if quote['status']=='available' else
               {'basis':'last_completed_close','value':last['close'],'time':last['close_time']})
    if request.zones is None:
        original=record['context'].get('setup')
        zone_inputs=[SetupZone(**{k:z[k] for k in SetupZone.model_fields if k in z}) for z in original['snapshot']['zones']] if original else []
        zone_source='saved_entry_setup'
    else: zone_inputs=request.zones;zone_source='review_annotations'
    if any((z.origin_at and z.origin_at>cutoff) or (z.observed_at and z.observed_at>cutoff) for z in zone_inputs):
        raise md.MarketDataError('Zone observation and origin times cannot be after the review cutoff.',422)
    zones=market.zone_evidence(zone_inputs,reference,last)
    for zone in zones:
        zone['history']=analyze_zone_history(zone,source,cutoff)
        zone['patterns']=analyze_zone_patterns(zone,source,cutoff,zone['history'])
    entry=record['entry'];sign=1 if entry['direction']=='long' else -1
    before=calculated['entry_score']['summary'];after=scores.directional_summary(latest,entry['direction'])
    delta=None if before['net_score'] is None or after['net_score'] is None else sign*(after['net_score']-before['net_score'])
    changes=[]
    for old,new in zip(calculated['entry_score']['candle']['factors'],latest['factors']):
        if old['factor_id'] != new['factor_id']: raise trades.TradeConflict('Entry and current factors use different definitions.')
        changes.append({'factor_id':new['factor_id'],'name':new['name'],'entry':old,'latest':new})
    unrealized=trade_outcome(entry,{'exit_price':str(reference['value'])})
    levels={}
    for name in ('initial_stop_loss','initial_take_profit'):
        value=entry.get(name)
        levels[name]={'price':value,'distance_from_reference_pips':float(abs(Decimal(value)-Decimal(str(reference['value'])))/Decimal('0.0001')) if value else None}
    return {'schema_version':1,'version':VERSION,'trade_id':record['id'],'entry_evidence_hash':record['evidence_hash'],
            'trade_revision':record['revision'],'trade_edited_at':record.get('edited_at'),'trade':deepcopy(entry),'entry_logged_at':record['created_at'],'cutoff_at':cutoff.isoformat(),
            'captured_at':datetime.now(md.UTC).isoformat(),'data_through':latest['close_time'],
            'latest_scheduled_close':latest_scheduled_close(cutoff).isoformat(),
            'covers_latest_close':datetime.fromisoformat(latest['close_time'])==latest_scheduled_close(cutoff),
            'rule_set':calculated['rule_set'],'calculation_version':calculated['calculation_version'],
            'entry_analysis_id':saved['id'],'entry_analysis_hash':saved['analysis_hash'],
            'entry_score':calculated['entry_score'],'latest':latest,'latest_summary':{k:v for k,v in after.items() if k!='factors'},
            'recent_candles':deepcopy(rows[-6:]),'full_trade':calculated['full_trade'],
            'source_candles':deepcopy(source),'quote':quote,'reference_price':reference,
            'unrealized':{'pips':unrealized['pips'],'outcome':unrealized['outcome'],'basis':reference['basis']},
            'initial_levels':levels,'directional_net_change':delta,'factor_changes':changes,
            'zones':zones,'zone_source':zone_source,'zone_history_version':HISTORY_VERSION,'zone_pattern_version':PATTERN_VERSION,
            'review_observations':request.observations,'annotation_provenance':'user_input_at_review_not_entry'}
