import { chartTime } from './marketChartData.js'

export function validTradeScores(data,record) {
  const cutoff=chartTime(data?.full_trade?.cutoff_at), entered=chartTime(record.entry.entry_at)
  const exited=chartTime(record.exit?.exit_at), rows=data?.full_trade?.candles
  const entry=data?.entry_score, through=chartTime(entry?.data_through), asOf=chartTime(data?.as_of)
  const periodValid = data?.full_trade?.error ? typeof data.full_trade.error==='string' && data.full_trade.summary===null && Array.isArray(rows) && rows.length===0 :
    Array.isArray(rows) && rows.length === data?.full_trade?.summary?.candle_count &&
    data.full_trade.summary.method === (exited===null ? 'trade_to_date_average' : 'full_trade_average') &&
    cutoff !== null && cutoff >= entered && cutoff <= asOf && (exited === null || cutoff === exited) &&
    rows.every((row,i)=>chartTime(row.open_time)!==null && chartTime(row.open_time)<chartTime(row.close_time) &&
      chartTime(row.close_time)>entered && chartTime(row.close_time)<=cutoff &&
      (i===0 || chartTime(row.open_time)>=chartTime(rows[i-1].close_time)))
  return periodValid && data?.schema_version === 1 && data.version === 'trade_scores_v1' && data.trade_id === record.id &&
    (data.trade_revision ?? 0) === (record.revision ?? 0) &&
    data.status === record.status && data.trade_direction === record.entry.direction &&
    chartTime(data.entry_at) === entered && chartTime(data.exit_at) === exited &&
    entered !== null && through !== null && asOf !== null && asOf >= entered &&
    chartTime(entry?.cutoff_at) === entered && through <= entered &&
    chartTime(entry?.candle?.close_time)===through && Array.isArray(entry?.candle?.factors) && entry.candle.factors.length===4 &&
    entry?.summary?.method === 'latest_completed_at_entry' && Number.isFinite(data.rule_set?.max_points) &&
    data.entry_analysis?.source === 'entry_time' && data.entry_analysis.id === data.entry_analysis_id &&
    !!data.entry_analysis.analysis
}

export const scoreNumber = value => Number.isFinite(value) ? value.toFixed(2) : 'Unavailable'
export const signedScore = value => Number.isFinite(value) ? `${value>0 ? '+' : ''}${value.toFixed(2)}` : 'Unavailable'
export const scoreDirection = value => ({bullish:'Bullish',bearish:'Bearish',mixed:'Mixed',neutral:'Neutral',insufficient_data:'Unavailable'}[value] ?? 'Unavailable')

export function sessionScoreReadout(view) {
  const count = view.session.candle_count
  const summary = view.rule_evaluation?.summary
  if (count === 0) return {headline:'Awaiting first H4 close', coverage:'0 / 6 candles closed'}
  const coverage = count + ' / 6 candles closed'
  if (!Number.isFinite(summary?.net_score)) return {headline:'Score unavailable', coverage, detail:'Indicator data incomplete'}
  return {
    headline:'Avg. net ' + signedScore(summary.net_score),
    coverage:scoreDirection(summary.direction) + ' · ' + coverage,
    detail:'Bull ' + scoreNumber(summary.bullish_points) + ' · Bear ' + scoreNumber(summary.bearish_points) + ' · / ' + summary.max_points,
  }
}
