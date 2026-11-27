import { lazy, Suspense, useEffect, useId, useMemo, useRef, useState } from 'react'
import { chartZones, savedTradeZones } from './tradeZones.js'
import { API } from './api.js'
import { chartStamp, chartTime } from './marketChartData.js'
import TradeSessionScore, { TradeSessionEvidence } from './TradeSessionScore.jsx'
import useTodayView from './useTodayView.js'
import TradeCoach from './TradeCoach.jsx'
import useTradeScores from './useTradeScores.js'
import { TradeScoreCards,TradeScoreDetails } from './TradeScores.jsx'
import { validTradeTimeline,timelinePriceResult } from './tradeTimeline.js'

const MarketChart = lazy(() => import('./MarketChart.jsx'))
const stamp = value => chartStamp(chartTime(value))

export default function TradeTimeline({ record, active, onPriceResult, onCoachBusyChange, onCoachDirtyChange, onOpenTodayBreakdown, children }) {
  const zones = useMemo(() => chartZones(savedTradeZones(record.context)), [record.context])
  const scores=useTradeScores(record,active)
  const priceCallback=useRef(onPriceResult)
  useEffect(()=>{priceCallback.current=onPriceResult},[onPriceResult])
  const evidenceId=useId()
  const entryEvidenceRef=useRef(null), fullEvidenceRef=useRef(null), sessionEvidenceRef=useRef(null)
  const evidenceIds={entry:`${evidenceId}-entry`,full:`${evidenceId}-full`,session:`${evidenceId}-session`}
  function showEvidence(kind) {
    const target={entry:entryEvidenceRef,full:fullEvidenceRef,session:sessionEvidenceRef}[kind].current
    const details=target?.closest('details')
    if (!details) return
    details.open=true
    target.focus({preventScroll:true})
    target.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'})
  }
  const [view, setView] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')
  const [fetching, setFetching] = useState(false)
  const [reload, setReload] = useState(0)
  const isOpen = record.status === 'open'
  const session = useTodayView(active && isOpen, reload)
  const id = record.id, revision = record.revision ?? 0, exitAt = record.exit?.exit_at ?? null

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
        if (!validTradeTimeline(data, id, exitAt, revision)) throw new Error('The trade changed or its chart response is unsupported. Reopen the trade to refresh its details.')
        if (!disposed) { setView(data); setError(''); priceCallback.current?.({tradeId:id,result:timelinePriceResult(data),error:false}) }
      } catch (err) {
        if (!disposed) priceCallback.current?.({tradeId:id,result:null,error:true})
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
  }, [id, revision, exitAt, active, reload])

  return <section className="trade-card trade-timeline" aria-label="Trade timeline">
    <div className="trade-timeline-toolbar">
      <p className="trade-help">{view ? `Checked ${stamp(view.as_of)}` : 'Trade timeline'} · {exitAt ? 'Refresh for later candles' : 'Updates every minute'} · OANDA midpoint</p>
      <button type="button" onClick={() => {setReload(value => value + 1);scores.refresh()}} disabled={fetching}>{fetching ? 'Refreshing chart…' : 'Refresh chart'}</button>
    </div>
    {error && <p className="trade-error" role="alert">{error} {view && 'Showing the last successful chart; it may be outdated.'}</p>}
    {!view && !error && <p role="status">Loading the trade’s candles and indicators…</p>}
    <TradeScoreCards scores={scores} record={record} evidenceIds={evidenceIds} onShowEvidence={showEvidence}
      sessionCard={isOpen && <TradeSessionScore session={session} evidenceId={evidenceIds.session} onShowEvidence={()=>showEvidence('session')} />}
      coach={<TradeCoach record={record} active={active} latestClose={scores.error ? null : scores.value?.full_trade?.data_through ?? scores.value?.entry_score?.data_through} onBusyChange={onCoachBusyChange} onDirtyChange={onCoachDirtyChange} />}>
      {children}
    </TradeScoreCards>
    {view && <>
      <div className="trade-chart-status">
        {exitAt && <span>{view.coverage.after_exit_count ?? 0} / {view.coverage.after_exit_target ?? 160} candles after exit</span>}
        <span>Chart context only · entry scores stay fixed</span>
        {view.coverage.contains_post_exit_prices && <span>Exit candle includes prices after exit</span>}
        {view.coverage.exit_candle_pending && <span>Exit candle still forming</span>}
      </div>
      {view.coverage.missing_candle_count > 0 && <p className="trade-error" role="status">{view.coverage.missing_candle_count} scheduled H4 candle(s) unavailable. See chart details below.</p>}
      {!view.candles.length && <p className="trade-help">No candle is available from entry onward yet. Showing earlier context.</p>}
      <Suspense fallback={<p role="status">Loading chart…</p>}><MarketChart snapshot={view} guideRuleSet={scores.value?.rule_set} selectedTime={selected} onSelect={setSelected} draftZones={zones} tradeTimeline /></Suspense>
      <details className="trade-chart-details"><summary>Chart details & timing</summary>
        <dl className="trade-metrics">{view.events.map(event => <div key={event.kind}><dt>{event.kind === 'entry' ? 'Entry' : 'Exit'} · actual fill</dt><dd>{event.price}<small>{stamp(event.at)}</small></dd></div>)}</dl>
        <p className="trade-help">Arrows mark the H4 candles containing each fill. Exact fill times are shown here and in the trade overview. Midpoint prices may differ from your broker fills. A full entry candle may include prices from before entry.</p>
        {exitAt && <p className="trade-help">The first 160 available candles after the exit candle provide review context. Refresh later for more candles if fewer are available; closed trades do not refresh automatically.</p>}
        {view.coverage.contains_post_exit_prices && <p className="trade-help">Your exit happened partway through an H4 candle. Its full prices include movement after exit and do not affect your recorded result.</p>}
        {view.coverage.forming_count > 0 && <p className="trade-help">Forming prices and indicators change until the candle closes. They never receive strategy points or change your saved entry assessment.</p>}
        {view.coverage.exit_candle_pending && <p className="trade-help">Refresh after the exit candle’s scheduled close to see the full candle.</p>}
        {view.coverage.missing_candle_count > 0 && <p className="trade-help">Missing candles start at {stamp(view.coverage.first_missing_open)}. This can reflect a market closure or data gap; prices are never filled in.</p>}
        {view.events.some(event => !event.candle_open_time) && <p className="trade-help">An entry or exit occurred outside available candles; no marker is placed on an unrelated candle.</p>}
      </details>
    </>}
    <TradeScoreDetails value={scores.value} entryRef={entryEvidenceRef} fullRef={fullEvidenceRef} evidenceIds={evidenceIds} />
    {isOpen && session.view && !session.dataError &&
      <TradeSessionEvidence view={session.view} evidenceId={evidenceIds.session} headingRef={sessionEvidenceRef} onOpenTodayBreakdown={onOpenTodayBreakdown} />}
  </section>
}
