import { useEffect, useRef, useState } from 'react'
import { API } from './api.js'
import { setupTime, setupPageOffset } from './setupEvaluation.js'
import TradeAlignment from './TradeAlignment.jsx'
import TradeTimeline from './TradeTimeline.jsx'
import { preferredAnalysis } from './tradeAlignment.js'
import SavedTradePlan from './SetupTradePlan.jsx'
import { blankTrade, blankExit, formFromSetup, tradeRequest, exitRequest, reviewChanged, disciplineLabels } from './tradeLog.js'
import './TradesPage.css'

async function request(path, body, signal) {
  const response = await fetch(`${API}${path}`, body === undefined ? { signal } : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail
    : Array.isArray(data?.detail) ? data.detail.map(item => item.msg).join(' ') : `Request failed (${response.status}). Please try again.`)
  if (!data) throw new Error('The server returned an empty response.')
  return data
}
const shownPrice = value => value ?? 'Not recorded'
const neutralReview = () => ({ discipline: 'not_reviewed', notes: '' })

export default function TradesPage({ active, seed, onBusyChange, onDirtyChange }) {
  const [form, setForm] = useState(() => formFromSetup(seed?.record))
  const [linkedSetup, setLinkedSetup] = useState(seed?.record ?? null)
  const [creating, setCreating] = useState(Boolean(seed))
  const [entryDirty, setEntryDirty] = useState(Boolean(seed))
  const [record, setRecord] = useState(null)
  const [exit, setExit] = useState(blankExit)
  const [review, setReview] = useState(neutralReview)
  const [reviewBase, setReviewBase] = useState(() => ({ ...neutralReview(), revision: 0 }))
  const [comparisonSource, setComparisonSource] = useState('entry_time')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [history, setHistory] = useState({ items: [], total: 0 })
  const [historyError, setHistoryError] = useState('')
  const [status, setStatus] = useState('all')
  const [offset, setOffset] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const requests = useRef({})
  const detailRef = useRef(null)
  const errorRef = useRef(null)
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const exitDirty = Object.values(exit).some(value => value.trim())
  const reviewDirty = Boolean(record && reviewChanged(review, reviewBase))
  const dirty = entryDirty || exitDirty || reviewDirty

  useEffect(() => { onBusyChange(Boolean(busy)) }, [busy, onBusyChange])
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const warn = event => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  useEffect(() => { if (error) errorRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }, [error])
  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    request(`/trades?status=${status}&limit=20&offset=${offset}`, undefined, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        const page = setupPageOffset(offset, data.total, 20)
        if (page !== offset) { setOffset(page); return }
        setHistory(data); setHistoryError('')
      }).catch(err => { if (!controller.signal.aborted) setHistoryError(err.message) })
    return () => controller.abort()
  }, [active, status, offset, refresh])

  function edit(values) { setForm(current => ({ ...current, ...values })); setEntryDirty(true); setError(''); setMessage('') }
  function present(value) {
    setRecord(value); setExit(blankExit()); setReview({ discipline: value.review.discipline, notes: value.review.notes }); setReviewBase(value.review); setComparisonSource(preferredAnalysis(value))
    requestAnimationFrame(() => { detailRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }); detailRef.current?.focus({ preventScroll: true }) })
  }
  async function save(kind, path, body) {
    const signature = JSON.stringify({ path, body })
    if (requests.current[kind]?.signature !== signature) requests.current[kind] = { signature, id: crypto.randomUUID() }
    const data = await request(path, { ...body, request_id: requests.current[kind].id })
    delete requests.current[kind]
    setRefresh(value => value + 1)
    return data
  }
  async function create(event) {
    event.preventDefault()
    if (busy) return
    setError(''); setMessage('')
    try {
      if ((exitDirty || reviewDirty) && !window.confirm('Discard the unsaved exit or self-review when opening this new trade?')) return
      const body = tradeRequest(form)
      setBusy('Saving your trade and entry evidence…')
      const data = await save('entry', '/trades', body)
      present(data); setCreating(false); setEntryDirty(false); setForm(blankTrade()); setLinkedSetup(null); setOffset(0)
      setMessage('Trade recorded. Add its full exit when the position is closed.')
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }
  async function open(id) {
    if (busy || ((exitDirty || reviewDirty) && !window.confirm('Discard unsaved exit or review changes and open this trade?'))) return
    setBusy('Opening saved trade…'); setError(''); setMessage('')
    try { present(await request(`/trades/${id}`)) } catch (err) { setError(err.message) } finally { setBusy('') }
  }
  async function close(event) {
    event.preventDefault()
    if (busy) return
    setError(''); setMessage('')
    try {
      const body = exitRequest(exit, record.entry.entry_at)
      setBusy('Saving the full exit and calculating the result…')
      const data = await save('exit', `/trades/${record.id}/close`, body)
      // Keep any unsaved self-review separate from the exit save.
      setRecord(data); setExit(blankExit());
      if (!reviewDirty) { setReview({ discipline: data.review.discipline, notes: data.review.notes }); setReviewBase(data.review) }
      setMessage('Full exit saved. The result does not determine your discipline rating.')
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }
  async function saveReview(event) {
    event.preventDefault()
    if (busy) return
    setBusy('Saving your self-review…'); setError(''); setMessage('')
    try {
      const data = await save('review', `/trades/${record.id}/reviews`, { discipline: review.discipline, notes: review.notes.trim(), expected_revision: reviewBase.revision })
      setRecord(data); setReview({ discipline: data.review.discipline, notes: data.review.notes }); setReviewBase(data.review); setMessage('Self-review saved. Earlier reviews are retained.')
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }
  async function analyze(source) {
    if (busy) return
    setBusy(source === 'entry_time' ? 'Reconstructing completed candles at entry…' : 'Comparing saved four-factor evidence…')
    setError(''); setMessage('')
    try {
      const data = await save('analysis', `/trades/${record.id}/strategy-analysis`, { source })
      // Keep unsaved exit/review drafts and their original review revision intact.
      setRecord(current => ({ ...current, strategy_analyses: data.strategy_analyses }))
      setComparisonSource(source)
      setMessage('Four-factor comparison saved. The original entry evidence remains unchanged.')
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }
  function startNew() {
    if (entryDirty && !window.confirm('Replace the unsaved entry form?')) return
    setForm(blankTrade()); setLinkedSetup(null); setEntryDirty(false); setCreating(true); setError(''); setMessage('')
    requestAnimationFrame(() => document.getElementById('trade-entry-title')?.focus())
  }
  function cancelEntry() {
    if (entryDirty && !window.confirm('Discard this unsaved entry form?')) return
    setCreating(false); setEntryDirty(false); setForm(blankTrade()); setLinkedSetup(null)
  }

  const evidence = record?.context?.setup?.snapshot
  const entry = record?.entry
  return <section id="trades-panel" className="trade-page" hidden={!active} tabIndex={-1} aria-label="Trades">
    <header className="trade-heading"><div><p className="trade-eyebrow">EUR/USD · H4 · MANUAL TRADE LOG</p><h2>Your trades</h2><p>Record your execution. Review your decisions separately from the outcome.</p></div>
      <button type="button" className="trade-primary" disabled={Boolean(busy)} onClick={startNew}>Record trade</button></header>
    {error && <p ref={errorRef} className="trade-error" role="alert">{error}</p>}
    {(busy || message) && <p className="trade-notice" role="status">{busy || message}</p>}
    {creating && <form className="trade-card trade-entry-form trade-form" onSubmit={create}>
      <h3 id="trade-entry-title" tabIndex={-1}>Record an entry</h3>
      <p className="trade-help">Enter actual execution details. Entry details and linked evidence are fixed after saving; check the prices and time first.</p>
      {linkedSetup ? <div className="trade-notice"><strong>Linked setup: {linkedSetup.snapshot.entry.title || 'Saved setup'}</strong><p>Evidence cutoff: {setupTime(linkedSetup.snapshot.cutoff_at)}. It must be at or before your entry time.</p>
        {linkedSetup.snapshot.trade_plan && <p>Planned prices were copied into this form. Verify the actual entry fill and the initial stop and target you used.</p>}
        <button type="button" disabled={Boolean(busy)} onClick={() => { setLinkedSetup(null); edit({ setupId: null }) }}>Remove setup link</button></div>
        : <p className="trade-help">Manual entry: after saving, you can reconstruct market evidence at entry. To preserve an existing setup instead, open it and choose Record trade.</p>}
      <fieldset disabled={Boolean(busy)}><div className="trade-fields">
        <label>Trade name <span>(optional)</span><input value={form.title} maxLength={120} onChange={e => edit({ title: e.target.value })} placeholder="e.g. London support reaction" /></label>
        <label>Direction<select value={form.direction} onChange={e => edit({ direction: e.target.value })}><option value="long">Long</option><option value="short">Short</option></select></label>
        <label>Actual entry price<input required inputMode="decimal" value={form.entryPrice} onChange={e => edit({ entryPrice: e.target.value })} placeholder="1.10000" /></label>
        <label>Entry time · {timezone}<input required type="datetime-local" value={form.entryAt} onChange={e => edit({ entryAt: e.target.value })} /></label>
        <label>Initial stop loss <span>(optional)</span><input inputMode="decimal" value={form.stopLoss} onChange={e => edit({ stopLoss: e.target.value })} placeholder="No initial stop" /></label>
        <label>Initial take profit <span>(optional)</span><input inputMode="decimal" value={form.takeProfit} onChange={e => edit({ takeProfit: e.target.value })} placeholder="No initial target" /></label>
        <label className="trade-wide">Reason for entry<textarea required maxLength={5000} rows={3} value={form.reason} onChange={e => edit({ reason: e.target.value })} placeholder="What supported your decision at entry?" /></label>
        <label className="trade-wide">Support/resistance and entry observations <span>(optional)</span><textarea maxLength={5000} rows={2} value={form.observations} onChange={e => edit({ observations: e.target.value })} /></label>
      </div><p className="trade-help">No stop recorded means R will be unavailable. These fields record your actions; they do not define mandatory trading rules.</p>
      <div className="trade-actions"><button type="button" onClick={cancelEntry}>Cancel entry</button><button className="trade-primary" type="submit">Save trade entry</button></div></fieldset>
    </form>}
    <div className="trade-workspace">
      <aside className="trade-card trade-history" aria-label="Trade history"><div className="trade-history-toolbar"><h3>Trade history</h3>
        <label>Show trades<select value={status} disabled={Boolean(busy)} onChange={e => { setStatus(e.target.value); setOffset(0) }}><option value="all">All trades</option><option value="open">Open</option><option value="closed">Closed</option></select></label>
        <button type="button" disabled={Boolean(busy)} onClick={() => setRefresh(v => v + 1)}>Refresh</button></div>
        {historyError && <p role="alert" className="trade-error">{historyError}</p>}
        {!historyError && !history.total && <p className="trade-help">No {status === 'all' ? '' : status+' '}trades recorded yet.</p>}
        <ul>{history.items.map(item => <li key={item.id}><button type="button" disabled={Boolean(busy)} aria-pressed={item.id === record?.id} onClick={() => open(item.id)}>
          <strong>{item.entry.title || `${item.entry.direction === 'long' ? 'Long' : 'Short'} EUR/USD`}</strong><span>{setupTime(item.entry.entry_at)}</span>
          <span>{item.entry.direction.toUpperCase()} · {item.status === 'open' ? 'Open' : 'Closed'}</span>
          {item.result && <span className={`trade-${item.result.outcome}`}>{item.result.pips} pips · {item.result.r_display !== null ? `${item.result.r_display} R` : 'R unavailable'}</span>}
          <small>{disciplineLabels[item.review.discipline]}</small></button></li>)}</ul>
        {history.total > 20 && <div className="trade-row"><button type="button" disabled={Boolean(busy) || !offset} onClick={() => setOffset(v => Math.max(0,v-20))}>Previous</button><span>{offset+1}–{Math.min(offset+20,history.total)} / {history.total}</span><button type="button" disabled={Boolean(busy) || offset+20>=history.total} onClick={() => setOffset(v => v+20)}>Next</button></div>}
      </aside>
      {record ? <article className="trade-detail" ref={detailRef} tabIndex={-1} aria-label="Selected trade">
        <section className="trade-card"><div className="trade-row"><h3>{entry.title || `${entry.direction === 'long' ? 'Long' : 'Short'} EUR/USD`}</h3><span className="trade-badge">{record.status === 'open' ? 'Open trade' : 'Closed trade'}</span></div>
          <p className="trade-help">EUR/USD · H4 · {entry.direction === 'long' ? 'Long' : 'Short'} · Logged {setupTime(record.created_at)}</p>
          <dl className="trade-metrics"><div><dt>Actual entry</dt><dd>{entry.entry_price}</dd></div><div><dt>Entry time</dt><dd>{setupTime(entry.entry_at)}</dd></div><div><dt>Initial stop</dt><dd>{shownPrice(entry.initial_stop_loss)}</dd></div><div><dt>Initial target</dt><dd>{shownPrice(entry.initial_take_profit)}</dd></div></dl>
          <h4>Reason for entry</h4><p className="trade-prose">{entry.entry_reason}</p>{entry.entry_observations && <><h4>Entry observations</h4><p className="trade-prose">{entry.entry_observations}</p></>}
        </section>
        <TradeTimeline key={`${record.id}:${record.exit?.exit_at ?? 'open'}`} record={record} active={active} />
        <TradeAlignment key={`${record.id}:${comparisonSource}`} record={record} source={comparisonSource} onSourceChange={setComparisonSource} onAnalyze={analyze} busy={Boolean(busy)} active={active} />
        <section className="trade-card"><h3>Original entry context</h3>{evidence ? <>
          <p className="trade-help">{record.context.setup.snapshot.entry.title || 'Saved setup'} · cutoff {setupTime(evidence.cutoff_at)}</p>
          <p className="trade-notice">{record.context_timing === 'captured_before_entry' ? 'Setup captured before entry. Your manual entry notes were logged separately at the time shown above.' : 'Retrospective context: this setup was reconstructed historically or saved after entry. It does not establish what you knew at entry.'}</p>
          <dl className="trade-metrics"><div><dt>Strategy</dt><dd>{evidence.rule_evaluation.rule_set.name || evidence.rule_evaluation.rule_set.id}<small>Version {evidence.rule_evaluation.rule_set.version} · revision {evidence.rule_evaluation.rule_set.revision}</small></dd></div><div><dt>{evidence.prior_session_context ? 'Previous-session bias' : 'Session bias at cutoff'}</dt><dd>{evidence.rule_evaluation.summary.direction}<small>Average net: {typeof evidence.rule_evaluation.summary.net_score === 'number' ? evidence.rule_evaluation.summary.net_score.toFixed(2) : 'Unavailable'}</small></dd></div></dl>
          {entry.direction !== evidence.entry.direction && <p className="trade-notice">Recorded direction differs from the setup’s proposed direction. This is a comparison, not a discipline grade.</p>}
          {evidence.trade_plan && <div className="trade-original-plan"><h4>Original proposed plan</h4><SavedTradePlan plan={evidence.trade_plan} /></div>}
          {evidence.zones.length > 0 && <ul className="trade-zones">{evidence.zones.map(zone => <li key={zone.id}><strong>{zone.label}</strong> · {zone.kind} · {zone.lower}–{zone.upper}</li>)}</ul>}
          <p className="trade-help">This entry copy stays with the trade if its original setup is deleted. It is never refreshed with later market data.</p>
        </> : <p className="trade-help">The original entry was logged manually without a market snapshot. Your reasoning and observations are self-reported. Any later reconstruction is stored separately above.</p>}</section>
        <section className="trade-card"><h3>{record.status === 'open' ? 'Record a full exit' : 'Recorded outcome'}</h3>
          {record.status === 'open' ? <form className="trade-form" onSubmit={close}><p className="trade-help">One full exit per trade. Enter your actual exit fill; price touching a chart level does not close this record. Exit details are fixed after saving.</p><fieldset disabled={Boolean(busy)}><div className="trade-fields">
            <label>Actual exit price<input required inputMode="decimal" value={exit.price} onChange={e => setExit({ ...exit, price: e.target.value })} /></label>
            <label>Exit time · {timezone}<input required type="datetime-local" value={exit.at} onChange={e => setExit({ ...exit, at: e.target.value })} /></label>
            <label className="trade-wide">Exit notes <span>(optional)</span><textarea maxLength={5000} rows={2} value={exit.notes} onChange={e => setExit({ ...exit, notes: e.target.value })} /></label>
          </div><div className="trade-actions"><button className="trade-primary" type="submit">Save full exit</button></div></fieldset></form> : <>
            <dl className="trade-metrics"><div><dt>Actual exit</dt><dd>{record.exit.exit_price}</dd></div><div><dt>Exit time</dt><dd>{setupTime(record.exit.exit_at)}</dd></div><div><dt>Price result</dt><dd className={`trade-${record.result.outcome}`}>{record.result.pips} pips</dd></div><div><dt>Result in R</dt><dd>{record.result.r_display !== null ? `${record.result.r_display} R` : 'Unavailable'}<small>{record.result.initial_risk_pips !== null ? `Initial risk: ${record.result.initial_risk_pips} pips` : 'No initial stop recorded'}</small></dd></div></dl>
            <p className="trade-help">{record.result.assumptions}</p>{record.exit.exit_notes && <p className="trade-prose">{record.exit.exit_notes}</p>}
          </>}
        </section>
        <section className="trade-card"><h3>Trading discipline · your self-review</h3><p className="trade-help">You have not defined mandatory rules yet. This is your own assessment, separate from profit or loss; the app does not grade your discipline.</p>
          <form className="trade-form" onSubmit={saveReview}><fieldset disabled={Boolean(busy)}><label>Did you follow your plan?<select value={review.discipline} onChange={e => setReview({ ...review, discipline: e.target.value })}>{Object.entries(disciplineLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>Review notes<textarea maxLength={5000} rows={3} value={review.notes} onChange={e => setReview({ ...review, notes: e.target.value })} placeholder="What matched your plan? What did you change, miss, or learn?" /></label>
            <div className="trade-actions"><button type="submit" className="trade-primary" disabled={!reviewDirty}>Save self-review</button></div></fieldset></form>
          {record.reviews.length > 0 && <details><summary>Saved self-review history ({record.reviews.length})</summary>{record.reviews.map(item => <div key={item.revision} className="trade-review-history"><strong>{disciplineLabels[item.discipline]}</strong><small>{setupTime(item.recorded_at)}</small><p className="trade-prose">{item.notes || 'No review notes.'}</p></div>)}</details>}
        </section>
      </article> : <div className="trade-card trade-empty"><h3>Keep the decision and the result together</h3><p>Open a trade to record its exit and review your execution. You can also start from a saved setup to retain its strategy and zone evidence.</p></div>}
    </div>
  </section>
}
