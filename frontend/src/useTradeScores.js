import { useEffect,useRef,useState } from 'react'
import { API } from './api.js'
import { validTradeScores } from './tradeScores.js'

export default function useTradeScores(record,active,onEntryAnalysis) {
  const [value,setValue]=useState(null), [error,setError]=useState(''), [loading,setLoading]=useState(false), [reload,setReload]=useState(0)
  const callback=useRef(onEntryAnalysis)
  useEffect(()=>{callback.current=onEntryAnalysis},[onEntryAnalysis])
  const id=record.id, revision=record.revision ?? 0, exitAt=record.exit?.exit_at ?? null, entryAt=record.entry.entry_at, direction=record.entry.direction, status=record.status
  useEffect(()=>{
    if (!active) return
    let disposed=false, inFlight=false,controller
    async function refresh() {
      if(disposed || inFlight || document.visibilityState==='hidden') return
      inFlight=true; controller=new AbortController()
      const timeout=setTimeout(()=>controller.abort(),90000)
      setLoading(true)
      try {
        const response=await fetch(`${API}/trades/${id}/scores`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:controller.signal,cache:'no-store'})
        const data=await response.json().catch(()=>null)
        if(!response.ok) throw new Error(typeof data?.detail==='string' ? data.detail : 'Could not calculate trade scores.')
        if(!validTradeScores(data,{id,revision,status,entry:{entry_at:entryAt,direction},exit:exitAt ? {exit_at:exitAt} : null})) throw new Error('The trade changed or its score response is unsupported. Reopen the trade to refresh it.')
        if(!disposed) {setValue(data);setError(data.full_trade.error ?? '');callback.current?.(data.entry_analysis)}
      } catch(err) {if(!disposed) setError(err.name==='AbortError' ? 'Trade scoring timed out. Please retry.' : err.message)}
      finally {clearTimeout(timeout);inFlight=false;if(!disposed)setLoading(false)}
    }
    function visible(){if(document.visibilityState==='visible')refresh()}
    refresh()
    const poll=exitAt ? null : setInterval(refresh,60000)
    document.addEventListener('visibilitychange',visible)
    return()=>{disposed=true;controller?.abort();clearInterval(poll);document.removeEventListener('visibilitychange',visible)}
  },[active,id,revision,exitAt,entryAt,direction,status,reload])
  return {value,error,loading,refresh:()=>setReload(v=>v+1)}
}
