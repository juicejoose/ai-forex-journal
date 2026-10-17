import { useState } from 'react'
import JournalHistory from './JournalHistory.jsx'

function App() {
  const [pair, setPair] = useState('EURUSD')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [journalDate, setJournalDate] = useState('')
  const [timeframe, setTimeframe] = useState('1h')
  const [strategy, setStrategy] = useState('')
  const [editedDraft, setEditedDraft] = useState('')

  const [preview, setPreview] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [savedJournal, setSavedJournal] = useState(null)
  const [opening, setOpening] = useState(false)
  const [historyVersion, setHistoryVersion] = useState(0)

  const busy = loading || saving || opening

  const isSaved =
    savedJournal !== null && editedDraft.trim() === savedJournal.edited_draft

  async function handleSubmit(event) {
    event.preventDefault()
    if (busy) return
    setSaveError('')
    setError('')
    const trimmedPair = pair.trim()
    const trimmedNotes = notes.trim()
    const trimmedStrategy = strategy.trim()


    if (!trimmedPair) {
      setError('Please enter a currency pair.')
      return
    }

    if (!trimmedNotes) {
      setError('Please enter your market observations.')
      return
    }

    if (!journalDate) {
      setError('Please choose a journal date.')
      return
    }

    if (!trimmedStrategy) {
      setError('Please enter your strategy rules.')
      return
    }

    if (
      preview &&
      !isSaved &&
      !window.confirm('Replace the unsaved journal in the editor with a new draft?')
    ) {
      return
    }

    setLoading(true)

    try {
      const response = await fetch(
        'http://127.0.0.1:8000/journal/generate',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            pair: trimmedPair,
            journal_date: journalDate,
            timeframe,
            strategy: trimmedStrategy,
            notes: trimmedNotes,
          }),
        }
      )

      const data = await response.json().catch(() => null)

      if (!response.ok) {
        const message =
          typeof data?.detail === 'string'
            ? data.detail
            : `Request failed (${response.status}). Please check your inputs.`

        throw new Error(message)
      }

      if (!data?.entry || typeof data?.draft !== 'string' || !data.draft.trim()) {
        throw new Error('The server did not return a journal draft.')
      }

      setPreview(data)
      setEditedDraft(data.draft)
      setSavedJournal(null)

    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    if (!preview || busy || isSaved) return

    setSaveError('')
    const text = editedDraft.trim()

    if (!text || text.length > 20000) {
      setSaveError('Please enter a journal between 1 and 20,000 characters.')
      return
    }

    const existingId = savedJournal?.id

    const url = existingId
      ? `http://127.0.0.1:8000/journals/${existingId}`
      : 'http://127.0.0.1:8000/journals'

    const body = existingId
      ? { edited_draft: text }
      : {
        entry: preview.entry,
        original_draft: preview.draft,
        edited_draft: text,
      }

    setSaving(true)

    try {
      const response = await fetch(url, {
        method: existingId ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      const data = await response.json().catch(() => null)

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === 'string'
            ? data.detail
            : `Could not save journal (${response.status}).`
        )
      }

      if (!Number.isInteger(data?.id) || typeof data?.edited_draft !== 'string') {
        throw new Error('The server did not confirm the saved entry.')
      }

      setSavedJournal(data)
      setEditedDraft(data.edited_draft)
      setHistoryVersion((value) => value + 1)
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleOpenJournal(journalId) {
    if (busy) return

    if (
      preview &&
      !isSaved &&
      !window.confirm('Discard the unsaved journal in the editor and open this entry?')
    ) {
      return
    }

    setError('')
    setSaveError('')
    setOpening(true)

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/journals/${journalId}`
      )
      const data = await response.json().catch(() => null)

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === 'string'
            ? data.detail
            : 'Could not open this journal.'
        )
      }

      const textFields = [
        'pair', 'journal_date', 'timeframe', 'strategy', 'notes',
        'original_draft', 'edited_draft',
      ]

      if (
        data?.id !== journalId ||
        !textFields.every((field) => typeof data[field] === 'string')
      ) {
        throw new Error('The server returned an invalid journal.')
      }

      setPreview({
        entry: {
          pair: data.pair,
          journal_date: data.journal_date,
          timeframe: data.timeframe,
          strategy: data.strategy,
          notes: data.notes,
        },
        draft: data.original_draft,
      })

      setEditedDraft(data.edited_draft)
      setSavedJournal(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setOpening(false)
    }
  }

  return (
    <main>
      <h1>Forex AI Journal</h1>
      <p>Turn your market observations into journal entries.</p>

      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="pair">Currency pair</label>
          <input
            id="pair"
            type="text"
            value={pair}
            onChange={(event) => setPair(event.target.value)}
            maxLength={20}
          />
        </div>

        <div>
          <label htmlFor="journal-date">Journal date</label>
          <input
            id="journal-date"
            type="date"
            value={journalDate}
            onChange={(event) => setJournalDate(event.target.value)}
          />
        </div>

        <div>
          <label htmlFor="timeframe">Candle timeframe</label>
          <select
            id="timeframe"
            value={timeframe}
            onChange={(event) => setTimeframe(event.target.value)}
          >
            <option value="15m">15 minutes</option>
            <option value="1h">1 hour</option>
            <option value="4h">4 hours</option>
            <option value="1d">1 day</option>
          </select>
        </div>

        <div>
          <label htmlFor="strategy">Strategy rules</label>
          <textarea
            id="strategy"
            rows={5}
            value={strategy}
            onChange={(event) => setStrategy(event.target.value)}
            maxLength={10000}
          />
        </div>

        <div>
          <label htmlFor="notes">Market observations</label>
          <textarea
            id="notes"
            rows={5}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            maxLength={10000}
          />
        </div>

        <button type="submit" disabled={busy}>
          {loading ? 'Generating...' : 'Generate journal'}
        </button>

      </form>

      {error && <p role="alert">{error}</p>}

      {opening && <p role="status">Opening journal...</p>}

      <JournalHistory
        key={historyVersion}
        onOpen={handleOpenJournal}
        busy={busy}
      />

      {preview && (
        <section>
          <h2>
            {savedJournal ? `Journal #${savedJournal.id}` : 'AI journal draft'}
          </h2>

          <p>Currency pair: {preview.entry.pair}</p>
          <p>Journal date: {preview.entry.journal_date}</p>
          <p>Candle timeframe: {preview.entry.timeframe}</p>
          <p>Strategy rules: {preview.entry.strategy}</p>
          <p>Observations: {preview.entry.notes}</p>

          <div>
            <label htmlFor="journal-draft">Review and edit your journal</label>

            <textarea
              id="journal-draft"
              rows={18}
              value={editedDraft}
              onChange={(event) => setEditedDraft(event.target.value)}
              disabled={busy}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                lineHeight: 1.6,
              }}
              maxLength={20000}
            />

            <button
              type="button"
              onClick={() => setEditedDraft(preview.draft)}
              disabled={busy || editedDraft === preview.draft}
            >
              Restore AI draft
            </button>
          </div>

          <button
            type="button"
            onClick={handleSave}
            disabled={busy || isSaved || !editedDraft.trim()}
          >
            {saving ? 'Saving...' : isSaved ? 'Saved' : 'Save journal'}
          </button>

          {saveError && <p role="alert">{saveError}</p>}

          <p role="status">
            {isSaved
              ? `Saved as journal #${savedJournal.id}.`
              : savedJournal
                ? `Unsaved changes to journal #${savedJournal.id}.`
                : 'This draft has not been saved yet.'}
          </p>

          <p>Generating another journal replaces the draft shown here.</p>
        </section>
      )}
    </main>
  )
}

export default App