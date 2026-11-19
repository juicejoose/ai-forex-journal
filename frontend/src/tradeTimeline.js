import { chartTime } from './marketChartData.js'

export function validTradeTimeline(view, id, exitAt) {
  return view?.schema_version === 1 && view.analysis_kind === 'trade_timeline' && view.trade_id === id &&
    view.status === (exitAt ? 'closed' : 'open') && view.exit_at === (exitAt ?? null) &&
    chartTime(view.as_of) !== null && chartTime(view.entry_at) !== null &&
    Array.isArray(view.candles) && Array.isArray(view.chart_context?.candles) &&
    Array.isArray(view.events) && view.events.length === (exitAt ? 2 : 1) &&
    view.events.every(event => ['entry', 'exit'].includes(event.kind) && chartTime(event.at) !== null && Number(event.price) > 0) &&
    Number.isInteger(view.coverage?.missing_candle_count)
}

export function tradeTimelineMarkers(view, rows) {
  const times = new Set(rows.map(row => row.time))
  const markers = (view?.events ?? []).filter(event => times.has(chartTime(event.candle_open_time))).map(event => ({
    time: chartTime(event.candle_open_time), position: event.kind === 'entry' ? 'belowBar' : 'aboveBar',
    shape: event.kind === 'entry' ? 'arrowUp' : 'arrowDown',
    color: event.kind === 'entry' ? '#598cec' : '#d89a37',
    text: `${event.kind === 'entry' ? 'Entry' : 'Exit'} ${Number(event.price).toFixed(5)}`,
  }))
  const forming = rows.find(row => row.candle.complete === false)
  if (forming) markers.push({ time: forming.time, position: 'aboveBar', shape: 'circle', color: '#84949d', text: 'Forming' })
  return markers.sort((a, b) => a.time - b.time)
}

export function timelineCandleState(candle) {
  return [candle.timeline_phase === 'after_exit' ? 'After exit' : candle.timeline_phase === 'after_review' ? 'After review' : null, candle.complete === false ? 'Forming · provisional' : 'Completed',
    candle.contains_post_exit_prices ? 'Includes prices after exit' : null].filter(Boolean).join(' · ')
}


export function timelinePriceResult(view) {
  const result=view?.price_result, row=view?.candles?.at(-1)
  const at=chartTime(result?.reference_at), entered=chartTime(view?.entry_at), asOf=chartTime(view?.as_of)
  if (view?.status!=='open' || !row || !result || result.version!=='trade_live_pips_v1' || result.price_basis!=='midpoint' ||
      !['forming','completed'].includes(result.reference_kind) || typeof result.pips!=='string' || !/^[+-]?\d+\.\d$/.test(result.pips) ||
      !['positive','negative','flat'].includes(result.outcome) || !Number.isFinite(Number(result.reference_price)) || Number(result.reference_price)<=0 ||
      Number(result.reference_price)!==row.close || at===null || entered===null || asOf===null || at<entered || at>asOf ||
      (result.reference_kind==='forming' ? row.complete!==false || at!==asOf : row.complete!==true || at!==chartTime(row.close_time))) return null
  return result
}
