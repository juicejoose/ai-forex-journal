import { chartTime } from './marketChartData.js'

export function setupChartSnapshot(snapshot, extend = false) {
  const market = snapshot?.market_data
  if (!market || (!extend && !snapshot.zones?.some(zone => zone.history?.origin_at))) return market
  const first = chartTime(market.candles?.[0]?.open_time)
  const cutoff = chartTime(snapshot.cutoff_at)
  const detailed = new Map((market.chart_context?.candles ?? []).map(candle => [candle.open_time, candle]))
  const history = (snapshot.source_candles ?? []).filter(candle => {
    const closed = chartTime(candle.close_time)
    return closed !== null && closed <= first && closed <= cutoff
  }).map(candle => detailed.get(candle.open_time) ?? candle)
  return { ...market, chart_context: { purpose: 'display_only', candles: history, extended_zone_history: true } }
}

export function zoneChartMarkers(zone, rows, showCloses = false) {
  const candles = new Map(rows.map(row => [row.time, row.candle]))
  const markers = (zone?.history?.events ?? []).filter(event => {
    const time = chartTime(event.open_time)
    const candle = candles.get(time)
    return candle && chartTime(candle.close_time) === chartTime(event.close_time) &&
      (event.kind === 'visit_start' || showCloses && event.kind === 'close_position')
  }).map(event => ({
    time: chartTime(event.open_time), position: 'belowBar',
    shape: event.kind === 'visit_start' ? 'circle' : 'square',
    color: event.kind === 'visit_start' ? '#d8a64b' : event.position === 'above' ? '#598cec' : event.position === 'below' ? '#d65e70' : '#84949d',
    text: event.kind === 'visit_start' ? `V${event.visit_number}${event.boundary_start ? '*' : ''}` : event.position,
  }))
  const start = chartTime(zone?.history?.coverage_start)
  if (start !== null && candles.has(start)) markers.push({
    time: start, position: 'aboveBar', shape: 'square', color: '#d8a64b', text: 'Zone history',
  })
  return markers.sort((a, b) => a.time - b.time)
}

export function zoneLineData(zone, rows, boundary) {
  const start = chartTime(zone?.history?.coverage_start)
  const end = chartTime(zone?.history?.coverage_end)
  const price = Number(zone?.[boundary])
  if (start === null || end === null || !Number.isFinite(price) || price <= 0) return []
  const eligible = rows.filter(row => row.time >= start && chartTime(row.candle.close_time) <= end)
  if (!eligible.length) return []
  return [...new Set([eligible[0].time, eligible.at(-1).time])].map(time => ({ time, value: price }))
}

export function zoneEventLabel(event) {
  if (event.kind === 'visit_start') return `Visit V${event.visit_number}${event.boundary_start ? ' · boundary group' : ''}`
  const prefix = event.after_gap ? 'First close after gap' : event.previous_position ? 'Close changed to' : 'First observed close'
  return `${prefix} ${event.position}`
}
