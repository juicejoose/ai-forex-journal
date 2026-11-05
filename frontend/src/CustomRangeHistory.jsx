import { useEffect, useState } from 'react'
import { changeTone, formatChange, formatDay, isDateKey } from './journalCalendar.js'
import './JournalHistory.css'
import { journalName } from './journalNames.js'

const PAGE_SIZE = 20
export default function CustomRangeHistory({ active, refreshVersion, onOpen, onDelete, busy }) {
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState(null)
  const key = `${offset}:${refreshVersion}:${reload}`
  const current = result?.key === key ? result : null
  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    async function load() {
      try {
        const response = await fetch(`http://127.0.0.1:8000/range-journals?limit=${PAGE_SIZE}&offset=${offset}`, { signal: controller.signal })
        const data = await response.json().catch(() => null)
        if (!response.ok || !Array.isArray(data?.items) || !Number.isInteger(data.total) || data.total < 0 ||
            data.offset !== offset || data.limit !== PAGE_SIZE || data.items.length > PAGE_SIZE ||
            !data.items.every(item => Number.isInteger(item.id) && item.id > 0 && isDateKey(item.start_date) &&
              isDateKey(item.end_date) && item.start_date <= item.end_date && Number.isFinite(item.change_percent) &&
              (item.title == null || typeof item.title === 'string'))) {
          throw new Error('Could not load custom journals. Refresh to try again.')
        }
        if (controller.signal.aborted) return
        if (offset > 0 && offset >= data.total) {
          setOffset(Math.max(0, Math.floor((data.total - 1) / PAGE_SIZE) * PAGE_SIZE))
          return
        }
        setResult({ key, data })
      } catch (err) {
        if (!controller.signal.aborted) setResult({ key, error: err.message })
      }
    }
    load()
    return () => controller.abort()
  }, [active, key, offset])
  return <section className="journal-history" aria-labelledby="custom-history-heading">
    <header className="jh-heading"><div><span className="jh-eyebrow">YOUR RANGE REVIEWS</span><h2 id="custom-history-heading" tabIndex={-1}>Saved custom journals</h2><p>Revisit your saved date ranges and their original analysis.</p></div>
      <button className="jh-button" type="button" onClick={() => setReload(v => v + 1)} disabled={busy}>Refresh custom journals</button></header>
    {!current ? <p role="status">Loading custom journals…</p> : current.error ? <p className="jh-error" role="alert">{current.error}</p> : <>
      <p className="cr-list-count" role="status">{current.data.total} saved custom {current.data.total === 1 ? 'journal' : 'journals'}</p>
      {!current.data.total && <div className="jh-empty-state"><h3>No custom journals yet</h3><p>Generate a date-range journal and save it to add it here.</p></div>}
      <ul className="cr-history-grid">{current.data.items.map(journal => <li className="jh-entry-card" key={journal.id}>
        <div className="jh-entry-title"><h3>{journalName(journal, true)}</h3><span className="jh-pair">EUR/USD · H4</span></div>
        {journal.title && <p className="jh-saved-time">Custom journal #{journal.id}</p>}
        <p className="cr-date-label">{formatDay(journal.start_date)}<br /><span>through</span> {formatDay(journal.end_date)}</p>
        <p className="jh-entry-change">Range change <strong className={`jh-text-${changeTone(journal.change_percent)}`}>{formatChange(journal.change_percent)}</strong></p>
        <div className="jh-entry-actions"><button className="jh-button jh-open-button" type="button" disabled={busy} onClick={() => onOpen(journal.id)} aria-label={`Open custom journal #${journal.id}`}>Open journal ↗</button>
          <button className="jh-delete-button" type="button" disabled={busy} onClick={() => onDelete({ ...journal, pair: 'EURUSD', timeframe: '4h' })} aria-label={`Delete custom journal #${journal.id}`}>Delete</button></div>
      </li>)}</ul>
      {current.data.total > PAGE_SIZE && <div className="jh-pagination"><button className="jh-button" type="button" disabled={busy || offset === 0} onClick={() => setOffset(v => Math.max(0, v - PAGE_SIZE))}>Previous custom journals</button>
        <span>{Math.floor(offset / PAGE_SIZE) + 1} / {Math.ceil(current.data.total / PAGE_SIZE)}</span>
        <button className="jh-button" type="button" disabled={busy || offset + PAGE_SIZE >= current.data.total} onClick={() => setOffset(v => v + PAGE_SIZE)}>Next custom journals</button></div>}
    </>}
  </section>
}
