import { chartTime, validCandle } from './marketChartData.js'

export const CONTEXT_CANDLES = 160

export function chartBoundaries(snapshot, includeAfter) {
  const rows = snapshot?.candles ?? []
  return { before:rows[0]?.open_time ?? null, after:includeAfter ? rows.at(-1)?.close_time ?? null : null }
}

export function validChartContext(data, before, after) {
  const start = chartTime(before), end = chartTime(after), retrieved = chartTime(data?.retrieved_at)
  const ordered = rows => rows.every((row,index) => validCandle(row) &&
    (index === 0 || chartTime(row.open_time) >= chartTime(rows[index-1].close_time)))
  return start !== null && retrieved !== null && data?.schema_version === 1 &&
    data.purpose === 'display_only' && data.instrument === 'EUR_USD' && data.timeframe === 'H4' &&
    data.target_count === CONTEXT_CANDLES && chartTime(data.before_at) === start && chartTime(data.after_at) === end &&
    Array.isArray(data.preceding) && data.preceding.length <= CONTEXT_CANDLES && ordered(data.preceding) &&
    Array.isArray(data.following) && data.following.length <= CONTEXT_CANDLES && ordered(data.following) &&
    data.preceding.every(row => row.complete === true && chartTime(row.close_time) <= start) &&
    data.following.every(row => end !== null && typeof row.complete === 'boolean' &&
      chartTime(row.open_time) >= end && chartTime(row.open_time) < retrieved &&
      (!row.complete || chartTime(row.close_time) <= retrieved))
}

export function withChartContext(snapshot, context) {
  if (!snapshot) return snapshot
  const saved = snapshot.chart_context?.candles ?? snapshot.previous_candles ?? (snapshot.previous_candle ? [snapshot.previous_candle] : [])
  // Keep saved price/indicator pairs together. Raw legacy context without
  // indicators uses the newly calculated display row, never mixed price sources.
  const originals = new Map(saved.map(row => [chartTime(row.open_time), row]))
  const history = (context?.preceding ?? saved).slice(-CONTEXT_CANDLES).map(row => {
    const original = originals.get(chartTime(row.open_time))
    return original?.indicators && original.close_time === row.close_time ? original : row
  })
  return {...snapshot,
    chart_context:{purpose:'display_only',candles:history,reconstructed_context:Boolean(context)},
    chart_followup:{purpose:'display_only',candles:context?.following ?? []},
  }
}
