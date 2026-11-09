import { API } from './api.js'
import { useEffect, useState } from 'react'
import CustomRangeForm from './CustomRangeForm.jsx'
import CustomRangeHistory from './CustomRangeHistory.jsx'
import JournalView from './JournalView.jsx'
import { CURRENT_RULE_SET_ID } from './strategyChoices.js'
import { journalEditsSaved } from './journalNames.js'
import DeleteJournalDialog from './DeleteJournalDialog.jsx'
import { customRangeDetails, rangePreview, validRangePreview } from './customRange.js'
import './CustomRangeJournals.css'

async function readResponse(response, fallback) {
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : fallback)
  return data
}

export default function CustomRangeJournals({ activeTab, onBusyChange, onDirtyTabChange, busy }) {
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [notes, setNotes] = useState('')
  const [optionsResult, setOptionsResult] = useState(null)
  const [retry, setRetry] = useState(0)
  const [preview, setPreview] = useState(null)
  const [saved, setSaved] = useState(null)
  const [text, setText] = useState('')
  const [journalTitle, setJournalTitle] = useState('')
  const [editorTab, setEditorTab] = useState('custom')
  const [action, setAction] = useState('')
  const [error, setError] = useState('')
  const [saveError, setSaveError] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [historyVersion, setHistoryVersion] = useState(0)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleteError, setDeleteError] = useState('')
  const [message, setMessage] = useState('')
  const options = optionsResult?.retry === retry ? optionsResult.data : null
  const optionsError = optionsResult?.retry === retry ? optionsResult.error : null
  const isSaved = journalEditsSaved(saved, text, journalTitle)
  const dirty = preview !== null && !isSaved

  useEffect(() => { onDirtyTabChange(dirty ? editorTab : null) }, [dirty, editorTab, onDirtyTabChange])
  useEffect(() => {
    const controller = new AbortController()
    async function loadOptions() {
      try {
        const response = await fetch(`${API}/range-journal/options`, { signal: controller.signal })
        const data = await readResponse(response, 'Could not load custom-range strategy rules.')
        if (data?.max_calendar_days !== 31 || data.rule_set?.scope !== 'custom_range' ||
            data.rule_set?.summary_method !== 'range_average' || typeof data.rule_set.rules !== 'string') {
          throw new Error('Custom-range rules are unavailable. Check that the updated backend is running.')
        }
        if (!controller.signal.aborted) setOptionsResult({ retry, data })
      } catch (err) {
        if (!controller.signal.aborted) setOptionsResult({ retry, error: err.message })
      }
    }
    loadOptions()
    return () => controller.abort()
  }, [retry])

  function setPending(value) { setAction(value); onBusyChange(Boolean(value)) }
  function canReplace() { return !dirty || window.confirm('Replace your unsaved custom journal or edits? Save first to keep them.') }

  async function generate(event) {
    event.preventDefault()
    if (busy || !options) return
    const details = customRangeDetails(start, end, options.max_calendar_days)
    if (details.error) { setError(details.error); return }
    if (!canReplace()) return
    setError(''); setPending('generate')
    try {
      const response = await fetch(`${API}/range-journal/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_date: start, end_date: end, pair: 'EURUSD', timeframe: '4h', rule_set_id: CURRENT_RULE_SET_ID, notes: notes.trim() }) })
      const data = await readResponse(response, 'Could not generate a custom journal. Please try again.')
      if (!validRangePreview(data)) throw new Error('The server did not return a complete custom journal.')
      setPreview(data); setSaved(null); setText(data.draft); setJournalTitle(''); setEditorTab('custom'); setSaveError(''); setMessage('')
    } catch (err) { setError(err.message) } finally { setPending('') }
  }

  async function save() {
    if (busy || !preview || isSaved || !text.trim()) return
    setSaveError(''); setPending('save')
    try {
      const response = await fetch(`${API}/range-journals${saved ? `/${saved.id}` : ''}`, { method: saved ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(saved
          ? { edited_draft: text.trim(), title: journalTitle.trim() } : { generation_id: preview.generation_id, edited_draft: text.trim(), title: journalTitle.trim() }) })
      const data = await readResponse(response, 'Could not save the custom journal. Your draft is still here.')
      if (!Number.isInteger(data?.id) || data.title !== journalTitle.trim() || typeof data.edited_draft !== 'string' || !validRangePreview(rangePreview(data))) {
        throw new Error('The server returned an invalid saved custom journal. Refresh the saved library before retrying.')
      }
      setSaved(data); setText(data.edited_draft); setJournalTitle(data.title ?? ''); setHistoryVersion(v => v + 1)
    } catch (err) { setSaveError(err.message) } finally { setPending('') }
  }

  async function open(id) {
    if (busy || !canReplace()) return
    setHistoryError(''); setPending('open')
    try {
      const response = await fetch(`${API}/range-journals/${id}`)
      const data = await readResponse(response, 'Could not open the custom journal.')
      if (data?.id !== id || typeof data.edited_draft !== 'string' || !validRangePreview(rangePreview(data))) {
        throw new Error('The saved custom journal has an unsupported format.')
      }
      setPreview(rangePreview(data)); setSaved(data); setText(data.edited_draft); setJournalTitle(data.title ?? ''); setEditorTab('custom-saved'); setSaveError(''); setMessage('')
    } catch (err) { setHistoryError(err.message) } finally { setPending('') }
  }

  function requestDelete(journal) {
    if (busy) return
    setDeleteTarget(journal); setDeleteError('')
  }
  async function remove() {
    if (busy || !deleteTarget) return
    setDeleteError(''); setPending('delete')
    try {
      const response = await fetch(`${API}/range-journals/${deleteTarget.id}`, { method: 'DELETE' })
      if (response.status !== 204 && response.status !== 404) {
        await readResponse(response, 'Could not delete the custom journal.')
        throw new Error('The server did not confirm deletion. Refresh the custom library to check its status.')
      }
      if (saved?.id === deleteTarget.id) { setPreview(null); setSaved(null); setText(''); setJournalTitle(''); setSaveError('') }
      setMessage(`Custom journal #${deleteTarget.id} ${response.status === 404 ? 'was already deleted' : 'deleted'}.`)
      setDeleteTarget(null); setHistoryVersion(v => v + 1)
    } catch (err) { setDeleteError(err.message) } finally { setPending('') }
  }

  const editor = preview && editorTab === activeTab && <JournalView key={preview.generation_id} preview={preview}
    savedJournal={saved} text={text} name={journalTitle} onNameChange={setJournalTitle} onChange={setText} onSave={save} onDelete={() => requestDelete(saved)}
    busy={busy} saving={action === 'save'} deleting={action === 'delete'} isSaved={isSaved} error={saveError}
    backLabel="Back to custom journals" onBack={editorTab === 'custom-saved' ? () => {
      document.getElementById('custom-history-heading')?.focus()
      document.getElementById('custom-history-heading')?.scrollIntoView({ block: 'start' })
    } : undefined} />

  return <>
    <section id="custom-panel" role="tabpanel" aria-labelledby="custom-tab" hidden={activeTab !== 'custom'} tabIndex={0} className="cr-panel">
      <CustomRangeForm start={start} end={end} notes={notes} options={options} optionsError={optionsError}
        onRetry={() => setRetry(v => v + 1)} onStart={setStart} onEnd={setEnd} onNotes={setNotes}
        onSubmit={generate} busy={busy} loading={action === 'generate'} error={error} />
      {editorTab === 'custom' && editor}
    </section>
    <section id="custom-saved-panel" role="tabpanel" aria-labelledby="custom-saved-tab" hidden={activeTab !== 'custom-saved'} tabIndex={0} className="cr-panel">
      {message && <p role="status">{message}</p>}{historyError && <p className="jv-error" role="alert">{historyError}</p>}
      {action === 'open' && <p role="status">Opening custom journal…</p>}
      <CustomRangeHistory active={activeTab === 'custom-saved'} refreshVersion={historyVersion} onOpen={open} onDelete={requestDelete} busy={busy} />
      {editorTab === 'custom-saved' && editor}
    </section>
    {deleteTarget && <DeleteJournalDialog journal={deleteTarget} hasUnsavedEdits={saved?.id === deleteTarget.id && !isSaved}
      pending={action === 'delete'} error={deleteError} onCancel={() => setDeleteTarget(null)} onConfirm={remove} />}
  </>
}
