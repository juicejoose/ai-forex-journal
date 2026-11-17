import { useEffect, useMemo, useRef, useState } from 'react'
import { API } from './api.js'
import MarketReview from './MarketReview.jsx'
import { referencedItems, setupRequest, setupTime, previewRequest, setupPageOffset } from './setupEvaluation.js'
import { setupChartSnapshot } from './setupHistory.js'
import SetupChartEditor from './SetupChartEditor.jsx'
import SavedTradePlan, { TradePlanFields } from './SetupTradePlan.jsx'
import DeleteSetupDialog from './DeleteSetupDialog.jsx'
import './SetupEvaluator.css'

const freshForm = () => ({ title: '', direction: 'long', mode: 'live', asOf: '', includeQuote: true, zones: [], observations: '',
  tradePlan: { entryPrice: '', stopLoss: '', takeProfit: '' } })
const labels = { supported: 'Supported', contradicted: 'Contradicted', mixed: 'Mixed evidence', insufficient_evidence: 'Insufficient evidence' }
const displayPrice = value => Number.isFinite(value) ? value.toFixed(5) : '—'

async function request(path, body, signal, method = body === undefined ? 'GET' : 'POST') {
  const response = await fetch(`${API}${path}`, { method, signal,
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  if (response.ok && response.status === 204) return null
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const error = new Error(typeof data?.detail === 'string' ? data.detail : `Request failed (${response.status}). Check the setup inputs and try again.`)
    error.status = response.status
    throw error
  }
  if (!data) throw new Error('The server returned an empty response.')
  return data
}

function EvidenceList({ title, ids, items }) {
  const selected = referencedItems(ids, items)
  return selected.length > 0 && <div className="se-evidence-group">
    <h4>{title}</h4><ul>{selected.map(item => <li key={item.id}>{item.text}</li>)}</ul>
  </div>
}

function Assessment({ attempt, catalog }) {
  const result = attempt.result
  return <article className="se-assessment">
    <div className="se-row"><strong className={`se-verdict se-${result.assessment}`}>{labels[result.assessment]}</strong>
      <span className="se-help">{setupTime(attempt.completed_at)}</span></div>
    <p className="se-explanation">{result.explanation}</p>
    <div className="se-evidence-grid">
      <EvidenceList title="Supporting evidence" ids={result.supporting_facts} items={catalog.facts} />
      <EvidenceList title="Conflicting evidence" ids={result.conflicting_facts} items={catalog.facts} />
    </div>
    <EvidenceList title="Price and setup context" ids={result.context_facts} items={catalog.facts} />
    <EvidenceList title="Conditions to monitor" ids={result.watch_conditions} items={catalog.conditions} />
    <EvidenceList title="Possible invalidation scenarios" ids={result.invalidation_conditions} items={catalog.conditions} />
    <details className="se-help"><summary>Assessment record</summary>
      <p>Model: {attempt.provider_model || attempt.requested_model} · Prompt: {attempt.prompt_version}</p>
      <p>This interpretation uses the saved snapshot. It does not change your strategy scores.</p>
    </details>
  </article>
}

export default function SetupEvaluator({ active, onBusyChange, onDirtyChange, onRecordTrade }) {
  const [form, setForm] = useState(freshForm)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [record, setRecord] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleteError, setDeleteError] = useState('')
  const [notice, setNotice] = useState('')
  const historyRef = useRef(null)
  const deleteReturnRef = useRef(null)
  const historyRevision = useRef(0)
  const [preview, setPreview] = useState(null)
  const [drawing, setDrawing] = useState(null)
  const previewRetry = useRef(null)
  const previewRef = useRef(null)
  const [history, setHistory] = useState({ items: [], total: 0 })
  const [historyError, setHistoryError] = useState('')
  const [offset, setOffset] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const captureRequest = useRef(null)
  const aiRequest = useRef(null)
  const resultRef = useRef(null)
  const errorRef = useRef(null)
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone

  useEffect(() => { onBusyChange(Boolean(busy)) }, [busy, onBusyChange])
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  useEffect(() => {
    if (error) errorRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [error])
  useEffect(() => {
    if (!dirty) return
    const warn = event => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    const revision = ++historyRevision.current
    request(`/setup-snapshots?limit=10&offset=${offset}`, undefined, controller.signal)
      .then(data => {
        if (controller.signal.aborted || historyRevision.current !== revision) return
        const page = setupPageOffset(offset, data.total)
        if (page !== offset) { setOffset(page); return }
        setHistory(data); setHistoryError('')
      })
      .catch(err => { if (!controller.signal.aborted && historyRevision.current === revision) setHistoryError(err.message) })
    return () => controller.abort()
  }, [active, offset, refresh])

  function edit(values) {
    if (['mode', 'asOf', 'includeQuote'].some(key => key in values)) {
      setPreview(null)
      setDrawing(null)
      previewRetry.current = null
    }
    if ('zones' in values) setDrawing(null)
    setForm(current => ({ ...current, ...values }))
    setDirty(true)
    setError('')
  }
  function editZone(index, values) {
    edit({ zones: form.zones.map((zone, i) => i === index ? { ...zone, ...values } : zone) })
  }
  function showRecord(value) {
    setRecord(value)
    aiRequest.current = null
    requestAnimationFrame(() => {
      resultRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
      resultRef.current?.focus({ preventScroll: true })
    })
  }
  async function loadPreview() {
    if (busy) return
    setError('')
    setDrawing(null)
    try {
      const body = previewRequest(form, 'pending')
      const signature = JSON.stringify(body)
      if (previewRetry.current?.signature !== signature) previewRetry.current = { signature, id: crypto.randomUUID() }
      body.request_id = previewRetry.current.id
      setBusy('Loading a fixed chart preview…')
      const data = await request('/setup-previews', body)
      setPreview(data)
      previewRetry.current = null
    } catch (err) {
      // An expired retry needs a new preview ID; network failures keep the old ID.
      if (err.status === 409) previewRetry.current = null
      setError(err.message)
    }
    finally { setBusy('') }
  }
  function pickOrigin(key) {
    setDrawing({ kind: 'origin', key })
    previewRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }
  async function capture(event) {
    event.preventDefault()
    if (busy) return
    setError('')
    try {
      if (drawing) throw new Error('Finish or cancel the drawing before capturing the setup.')
      const body = setupRequest(form, 'pending', preview)
      const signature = JSON.stringify(body)
      if (captureRequest.current?.signature !== signature) captureRequest.current = { signature, id: crypto.randomUUID() }
      body.request_id = captureRequest.current.id
      setBusy('Capturing completed candles and saving your setup…')
      const data = await request('/setup-snapshots', body)
      showRecord(data)
      setDirty(false)
      captureRequest.current = null
      setOffset(0)
      setRefresh(value => value + 1)
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }
  async function openRecord(id) {
    if (busy) return
    setError('')
    setBusy('Opening saved setup…')
    try { showRecord(await request(`/setup-snapshots/${id}`)) }
    catch (err) { setError(err.message) }
    finally { setBusy('') }
  }
  function askDelete(target, opener) {
    deleteReturnRef.current = opener
    setDeleteError('')
    setNotice('')
    setDeleteTarget(target)
  }
  function cancelDelete() {
    setDeleteTarget(null)
    requestAnimationFrame(() => deleteReturnRef.current?.focus())
  }
  async function confirmDelete() {
    if (busy || !deleteTarget) return
    const target = deleteTarget
    setDeleteError('')
    setBusy('Deleting saved setup…')
    try {
      try { await request(`/setup-snapshots/${target.id}`, undefined, undefined, 'DELETE') }
      catch (err) { if (err.status !== 404) throw err }
      // Ignore an older list response that still contains the deleted setup.
      historyRevision.current += 1
      setHistory(current => ({ ...current, items: current.items.filter(item => item.id !== target.id), total: Math.max(0, current.total - 1) }))
      setOffset(current => setupPageOffset(current, Math.max(0, history.total - 1)))
      if (record?.id === target.id) { setRecord(null); aiRequest.current = null }
      setDeleteTarget(null)
      setError('')
      setNotice('Saved setup and its AI assessments deleted.')
      setRefresh(value => value + 1)
      requestAnimationFrame(() => historyRef.current?.focus())
    } catch (err) { setDeleteError(err.message) }
    finally { setBusy('') }
  }
  async function evaluate() {
    if (busy || !record) return
    setError('')
    setBusy('Generating an assessment from this saved snapshot…')
    aiRequest.current ??= crypto.randomUUID()
    try {
      const attempt = await request(`/setup-snapshots/${record.id}/evaluate`, { request_id: aiRequest.current })
      setRecord(current => ({ ...current, evaluations: [attempt, ...current.evaluations.filter(item => item.id !== attempt.id)] }))
      // A network retry reuses the request ID. A completed/failed attempt permits a deliberate new review.
      if (attempt.status !== 'pending') aiRequest.current = null
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }

  const snapshot = record?.snapshot
  const chartSnapshot = useMemo(() => setupChartSnapshot(snapshot), [snapshot])
  const latest = record?.evaluations?.[0]
  const completed = record?.evaluations?.filter(item => item.status === 'completed') ?? []
  const fieldsDisabled = Boolean(busy)

  return <section id="setup-panel" className="setup-evaluator" aria-label="Evaluate setup" hidden={!active} tabIndex={-1}>
    <header className="se-heading">
      <p className="se-eyebrow">EUR/USD · H4 · MANUAL DECISIONS</p>
      <h2>Evaluate a setup</h2>
      <p>Bring your levels. Review the strategy evidence, the conflicts, and what still needs confirmation.</p>
    </header>
    {error && <p ref={errorRef} className="se-error" role="alert">{error}</p>}
    {busy && <p className="se-notice" role="status">{busy}</p>}
    {notice && <p className="se-notice" role="status">{notice}</p>}
    <div className="se-workspace">
      <form className="se-card se-form" onSubmit={capture}>
        <div className="se-card-heading"><span className="se-step">1</span><h3>Capture the evidence</h3><span className="se-help">Four-factor v7</span></div>
        <fieldset disabled={fieldsDisabled}>
          <div className="se-fields">
            <label>Setup name <span className="se-help">(optional)</span>
              <input value={form.title} maxLength={120} onChange={e => edit({ title: e.target.value })} placeholder="e.g. Support test before London" />
            </label>
            <label>Proposed direction
              <select value={form.direction} onChange={e => edit({ direction: e.target.value })}><option value="long">Long / bullish</option><option value="short">Short / bearish</option></select>
            </label>
            <label>Evaluation time
              <select value={form.mode} onChange={e => edit({ mode: e.target.value })}><option value="live">Now</option><option value="historical">Historical cutoff</option></select>
            </label>
            {form.mode === 'historical' ? <label>Cutoff · {timezone}
              <input type="datetime-local" required value={form.asOf} onChange={e => edit({ asOf: e.target.value })} />
            </label> : <label className="se-checkbox"><input type="checkbox" checked={form.includeQuote} onChange={e => edit({ includeQuote: e.target.checked })} />Include a fresh practice quote</label>}
          </div>
          {form.mode === 'historical' && <p className="se-notice">A historical reconstruction uses only candles completed by the cutoff. Zones, notes and any trade plan entered now are labelled retrospective.</p>}
          <TradePlanFields value={form.tradePlan} direction={form.direction} onChange={tradePlan => edit({ tradePlan })} />
          <div className="se-preview" ref={previewRef}>
            <div className="se-row"><div><h4>Chart preview</h4><p className="se-help">Load completed candles to mark zones visually, or enter prices manually below.</p></div>
              <button type="button" onClick={loadPreview}>{preview ? 'Refresh chart' : 'Load chart'}</button></div>
            {preview && <>
              <p className="se-help">Refresh explicitly to update the evidence. Draft zones are kept. This preview is available until {setupTime(preview.expires_at)}; capture saves a permanent copy.</p>
              {active && <SetupChartEditor key={preview.id} preview={preview} zones={form.zones} onZonesChange={zones => edit({ zones })}
                drawing={drawing} onDrawingChange={setDrawing} disabled={fieldsDisabled} />}
            </>}
          </div>
          <div className="se-row se-zone-heading"><div><h4>Your support &amp; resistance</h4><p className="se-help">Optional · up to eight zones · equal prices create a single level</p></div>
            <button type="button" onClick={() => edit({ zones: [...form.zones, { key: crypto.randomUUID(), label: '', kind: 'support', timeframe: 'H4', lower: '', upper: '', originAt: '' }] })} disabled={form.zones.length >= 8}>+ Add zone</button></div>
          {form.zones.length === 0 && <p className="se-empty">Add your levels to compare price with support and resistance. Without zones, the review covers strategy evidence only.</p>}
          {form.zones.map((zone, index) => <div className="se-zone" key={zone.key}>
            <div className="se-row"><strong>Zone {index + 1}</strong><button type="button" aria-label={`Remove zone ${index + 1}`} onClick={() => edit({ zones: form.zones.filter((_, i) => i !== index) })}>Remove</button></div>
            <div className="se-fields se-zone-fields">
              <label>Name<input required maxLength={80} value={zone.label} onChange={e => editZone(index, { label: e.target.value })} placeholder="e.g. Prior swing low" /></label>
              <label>Type<select value={zone.kind} onChange={e => editZone(index, { kind: e.target.value })}><option value="support">Support</option><option value="resistance">Resistance</option></select></label>
              <label>Chart<select value={zone.timeframe} onChange={e => editZone(index, { timeframe: e.target.value })}><option>H4</option><option>D1</option><option>W1</option></select></label>
              <label>Lower price<input required inputMode="decimal" value={zone.lower} onChange={e => editZone(index, { lower: e.target.value })} placeholder="1.08000" /></label>
              <label>Upper price<input required inputMode="decimal" value={zone.upper} onChange={e => editZone(index, { upper: e.target.value })} placeholder="1.08200" /></label>
              <label className="se-zone-origin">Origin time · {timezone} <span className="se-help">(optional)</span>
                <input type="datetime-local" value={zone.originAt ?? ''} onChange={e => editZone(index, { originAt: e.target.value })} />
              </label>
            </div>
            {preview && <button type="button" onClick={() => pickOrigin(zone.key)}>Pick origin for {zone.label || `zone ${index + 1}`} on chart</button>}
            <p className="se-help">Historical checks use whole H4 candles opening at or after this time, up to the cutoff. Up to 300 earlier candles are available; older origins show partial coverage.</p>
          </div>)}
          <label className="se-notes">Your chart observations <span className="se-help">(optional)</span>
            <textarea rows={3} maxLength={5000} value={form.observations} onChange={e => edit({ observations: e.target.value })} placeholder="What are you watching? Keep observations separate from a confirmed signal." />
          </label>
          <div className="se-row se-submit"><p className="se-help">Saves a fixed record of your inputs and market evidence.<br />AI review is a separate next step.</p><button className="se-primary" type="submit">Capture setup</button></div>
        </fieldset>
      </form>
      <aside className="se-card se-history">
        <div className="se-row"><h3 ref={historyRef} tabIndex={-1}>Saved setups</h3><button type="button" disabled={fieldsDisabled} onClick={() => setRefresh(value => value + 1)}>Refresh</button></div>
        <p className="se-help">Reopen the evidence as it was captured.</p>
        {historyError && <p className="se-error" role="alert">{historyError}</p>}
        {!historyError && history.total === 0 && <p className="se-empty">Your first captured setup will appear here.</p>}
        <ul>{history.items.map(item => <li key={item.id}><button className="se-open-setup" type="button" disabled={fieldsDisabled} aria-pressed={record?.id === item.id} onClick={() => openRecord(item.id)}>
          <strong>{item.title || `${item.direction === 'long' ? 'Long' : 'Short'} setup`}</strong><span>{setupTime(item.cutoff_at)}</span>
          <small>{item.direction.toUpperCase()} · {item.mode === 'live' ? 'Captured live' : 'Historical'}</small>
        </button><button type="button" className="se-delete-link" disabled={fieldsDisabled}
          aria-label={`Delete ${item.title || `${item.direction === 'long' ? 'Long' : 'Short'} setup`} · ${setupTime(item.cutoff_at)}`}
          onClick={event => askDelete(item, event.currentTarget)}>Delete</button></li>)}</ul>
        {history.total > 10 && <div className="se-row"><button type="button" disabled={fieldsDisabled || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 10))}>Previous</button>
          <span className="se-help">{offset + 1}–{Math.min(offset + 10, history.total)} / {history.total}</span>
          <button type="button" disabled={fieldsDisabled || offset + 10 >= history.total} onClick={() => setOffset(value => value + 10)}>Next</button></div>}
      </aside>
    </div>
    {record && <div className="se-results" ref={resultRef} tabIndex={-1}>
      <div className="se-card">
        <div className="se-card-heading"><span className="se-step">2</span><h3>{snapshot.entry.title || 'Saved setup'}</h3><span className="se-saved">Snapshot saved</span>
          <button type="button" className="se-primary" disabled={fieldsDisabled} onClick={() => onRecordTrade(record)}>Record trade</button>
          <button type="button" className="se-delete-link" disabled={fieldsDisabled} onClick={event => askDelete({ id: record.id, title: snapshot.entry.title, direction: snapshot.entry.direction, cutoff_at: snapshot.cutoff_at, mode: snapshot.mode }, event.currentTarget)}>Delete setup</button></div>
        <div className="se-snapshot-grid">
          <div><span>Proposed direction</span><strong>{snapshot.entry.direction === 'long' ? 'Long / bullish' : 'Short / bearish'}</strong></div>
          <div><span>Evidence cutoff</span><strong>{setupTime(snapshot.cutoff_at)}</strong></div>
          <div><span>Last completed candle</span><strong>{setupTime(snapshot.data_through)}</strong></div>
          <div><span>{snapshot.reference_price.basis === 'quote_midpoint' ? 'Practice quote midpoint' : 'Reference · last H4 close'}</span><strong>{displayPrice(snapshot.reference_price.value)}</strong><small>{setupTime(snapshot.reference_price.time)}</small></div>
        </div>
        {snapshot.quote.status === 'available' && <p className="se-help">Practice bid {displayPrice(snapshot.quote.bid)} · ask {displayPrice(snapshot.quote.ask)}. The quote does not affect four-factor scores.</p>}
        {snapshot.quote.reason && <p className="se-help">{snapshot.quote.reason} Using the last completed close.</p>}
        {snapshot.prior_session_context && <p className="se-notice">No H4 candle has closed in the current session. These scores describe the previous completed session.</p>}
        {snapshot.preview_id && <p className="se-notice">Captured from a fixed chart preview. Prices and scores are as of the evidence cutoff; your zones, notes and any trade plan were finalized at {setupTime(snapshot.finalized_at)}.</p>}
        {snapshot.mode === 'historical' && <p className="se-notice">Historical reconstruction. The market data stops at the cutoff; your zones, notes and any trade plan were entered afterward.</p>}
        <SavedTradePlan plan={snapshot.trade_plan} />
        {snapshot.zones.length > 0 && <div className="se-zone-results">{snapshot.zones.map(zone => <div key={zone.id}>
          <strong>{zone.label} <span className="se-help">· {zone.kind} · {zone.timeframe}</span></strong>
          <p>{zone.lower}–{zone.upper}</p><p className="se-help">Reference is {zone.price_position} · {zone.distance_pips.toFixed(1)} pips from edge. Last completed close is {zone.last_close_position}.</p>
        </div>)}</div>}
        {snapshot.entry.observations && <details className="se-observations"><summary>Saved observations</summary><p>{snapshot.entry.observations}</p></details>}
        <div className="se-row se-submit"><div><h4>AI setup assessment</h4><p className="se-help">Uses this saved evidence. Capture another setup for newer data.</p></div>
          <button type="button" className="se-primary" disabled={fieldsDisabled} onClick={evaluate}>{latest ? 'Request another assessment' : 'Generate AI assessment'}</button></div>
        {latest?.status === 'failed' && <p className="se-error" role="alert">{latest.error_message}</p>}
        {latest?.status === 'pending' && <p className="se-notice">An assessment is pending. <button type="button" disabled={fieldsDisabled} onClick={() => openRecord(record.id)}>Check status</button> If interrupted, a new attempt is available after five minutes.</p>}
        {completed.length > 0 && <Assessment attempt={completed[0]} catalog={snapshot.catalog} />}
        {completed.length > 1 && <details><summary>Earlier assessments ({completed.length - 1})</summary>{completed.slice(1).map(item => <Assessment key={item.id} attempt={item} catalog={snapshot.catalog} />)}</details>}
        <details className="se-limitations" open><summary>Missing confirmation &amp; limits</summary><ul>{snapshot.catalog.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
        <details className="se-help"><summary>All calculated evidence</summary><ul>{snapshot.catalog.facts.map(item => <li key={item.id}>{item.text}</li>)}</ul></details>
      </div>
      {active && <MarketReview key={record.id} snapshot={chartSnapshot} evaluation={snapshot.rule_evaluation} setupZones={snapshot.zones} />}
    </div>}
    {deleteTarget && <DeleteSetupDialog setup={deleteTarget} pending={Boolean(busy)} error={deleteError}
      onCancel={cancelDelete} onConfirm={confirmDelete} />}
  </section>
}
