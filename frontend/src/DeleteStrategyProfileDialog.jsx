import { useEffect, useRef } from 'react'

export default function DeleteStrategyProfileDialog({ profile, hasUnsavedEdits, pending, error, onCancel, onConfirm }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    const dialog = dialogRef.current
    dialog.showModal()
    return () => dialog.close()
  }, [])

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="delete-profile-heading"
      aria-describedby="delete-profile-details delete-profile-warning"
      aria-busy={pending}
      onCancel={(event) => {
        event.preventDefault()
        if (!pending) onCancel()
      }}
      style={{
        width: 'min(32rem, calc(100% - 2rem))', boxSizing: 'border-box',
        padding: '1.5rem', border: '1px solid var(--border)', borderRadius: '8px',
        background: 'var(--bg)', color: 'var(--text)', textAlign: 'left',
      }}
    >
      <h2 id="delete-profile-heading">Delete strategy profile?</h2>
      <p id="delete-profile-details" style={{ marginTop: '1rem', overflowWrap: 'anywhere' }}>
        Profile: <strong>{profile.name}</strong>
      </p>
      <p id="delete-profile-warning" style={{ marginTop: '1rem' }}>
        This permanently removes this saved profile and cannot be undone.
        {' '}Existing journals and rules already copied into the generation form are kept.
        {hasUnsavedEdits && ' Your unsaved edits to this profile will also be discarded.'}
      </p>
      {error && <p role="alert" style={{ marginTop: '1rem' }}>{error}</p>}
      {pending && <p role="status" style={{ marginTop: '1rem' }}>Deleting profile...</p>}
      <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
        <button type="button" onClick={onCancel} disabled={pending} autoFocus>Cancel</button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={pending}
          style={{ background: '#b42318', color: '#fff', border: '1px solid #b42318', borderRadius: '4px', padding: '0.5rem 0.75rem', opacity: pending ? 0.6 : 1 }}
        >
          {pending ? 'Deleting...' : 'Delete permanently'}
        </button>
      </div>
    </dialog>
  )
}
