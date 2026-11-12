const dateFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric',
})
const clockFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit',
})
const fullFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
})

export const chartTime = value => {
  const millis = typeof value === 'string' ? Date.parse(value) : NaN
  return Number.isFinite(millis) ? millis / 1000 : null
}
export const chartStamp = time => fullFormat.format(new Date(time * 1000))
export function chartTick(time, tickType) {
  const date = new Date(time * 1000)
  return tickType < 3 ? dateFormat.format(date).replace(/, \d{4}$/, '') : clockFormat.format(date)
}
export function candleLabel(candle) {
  return `${chartStamp(chartTime(candle.open_time))} – ${clockFormat.format(new Date(candle.close_time))}`
}
export const chartNumber = (value, digits = 5) => Number.isFinite(value) ? value.toFixed(digits) : 'Unavailable'

function validCandle(candle) {
  return chartTime(candle?.open_time) !== null && chartTime(candle?.close_time) > chartTime(candle?.open_time) &&
    ['open', 'high', 'low', 'close'].every(key => Number.isFinite(candle[key]) && candle[key] > 0) &&
    candle.low <= Math.min(candle.open, candle.close) && candle.high >= Math.max(candle.open, candle.close)
}

export function buildChartData(snapshot, evaluation) {
  const candles = Array.isArray(snapshot?.candles) ? snapshot.candles.filter(validCandle) : []
  if (!candles.length) return { rows: [], startIndex: 0, hasRsiMa: false, guides: [] }
  const first = Math.min(...candles.map(candle => chartTime(candle.open_time)))
  const storedHistory = snapshot.chart_context?.candles
  const history = Array.isArray(storedHistory) ? storedHistory
    : Array.isArray(snapshot.previous_candles) ? snapshot.previous_candles
      : snapshot.previous_candle ? [snapshot.previous_candle] : []
  const scores = new Map((evaluation?.candles ?? []).map(score => [chartTime(score.open_time), score]))
  const byTime = new Map()
  for (const candle of history) {
    if (validCandle(candle) && chartTime(candle.close_time) <= first) {
      byTime.set(chartTime(candle.open_time), { time: chartTime(candle.open_time), candle, analyzed: false })
    }
  }
  for (const candle of candles) {
    const time = chartTime(candle.open_time)
    const score = scores.get(time)
    byTime.set(time, { time, candle, analyzed: true,
      score: chartTime(score?.close_time) === chartTime(candle.close_time) ? score : null })
  }
  const rows = [...byTime.values()].sort((a, b) => a.time - b.time)
  const factor = evaluation?.rule_set?.factors?.find(item => item.id === 'rsi_extreme')
  const guides = factor ? [
    { value: factor.trend?.lower_threshold ?? (evaluation.rule_set.version === 1 ? 30 : 40), label: 'Oversold' },
    { value: factor.trend?.upper_threshold ?? (evaluation.rule_set.version === 1 ? 70 : 60), label: 'Overbought' },
  ] : []
  if (factor?.trend_reduction) {
    guides.push({ value: factor.trend_reduction.bearish_max, label: 'Near oversold', proximity: true },
      { value: factor.trend_reduction.bullish_min, label: 'Near overbought', proximity: true })
  }
  return { rows, startIndex: rows.findIndex(row => row.analyzed),
    hasRsiMa: rows.some(row => Number.isFinite(row.candle.indicators?.rsi14_sma14)),
    rsiSource: factor?.source === 'rsi14_sma14' ? 'RSI MA' : 'RSI14', guides }
}

// Missing readings are whitespace, never zero or connected across a missing bar.
export function indicatorSeries(rows, read) {
  return rows.map(row => {
    const value = read(row.candle.indicators ?? {})
    return Number.isFinite(value) ? { time: row.time, value } : { time: row.time }
  })
}
