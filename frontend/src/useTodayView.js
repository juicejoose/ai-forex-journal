import { useEffect, useState } from 'react'
import { API } from './api.js'
import { validTodayView, freshTodayView } from './todaySession.js'

export default function useTodayView(active, refreshKey = 0) {
  const [view, setView] = useState(null)
  const [reload, setReload] = useState(0)
  const [fetching, setFetching] = useState(false)
  const [dataError, setDataError] = useState('')
  const [now, setNow] = useState(0)
  useEffect(() => {
    if (!active) return
    let disposed = false, inFlight = false, controller
    async function refresh() {
      if (disposed || inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 45000)
      setFetching(true)
      try {
        const response = await fetch(API + '/today', { signal: controller.signal, cache: 'no-store' })
        const data = await response.json().catch(() => null)
        if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not refresh today’s session.')
        if (!validTodayView(data)) throw new Error('The session data could not be verified. Reopen the page and retry.')
        if (!disposed) { setView(data); setDataError(''); setNow(Date.now()) }
      } catch (err) {
        if (!disposed) setDataError(err.name === 'AbortError' ? 'The refresh timed out. Retry to get current data.' : err.message)
      } finally {
        clearTimeout(timeout)
        inFlight = false
        if (!disposed) setFetching(false)
      }
    }
    function visibility() { if (document.visibilityState === 'visible') refresh() }
    refresh()
    const poll = setInterval(refresh, 60000)
    const age = setInterval(() => setNow(Date.now()), 10000)
    document.addEventListener('visibilitychange', visibility)
    return () => { disposed = true; controller?.abort(); clearInterval(poll); clearInterval(age); document.removeEventListener('visibilitychange', visibility) }
  }, [active, reload, refreshKey])

  return {view, fetching, dataError, fresh:freshTodayView(view,now), refresh:()=>setReload(v=>v+1)}
}
