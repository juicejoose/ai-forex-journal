import { useEffect, useMemo, useState } from 'react'
import { API } from './api.js'
import { chartBoundaries, validChartContext, withChartContext } from './chartContext.js'

const cache = new Map()

export default function useChartContext(snapshot, includeAfter=false) {
  const {before,after} = chartBoundaries(snapshot,includeAfter)
  const key = `${before}|${after}`
  const [result,setResult] = useState(null)
  const [error,setError] = useState(null)
  const [loading,setLoading] = useState(false)
  const [reload,setReload] = useState(0)
  useEffect(() => {
    if (!before) return
    const controller = new AbortController()
    let disposed = false
    async function load() {
      const timeout = setTimeout(() => controller.abort(),90000)
      setLoading(true)
      try {
        let data = cache.get(key)?.expires > Date.now() ? cache.get(key).data : null
        if (!data) {
          const params = new URLSearchParams({before_at:before})
          if (after) params.set('after_at',after)
          const response = await fetch(`${API}/chart-context?${params}`,{signal:controller.signal,cache:'no-store'})
          data = await response.json().catch(() => null)
          if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Additional chart context is unavailable.')
          if (!validChartContext(data,before,after)) throw new Error('The server returned unsupported chart context. Check that the updated backend is running.')
          cache.set(key,{data,expires:Date.now()+(after ? 55000 : 3600000)})
          while (cache.size > 20) cache.delete(cache.keys().next().value)
        }
        if (!disposed) { setResult({key,data}); setError(null) }
      } catch (err) {
        if (!disposed) setError({key,message:err.name === 'AbortError' ? 'The chart context request timed out.' : err.message})
      } finally { clearTimeout(timeout); if (!disposed) setLoading(false) }
    }
    load()
    return () => { disposed=true; controller.abort() }
  },[before,after,key,reload])
  const context = result?.key === key ? result.data : null
  const chart = useMemo(() => withChartContext(snapshot,context),[snapshot,context])
  return {chart,context,loading,error:error?.key === key ? error.message : '',
    refresh:() => { cache.delete(key); setReload(value => value+1) }}
}
