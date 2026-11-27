import { useEffect,useRef,useState } from 'react'
import { savedTradeZones } from './tradeZones.js'
import { API } from './api.js'
import { setupTime } from './setupEvaluation.js'
import { alignmentChange,coachLabels,coachReadoutLabels,holdAlignmentText,premiseStatus,coachZones,coachRequest,newerCoachEvidence,runningReview,validCoachReview } from './tradeCoach.js'
import { CapturedEvidence, EvidenceList } from './CoachEvidence.jsx'
import './TradeCoach.css'

async function api(path,options={}) {
  const response=await fetch(`${API}${path}`,{cache:'no-store',...options})
  const value=await response.json().catch(()=>null)
  if(!response.ok) throw new Error(typeof value?.detail==='string' ? value.detail : 'The coach request could not be completed.')
  return value
}

function TradePremise({checks, evidence, sectionRef}) {
  return <section className="coach-premise" ref={sectionRef} tabIndex={-1} aria-label="Your trade premise">
    <h4>Your trade premise</h4>
    <ul>{checks.map(check => <li key={JSON.stringify([check.source,check.excerpt,check.window])}>
      <small>{check.source === 'entry_reason' ? 'Reason for entry' : 'Entry observations'} · {check.window === 'at_entry' ? 'At entry' : 'Since entry'}</small>
      <blockquote>{check.excerpt}</blockquote>
      <p><strong>{premiseStatus[check.status]}</strong> · {check.explanation}</p>
      {check.evidence_ids.length > 0 && <details><summary>Market evidence ({check.evidence_ids.length})</summary>
        <ul>{check.evidence_ids.map(id => {
          const fact = evidence.find(item => item.id === id)
          return <li key={id}>{fact ? <><time dateTime={fact.through}>{setupTime(fact.through)}</time> · {fact.text}</> : 'Evidence unavailable'}</li>
        })}</ul></details>}
    </li>)}</ul>
  </section>
}

function FactorChanges({history}) {
  function describe(state) {
    if (state.outcome === 'neutral' || state.outcome === 'unavailable') return state.outcome
    const points = state.bullish_points + state.bearish_points
    return `${state.outcome} (${points} ${points === 1 ? 'point' : 'points'})`
  }
  return <section><h4>What changed since entry</h4><ul className="coach-evidence-list">
    {history.map(factor=><li key={factor.factor_id}><b>{factor.name}</b>
      <p>{factor.changed_at
        ? `${describe(factor.previous)} → ${describe(factor.latest)} at ${setupTime(factor.changed_at)}`
        : `${describe(factor.entry)} since entry`}
        {' · '}{factor.consecutive_closes} consecutive in-trade {factor.consecutive_closes === 1 ? 'close' : 'closes'}</p>
    </li>)}
  </ul></section>
}

function HoldAlignment({alignment}) {
  return <><p className="coach-signal"><b>Four-factor alignment</b> · {alignment.headline}</p>
    <div className="coach-hold-context"><p>{alignment.context}</p><p>{alignment.coverage}</p></div></>
}

function CoachReadout({snapshot,labels,alignment,details=false}) {
  if (!labels) return alignment ? <HoldAlignment alignment={alignment} /> : null
  const readout = snapshot.catalog.readout
  const net = readout.market_net_score
  return <>{labels.atEntry && <strong>{labels.headline}</strong>}
    {alignment ? <HoldAlignment alignment={alignment} /> :
      <p className="coach-signal"><b>{labels.atEntry ? 'Strategy at entry' : 'Four-factor alignment'}</b> · {labels.alignment}
        {Number.isFinite(net) && <> · market net {net>0 ? '+' : ''}{net}</>}</p>}
    <p className="coach-signal"><b>Price action</b> · {labels.priceAction}</p>
    {details && <>
      {readout.price_action.matches.length>0 && <ul>{readout.price_action.matches.map(match=>
        <li key={match.event_id}>{match.zone_label} · {match.kind.replaceAll('_',' ')} · {match.direction}</li>)}</ul>}
      {readout.price_action.partial_coverage && !labels.atEntry && <p>Some zones have incomplete history.</p>}
      {!labels.atEntry && <FactorChanges history={readout.factor_history} />}
    </>}
  </>
}

