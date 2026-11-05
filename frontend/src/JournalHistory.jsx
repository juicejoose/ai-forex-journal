import { useEffect, useState } from 'react'
import {
  calendarCells, changeTone, formatChange, formatAverageNet, formatDay, formatMonth,
  isDateKey, isMonthKey, newYorkToday, shiftDate, shiftMonth,
} from './journalCalendar.js'
import './JournalHistory.css'

const API_URL = 'http://127.0.0.1:8000/journals'
const PAGE_SIZE = 20
const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const savedTime = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
})
const countLabel = (count) => `${count} ${count === 1 ? 'entry' : 'entries'}`
const validChange = (value) => value === null || Number.isFinite(value)

function validCalendar(data, month) {
  return data?.month === month && Array.isArray(data.days) &&
    Number.isInteger(data.journal_count) && data.journal_count >= 0 &&
    Number.isInteger(data.total_journals) && data.total_journals >= data.journal_count &&
    (data.latest_journal_date === null || isDateKey(data.latest_journal_date)) &&
    data.days.every((day) => isDateKey(day?.date) && day.date.startsWith(`${month}-`) &&
      Number.isInteger(day.journal_count) && day.journal_count > 0 && validChange(day.change_percent) &&
      validChange(day.average_net_score ?? null)) &&
    new Set(data.days.map((day) => day.date)).size === data.days.length &&
    data.days.reduce((total, day) => total + day.journal_count, 0) === data.journal_count
}

function validEntries(data, date, offset) {
  return Array.isArray(data?.items) && Number.isInteger(data.total) && data.total >= 0 &&
    data.limit === PAGE_SIZE && data.offset === offset && data.items.length <= PAGE_SIZE &&
    data.items.every((item) => Number.isInteger(item?.id) && item.id > 0 && item.journal_date === date &&
      typeof item.pair === 'string' && typeof item.timeframe === 'string' && validChange(item.change_percent))
}

