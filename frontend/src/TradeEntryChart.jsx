import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { API } from './api.js'
import { chartTime } from './marketChartData.js'
import { drawnZone, localInputTime } from './setupDrawing.js'
import { chartZones } from './tradeZones.js'
import { entryChartFields, entryChartWindow, pickTradeField } from './tradeEntryChart.js'

const MarketChart = lazy(() => import('./MarketChart.jsx'))
const noZones = []
const levelColors = { stopLoss:'#d65e70', takeProfit:'#249c79'}

export default function TradeEntryChart({active, guideRuleSet, form, onEdit, cutoff, linkedZones = noZones, disabled}) {
  const [visible,setVisible] = useState(true)
  const [around,setAround] = useState(() => cutoff ? localInputTime(cutoff) : '')
  const [request,setRequest] = useState(() => ({at:cutoff || null}))
  const [loaded,setLoaded] = useState(null)
  const [fetchError,setFetchError] = useState(null)
  const [selected,setSelected] = useState(null)
  const [tool,setTool] = useState(null)
  const [feedback,setFeedback] = useState('')
  const chart = loaded?.request === request ? loaded.snapshot : null
  const error = fetchError?.request === request ? fetchError.message : ''
  const candle = chart?.candles.find(row=>chartTime(row.open_time)===selected)
  const {stopLoss,takeProfit,entryZones,zoneBoundary} = form
  const allZones = useMemo(() => [...chartZones(linkedZones), ...entryZones], [linkedZones, entryZones])
  const zoneTool = tool === 'support' || tool === 'resistance'
  const maxZones = allZones.length >= 8
  const levels = useMemo(() => Object.entries({stopLoss,takeProfit})
    .filter(([,price]) => /^\d+(\.\d{1,5})?$/.test(price) && Number(price)>0 && Number(price)<=100)
    .map(([key,price]) => ({title:entryChartFields[key],price:Number(price),color:levelColors[key]})),
    [stopLoss,takeProfit])

  useEffect(() => {
    if (!active || !visible) return
    const controller = new AbortController()
    let disposed = false
    const timeout = setTimeout(()=>controller.abort(),90000)
    async function load() {
      try {
        const query = request.at ? '?' + new URLSearchParams({at:request.at}) : ''
        const response = await fetch(`${API}/trade-entry-chart${query}`,{signal:controller.signal,cache:'no-store'})
        const data = await response.json().catch(()=>null)
        if (!response.ok) throw new Error(typeof data?.detail==='string' ? data.detail : 'Could not load the entry chart.')
        const result = entryChartWindow(data,request.at)
        if (!disposed) {
          setLoaded({snapshot:result.snapshot,request})
          setSelected(result.selected)
          setFetchError(null)
        }
      } catch (err) {
        if (!disposed) setFetchError({request,message:err.name==='AbortError' ? 'The chart request timed out.' : err.message})
      } finally {clearTimeout(timeout)}
    }
    load()
    return () => {disposed=true; clearTimeout(timeout); controller.abort()}
  },[active,visible,request])

  function chooseTool(next) {
    setTool(next)
    setFeedback('')
    if (zoneBoundary != null) onEdit({zoneBoundary:null})
  }
  function editZone(key, patch) {
    onEdit({entryZones:entryZones.map(zone => zone.key === key ? {...zone,...patch} : zone)})
  }
  function loadWindow(latest=false) {
    const time = around && !latest ? new Date(around) : null
    if (time && (!Number.isFinite(time.getTime()) || time.getTime()>Date.now())) {
      setFeedback('Choose a past chart time.')
      return
    }
    if (latest) setAround('')
    chooseTool(null); setRequest({at:time ? time.toISOString() : null})
  }
  function applyPoint(point) {
    if (disabled || !tool || !point?.candle) return
    try {
      setSelected(chartTime(point.candle.open_time))
      if (zoneTool) {
        if (zoneBoundary == null) {
          onEdit({zoneBoundary:point.price})
          return
        }
        const zone = drawnZone(tool,zoneBoundary,point.price,allZones,crypto.randomUUID())
        if (!zone) throw new Error('Choose a valid zone range. Up to eight zones can be saved.')
        onEdit({entryZones:[...entryZones,zone],zoneBoundary:null})
        setFeedback(zone.label + ' added.')
      } else {
        const patch = pickTradeField(tool,point.price)
        onEdit(patch)
        setFeedback(entryChartFields[tool] + ' set to ' + patch[tool] + '.')
      }
      setTool(null)
    } catch (err) {setFeedback(err.message)}
  }
  return <section className="trade-entry-chart" aria-label="Trade entry chart picker"
    onKeyDown={e=>{if (e.key==='Escape') chooseTool(null)}}>
    <div className="trade-row"><h4>Pick from chart</h4><button type="button" aria-expanded={visible}
      onClick={()=>{setVisible(!visible);chooseTool(null)}}>{visible ? 'Hide chart' : 'Show chart'}</button></div>
    {visible && <>
      <div className="trade-window-controls"><label>Chart around · {Intl.DateTimeFormat().resolvedOptions().timeZone}
        <input type="datetime-local" value={around} onChange={e=>setAround(e.target.value)} /></label>
        <button type="button" onClick={()=>loadWindow()}>Load chart</button>
        {around && <button type="button" onClick={()=>loadWindow(true)}>Latest candles</button>}</div>
      {error && <p role="alert" className="trade-error">{error} You can enter the trade manually or load the chart again.</p>}
      {!chart && !error && <p role="status">Loading EUR/USD candles…</p>}
      {chart && <>
        <div className="trade-pick-tools" role="group" aria-label="Field to set on chart">
          {Object.entries({...entryChartFields,support:'Draw support',resistance:'Draw resistance'}).map(([key,label])=>
            <button key={key} type="button" disabled={disabled || (maxZones && ['support','resistance'].includes(key))}
              aria-pressed={tool===key} onClick={()=>chooseTool(tool===key ? null : key)}>{label}</button>)}
          {tool && <button type="button" onClick={()=>chooseTool(null)}>Cancel selection</button>}
        </div>
        <p className="trade-help" role="status">{zoneTool ? (zoneBoundary == null ? 'Tap the first boundary of the ' + tool + ' zone.' :
          'First boundary ' + zoneBoundary.toFixed(5) + '. Tap the second boundary.') : tool ?
          'Tap the price pane to set ' + entryChartFields[tool].toLowerCase() + '.' :
          'Pick a stop or target with one tap. To draw a zone, tap its two price boundaries in either order.'}</p>
      </>}
      <p className="trade-pick-feedback" role="status">{feedback}</p>
      {chart && active && <Suspense fallback={<p role="status">Opening chart…</p>}>
        <MarketChart snapshot={chart} guideRuleSet={guideRuleSet} selectedTime={selected} onSelect={setSelected} priceLevels={levels} draftZones={allZones}
          drawing={tool && !disabled ? {kind:tool,first:zoneBoundary} : null} onDrawingPoint={applyPoint} />
        {tool && candle && <div className="trade-pick-tools" role="group" aria-label="Use selected candle">
          {['open','high','low','close'].map(key=><button type="button" key={key} disabled={disabled}
              onClick={()=>applyPoint({candle,price:candle[key]})}>Use {key==='close' && candle.complete===false ? 'latest' : key} · {candle[key].toFixed(5)}</button>)}
        </div>}
      </Suspense>}
    </>}
    <fieldset className="trade-entry-zones" disabled={disabled}>
      <legend>Support &amp; resistance zones · {allZones.length}/8</legend>
      {linkedZones.length > 0 && <p className="trade-help">From the linked setup: {linkedZones.map(z=>z.label).join(', ')}</p>}
      {entryZones.map(zone => <div className="trade-zone-fields" key={zone.key}>
        <label>Name<input maxLength={80} value={zone.label} onChange={e=>editZone(zone.key,{label:e.target.value})} /></label>
        <label>Type<select value={zone.kind} onChange={e=>editZone(zone.key,{kind:e.target.value})}><option value="support">Support</option><option value="resistance">Resistance</option></select></label>
        {['lower','upper'].map(side=><label key={side}>{side==='lower' ? 'Lower price' : 'Upper price'}
          <input inputMode="decimal" value={zone[side]} onChange={e=>editZone(zone.key,{[side]:e.target.value})} /></label>)}
        <label>Origin time (optional) · {Intl.DateTimeFormat().resolvedOptions().timeZone}
          <input type="datetime-local" value={zone.originAt} max={form.entryAt || undefined} onChange={e=>editZone(zone.key,{originAt:e.target.value})} /></label>
        <button type="button" aria-label={'Remove ' + (zone.label || 'zone')} onClick={()=>onEdit({entryZones:entryZones.filter(z=>z.key!==zone.key)})}>Remove</button>
      </div>)}
      <button type="button" disabled={maxZones} onClick={()=>{
        chooseTool(null)
        onEdit({entryZones:[...entryZones,{key:crypto.randomUUID(),kind:'support',label:'',timeframe:'H4',lower:'',upper:'',originAt:''}]})
      }}>Add zone manually</button>
    </fieldset>
  </section>
}
