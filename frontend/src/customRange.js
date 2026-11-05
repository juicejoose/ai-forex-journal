import { isDateKey, shiftDate } from './journalCalendar.js'

export function customRangeDetails(start, end, maximum = 31) {
  if (!isDateKey(start) || !isDateKey(end)) return { error: 'Choose a start date and an end date.' }
  if (start === '0001-01-01' || end < start) return { error: 'Choose a valid start date on or before the end date.' }
  const days = Math.round((new Date(`${end}T12:00:00Z`) - new Date(`${start}T12:00:00Z`)) / 86400000) + 1
  if (days > maximum) return { error: `Choose at most ${maximum} calendar days, including both dates.` }
  const dates = Array.from({ length: days }, (_, i) => shiftDate(start, i)).filter((day) => {
    const weekday = new Date(`${day}T12:00:00Z`).getUTCDay()
    return weekday !== 0 && weekday !== 6
  })
  if (!dates.length) return { error: 'Include at least one weekday trading session.' }
  return { dates, calendarDays: days, candleCount: dates.length * 6,
    firstOpenDate: shiftDate(dates[0], -1), lastCloseDate: dates.at(-1) }
}

export function rangePreview(journal) {
  return { generation_id: journal.generation_id,
    entry: { pair: journal.pair, timeframe: journal.timeframe, start_date: journal.start_date,
      end_date: journal.end_date, strategy: journal.strategy, notes: journal.notes, rule_set_id: journal.rule_set_id },
    draft: journal.original_draft, market_data: journal.market_data, rule_evaluation: journal.rule_evaluation }
}

export function validRangePreview(data) {
  if (!data?.entry || !isDateKey(data.entry.start_date) || !isDateKey(data.entry.end_date) ||
      typeof data.draft !== 'string' || !data.draft.trim() || typeof data.generation_id !== 'string') return false
  const details = customRangeDetails(data.entry.start_date, data.entry.end_date)
  return !details.error && data.market_data?.analysis_kind === 'custom_range' &&
    data.market_data.session?.complete === true && data.market_data.candles?.length === details.candleCount &&
    data.market_data.range?.start_date === data.entry.start_date && data.market_data.range?.end_date === data.entry.end_date &&
    data.rule_evaluation?.analysis_kind === 'custom_range' && data.rule_evaluation.candles?.length === details.candleCount &&
    data.rule_evaluation.summary?.method === 'range_average'
}
