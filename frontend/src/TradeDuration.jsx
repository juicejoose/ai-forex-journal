import { useEffect, useState } from 'react'
import { tradeDuration } from './tradeLog.js'

export default function TradeDuration({ entryAt, exitAt, active }) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (!active || exitAt) return
    const refresh = () => { if (document.visibilityState === 'visible') setNow(Date.now()) }
    const timer = setInterval(refresh, 60000)
    document.addEventListener('visibilitychange', refresh)
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', refresh) }
  }, [active, exitAt])
  return <><span title="Elapsed time in full days and hours, including weekends.">{tradeDuration(entryAt, exitAt, now)}</span><small>{exitAt ? 'Entry to exit' : 'Open · elapsed'}</small></>
}
