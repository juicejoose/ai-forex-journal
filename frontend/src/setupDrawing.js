import { chartTime } from './marketChartData.js'

export function localInputTime(iso) {
  const date = new Date(iso)
  if (!Number.isFinite(date.getTime())) return ''
  const pad = value => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function drawingPoint(event, rows, toPrice) {
  if (event.paneIndex !== 0 || !event.point || !Number.isFinite(event.time)) return null
  const row = rows.find(item => item.time === event.time)
  const price = toPrice(event.point.y)
  if (!row || !Number.isFinite(price) || price <= 0 || price > 100) return null
  return { price: Number(price.toFixed(5)), candle: row.candle }
}

export function drawnZone(kind, first, second, zones, key) {
  if (!['support', 'resistance'].includes(kind) || zones.length >= 8 ||
      ![first, second].every(value => Number.isFinite(value) && value > 0 && value <= 100)) return null
  const prefix = kind === 'support' ? 'Support' : 'Resistance'
  const labels = new Set(zones.map(zone => zone.label.trim().toLowerCase()))
  let number = 1
  while (labels.has(`${prefix} ${number}`.toLowerCase())) number++
  return { key, label: `${prefix} ${number}`, kind, timeframe: 'H4', originAt: '',
    lower: Math.min(first, second).toFixed(5), upper: Math.max(first, second).toFixed(5) }
}

export function draftBands(zones, rows) {
  return zones.flatMap(zone => {
    const lower = Number(zone.lower), upper = Number(zone.upper)
    const origin = zone.originAt ? chartTime(zone.originAt) : null
    if (zone.originAt && origin === null) return []
    if (!Number.isFinite(lower) || !Number.isFinite(upper) || lower <= 0 || upper > 100 || lower > upper) return []
    const start = origin === null ? 0 : rows.findIndex(row => row.time >= origin)
    if (start < 0 || !rows.length) return []
    return [{ lower, upper, start, end: rows.length - 1, kind: zone.kind, label: zone.label || 'Unnamed zone' }]
  })
}
