import { useEffect, useRef } from 'react'

export default function DeleteJournalDialog({ journal, hasUnsavedEdits, pending, error, onCancel, onConfirm }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    const dialog = dialogRef.current
    dialog.showModal()
    return () => dialog.close()
  }, [])

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="delete-journal-heading"
      aria-describedby="delete-journal-details delete-journal-warning"
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
      <h2 id="delete-journal-heading">Delete saved journal?</h2>
      <p id="delete-journal-details" style={{ marginTop: '1rem' }}>
        Journal #{journal.id} · {journal.journal_date} · {journal.pair} ({journal.timeframe})
      </p>
      <p id="delete-journal-warning" style={{ marginTop: '1rem' }}>
        This permanently removes the original draft, saved edits, and market snapshot.
        {' '}This cannot be undone.
        {hasUnsavedEdits && ' Your unsaved edits to this journal will also be discarded.'}
      </p>
      {error && <p role="alert" style={{ marginTop: '1rem' }}>{error}</p>}
      {pending && <p role="status" style={{ marginTop: '1rem' }}>Deleting journal...</p>}
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