export default function TradeCoach({record,active,latestClose,onBusyChange,onDirtyChange}) {
  const [history,setHistory]=useState({items:[],total:0,offset:0}),[review,setReview]=useState(null)
  const [form,setForm]=useState(()=>({inherit:true,zones:coachZones(record),observations:''}))
  const [dirty,setDirty]=useState(false),[generating,setGenerating]=useState(false),[loading,setLoading]=useState(false)
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[reload,setReload]=useState(0),[offset,setOffset]=useState(0)
  const premiseSection = useRef(null)
  const dialog=useRef(null),returnFocus=useRef(null),controller=useRef(null),request=useRef(null),editor=useRef(null)
  const selectSequence=useRef(0),alive=useRef(true)
  const id=record.id,isOpen=record.status==='open',running=runningReview(review)
  useEffect(()=>{onBusyChange?.(generating)},[generating,onBusyChange])
  useEffect(()=>{onDirtyChange?.(dirty)},[dirty,onDirtyChange])
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;controller.current?.abort();onBusyChange?.(false);onDirtyChange?.(false)}},[onBusyChange,onDirtyChange])
  useEffect(()=>{
    if(!active)return
    const abort=new AbortController();let disposed=false
    const sequence=++selectSequence.current
    async function load() {
      setLoading(true)
      try {
        const data=await api(`/trades/${id}/coach-reviews?limit=10&offset=${offset}`,{signal:abort.signal})
        if(disposed || sequence!==selectSequence.current)return
        setHistory(data)
        if(data.items.length){
          const value=await api(`/trades/${id}/coach-reviews/${data.items[0].id}`,{signal:abort.signal})
          if(!validCoachReview(value,id))throw new Error('The saved review could not be validated.')
          if(!disposed && sequence===selectSequence.current)setReview(value)
        } else setReview(null)
        setError('')
      }catch(err){if(!disposed && sequence===selectSequence.current)setError(err.message)}
      finally{if(!disposed)setLoading(false)}
    }
    load()
    return()=>{disposed=true;abort.abort()}
  },[id,active,record.status,reload,offset])
  useEffect(()=>{
    if(!active || !running || generating)return
    const timer=setInterval(()=>{if(document.visibilityState==='visible')setReload(n=>n+1)},5000)
    return()=>clearInterval(timer)
  },[active,running,generating])
  function show(event,edit=false){returnFocus.current=event.currentTarget;dialog.current.showModal();if(edit)editor.current.open=true}
  function closeDialog(){dialog.current.close();returnFocus.current?.focus()}
  function edit(patch){setForm(current=>({...current,...patch}));setDirty(true);setNotice('')}
  async function select(reviewId){
    const sequence=++selectSequence.current;setLoading(true);setError('')
    try{const value=await api(`/trades/${id}/coach-reviews/${reviewId}`);if(!validCoachReview(value,id))throw new Error('The review response is unsupported.');if(alive.current && sequence===selectSequence.current)setReview(value)}
    catch(err){if(alive.current && sequence===selectSequence.current)setError(err.message)}finally{if(alive.current)setLoading(false)}
  }
  async function generate(event){
    event.preventDefault();if(generating)return
    let body
    try{body=coachRequest(form)}catch(err){setError(err.message);return}
    const signature=JSON.stringify(body)
    if(request.current?.signature!==signature)request.current={signature,id:crypto.randomUUID()}
    setGenerating(true);setError('');setNotice('Saving evidence and requesting the coach review…')
    controller.current=new AbortController();const timeout=setTimeout(()=>controller.current?.abort(),240000)
    ++selectSequence.current
    try{
      const value=await api(`/trades/${id}/coach-reviews`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,request_id:request.current.id}),signal:controller.current.signal})
      if(!validCoachReview(value,id))throw new Error('The review response is unsupported. Reload history before retrying.')
      if(!alive.current)return
      setReview(value);setDirty(false)
      if(value.status==='completed' && editor.current){editor.current.open=false;dialog.current.scrollTop=0}
      if(!runningReview(value))request.current=null
      setNotice(value.status==='completed' ? 'Coach review saved with its evidence.' : value.error_message || 'Review running. Reload history to check progress.')
      setOffset(0);setReload(n=>n+1)
    }catch(err){if(alive.current){setError(err.name==='AbortError' ? 'The request timed out. It may still be running; reload history before retrying.' : err.message);setNotice('')}}
    finally{clearTimeout(timeout);if(alive.current)setGenerating(false)}
  }
  const stale=newerCoachEvidence(review,latestClose),snapshot=review?.snapshot,result=review?.result
  const labels = coachReadoutLabels(snapshot)
  const alignment = snapshot && holdAlignmentText(review.hold_alignment, snapshot.trade.direction, snapshot.covers_latest_close)
  const change = alignmentChange(snapshot)
  const previousVersion = snapshot && (snapshot.trade_revision ?? 0) !== (record.revision ?? 0)
  const afterExit=record.exit && snapshot && Date.parse(snapshot.cutoff_at)>Date.parse(record.exit.exit_at)
  return <div className="trade-coach-card">
    <div className="trade-score-heading"><h4>AI Coach</h4><button className="trade-score-evidence-link" type="button" onClick={e=>show(e)} aria-label="Open coach evidence and history">Evidence ↓</button></div>
    {(labels || alignment) && result && !previousVersion && !running && !generating ? <CoachReadout snapshot={snapshot} labels={labels} alignment={alignment} /> :
      <strong>{generating || running ? 'Review in progress' : previousVersion ? 'Trade edited since review' : result ? coachLabels[result.assessment] : review?.status==='failed' ? 'Review unavailable' : 'No review yet'}</strong>}
    {previousVersion ? <p>View the earlier review in Evidence.</p> : result ? <p className="coach-excerpt">{result.summary}</p> : <p>Review the factors, zones and changes since entry.</p>}
    {labels && result && !previousVersion && change && <p className="coach-signal"><b>Since entry</b> · {change}</p>}
    {result?.premise_checks && !previousVersion && <button type="button" className="trade-score-evidence-link"
      onClick={event=>{show(event); premiseSection.current?.focus()}}>Your trade premise ↓</button>}
    {review?.cutoff_at && <small>As of {setupTime(review.cutoff_at)}</small>}
    {stale && <p className="coach-stale">{isOpen ? 'New completed candles · refresh the coach' : 'Newer completed candles outside this review'}</p>}
    {!isOpen && <p>{review ? 'Historical open-trade review · trade now closed' : 'No open-trade review was saved.'}</p>}
    {isOpen && <button type="button" disabled={generating || running} onClick={e=>show(e,true)}>{result ? 'Refresh coach' : 'Review trade'}</button>}
    {error && <p className="trade-error" role="alert">{error}</p>}
    <dialog ref={dialog} className="coach-dialog" onCancel={event=>{event.preventDefault();closeDialog()}} aria-label="AI coach review">
      <header className="trade-row"><div><h3>AI Coach · {record.entry.title || 'EUR/USD trade'}</h3><p className="trade-help">Technical second opinion · {record.entry.direction} · manual decisions</p></div><button type="button" onClick={closeDialog}>Close</button></header>
      <p className="trade-help">Submitting Review trade requests a paid AI review. Chart refreshes never call the coach. Notes and zones are sent with the trade evidence; no external news is retrieved.</p>
      {error && <p className="trade-error" role="alert">{error}</p>}{notice && <p className="trade-notice" role="status">{notice}</p>}
      {isOpen && <details ref={editor}><summary>Review inputs {dirty ? '· unsaved changes' : ''}</summary>
        <form onSubmit={generate} className="trade-form"><fieldset disabled={generating || running}>
          <label><span>Current observations (optional)</span><textarea rows={3} maxLength={5000} value={form.observations} onChange={e=>edit({observations:e.target.value})} placeholder="What changed or concerns you? These notes are separate from entry reasoning." /></label>
          <label className="coach-checkbox"><input type="checkbox" checked={form.inherit} onChange={e=>edit({inherit:e.target.checked})} />Use zones saved with entry ({savedTradeZones(record.context).length})</label>
          {!form.inherit && <><p className="trade-help">These zones apply to this review only. Original entry evidence stays fixed. Origin time enables historical rule checks; without it, only zone position is available.</p>
            {form.zones.map((zone,index)=><div className="coach-zone" key={zone.key}><label>Name<input maxLength={80} value={zone.label} onChange={e=>edit({zones:form.zones.map((z,i)=>i===index ? {...z,label:e.target.value}:z)})} /></label>
              <label>Type<select value={zone.kind} onChange={e=>edit({zones:form.zones.map((z,i)=>i===index ? {...z,kind:e.target.value}:z)})}><option value="support">Support</option><option value="resistance">Resistance</option></select></label>
              {['lower','upper'].map(key=><label key={key}>{key==='lower' ? 'Lower price':'Upper price'}<input inputMode="decimal" value={zone[key]} onChange={e=>edit({zones:form.zones.map((z,i)=>i===index ? {...z,[key]:e.target.value}:z)})} /></label>)}
              <label>Origin · {Intl.DateTimeFormat().resolvedOptions().timeZone}<input type="datetime-local" value={zone.originAt} onChange={e=>edit({zones:form.zones.map((z,i)=>i===index ? {...z,originAt:e.target.value}:z)})} /></label>
              <button type="button" onClick={()=>edit({zones:form.zones.filter((_,i)=>i!==index)})}>Remove zone</button></div>)}
            <button type="button" disabled={form.zones.length>=8} onClick={()=>edit({zones:[...form.zones,{key:crypto.randomUUID(),label:'',kind:'support',timeframe:'H4',lower:'',upper:'',originAt:''}]})}>Add zone</button></>}
          <p className="trade-help">Recorded stop and target are initial levels, not confirmed current levels. The coach cannot infer a stop change from price movement.</p>
          <button type="submit" className="trade-primary">{generating ? 'Reviewing…' : 'Review trade'}</button>
        </fieldset></form></details>}
      <section className="coach-history"><div className="trade-row"><h4>Saved reviews ({history.total})</h4><button type="button" disabled={generating || loading} onClick={()=>setReload(n=>n+1)}>Reload history</button></div>
        {running && <p className="trade-help">An interrupted review expires after five minutes. You can start a new review then; it captures fresh evidence.</p>}
        {running && isOpen && <button type="button" disabled={generating} onClick={()=>{request.current=null;setReview(null);setNotice('Start a new review below. The server will reject it if the previous request has not expired.');editor.current.open=true}}>New request after interruption</button>}
        {history.items.length>0 && <label>Choose review<select value={review?.id ?? ''} disabled={generating || loading} onChange={e=>select(e.target.value)}>{history.items.map(item=><option key={item.id} value={item.id}>{setupTime(item.created_at)} · {item.status}</option>)}</select></label>}
        {history.total>10 && <div className="trade-row"><button type="button" disabled={!offset || generating || loading} onClick={()=>setOffset(n=>Math.max(0,n-10))}>Newer</button><span>{offset+1}–{Math.min(offset+10,history.total)}</span><button type="button" disabled={offset+10>=history.total || generating || loading} onClick={()=>setOffset(n=>n+10)}>Older</button></div>}
      </section>
      {review?.error_message && <p className="trade-error">{review.error_message}</p>}
      {snapshot && <>{previousVersion && <p className="coach-stale">Earlier trade details · {snapshot.trade.direction} · revision {snapshot.trade_revision ?? 0}</p>}<p className="trade-help">Evidence cutoff {setupTime(snapshot.cutoff_at)} · completed data through {setupTime(snapshot.data_through)} · Four-factor v{snapshot.rule_set.version}, revision {snapshot.rule_set.revision} · {review.provider_model || review.requested_model}</p>
        {stale && <p className="coach-stale">Newer completed candles are available. This saved review does not cover them.</p>}
        {dirty && <p className="coach-stale">Draft inputs differ from the saved review.</p>}
        {afterExit && <p className="coach-stale">This review was captured after the exit time later recorded for this trade. It is post-exit context, not an opinion available while holding.</p>}
        {result?.premise_checks && <TradePremise checks={result.premise_checks} evidence={snapshot.premise_evidence} sectionRef={premiseSection} />}
        <CoachReadout snapshot={snapshot} labels={labels} alignment={alignment} details />
        {result && <>{labels ? <h4>Coach interpretation</h4> : <h4>{coachLabels[result.assessment]} · earlier review method</h4>}<p>{result.summary}</p><h4>Main concern</h4><p>{result.main_concern}</p>
          <EvidenceList title="Supporting evidence" ids={result.supporting_facts} catalog={snapshot.catalog} />
          <EvidenceList title="Conflicting evidence" ids={result.conflicting_facts} catalog={snapshot.catalog} />
          <EvidenceList title="Changes since entry" ids={result.change_facts} catalog={snapshot.catalog} />
          <EvidenceList title="Market, plan and zone context" ids={result.context_facts} catalog={snapshot.catalog} />
          <EvidenceList title="Conditions to monitor" ids={result.watch_conditions} catalog={snapshot.catalog} conditions />
          <EvidenceList title="Possible invalidation scenarios" ids={result.invalidation_conditions} catalog={snapshot.catalog} conditions /></>}
        <h4>Limitations</h4><ul>{snapshot.catalog.limitations.map(text=><li key={text}>{text}</li>)}</ul>
        <CapturedEvidence snapshot={snapshot} />
      </>}
    </dialog>
  </div>
}
