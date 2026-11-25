import { useEffect, useRef, useState } from 'react'
import { localInputTime } from './setupDrawing.js'
import { setupTime } from './setupEvaluation.js'
import { tradeEditRequest } from './tradeLog.js'
import TradeEntryFields from './TradeEntryFields.jsx'

const fieldNames = {title:'Trade name', direction:'Direction', entry_price:'Entry price', entry_at:'Entry time',
  initial_stop_loss:'Initial stop', initial_take_profit:'Initial target', entry_reason:'Reason for entry',
  entry_observations:'Entry observations', exit_price:'Exit price', exit_at:'Exit time', exit_notes:'Exit notes'}

function dateLabel(key,value) {
  return key.endsWith('_at') ? setupTime(value) : value || 'Empty'
}

export function TradeEditHistory({edits}) {
  if (!edits?.length) return null
  return <details className="trade-edit-history"><summary>Edit history ({edits.length})</summary>
    {edits.map(edit=><section key={edit.revision}><h4>Revision {edit.revision} · {setupTime(edit.at)}</h4>
      <ul>{Object.entries(edit.changes).map(([key,change])=><li key={key}>
        <strong>{fieldNames[key] ?? key}</strong> · {dateLabel(key,change.before)} → {dateLabel(key,change.after)}
      </li>)}</ul></section>)}
  </details>
}

export default function TradeEditDialog({record,pending,onDirty,onSave,onClose}) {
  const entry=record.entry, closed=record.exit
  const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone
  const [form,setForm]=useState(()=>({title:entry.title, direction:entry.direction, entryPrice:entry.entry_price,
    entryAt:localInputTime(entry.entry_at), stopLoss:entry.initial_stop_loss ?? '', takeProfit:entry.initial_take_profit ?? '',
    reason:entry.entry_reason, observations:entry.entry_observations}))
  const [exit,setExit]=useState(()=>closed && ({price:closed.exit_price, at:localInputTime(closed.exit_at), notes:closed.exit_notes}))
  const [dirty,setDirty]=useState(false), [error,setError]=useState('')
  const dialog=useRef(null)
  useEffect(()=>{
    const element=dialog.current
    element.showModal()
    return ()=>element.close()
  },[])
  function change(setter,values) {
    setter(current=>({...current,...values}))
    setDirty(true)
    onDirty(true)
    setError('')
  }
  function cancel() {
    if (!pending && (!dirty || window.confirm('Discard these trade edits?'))) onClose()
  }
  async function submit(event) {
    event.preventDefault()
    if (pending) return
    try {
      await onSave(tradeEditRequest(record,form,exit))
    } catch(err) { setError(err.message) }
  }
  return <dialog ref={dialog} className="trade-edit-dialog" aria-labelledby="trade-edit-title"
    onCancel={event=>{event.preventDefault();cancel()}}>
    <h2 id="trade-edit-title">Edit trade</h2>
    <form className="trade-form" onSubmit={submit}><fieldset disabled={pending}>
      <div className="trade-fields"><TradeEntryFields form={form} timezone={timezone} edit={values=>change(setForm,values)} /></div>
      {closed && <><h3>Recorded exit</h3><div className="trade-fields">
        <label>Exit price<input required inputMode="decimal" value={exit.price} onChange={e=>change(setExit,{price:e.target.value})} /></label>
        <label>Exit time · {timezone}<input required type="datetime-local" value={exit.at} onChange={e=>change(setExit,{at:e.target.value})} /></label>
        <label className="trade-wide">Exit notes<textarea maxLength={5000} value={exit.notes} onChange={e=>change(setExit,{notes:e.target.value})} /></label>
      </div></>}
      {error && <p className="trade-error" role="alert">{error}</p>}
      <div className="trade-actions"><button type="button" onClick={cancel}>Cancel</button>
      <button type="submit" disabled={!dirty} className="trade-primary">{pending ? 'Saving…' : 'Save changes'}</button></div>
    </fieldset></form>
  </dialog>
}
