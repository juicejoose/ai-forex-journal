import { useEffect, useRef } from 'react'
import { setupTime } from './setupEvaluation.js'

export default function DeleteSetupDialog({ setup, pending, error, onCancel, onConfirm }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    dialog.showModal()
    return () => dialog.close()
  }, [])

  return <dialog ref={ref} className="se-delete-dialog" aria-labelledby="delete-setup-title"
    aria-describedby="delete-setup-details delete-setup-warning" aria-busy={pending}
    onCancel={event => { event.preventDefault(); if (!pending) onCancel() }}>
    <h2 id="delete-setup-title">Delete saved setup?</h2>
    <p id="delete-setup-details"><strong>{setup.title || `${setup.direction === 'long' ? 'Long' : 'Short'} setup`}</strong><br />
      EUR/USD · H4 · {setup.direction === 'long' ? 'Long' : 'Short'}<br />
      {setupTime(setup.cutoff_at)} · {setup.mode === 'live' ? 'Captured live' : 'Historical'}</p>
    <p id="delete-setup-warning">This permanently removes this saved setup, its market snapshot, zones, trade plan, and all AI assessments. This cannot be undone.</p>
    <p>Your current form, saved journals and strategy profiles are kept.</p>
    {error && <p className="se-error" role="alert">{error}</p>}
    {pending && <p role="status">Deleting setup…</p>}
    <div className="se-dialog-actions">
      <button type="button" autoFocus disabled={pending} onClick={onCancel}>Cancel</button>
      <button type="button" className="se-delete-confirm" disabled={pending} onClick={onConfirm}>{pending ? 'Deleting…' : 'Delete permanently'}</button>
    </div>
  </dialog>
}
