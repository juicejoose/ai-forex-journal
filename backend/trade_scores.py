"""Fixed entry alignment and equal-weight scores for closes occurring during a trade."""
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

import market_data as md
import strategy_rules as rules
import trade_database as db
import trade_timeline as timeline
from setup_market import _version_hash
from trade_analysis import _validate, relation
from trade_models import TradeAnalysisInput

VERSION = 'trade_scores_v1'


def directional_summary(summary, direction):
    result = deepcopy(summary)
    available = result['direction'] != 'insufficient_data'
    support, conflict = ('bullish','bearish') if direction == 'long' else ('bearish','bullish')
    result.update(relation=relation(result['direction'], direction),
                  supporting_points=result[support+'_points'] if available else None,
                  conflicting_points=result[conflict+'_points'] if available else None,
                  entry_alignment_percent=result[support+'_alignment_percent'] if available else None)
    if not available:
        for key in ('bullish_points','bearish_points','net_score','bullish_alignment_percent','bearish_alignment_percent'):
            result[key] = None
    return result


def entry_score(record, saved):
    analysis = saved['analysis']
    snapshot = analysis['reconstructed_snapshot']
    entered, cutoff, _ = _validate(record['entry'], snapshot)
    if cutoff != entered or saved['source'] != 'entry_time':
        raise db.TradeConflict('The entry score needs evidence reconstructed at the exact recorded entry time.')
    row = deepcopy(snapshot['rule_evaluation']['candles'][-1])
    summary = rules._score(row['factors'], analysis['rule_set']['max_points'])
    summary.update(method='latest_completed_at_entry',candle_count=1)
    return {'summary':directional_summary(summary, record['entry']['direction']), 'candle':row,
            'data_through':row['close_time'], 'cutoff_at':snapshot['cutoff_at'],
            'latest_scheduled_close':analysis['coverage']['latest_scheduled_close'],
            'covers_latest_scheduled_close':analysis['coverage']['covers_latest_scheduled_close'],
            'timing':'retrospective', 'saved_at':saved['created_at']}


