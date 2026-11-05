import { useEffect, useState } from 'react'
import MarketEvidence from './MarketEvidence.jsx'
import StrategyScores from './StrategyScores.jsx'
import JournalView from './JournalView.jsx'
import { formatDay } from './journalCalendar.js'
import { validTodayView, validTodayEvidence, summaryIsBehind, freshTodayView } from './todaySession.js'
import './TodayPage.css'

const API = 'http://127.0.0.1:8000'
const stamp = value => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date(value))
const clock = value => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' }).format(new Date(value))
async function responseData(response, fallback) {
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : fallback)
  return data
}

export default function TodayPage({ active, busy, onBusyChange, onDirtyChange, onSaved }) {
  const [view, setView] = useState(null)
  const [reload, setReload] = useState(0)
  const [fetching, setFetching] = useState(false)
  const [dataError, setDataError] = useState('')
  const [now, setNow] = useState(0)
  const [notes, setNotes] = useState('')
  const [preview, setPreview] = useState(null)
  const [saved, setSaved] = useState(null)
  const [text, setText] = useState('')
  const [action, setAction] = useState('')
  const [error, setError] = useState('')
  const [saveError, setSaveError] = useState('')
  const isSaved = saved !== null && text.trim() === saved.edited_draft
  const dirty = preview !== null && !isSaved
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])

  useEffect(() => {
    if (!active) return
    let disposed = false, inFlight = false, controller
    async function refresh() {
      if (disposed || inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 45000)
      setFetching(true)
      try {
        const response = await fetch(`${API}/today`, { signal: controller.signal, cache: 'no-store' })
        const data = await responseData(response, 'Could not refresh today’s session.')
        if (!validTodayView(data)) throw new Error('The server returned an unsupported Today snapshot. Check that the updated backend is running.')
        if (!disposed) { setView(data); setDataError(''); setNow(Date.now()) }
      } catch (err) {
        if (!disposed) setDataError(err.name === 'AbortError' ? 'The refresh timed out. Retry to get current data.' : err.message)
      } finally {
        clearTimeout(timeout)
        inFlight = false
        if (!disposed) setFetching(false)
      }
    }
    function visibility() { if (document.visibilityState === 'visible') refresh() }
    refresh()
    const poll = setInterval(refresh, 60000)
    const age = setInterval(() => setNow(Date.now()), 10000)
    document.addEventListener('visibilitychange', visibility)
    return () => { disposed = true; controller?.abort(); clearInterval(poll); clearInterval(age); document.removeEventListener('visibilitychange', visibility) }
  }, [active, reload])

  const fresh = freshTodayView(view, now)
  const staleSummary = summaryIsBehind(preview, view)
  function pending(value) { setAction(value); onBusyChange(Boolean(value)) }
  async function generate() {
    if (busy || fetching || dataError || !fresh || !view?.snapshot_id) return
    if (dirty && !window.confirm('Replace this unsaved Today summary or your edits? Save first to keep them.')) return
    setError(''); pending('generate')
    try {
      const response = await fetch(`${API}/today/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot_id: view.snapshot_id, notes: notes.trim() }) })
      const data = await responseData(response, 'Could not generate a summary. Your previous review is still here.')
      if (!data?.entry || typeof data.generation_id !== 'string' || typeof data.draft !== 'string' || !data.draft.trim() ||
          !validTodayEvidence(data.market_data, data.rule_evaluation)) throw new Error('The server did not return a valid Today summary.')
      setPreview(data); setSaved(null); setText(data.draft); setSaveError('')
    } catch (err) { setError(err.message) } finally { pending('') }
  }
  async function save() {
    if (busy || !preview || isSaved || !text.trim()) return
    setSaveError(''); pending('save')
    try {
      const response = await fetch(`${API}/journals${saved ? `/${saved.id}` : ''}`, { method: saved ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(saved ? { edited_draft: text.trim() }
          : { generation_id: preview.generation_id, edited_draft: text.trim() }) })
      const data = await responseData(response, 'Could not save this review. Your text is still here.')
      if (!Number.isInteger(data?.id) || typeof data.edited_draft !== 'string' || !validTodayEvidence(data.market_data, data.rule_evaluation)) {
        throw new Error('The server did not confirm a valid saved review. Check Saved journals before retrying.')
      }
      setSaved(data); setText(data.edited_draft); onSaved()
    } catch (err) { setSaveError(err.message) } finally { pending('') }
  }

  return <section id="today-panel" role="tabpanel" aria-labelledby="today-tab" hidden={!active} tabIndex={0} className="today-page">
    {active && <>
      <header className="today-heading"><div><p className="jv-eyebrow">CURRENT TRADING SESSION</p><h2>Today, as it unfolds</h2>
        <p>EUR/USD · 4-hour candles · Four-factor strategy v4</p></div>
        <button className="jv-button" type="button" onClick={() => setReload(value => value + 1)} disabled={fetching || busy}>{fetching ? 'Refreshing…' : 'Refresh data'}</button>
      </header>
      <p className="today-refresh" role="status">Checks for completed candles every minute while this page is visible. The backend must be running. AI summaries refresh only when you request them.</p>
      {dataError && <p role="alert" className="jv-error">{dataError} {view && 'Showing the last successful snapshot; it may be outdated.'}</p>}
      {!view && !dataError && <p role="status">Loading today’s session…</p>}
      {view && <>
        <div className="today-window"><div><span className="jv-eyebrow">SESSION ENDING</span><h3>{formatDay(view.journal_date)}</h3>
          <p>{stamp(view.session.start)} → {stamp(view.session.end)}</p></div>
          <div className="today-coverage"><strong>{view.session.candle_count}<small> / 6</small></strong><span>candles completed</span></div>
        </div>
        <p className="today-refresh">Last checked {stamp(view.as_of)}{!fresh && ' · Refresh needed'} · Session dates use the 5 PM New York close. After 5 PM, the next trading session begins.</p>
        {view.market_state === 'weekend_closed' && <p className="today-notice">Weekend closure · Showing the latest Friday session. The next scheduled opening is {stamp(view.next_open)}.</p>}
        <ol className="today-slots" aria-label="Six session candles">{view.slots.map(slot => <li key={slot.candle_id} className={`today-slot today-${slot.status}`}>
          <span>{slot.candle_id}</span><strong>{clock(slot.open_time)} – {clock(slot.close_time)}</strong>
          <small>{slot.status === 'completed' ? 'Completed' : slot.status === 'forming' ? 'Forming · score pending' : 'Upcoming · pending'}</small>
        </li>)}</ol>
        {view.market_data ? <><MarketEvidence snapshot={view.market_data} /><StrategyScores evaluation={view.rule_evaluation} snapshot={view.market_data} /></>
          : <div className="today-empty"><h3>Waiting for the first completed candle</h3><p>The first H4 candle closes at {clock(view.slots[0].close_time)}. Scores and an AI review become available after that close. Previous-session candles provide indicator history only.</p></div>}
      </>}
      <section className="today-ai" aria-labelledby="today-ai-heading"><div><p className="jv-eyebrow">YOUR SESSION REVIEW</p><h3 id="today-ai-heading">Generate when you’re ready</h3>
        <p>The AI receives the completed candles, Python scores, and current coverage. Saving keeps this exact review in Saved journals, labeled with its cutoff.</p></div>
        <label htmlFor="today-notes">Your observations <span>(optional)</span></label>
        <textarea id="today-notes" value={notes} maxLength={10000} rows={3} onChange={event => setNotes(event.target.value)} disabled={busy} placeholder="What would you like to review about the session so far?" />
        <div className="today-ai-actions"><span>{notes.length.toLocaleString()} / 10,000</span><button className="jv-button jv-primary" type="button" onClick={generate} disabled={busy || fetching || Boolean(dataError) || !fresh || !view?.snapshot_id}>
          {action === 'generate' ? 'Writing summary…' : preview ? 'Refresh AI summary' : 'Generate AI summary'}</button></div>
        {error && <p className="jv-error" role="alert">{error}</p>}
      </section>
      {staleSummary && <p className="today-notice" role="status">The live data has changed since this summary was generated. The review below still uses its original snapshot. Refresh the AI summary when ready.</p>}
      {saved && <p className="today-refresh">Saved as journal #{saved.id} in Saved journals for {formatDay(saved.journal_date)}. Reopen or delete it there.</p>}
      {preview && <JournalView key={preview.generation_id} preview={preview} savedJournal={saved} text={text} onChange={setText} onSave={save}
        busy={busy} saving={action === 'save'} isSaved={isSaved} error={saveError} showEvidence={false} />}
    </>}
  </section>
}
