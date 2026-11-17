import { chartTime } from './marketChartData.js'

export const retestLabels = {
  pending: 'Awaiting retest', held: 'Retest held · rule met', invalidated: 'Retest attempt invalidated',
  expired: 'Window ended without hold', insufficient_data: 'Interrupted by missing data',
}

export function patternLabel(event) {
  const direction = event.direction === 'bullish' ? 'Bullish' : 'Bearish'
  if (event.kind === 'retest_invalidated') return `${direction} breakout · retest attempt invalidated`
  const label = { rejection: 'rejection', breakout: 'breakout', retest_held: 'retest held' }[event.kind]
  return label ? `${direction} ${label} · rule met` : 'Pattern observation'
}

export function patternMarkers(patterns, rows) {
  const candles = new Map(rows.map(row => [row.time, row.candle]))
  return (patterns?.events ?? []).flatMap(event => {
    const time = chartTime(event.open_time)
    const candle = candles.get(time)
    if (!candle || chartTime(candle.close_time) !== chartTime(event.close_time)) return []
    const text = { rejection: 'REJ', breakout: 'BRK', retest_held: 'RT', retest_invalidated: 'RT ended' }[event.kind]
    if (!text) return []
    const failed = event.kind === 'retest_invalidated'
    const bullish = event.direction === 'bullish'
    return [{ time, position: bullish ? 'belowBar' : 'aboveBar',
      shape: failed ? 'square' : bullish ? 'arrowUp' : 'arrowDown',
      color: failed ? '#a89979' : bullish ? '#249c79' : '#d65e70', text }]
  })
}
