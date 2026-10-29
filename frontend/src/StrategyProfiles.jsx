import { useEffect, useRef, useState } from 'react'
import DeleteStrategyProfileDialog from './DeleteStrategyProfileDialog.jsx'
import './StrategyProfiles.css'

const API_URL = 'http://127.0.0.1:8000/strategy-profiles'

function isProfile(value) {
  return Number.isInteger(value?.id) && value.id > 0 &&
    typeof value.name === 'string' && value.name.trim() !== '' &&
    typeof value.rules === 'string' && value.rules.trim() !== ''
}

export default function StrategyProfiles({ busy, onUse, onDeleted, onBusyChange, onDirtyChange }) {
  const listRequest = useRef(null)
  const editorHeading = useRef(null)
  const [page, setPage] = useState(null)
  const [listError, setListError] = useState('')
  const [reload, setReload] = useState(0)
  const [selected, setSelected] = useState(null)
  const [name, setName] = useState('')
  const [rules, setRules] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [message, setMessage] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const loading = page === null && !listError
  const blocked = busy || saving || deleting || loading
  const dirty = name !== (selected?.name ?? '') || rules !== (selected?.rules ?? '')

  useEffect(() => {
    onDirtyChange(dirty)
  }, [dirty, onDirtyChange])

  useEffect(() => {
    const controller = new AbortController()
    listRequest.current = controller
    async function loadProfiles() {
      try {
        const response = await fetch(API_URL, { signal: controller.signal })
        const data = await response.json().catch(() => null)
        if (!response.ok) throw new Error('Could not load strategy profiles. Please try again.')
        if (!Array.isArray(data?.items) || !Number.isInteger(data.total) ||
            !data.items.every(isProfile)) {
          throw new Error('The server returned an invalid profile list.')
        }
        if (!controller.signal.aborted) setPage(data)
      } catch (err) {
        if (!controller.signal.aborted) setListError(err.message)
      }
    }
    loadProfiles()
    return () => controller.abort()
  }, [reload])

  function refreshProfiles() {
    if (blocked) return
    setPage(null)
    setListError('')
    setReload((value) => value + 1)
  }

  function openEditor(profile) {
    if (blocked) return
    if (dirty && !window.confirm('Discard the unsaved profile changes and open another profile?')) return
    setSelected(profile)
    setName(profile?.name ?? '')
    setRules(profile?.rules ?? '')
    setSaveError('')
    setMessage('')
    requestAnimationFrame(() => {
      editorHeading.current?.focus({ preventScroll: true })
      editorHeading.current?.scrollIntoView({ block: 'nearest' })
    })
  }

  function requestDeleteProfile(profile) {
    if (blocked) return
    setDeleteError('')
    setMessage('')
    setDeleteTarget(profile)
  }

  async function deleteProfile() {
    if (blocked || !deleteTarget) return
    const target = deleteTarget
    // An older list response must not put a deleted profile back in the list.
    listRequest.current?.abort()
    setDeleting(true)
    onBusyChange(true)
    setDeleteError('')
    try {
      const response = await fetch(`${API_URL}/${target.id}`, { method: 'DELETE' })
      if (response.status !== 204 && response.status !== 404) {
        const data = await response.json().catch(() => null)
        throw new Error(typeof data?.detail === 'string'
          ? data.detail : `Could not delete the profile (${response.status}). Please try again.`)
      }
      setPage((current) => {
        if (!current) return current
        const items = current.items.filter((profile) => profile.id !== target.id)
        return { items, total: items.length }
      })
      if (selected?.id === target.id) {
        setSelected(null)
        setName('')
        setRules('')
        setSaveError('')
      }
      onDeleted(target.id)
      setDeleteTarget(null)
      setListError('')
      setReload((value) => value + 1)
      setMessage(response.status === 404
        ? `“${target.name}” was already deleted. The profile list has been refreshed.`
        : `Deleted “${target.name}”. Existing journals and rules copied into the generation form are kept.`)
    } catch (err) {
      setDeleteError(err.message)
    } finally {
      setDeleting(false)
      onBusyChange(false)
    }
  }

  async function saveProfile(event) {
    event.preventDefault()
    if (blocked || !dirty) return
    const cleanName = name.trim()
    const cleanRules = rules.trim()
    setSaveError('')
    setMessage('')
    if (!cleanName || cleanName.length > 100 || !cleanRules || cleanRules.length > 10000) {
      setSaveError('Enter a name of 1–100 characters and strategy rules of 1–10,000 characters.')
      return
    }
    setSaving(true)
    onBusyChange(true)
    try {
      const response = await fetch(selected ? `${API_URL}/${selected.id}` : API_URL, {
        method: selected ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: cleanName, rules: cleanRules }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(typeof data?.detail === 'string'
          ? data.detail : `Could not save the profile (${response.status}).`)
      }
      if (!isProfile(data) || (selected && data.id !== selected.id)) {
        throw new Error('The server did not confirm the saved profile.')
      }
      setPage((current) => {
        const items = [...(current?.items ?? []).filter((profile) => profile.id !== data.id), data]
        items.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
        return { items, total: items.length }
      })
      setSelected(data)
      setName(data.name)
      setRules(data.rules)
      setListError('')
      setReload((value) => value + 1)
      setMessage(`Saved “${data.name}”. You can now use it in a journal.`)
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
      onBusyChange(false)
    }
  }

  return (
    <section className="strategy-profiles" aria-labelledby="profiles-heading">
      <header className="sp-heading">
        <p className="sp-eyebrow">YOUR STRATEGIES</p>
        <h2 id="profiles-heading">Strategy profiles</h2>
        <p>Keep your rules in one place, ready for your next journal.</p>
      </header>
      {deleteTarget && (
        <DeleteStrategyProfileDialog
          profile={deleteTarget}
          hasUnsavedEdits={selected?.id === deleteTarget.id && dirty}
          pending={deleting}
          error={deleteError}
          onCancel={() => { if (!deleting) setDeleteTarget(null) }}
          onConfirm={deleteProfile}
        />
      )}
      <div className="sp-layout">
        <section className="sp-library" aria-labelledby="profile-list-heading">
          <header className="sp-library-heading">
            <h3 id="profile-list-heading">Saved profiles</h3>
            {page && <span className="sp-count" aria-label={`${page.total} saved profiles`}>{page.total}</span>}
          </header>
          <div className="sp-library-tools">
            <button className="sp-button sp-new" type="button" onClick={() => openEditor(null)} disabled={blocked}>
              <span aria-hidden="true">+</span> New profile
            </button>
            <button className="sp-button sp-subtle" type="button" onClick={refreshProfiles} disabled={blocked}>Refresh profiles</button>
          </div>
          {loading && <p className="sp-list-status" role="status">Loading profiles…</p>}
          {listError && <p className="sp-alert sp-error" role="alert">{listError}</p>}
          {page?.items.length === 0 && <div className="sp-empty">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2" stroke="currentColor" strokeWidth="1.4" /><path d="M9 8h6M9 12h6M9 16h4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
            <h4>Your first strategy starts here</h4>
            <p>Give it a name and add your rules in the form. Saved profiles will appear here.</p>
          </div>}
          {page?.items.length > 0 && (
            <ul className="sp-profile-list">
              {page.items.map((profile) => (
                <li key={profile.id} className={`sp-profile-card${selected?.id === profile.id ? ' sp-selected' : ''}`}>
                  <div className="sp-profile-title">
                    <h4>{profile.name}</h4>
                    {selected?.id === profile.id && <span className="sp-editing">Editing</span>}
                  </div>
                  <p className="sp-rule-preview">
                    {profile.rules.length > 160 ? `${profile.rules.slice(0, 160)}…` : profile.rules}
                  </p>
                  <div className="sp-profile-actions">
                    <button className="sp-button sp-small" type="button" aria-label={`Edit ${profile.name}`} onClick={() => openEditor(profile)} disabled={blocked}>Edit</button>
                    <button
                      className="sp-button sp-small sp-use"
                      type="button"
                      aria-label={`Use ${profile.name} in journal`}
                      onClick={() => onUse(profile)}
                      disabled={blocked || (selected?.id === profile.id && dirty)}
                      aria-describedby={selected?.id === profile.id && dirty ? 'profile-unsaved-help' : undefined}
                    >Use in journal</button>
                    <button className="sp-button sp-small sp-danger sp-subtle" type="button" aria-label={`Delete ${profile.name}`} onClick={() => requestDeleteProfile(profile)} disabled={blocked}>Delete</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="sp-editor-column" aria-labelledby="profile-editor-heading">
          <form className="sp-editor" onSubmit={saveProfile} aria-busy={saving}>
            <header className="sp-editor-heading">
              <div>
                <h3 id="profile-editor-heading" ref={editorHeading} tabIndex={-1}>{selected ? 'Edit strategy profile' : 'New strategy profile'}</h3>
                <p>{selected ? 'Refine your rules and save the updated profile.' : 'Create a reusable set of rules for your session reviews.'}</p>
              </div>
              <span className={`sp-badge${dirty ? ' sp-badge-dirty' : ''}`}>{dirty ? 'Unsaved changes' : selected ? 'Saved profile' : 'New profile'}</span>
            </header>
            <div className="sp-field">
              <label htmlFor="profile-name">Profile name <span aria-hidden="true">Required</span></label>
              <input id="profile-name" value={name} onChange={(event) => { setName(event.target.value); setMessage('') }} required maxLength={100} disabled={blocked} aria-describedby="profile-name-help profile-name-count" placeholder="e.g. EUR/USD trend & momentum" />
              <div className="sp-field-footer"><p id="profile-name-help">Choose a name you’ll recognize later.</p><span id="profile-name-count">{name.length} / 100</span></div>
            </div>
            <div className="sp-field sp-rules-field">
              <label htmlFor="profile-rules">Profile strategy rules <span aria-hidden="true">Required</span></label>
              <p id="profile-rules-help" className="sp-help">Include bullish and bearish factors, indicator settings, and when each condition should hold.</p>
              <textarea
                id="profile-rules"
                value={rules}
                onChange={(event) => { setRules(event.target.value); setMessage('') }}
                rows={12}
                required
                maxLength={10000}
                disabled={blocked}
                aria-describedby="profile-rules-help profile-rules-count"
                placeholder={'Bullish factors:\nDescribe the conditions you want checked.\n\nBearish factors:\nDescribe the conditions you want checked.\n\nTiming & context:\nState when the conditions should apply.'}
              />
              <div className="sp-field-footer"><span>Your rules, in your own words</span><span id="profile-rules-count">{rules.length.toLocaleString()} / 10,000 characters</span></div>
            </div>
            {saveError && <div className="sp-alert sp-error" role="alert"><strong>Could not save profile</strong><p>{saveError}</p></div>}
            {message && <p className="sp-alert sp-feedback" role="status">{message}</p>}
            {dirty && <p className="sp-unsaved" id="profile-unsaved-help" role="status">Unsaved profile changes. Save before using this version in a journal.</p>}
            <footer className="sp-editor-actions">
              {selected && (
                <button className="sp-button sp-danger sp-subtle" type="button" onClick={() => requestDeleteProfile(selected)} disabled={blocked}>Delete profile</button>
              )}
              <button className="sp-button sp-primary" type="submit" disabled={blocked || !dirty}>
                {saving ? <><span className="sp-spinner" aria-hidden="true" />Saving profile…</> : selected ? 'Save profile changes' : 'Save profile'}
              </button>
            </footer>
            {saving && <p className="sp-progress" role="status">Saving your strategy profile…</p>}
          </form>
          <aside className="sp-reuse-note" aria-labelledby="profile-reuse-heading">
            <h4 id="profile-reuse-heading">From profile to journal</h4>
            <p><strong>Use in journal</strong> copies a saved profile’s rules into the generation form. Customize that copy for a session without changing your saved profile.</p>
            <p>Switching tabs keeps your edits here. Updating a profile leaves past journals unchanged.</p>
          </aside>
        </section>
      </div>
    </section>
  )
}
