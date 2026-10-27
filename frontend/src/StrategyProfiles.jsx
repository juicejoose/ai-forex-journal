import { useEffect, useRef, useState } from 'react'
import DeleteStrategyProfileDialog from './DeleteStrategyProfileDialog.jsx'

const API_URL = 'http://127.0.0.1:8000/strategy-profiles'
const fieldStyle = { width: '100%', boxSizing: 'border-box', padding: '0.5rem' }

function isProfile(value) {
  return Number.isInteger(value?.id) && value.id > 0 &&
    typeof value.name === 'string' && value.name.trim() !== '' &&
    typeof value.rules === 'string' && value.rules.trim() !== ''
}

export default function StrategyProfiles({ busy, onUse, onDeleted, onBusyChange, onDirtyChange }) {
  const listRequest = useRef(null)
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
    <section aria-labelledby="profiles-heading" style={{ textAlign: 'left' }}>
      <h2 id="profiles-heading">Strategy profiles</h2>
      <p>Save named strategies and reuse their rules when generating a journal.</p>
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
      <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', marginTop: '1rem' }}>
        <section aria-labelledby="profile-list-heading" style={{ flex: '1 1 16rem', minWidth: 0 }}>
          <h3 id="profile-list-heading">Saved profiles</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            <button type="button" onClick={() => openEditor(null)} disabled={blocked}>New profile</button>
            <button type="button" onClick={refreshProfiles} disabled={blocked}>Refresh profiles</button>
          </div>
          {loading && <p role="status">Loading profiles...</p>}
          {listError && <p role="alert">{listError}</p>}
          {page?.items.length === 0 && <p>No profiles yet. Create your first strategy using the form.</p>}
          {page && (
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {page.items.map((profile) => (
                <li key={profile.id} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '0.75rem', marginBottom: '0.75rem', overflowWrap: 'anywhere' }}>
                  <h4 style={{ margin: '0 0 0.5rem' }}>{profile.name}</h4>
                  <p style={{ whiteSpace: 'pre-wrap' }}>
                    {profile.rules.length > 160 ? `${profile.rules.slice(0, 160)}…` : profile.rules}
                  </p>
                  <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                    <button type="button" aria-label={`Edit ${profile.name}`} onClick={() => openEditor(profile)} disabled={blocked}>Edit</button>
                    <button
                      type="button"
                      aria-label={`Use ${profile.name} in journal`}
                      onClick={() => onUse(profile)}
                      disabled={blocked || (selected?.id === profile.id && dirty)}
                    >Use in journal</button>
                    <button type="button" aria-label={`Delete ${profile.name}`} onClick={() => requestDeleteProfile(profile)} disabled={blocked}>Delete</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="profile-editor-heading" style={{ flex: '2 1 24rem', minWidth: 0 }}>
          <h3 id="profile-editor-heading">{selected ? 'Edit strategy profile' : 'New strategy profile'}</h3>
          <form onSubmit={saveProfile}>
            <div style={{ marginBottom: '1rem' }}>
              <label htmlFor="profile-name">Profile name</label>
              <input id="profile-name" value={name} onChange={(event) => { setName(event.target.value); setMessage('') }} required maxLength={100} disabled={blocked} style={fieldStyle} />
            </div>
            <div style={{ marginBottom: '1rem' }}>
              <label htmlFor="profile-rules">Profile strategy rules</label>
              <textarea
                id="profile-rules"
                value={rules}
                onChange={(event) => { setRules(event.target.value); setMessage('') }}
                rows={10}
                required
                maxLength={10000}
                disabled={blocked}
                style={{ ...fieldStyle, lineHeight: 1.6 }}
                placeholder="Describe your bullish and bearish factors, indicator periods, and when conditions must hold."
              />
            </div>
            <button type="submit" disabled={blocked || !dirty}>
              {saving ? 'Saving profile...' : selected ? 'Save profile changes' : 'Save profile'}
            </button>
            {selected && (
              <button type="button" onClick={() => requestDeleteProfile(selected)} disabled={blocked} style={{ marginLeft: '0.5rem' }}>
                Delete profile
              </button>
            )}
          </form>
          {saveError && <p role="alert">{saveError}</p>}
          {message && <p role="status">{message}</p>}
          {dirty && <p role="status">Unsaved profile changes. Save before using this version in a journal.</p>}
          <p style={{ marginTop: '1rem' }}>
            Switching tabs keeps your profile edits here. Using a saved profile copies its rules
            into the generation form. You can customize that copy for an individual journal.
          </p>
        </section>
      </div>
    </section>
  )
}
