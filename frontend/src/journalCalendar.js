const nyDate = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
})
const monthLabel = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const dayLabel = new Intl.DateTimeFormat('en-US', {
  weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})

export function newYorkToday(now = new Date()) {
  const parts = Object.fromEntries(nyDate.formatToParts(now).map(({ type, value }) => [type, value]))
  return `${parts.year}-${parts.month}-${parts.day}`
}

export function isDateKey(value) {
  if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value < '0001-01-01') return false
  const date = new Date(`${value}T12:00:00Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

export function isMonthKey(value) {
  return typeof value === 'string' && isDateKey(`${value}-01`)
}

export function shiftMonth(month, amount) {
  const date = new Date(`${month}-01T12:00:00Z`)
  date.setUTCMonth(date.getUTCMonth() + amount)
  if (date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) return month
  return date.toISOString().slice(0, 7)
}

export function shiftDate(value, amount) {
  const date = new Date(`${value}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate() + amount)
  if (date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) return value
  return date.toISOString().slice(0, 10)
}

export function calendarCells(month) {
  const first = new Date(`${month}-01T12:00:00Z`)
  const last = new Date(first)
  last.setUTCMonth(last.getUTCMonth() + 1, 0)
  const start = first.getUTCDay()
  return Array.from({ length: 42 }, (_, index) => {
    const day = index - start + 1
    return day < 1 || day > last.getUTCDate() ? null : `${month}-${String(day).padStart(2, '0')}`
  })
}

export function formatMonth(month) {
  return monthLabel.format(new Date(`${month}-01T12:00:00Z`))
}

export function formatDay(value) {
  return dayLabel.format(new Date(`${value}T12:00:00Z`))
}

export function changeTone(value) {
  return !Number.isFinite(value) ? 'unknown' : value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
}

export function formatChange(value) {
  if (!Number.isFinite(value)) return '—'
  if (value === 0) return '0.00%'
  const magnitude = Math.abs(value)
  return `${value > 0 ? '+' : '−'}${magnitude < 0.005 ? '<0.01' : magnitude.toFixed(2)}%`
}

export function formatAverageNet(value) {
  if (!Number.isFinite(value)) return '—'
  if (value === 0) return '0.00'
  const magnitude = Math.abs(value)
  return `${value > 0 ? '+' : '−'}${magnitude < 0.005 ? '<0.01' : magnitude.toFixed(2)}`
}