function Chevron({ next = false }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d={next ? 'm9 5 7 7-7 7' : 'm15 5-7 7 7 7'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}

export default function JournalHistory({ onOpen, onDelete, deletingId, busy, refreshVersion = 0 }) {
  const [view, setView] = useState(() => {
    const today = newYorkToday()
    return { month: today.slice(0, 7), date: today, offset: 0 }
  })
  const [reload, setReload] = useState(0)
  const [calendarResult, setCalendarResult] = useState(null)
  const [entriesResult, setEntriesResult] = useState(null)
  const calendarKey = `${view.month}:${refreshVersion}:${reload}`
  const entriesKey = `${view.date}:${view.offset}:${refreshVersion}:${reload}`
  const calendar = calendarResult?.key === calendarKey ? calendarResult : null
  const entries = entriesResult?.key === entriesKey ? entriesResult : null
  const loadingCalendar = !calendar
  const loadingEntries = !entries
  const today = newYorkToday()
  const days = new Map((calendar?.data?.days ?? []).map((day) => [day.date, day]))
  const selectedDay = days.get(view.date)
  const cells = calendarCells(view.month)

  useEffect(() => {
    const controller = new AbortController()
    async function loadCalendar() {
      try {
        const response = await fetch(`${API_URL}/calendar?month=${view.month}`, { signal: controller.signal })
        const data = await response.json().catch(() => null)
        if (!response.ok) throw new Error('Could not load the calendar. Refresh to try again.')
        if (!validCalendar(data, view.month)) throw new Error('The server returned an invalid calendar.')
        if (!controller.signal.aborted) setCalendarResult({ key: calendarKey, data })
      } catch (err) {
        if (!controller.signal.aborted) setCalendarResult({ key: calendarKey, error: err.message })
      }
    }
    loadCalendar()
    return () => controller.abort()
  }, [calendarKey, view.month])

  useEffect(() => {
    const controller = new AbortController()
    async function loadEntries() {
      try {
        const response = await fetch(`${API_URL}?journal_date=${view.date}&limit=${PAGE_SIZE}&offset=${view.offset}`, { signal: controller.signal })
        const data = await response.json().catch(() => null)
        if (!response.ok) throw new Error('Could not load this date’s entries. Refresh to try again.')
        if (!validEntries(data, view.date, view.offset)) throw new Error('The server returned an invalid journal list.')
        if (controller.signal.aborted) return
        // After a deletion, move to the last remaining page without changing the selected date.
        if (view.offset > 0 && view.offset >= data.total) {
          setView((current) => current.date === view.date && current.offset === view.offset
            ? { ...current, offset: Math.max(0, Math.floor((data.total - 1) / PAGE_SIZE) * PAGE_SIZE) }
            : current)
          return
        }
        setEntriesResult({ key: entriesKey, data })
      } catch (err) {
        if (!controller.signal.aborted) setEntriesResult({ key: entriesKey, error: err.message })
      }
    }
    loadEntries()
    return () => controller.abort()
  }, [entriesKey, view.date, view.offset])

  function selectDate(date, focus = false) {
    if (busy || !isDateKey(date)) return
    setView({ month: date.slice(0, 7), date, offset: 0 })
    if (focus) requestAnimationFrame(() => document.getElementById(`journal-day-${date}`)?.focus())
  }

  function selectMonth(month) {
    if (busy || !isMonthKey(month)) return
    selectDate(month === today.slice(0, 7) ? today : `${month}-01`)
  }

  function calendarKeyDown(event, date) {
    const weekday = new Date(`${date}T12:00:00Z`).getUTCDay()
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7, Home: -weekday, End: 6 - weekday }[event.key]
    if (delta === undefined || busy) return
    event.preventDefault()
    selectDate(shiftDate(date, delta), true)
  }

  return (
    <section className="journal-history" aria-labelledby="history-heading">
      <div className="jh-heading">
        <div>
          <span className="jh-eyebrow">YOUR JOURNAL</span>
          <h2 id="history-heading">Saved journals</h2>
          <p>Select a date to revisit your sessions.</p>
        </div>
        <button className="jh-button" type="button" onClick={() => setReload((value) => value + 1)} disabled={busy}>Refresh calendar</button>
      </div>
      <div className="jh-layout">
        <section className="jh-calendar" aria-labelledby="calendar-month" aria-busy={loadingCalendar}>
          <header className="jh-month-header">
            <div>
              <h3 id="calendar-month">{formatMonth(view.month)}</h3>
              <p className="jh-month-count" aria-live="polite">
                {loadingCalendar ? 'Loading saved sessions…' : calendar.error ? 'Calendar unavailable' :
                  `${countLabel(calendar.data.journal_count)} · ${calendar.data.days.length} journaled ${calendar.data.days.length === 1 ? 'day' : 'days'}`}
              </p>
            </div>
            <div className="jh-month-navigation">
              <button className="jh-icon-button" type="button" aria-label="Previous month" onClick={() => selectMonth(shiftMonth(view.month, -1))} disabled={busy || view.month === '0001-01'}><Chevron /></button>
              <button className="jh-button" type="button" onClick={() => selectDate(newYorkToday())} disabled={busy}>Today</button>
              <button className="jh-icon-button" type="button" aria-label="Next month" onClick={() => selectMonth(shiftMonth(view.month, 1))} disabled={busy || view.month === '9999-12'}><Chevron next /></button>
            </div>
          </header>
          <div className="jh-jump-row">
            <label htmlFor="journal-month">Jump to month</label>
            <input id="journal-month" type="month" min="0001-01" max="9999-12" value={view.month} onChange={(event) => selectMonth(event.target.value)} disabled={busy} />
            {calendar?.data?.latest_journal_date && <button className="jh-text-button" type="button" onClick={() => selectDate(calendar.data.latest_journal_date)} disabled={busy}>Latest saved date</button>}
          </div>
          {calendar?.error && <p role="alert" className="jh-notice jh-error">{calendar.error}</p>}
          {calendar?.data?.total_journals === 0 && <p className="jh-notice">Your calendar is ready. Save your first journal to add a session.</p>}
          <table className="jh-grid" aria-label={`${formatMonth(view.month)} saved journals`}>
            <thead><tr>{weekdays.map((day) => <th key={day} scope="col">{day}</th>)}</tr></thead>
            <tbody>{Array.from({ length: 6 }, (_, week) => (
              <tr key={week}>{cells.slice(week * 7, week * 7 + 7).map((date, weekday) => {
                if (!date) return <td key={`empty-${weekday}`} className="jh-empty-cell" />
                const savedDay = days.get(date)
                const change = savedDay?.change_percent
                const averageNet = savedDay?.average_net_score
                const tone = changeTone(change)
                const count = savedDay?.journal_count ?? 0
                const label = `${formatDay(date)}. ${loadingCalendar || calendar?.error ? 'Saved entries unavailable.' : `${countLabel(count)}.`}${count ? ` EUR/USD session change ${Number.isFinite(change) ? formatChange(change) : 'unavailable'}. Strategy average net score ${Number.isFinite(averageNet) ? `${formatAverageNet(averageNet)} points` : 'unavailable'}.` : ''}`
                return <td key={date}>
                  <button id={`journal-day-${date}`} type="button"
                    className={`jh-day jh-day-${tone}${view.date === date ? ' is-selected' : ''}${date === today ? ' is-today' : ''}`}
                    aria-label={label} aria-pressed={view.date === date} aria-current={date === today ? 'date' : undefined}
                    aria-controls="journal-day-entries" tabIndex={view.date === date ? 0 : -1}
                    onClick={() => selectDate(date)} onKeyDown={(event) => calendarKeyDown(event, date)} disabled={busy}>
                    <span className="jh-day-number">{Number(date.slice(-2))}</span>
                    {count > 0 && <>
                      <span className="jh-day-change" aria-hidden="true">{formatChange(change)}</span>
                      <span className="jh-day-net" aria-hidden="true"
                        title={Number.isFinite(averageNet) ? `Average bullish minus average bearish points · Journal #${savedDay.source_journal_id}` : 'No complete session-average strategy score in this saved snapshot'}>
                        <span>Avg net</span><span>{formatAverageNet(averageNet)}</span>
                      </span>
                      <span className="jh-day-count" aria-hidden="true"><span className="jh-entry-dot" />{count}<span className="jh-count-word">{count === 1 ? 'entry' : 'entries'}</span></span>
                    </>}
                  </button>
                </td>
              })}</tr>
            ))}</tbody>
          </table>
          <footer className="jh-calendar-footer">
            <div className="jh-legend" aria-label="Session price change legend">
              <span><i className="jh-dot-up" />Positive</span>
              <span><i className="jh-dot-down" />Negative</span>
              <span><i className="jh-dot-neutral" />Flat / unavailable</span>
            </div>
            <p>EUR/USD session change · 5 p.m. to 5 p.m. New York.<br />Colors use the latest available saved snapshot for each date.</p>
            <p>Avg net = average bullish minus average bearish points, from the same saved journal as the percent change. — means no complete session-average score.</p>
          </footer>
        </section>
        <section id="journal-day-entries" className="jh-entries" aria-labelledby="selected-date-heading" aria-busy={loadingEntries}>
          <header className="jh-entries-heading">
            <span className="jh-eyebrow">SELECTED DATE</span>
            <h3 id="selected-date-heading">{formatDay(view.date)}</h3>
            {Number.isFinite(selectedDay?.change_percent) && <p className={`jh-session-change jh-text-${changeTone(selectedDay.change_percent)}`}>
              {formatChange(selectedDay.change_percent)}<span>EUR/USD session</span>
            </p>}
          </header>
          <div aria-live="polite" className="jh-entries-status">
            {loadingEntries ? <p>Loading entries…</p> : entries.error ? <p role="alert" className="jh-error">{entries.error}</p> : <p>{countLabel(entries.data.total)} saved for this date</p>}
          </div>
          {entries?.data?.total === 0 && <div className="jh-empty-state">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect x="8" y="9" width="24" height="25" rx="4" stroke="currentColor" strokeWidth="1.5" /><path d="M8 17h24M14 6v7M26 6v7M15 24h10M15 28h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
            <h4>No entries for this date</h4>
            <p>Choose a marked day to read its journals, or save a new journal for this session.</p>
          </div>}
          {entries?.data && entries.data.items.length > 0 && <ul className="jh-entry-list">
            {entries.data.items.map((journal) => {
              const saved = new Date(journal.created_at)
              return <li key={journal.id} className="jh-entry-card">
                <div className="jh-entry-title"><h4>Journal #{journal.id}</h4><span className="jh-pair">{journal.pair.replace(/^EURUSD$/, 'EUR/USD')} · {journal.timeframe}</span></div>
                <p className="jh-saved-time">{Number.isFinite(saved.getTime()) ? `Saved ${savedTime.format(saved)} NY` : 'Saved time unavailable'}</p>
                {journal.session_complete === false && <p className="jh-saved-time">Intraday snapshot · {journal.completed_candles} of 6 candles · through {savedTime.format(new Date(journal.data_through))} NY</p>}
                <p className="jh-entry-change">Session change <strong className={`jh-text-${changeTone(journal.change_percent)}`}>{Number.isFinite(journal.change_percent) ? formatChange(journal.change_percent) : journal.session_complete === false ? 'Session was in progress' : 'Unavailable'}</strong></p>
                <div className="jh-entry-actions">
                  <button className="jh-button jh-open-button" type="button" onClick={() => onOpen(journal.id)} disabled={busy} aria-label={`Open journal #${journal.id}`}>Open journal <span aria-hidden="true">↗</span></button>
                  <button className="jh-delete-button" type="button" onClick={() => onDelete(journal)} disabled={busy} aria-label={`Delete journal #${journal.id} from ${journal.journal_date}`}>{deletingId === journal.id ? 'Deleting…' : 'Delete'}</button>
                </div>
              </li>
            })}
          </ul>}
          {entries?.data && entries.data.total > PAGE_SIZE && <div className="jh-pagination">
            <button className="jh-button" type="button" aria-label="Previous entries" onClick={() => setView((current) => ({ ...current, offset: Math.max(0, current.offset - PAGE_SIZE) }))} disabled={busy || loadingEntries || view.offset === 0}>Previous</button>
            <span>{Math.floor(view.offset / PAGE_SIZE) + 1} / {Math.ceil(entries.data.total / PAGE_SIZE)}</span>
            <button className="jh-button" type="button" aria-label="Next entries" onClick={() => setView((current) => ({ ...current, offset: current.offset + PAGE_SIZE }))} disabled={busy || loadingEntries || view.offset + PAGE_SIZE >= entries.data.total}>Next</button>
          </div>}
        </section>
      </div>
    </section>
  )
}
