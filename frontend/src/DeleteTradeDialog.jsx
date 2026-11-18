import { useEffect, useRef } from 'react'
import { setupTime } from './setupEvaluation.js'

export default function DeleteTradeDialog({ trade, pending, error, hasUnsavedEdits, onCancel, onConfirm }) {
  const ref = useRef(null)
  useEffect(() => { const dialog = ref.current; dialog.showModal(); return () => dialog.close() }, [])
  return <dialog ref={ref} className="trade-delete-dialog" aria-labelledby="delete-trade-title" aria-describedby="delete-trade-warning" aria-busy={pending}
    onCancel={event => { event.preventDefault(); if (!pending) onCancel() }}>
    <h2 id="delete-trade-title">Delete trade?</h2>
    <p><strong>{trade.entry.title || `${trade.entry.direction === 'long' ? 'Long' : 'Short'} EUR/USD`}</strong><br />{setupTime(trade.entry.entry_at)} · {trade.status === 'open' ? 'Open trade' : 'Closed trade'}</p>
    <p id="delete-trade-warning">This permanently removes this trade entry, its exit, self-reviews, copied entry evidence and saved strategy comparisons. This cannot be undone.</p>
    <p>Saved setups, journals and other trades are kept. Deleting this record does not close a position with your broker.</p>
    {hasUnsavedEdits && <p>Unsaved exit or review changes for this trade will also be discarded.</p>}
    {error && <p className="trade-error" role="alert">{error}</p>}
    <div className="trade-actions"><button type="button" autoFocus disabled={pending} onClick={onCancel}>Cancel</button>
      <button type="button" className="trade-delete-confirm" disabled={pending} onClick={onConfirm}>{pending ? 'Deleting…' : 'Delete permanently'}</button></div>
  </dialog>
}
