import { useEffect, useId, useRef, useState } from 'react'
import MarketReview from './MarketReview.jsx'
import { formatDay, isDateKey } from './journalCalendar.js'
import { isShortSummary, journalSections } from './journalPresentation.js'
import './JournalView.css'
import { JOURNAL_NAME_LIMIT } from './journalNames.js'

export default function JournalView({ preview, savedJournal, text, onChange, onSave, name, onNameChange,
  onDelete, busy, saving, deleting, isSaved, error, onBack, backLabel = 'Back to calendar', showEvidence = true }) {
  const [mode, setMode] = useState('read')
  const headingRef = useRef(null)
  const nameId = useId()
  const sections = journalSections(text)
  const shortSummary = isShortSummary(sections)
  const showOutline = !shortSummary && sections.some((section) => section.title)
  const entry = preview.entry
  const customRange = preview.market_data?.analysis_kind === 'custom_range'
  const partial = preview.rule_evaluation?.summary?.method === 'session_to_date'
  const cutoff = preview.market_data?.data_through
  const cutoffText = cutoff ? new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date(cutoff)) : ''
  const pair = entry.pair.replace(/^EUR_?\/?USD$/, 'EUR/USD')
  const date = customRange ? `${formatDay(entry.start_date)} – ${formatDay(entry.end_date)}`
    : isDateKey(entry.journal_date) ? formatDay(entry.journal_date) : entry.journal_date
  const title = savedJournal ? `Journal #${savedJournal.id}` : 'AI journal draft'

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true })
    headingRef.current?.closest('.journal-view')?.scrollIntoView({ block: 'start' })
  }, [preview])

  return <article className="journal-view" aria-labelledby="journal-view-title">
    {onBack && <button type="button" className="jv-back" onClick={onBack} disabled={busy}>← {backLabel}</button>}
    <header className="jv-header">
      <div>
        <p className="jv-eyebrow">{partial ? 'INTRADAY SNAPSHOT' : customRange ? 'CUSTOM RANGE JOURNAL' : 'SESSION JOURNAL'} · {title}</p>
        <h2 id="journal-view-title" ref={headingRef} tabIndex={-1}>{name.trim() || date}</h2>
        {name.trim() && <p className="jv-date-subtitle">{date}</p>}
        <div className="jv-tags">
          <span>{pair}</span><span>{entry.timeframe === '4h' ? '4-hour candles' : entry.timeframe}</span>
          <span className={`jv-save-state ${isSaved ? 'is-saved' : ''}`}>{isSaved ? 'Saved' : savedJournal ? 'Unsaved changes' : 'Unsaved draft'}</span>
        </div>
      </div>
      <button type="button" className="jv-button jv-primary" onClick={onSave} disabled={busy || isSaved || !text.trim()}>
        {saving ? 'Saving…' : isSaved ? 'Saved' : savedJournal ? 'Save changes' : 'Save journal'}
      </button>
    </header>

    <details className="jv-name-editor">
      <summary>{name.trim() ? 'Rename journal' : 'Add a journal name'}</summary>
      <div className="jv-name-field">
      <div className="jv-editor-label"><label htmlFor={nameId}>Journal name <span>(optional)</span></label><span>{name.length} / {JOURNAL_NAME_LIMIT}</span></div>
      <input id={nameId} type="text" value={name} onChange={event => onNameChange(event.target.value)}
        disabled={busy} maxLength={JOURNAL_NAME_LIMIT} aria-describedby={`${nameId}-help`}
        placeholder="e.g. EUR/USD — trend and momentum review" />
      <p id={`${nameId}-help`}>{savedJournal ? 'Rename this journal here, then choose Save changes. Clear the name to use its journal number.' : 'Add a name before saving, or leave it blank to use the journal number.'}</p>
      </div>
    </details>

    {partial && <p className="jv-session-window">Review data through: {cutoffText} · {preview.market_data.candles.length} of 6 candles · Remaining candles were pending. This snapshot does not update with the live page.</p>}
    {showEvidence && <MarketReview snapshot={preview.market_data} evaluation={preview.rule_evaluation} />}

    <details className="jv-context">
      <summary><span>Strategy & observations</span><span className="jv-summary-hint">Your inputs for this {customRange ? 'range' : 'session'}</span></summary>
      <div className="jv-context-grid">
        <section><h3>Strategy rules</h3><p>{entry.strategy}</p></section>
        <section><h3>Your observations</h3><p>{entry.notes || 'None provided.'}</p></section>
      </div>
    </details>

    <section className="jv-report" aria-labelledby="journal-report-heading">
      <header className="jv-report-header">
        <div><p className="jv-eyebrow">{customRange ? 'RANGE REVIEW' : 'SESSION REVIEW'}</p><h3 id="journal-report-heading">{shortSummary ? customRange ? 'Range summary' : 'Session summary' : 'Your journal'}</h3></div>
        <div className="jv-mode" role="group" aria-label="Journal view">
          <button type="button" aria-pressed={mode === 'read'} onClick={() => setMode('read')} disabled={busy}>Read</button>
          <button type="button" aria-pressed={mode === 'edit'} onClick={() => setMode('edit')} disabled={busy}>Edit</button>
        </div>
      </header>
      {mode === 'read' ? <div className={`jv-reading-layout${showOutline ? '' : ' jv-no-outline'}`}>
        {showOutline && <nav className="jv-outline" aria-label="Journal sections">
          <span className="jv-eyebrow">IN THIS JOURNAL</span>
          {sections.map((section, index) => section.title && <a key={index} href={`#journal-section-${index}`}>{section.title}</a>)}
        </nav>}
        <div className="jv-document">
          {sections.length === 0 ? <p className="jv-empty">Your journal is empty. Choose Edit to add your notes.</p> :
            sections.map((section, index) => <section className="jv-document-section" id={`journal-section-${index}`} key={index}>
              {section.title && <h4>{section.title}</h4>}
              <div className="jv-prose">{section.body.split(/\n\s*\n/).filter((paragraph) => paragraph.trim()).map((paragraph, paragraphIndex) => <p key={paragraphIndex}>{paragraph.replace(/^\n+|\n+$/g, '')}</p>)}</div>
            </section>)}
        </div>
      </div> : <div className="jv-edit-panel">
        <div className="jv-editor-label"><label htmlFor="journal-draft">Review and edit your journal</label><span>{text.length.toLocaleString()} / 20,000</span></div>
        <textarea id="journal-draft" rows={22} value={text} onChange={(event) => onChange(event.target.value)} disabled={busy} maxLength={20000} aria-describedby="journal-edit-help" autoFocus />
        <p id="journal-edit-help">Edit any part of the text. Switch to Read to preview your changes, then save when ready.</p>
      </div>}
      <footer className="jv-report-footer">
        <p role="status">{isSaved ? `Saved as journal #${savedJournal.id}.` : savedJournal ? `Unsaved changes to journal #${savedJournal.id}.` : 'This draft has not been saved yet.'}</p>
        <div className="jv-footer-actions">
          <button type="button" className="jv-button" onClick={() => onChange(preview.draft)} disabled={busy || text === preview.draft}>Restore AI draft</button>
          <button type="button" className="jv-button jv-primary" onClick={onSave} disabled={busy || isSaved || !text.trim()}>
            {saving ? 'Saving…' : isSaved ? 'Saved' : savedJournal ? 'Save changes' : 'Save journal'}
          </button>
        </div>
      </footer>
      {error && <p role="alert" className="jv-error">{error}</p>}
    </section>
    <footer className="jv-bottom">
      <p>Switching tabs keeps your journal here. Unsaved changes are lost if you refresh the page.</p>
      {savedJournal && onDelete && <button type="button" className="jv-delete" onClick={onDelete} disabled={busy}>{deleting ? 'Deleting…' : 'Delete journal'}</button>}
    </footer>
  </article>
}
