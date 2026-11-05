import { useEffect, useState } from 'react'
import JournalHistory from './JournalHistory.jsx'
import GenerateJournalForm from './GenerateJournalForm.jsx'
import JournalView from './JournalView.jsx'
import StrategyProfiles from './StrategyProfiles.jsx'
import DeleteJournalDialog from './DeleteJournalDialog.jsx'
import CustomRangeJournals from './CustomRangeJournals.jsx'
import TodayPage from './TodayPage.jsx'
import { journalEditsSaved } from './journalNames.js'
import { CURRENT_RULE_SET_ID, isRetiredRuleSet } from './strategyChoices.js'

const tabs = [
  { id: 'today', label: 'Today' },
  { id: 'generate', label: 'Generate journal' },
  { id: 'saved', label: 'Saved journals' },
  { id: 'custom', label: 'Custom range journal' },
  { id: 'custom-saved', label: 'Saved custom journals' },
  { id: 'profiles', label: 'Strategy profiles' },
]

function App() {
  const [todayBusy, setTodayBusy] = useState(false)
  const [todayDirty, setTodayDirty] = useState(false)
  const [rangeBusy, setRangeBusy] = useState(false)
  const [rangeDirtyTab, setRangeDirtyTab] = useState(null)
  const [activeTab, setActiveTab] = useState('generate')
  const [editorTab, setEditorTab] = useState('generate')
  const pair = 'EURUSD'
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [journalDate, setJournalDate] = useState('')
  const timeframe = '4h'
  const [strategy, setStrategy] = useState('')
  const [ruleSetId, setRuleSetId] = useState(CURRENT_RULE_SET_ID)
  const [ruleDefinitions, setRuleDefinitions] = useState([])
  const [ruleError, setRuleError] = useState('')
  const [ruleReload, setRuleReload] = useState(0)
  const [loadedProfile, setLoadedProfile] = useState(null)
  const [profileBusy, setProfileBusy] = useState(false)
  const [profileDirty, setProfileDirty] = useState(false)
  const [editedDraft, setEditedDraft] = useState('')
  const [journalTitle, setJournalTitle] = useState('')

  const [preview, setPreview] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [savedJournal, setSavedJournal] = useState(null)
  const [opening, setOpening] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [historyVersion, setHistoryVersion] = useState(0)
  const [deletingId, setDeletingId] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleteMessage, setDeleteMessage] = useState('')

  const ruleDefinition = ruleDefinitions.find((item) => item.id === ruleSetId)
  const busy = todayBusy || rangeBusy || loading || saving || opening || profileBusy || deletingId !== null

  const isSaved =
    journalEditsSaved(savedJournal, editedDraft, journalTitle)

  useEffect(() => {
    const controller = new AbortController()
    async function loadRuleSet() {
      try {
        const response = await fetch('http://127.0.0.1:8000/strategy-rule-sets', { signal: controller.signal })
        const data = await response.json()
        if (!response.ok || !Array.isArray(data?.items) ||
            !data.items.some((item) => item.id === CURRENT_RULE_SET_ID && item.version === 7 && item.revision === 1 &&
              typeof item.rules === 'string' && item.factors?.length === 4)) {
          throw new Error('Invalid strategy definition')
        }
        if (!controller.signal.aborted) setRuleDefinitions(data.items)
      } catch {
        if (!controller.signal.aborted) setRuleError('Could not load the scored strategy. Check that the updated backend is running, then retry.')
      }
    }
    loadRuleSet()
    return () => controller.abort()
  }, [ruleReload])

  function retryRuleSet() {
    setRuleError('')
    setRuleReload((value) => value + 1)
  }

  function handleTabKeyDown(event, index) {
    if (busy) return
    const nextIndex = {
      ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index - 1 + tabs.length) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }[event.key]
    if (nextIndex === undefined) return
    event.preventDefault()
    const nextTab = tabs[nextIndex].id
    setActiveTab(nextTab)
    document.getElementById(`${nextTab}-tab`)?.focus()
  }

  function handleUseProfile(profile) {
    if (busy || isRetiredRuleSet(profile.rule_set_id)) return
    if (strategy.trim() && strategy.trim() !== profile.rules.trim() &&
        !window.confirm(`Replace the strategy rules in the generation form with “${profile.name}”?`)) {
      return
    }
    setStrategy(profile.rules)
    setRuleSetId(profile.rule_set_id ?? '')
    setLoadedProfile({ id: profile.id, name: profile.name, rules: profile.rules, rule_set_id: profile.rule_set_id ?? null })
    setError('')
    setActiveTab('generate')
    requestAnimationFrame(() => document.getElementById('strategy')?.focus())
  }

  function handleProfileDeleted(profileId) {
    setLoadedProfile((current) => current?.id === profileId ? null : current)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (busy) return
    setSaveError('')
    setError('')
    const trimmedPair = pair.trim()
    const trimmedNotes = notes.trim()
    const trimmedStrategy = (ruleSetId ? ruleDefinition?.rules ?? '' : strategy).trim()

    if (isRetiredRuleSet(ruleSetId)) {
      setError('Choose v7 or Written strategy before generating a journal.')
      return
    }

    if (ruleSetId && !ruleDefinition) {
      setError('The scored strategy must finish loading before generating a journal.')
      return
    }


    if (!trimmedPair) {
      setError('Please enter a currency pair.')
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
            rule_set_id: ruleSetId || null,
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

      if (
        !data?.entry || typeof data?.draft !== 'string' || !data.draft.trim() ||
        typeof data.generation_id !== 'string' ||
        !data.market_data?.session?.complete ||
        !Array.isArray(data.market_data?.candles) || data.market_data.candles.length !== 6 ||
        (ruleSetId && (data.rule_evaluation?.rule_set?.id !== ruleSetId || data.rule_evaluation?.candles?.length !== 6))
      ) {
        throw new Error('The server did not return a journal draft.')
      }

      setPreview(data)
      setEditedDraft(data.draft)
      setJournalTitle('')
      setSavedJournal(null)
      setEditorTab('generate')

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
      ? { edited_draft: text, title: journalTitle.trim() }
      : {
        generation_id: preview.generation_id,
        edited_draft: text,
        title: journalTitle.trim(),
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

      if (!Number.isInteger(data?.id) || typeof data?.edited_draft !== 'string' || data.title !== journalTitle.trim()) {
        throw new Error('The server did not confirm the saved entry.')
      }

      setSavedJournal(data)
      setEditedDraft(data.edited_draft)
      setJournalTitle(data.title ?? '')
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
      !window.confirm(`Discard the unsaved journal in the ${editorTab === 'generate' ? 'Generate journal' : 'Saved journals'} tab and open this entry?`)
    ) {
      return
    }

    setHistoryError('')
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
          rule_set_id: data.rule_evaluation?.rule_set?.id ?? null,
        },
        draft: data.original_draft,
        generation_id: data.generation_id,
        market_data: data.market_data ?? null,
        rule_evaluation: data.rule_evaluation ?? null,
      })

      setEditedDraft(data.edited_draft)
      setJournalTitle(data.title ?? '')
      setSavedJournal(data)
      setEditorTab('saved')
    } catch (err) {
      setHistoryError(err.message)
    } finally {
      setOpening(false)
    }
  }

  function requestDeleteJournal(journal) {
    if (busy) return
    setDeleteError('')
    setDeleteMessage('')
    setDeleteTarget(journal)
  }

  async function handleDeleteJournal() {
    if (busy || !deleteTarget) return
    const journal = deleteTarget
    const isOpenJournal = savedJournal?.id === journal.id
    setDeletingId(journal.id)
    setDeleteError('')
    setDeleteMessage('')

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/journals/${journal.id}`,
        { method: 'DELETE' }
      )
      // A stale entry may already have been removed in another browser tab.
      if (response.status !== 204 && response.status !== 404) {
        const data = await response.json().catch(() => null)
        throw new Error(typeof data?.detail === 'string'
          ? data.detail : `Could not delete journal (${response.status}). Please try again.`)
      }

      if (isOpenJournal) {
        setPreview(null)
        setEditedDraft('')
        setJournalTitle('')
        setSavedJournal(null)
        setSaveError('')
        setHistoryError('')
      }
      setDeleteTarget(null)
      setHistoryVersion((value) => value + 1)
      setDeleteMessage(response.status === 404
        ? `Journal #${journal.id} was already deleted. History refreshed.`
        : `Journal #${journal.id} deleted.`)
    } catch (err) {
      setDeleteError(err.message)
    } finally {
      setDeletingId(null)
    }
  }

  const journalEditor = preview && activeTab === editorTab && (
    <JournalView
      key={preview.generation_id || savedJournal?.id || 'draft'}
      preview={preview}
      savedJournal={savedJournal}
      text={editedDraft}
      name={journalTitle}
      onNameChange={setJournalTitle}
      onChange={setEditedDraft}
      onSave={handleSave}
      onDelete={() => requestDeleteJournal(savedJournal)}
      busy={busy}
      saving={saving}
      deleting={deletingId === savedJournal?.id}
      isSaved={isSaved}
      error={saveError}
      onBack={editorTab === 'saved' ? () => {
        document.querySelector('.jh-day[aria-pressed="true"]')?.focus({ preventScroll: true })
        document.getElementById('history-heading')?.scrollIntoView({ block: 'start' })
      } : undefined}
    />
  )

  return (
    <main>
      <h1>Forex AI Journal</h1>
      <p>Review EUR/USD sessions against your strategy, as they unfold or after the close.</p>

      <div
        role="tablist"
        aria-label="Journal pages"
        style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', padding: '1rem', borderBottom: '1px solid var(--border)' }}
      >
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            id={`${tab.id}-tab`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`${tab.id}-panel`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => setActiveTab(tab.id)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
            disabled={busy}
            style={{
              padding: '0.65rem 1rem',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              background: activeTab === tab.id ? 'var(--accent-bg)' : 'var(--bg)',
              color: 'var(--text-h)',
              fontWeight: activeTab === tab.id ? 700 : 400,
              cursor: busy ? 'wait' : 'pointer',
            }}
          >
            {tab.label}
            {preview && editorTab === tab.id && !isSaved && ' · Unsaved'}
            {tab.id === 'profiles' && profileDirty && ' · Unsaved'}
            {tab.id === rangeDirtyTab && ' · Unsaved'}
            {tab.id === 'today' && todayDirty && ' · Unsaved'}
          </button>
        ))}
      </div>

      {deleteTarget && (
        <DeleteJournalDialog
          journal={deleteTarget}
          hasUnsavedEdits={savedJournal?.id === deleteTarget.id && !isSaved}
          pending={deletingId !== null}
          error={deleteError}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={handleDeleteJournal}
        />
      )}
      {deleteMessage && <p role="status">{deleteMessage}</p>}

      <section
        id="generate-panel"
        role="tabpanel"
        aria-labelledby="generate-tab"
        hidden={activeTab !== 'generate'}
        tabIndex={0}
        style={{ padding: '1rem' }}
      >
        <GenerateJournalForm
          pair={pair}
          journalDate={journalDate}
          timeframe={timeframe}
          strategy={ruleSetId ? ruleDefinition?.rules ?? '' : strategy}
          ruleSetId={ruleSetId}
          ruleDefinition={ruleDefinition}
          ruleDefinitions={ruleDefinitions}
          ruleError={ruleError}
          onRetryRules={retryRuleSet}
          onRuleSetChange={(value) => { setRuleSetId(value); setLoadedProfile(null); setError('') }}
          notes={notes}
          loadedProfile={loadedProfile}
          busy={busy}
          loading={loading}
          error={error}
          onDateChange={setJournalDate}
          onStrategyChange={setStrategy}
          onNotesChange={setNotes}
          onChooseProfile={() => {
            setActiveTab('profiles')
            requestAnimationFrame(() => document.getElementById('profiles-tab')?.focus())
          }}
          onSubmit={handleSubmit}
        />

        {editorTab === 'generate' && journalEditor}
      </section>

      <section
        id="saved-panel"
        role="tabpanel"
        aria-labelledby="saved-tab"
        hidden={activeTab !== 'saved'}
        tabIndex={0}
        style={{ padding: '1rem' }}
      >
        {historyError && <p role="alert">{historyError}</p>}
        {opening && <p role="status">Opening journal...</p>}

        <JournalHistory
          refreshVersion={historyVersion}
          onOpen={handleOpenJournal}
          onDelete={requestDeleteJournal}
          deletingId={deletingId}
          busy={busy}
        />
        {editorTab === 'saved' && journalEditor}
      </section>

      <section
        id="profiles-panel"
        role="tabpanel"
        aria-labelledby="profiles-tab"
        hidden={activeTab !== 'profiles'}
        tabIndex={0}
        style={{ padding: '1rem' }}
      >
        <StrategyProfiles
          ruleDefinitions={ruleDefinitions}
          ruleError={ruleError}
          onRetryRules={retryRuleSet}
          busy={busy}
          onUse={handleUseProfile}
          onDeleted={handleProfileDeleted}
          onBusyChange={setProfileBusy}
          onDirtyChange={setProfileDirty}
        />
      </section>
      <TodayPage active={activeTab === 'today'} busy={busy} onBusyChange={setTodayBusy} onDirtyChange={setTodayDirty}
        onSaved={() => setHistoryVersion(value => value + 1)} />
      <CustomRangeJournals activeTab={activeTab}
        onBusyChange={setRangeBusy} onDirtyTabChange={setRangeDirtyTab} busy={busy} />
    </main>
  )
}

export default App