def build_scores(record, saved, now):
    entered = datetime.fromisoformat(record['entry']['entry_at']).astimezone(md.UTC)
    exited = datetime.fromisoformat(record['exit']['exit_at']).astimezone(md.UTC) if record['exit'] else None
    end = exited or now
    if not entered <= end <= now:
        raise db.TradeConflict('Trade scoring requires entry and exit times in the past, in time order.')
    definition = deepcopy(saved['analysis']['rule_set'])
    current = rules.rule_set_definition(definition['id'])
    if any(definition.get(key) != current.get(key) for key in ('version','revision','factors','max_points')):
        raise db.TradeConflict('The saved entry strategy revision is not supported for a new full-trade calculation. Its original entry evidence is unchanged.')
    initial = entry_score(record, saved)
    start = timeline.bar_start(entered)
    expected = [at for at in timeline.scheduled_bars(start,end) if entered < at + md.CANDLE_DURATION <= end]
    if len(expected) > timeline.MAX_CANDLES:
        raise md.MarketDataError(f'Trade scores support up to {timeline.MAX_CANDLES:,} completed H4 candles.',422)
    rows, source = [], []
    if expected:
        warmup, selected = timeline._history(start,end)
        selected = [c for c in selected if c.complete and entered < c.close_time <= end]
        if [c.open_time for c in selected] != expected:
            raise md.MarketDataError('A candle that should have closed during this trade is missing. Retry when the provider data is available; missing candles are not scored as zero.',503)
        series = warmup[-md.WARMUP_COUNT:] + selected
        indicators = md._indicator_rows(series,md.WARMUP_COUNT-2)
        catalog = {f'C{i+1}':c for i,c in enumerate(indicators[2:])}
        rows = rules.score_candles(indicators[2:],indicators[0],indicators[1],definition,catalog)
        source = [{'open_time':c.open_time.isoformat(),'close_time':c.close_time.isoformat(),
                   'open':c.open,'high':c.high,'low':c.low,'close':c.close,'price_updates':c.price_updates} for c in series]
    if rows:
        summary = rules._session_average(rows,definition['max_points'])
        summary.update(method='full_trade_average' if exited else 'trade_to_date_average')
        summary = directional_summary(summary,record['entry']['direction'])
    else:
        summary = {'method':'full_trade_average' if exited else 'trade_to_date_average',
                   'direction':'insufficient_data','relation':'unavailable','candle_count':0,
                   'max_points':definition['max_points'],'bullish_points':None,'bearish_points':None,
                   'net_score':None,'supporting_points':None,'conflicting_points':None,
                   'bullish_alignment_percent':None,'bearish_alignment_percent':None,'entry_alignment_percent':None,
                   'complete':False}
    return {'schema_version':1,'version':VERSION,'trade_id':record['id'],'trade_direction':record['entry']['direction'],
            'status':record['status'],'entry_evidence_hash':record['evidence_hash'],
            'entry_analysis_id':saved['id'],'entry_analysis_hash':saved['analysis_hash'],
            'entry_at':entered.isoformat(),'exit_at':exited.isoformat() if exited else None,
            'as_of':now.isoformat(),'rule_set':definition,'calculation_version':_version_hash(),
            'entry_score':initial,
            'full_trade':{'summary':summary,'candles':rows,'cutoff_at':end.isoformat(),
                          'data_through':rows[-1]['close_time'] if rows else None,
                          'selection':'entry_at < candle.close_time <= exit_at_or_now',
                          'entry_candle_includes_pre_entry_prices':bool(rows and datetime.fromisoformat(rows[0]['open_time']) < entered),
                          'exit_candle_excluded':bool(exited and timeline.trading_bar(timeline.bar_start(exited)) and exited != timeline.bar_start(exited)),
                          'source_candles':source,'warmup_count':md.WARMUP_COUNT if source else 0}}


def calculate_scores(identifier):
    """First entry reconstruction is fixed; closed full-trade scores are saved once."""
    for _ in range(2):
        record = db.fetch_trade(identifier)
        saved = next((a for a in record['strategy_analyses'] if a['source']=='entry_time'),None)
        if saved is None:
            record = db.analyze_trade(identifier,TradeAnalysisInput(request_id=uuid4(),source='entry_time'))
            saved = next(a for a in record['strategy_analyses'] if a['source']=='entry_time')
        cached = db.fetch_score_snapshot(identifier,record,saved)
        if cached is not None:
            return {**cached,'entry_analysis':saved}
        now = datetime.now(md.UTC)
        try:
            value = build_scores(record,saved,now)
        except md.MarketDataError as exc:
            latest = db.fetch_trade(identifier)
            if latest['exit'] != record['exit']: continue
            # Keep a valid, fixed entry score visible if the separate trade-period
            # data request fails. Never persist an incomplete final calculation.
            return {'schema_version':1,'version':VERSION,'trade_id':record['id'],
                    'trade_direction':record['entry']['direction'],'status':record['status'],
                    'entry_at':record['entry']['entry_at'],'exit_at':record['exit']['exit_at'] if record['exit'] else None,
                    'as_of':now.isoformat(),'rule_set':saved['analysis']['rule_set'],
                    'entry_analysis_id':saved['id'],'entry_analysis':saved,
                    'entry_score':entry_score(record,saved),'saved_at':None,
                    'full_trade':{'error':str(exc),'summary':None,'candles':[]}}
        # Provider calls happen outside the write transaction. Recheck exit/deletion
        # before returning open scores or committing a fixed closed-trade result.
        result = db.finish_scores(identifier,record,saved,value)
        if result is not None:
            return {**result,'entry_analysis':saved}
    raise db.TradeConflict('The trade changed during calculation. Refresh its scores to use the saved exit.')
