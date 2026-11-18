import { lazy, Suspense, useEffect, useState } from 'react'
import { API } from './api.js'
import { chartStamp, chartTime } from './marketChartData.js'
import { validTradeTimeline } from './tradeTimeline.js'

const MarketChart = lazy(() => import('./MarketChart.jsx'))
const stamp = value => chartStamp(chartTime(value))

export default function TradeTimeline({ record, active }) {
  const [view, setView] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')
  const [fetching, setFetching] = useState(false)
  const [reload, setReload] = useState(0)
  const id = record.id, exitAt = record.exit?.exit_at ?? null

  useEffect(() => {
    if (!active) return
    let disposed = false, inFlight = false, controller
    async function refresh() {
      if (disposed || inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 90000)
      setFetching(true)
      try {
        const response = await fetch(`${API}/trades/${id}/timeline`, { signal: controller.signal, cache: 'no-store' })
        const data = await response.json().catch(() => null)
        if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not load the trade timeline.')
        if (!validTradeTimeline(data, id, exitAt)) throw new Error('The trade changed or its chart response is unsupported. Reopen the trade to refresh its details.')
        if (!disposed) { setView(data); setError('') }
      } catch (err) {
        if (!disposed) setError(err.name === 'AbortError' ? 'The chart refresh timed out. Please retry.' : err.message)
      } finally {
        clearTimeout(timeout)
        inFlight = false
        if (!disposed) setFetching(false)
      }
    }
    function visibility() { if (document.visibilityState === 'visible') refresh() }
    refresh()
    const poll = !exitAt ? setInterval(refresh, 60000) : null
    document.addEventListener('visibilitychange', visibility)
    return () => { disposed = true; controller?.abort(); clearInterval(poll); document.removeEventListener('visibilitychange', visibility) }
  }, [id, exitAt, active, reload])

  return <section className="trade-card trade-timeline" aria-label="Trade timeline">
    <div className="trade-row"><div><h3>Trade timeline</h3><p className="trade-help">{exitAt ? 'Entry, exit and up to 60 candles afterward' : 'Entry through the latest available candle · refreshes every minute'}</p></div>
      <button type="button" onClick={() => setReload(value => value + 1)} disabled={fetching}>{fetching ? 'Refreshing chart…' : 'Refresh chart'}</button></div>
    <p className="trade-help">Market prices after entry are for reviewing the trade. Your saved four-factor assessment stays unchanged.</p>
    {error && <p className="trade-error" role="alert">{error} {view && 'Showing the last successful chart; it may be outdated.'}</p>}
    {!view && !error && <p role="status">Loading the trade’s candles and indicators…</p>}
    {view && <>
      <dl className="trade-metrics">{view.events.map(event => <div key={event.kind}><dt>{event.kind === 'entry' ? 'Entry' : 'Exit'} · actual fill</dt><dd>{event.price}<small>{stamp(event.at)}</small></dd></div>)}
        <div><dt>Chart checked</dt><dd>{stamp(view.as_of)}<small>OANDA midpoint prices</small></dd></div></dl>
      {exitAt && <p className="trade-notice"><strong>{view.coverage.after_exit_count ?? 0} / {view.coverage.after_exit_target ?? 60} candles after exit</strong> · Market context only; these candles do not affect your trade result or entry assessment.
        {(view.coverage.after_exit_complete_count ?? 0) < (view.coverage.after_exit_target ?? 60) && ' Refresh later as more candles become available.'}</p>}
      {view.coverage.forming_count > 0 && <p className="trade-notice">Forming H4 candle · its price and indicator values can change until it closes. It does not receive strategy points.</p>}
      {view.coverage.contains_post_exit_prices && <p className="trade-notice">The exit happened during an H4 candle. That full candle includes prices after your exit; those prices are not part of your trade result.</p>}
      {view.coverage.exit_candle_pending && <p className="trade-notice">The exit candle is still forming. Refresh after its scheduled close to see the full candle. This closed trade does not refresh automatically.</p>}
      {view.coverage.missing_candle_count > 0 && <p className="trade-notice">{view.coverage.missing_candle_count} scheduled H4 candle(s) are unavailable, starting {stamp(view.coverage.first_missing_open)}. This can reflect a market closure or a data gap; the chart and indicators use only the available candles.</p>}
      {!view.candles.length && <p className="trade-notice">No candle is available from the entry onward yet. Showing earlier market context.</p>}
      {view.events.some(event => !event.candle_open_time) && <p className="trade-help">An entry or exit occurred outside the available candles. Its exact time is shown above; no marker is placed on an unrelated candle.</p>}
      <Suspense fallback={<p role="status">Loading chart…</p>}><MarketChart snapshot={view} selectedTime={selected} onSelect={setSelected} tradeTimeline /></Suspense>
      <p className="trade-help">Entry and exit arrows identify their H4 candles; exact fill times and prices are listed above. A full entry candle may also contain prices from before entry. Chart prices are midpoint data and may differ from your broker’s fills.</p>
    </>}
  </section>
}
