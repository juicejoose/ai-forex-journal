import { lazy, Suspense, useRef, useState } from 'react'
import MarketEvidence from './MarketEvidence.jsx'
import StrategyScores from './StrategyScores.jsx'
import { chartTime } from './marketChartData.js'
import SetupZoneHistory from './SetupZoneHistory.jsx'
import useChartContext from './useChartContext.js'
import ChartContextStatus from './ChartContextStatus.jsx'

const MarketChart = lazy(() => import('./MarketChart.jsx'))

export default function MarketReview({ snapshot, evaluation, setupZones, includeAfter = false, formingAt = null }) {
  const [chosenTime, setChosenTime] = useState(null)
  const [zoneId, setZoneId] = useState(null)
  const [showCloses, setShowCloses] = useState(false)
  const [showPatterns, setShowPatterns] = useState(true)
  const chartRef = useRef(null)
  const extra = useChartContext(snapshot,includeAfter,formingAt)
  const [selectionNotice,setSelectionNotice] = useState('')
  const selectedZone = setupZones?.find(zone => zone.id === zoneId) ?? setupZones?.[0]
  const available = [...(extra.chart?.chart_context?.candles ?? []), ...(snapshot?.candles ?? []), ...(extra.chart?.chart_followup?.candles ?? []), ...(extra.chart?.chart_forming?.candle ? [extra.chart.chart_forming.candle] : [])]
  const selectedTime = available.some(candle => chartTime(candle.open_time) === chosenTime)
    ? chosenTime : chartTime(snapshot?.candles?.at(-1)?.open_time)
  return <>
    {snapshot?.candles?.length !== 0 && <MarketEvidence snapshot={snapshot} />}
    <SetupZoneHistory zones={setupZones} selectedZone={selectedZone} onZoneChange={setZoneId}
      showPatterns={showPatterns} onShowPatterns={setShowPatterns}
      showCloses={showCloses} onShowCloses={setShowCloses} onSelect={time => {
        if (!available.some(candle => chartTime(candle.open_time) === time)) { setSelectionNotice('That saved zone event is outside this chart’s 160-candle context window. Its details remain in the zone evidence.'); return }
        setSelectionNotice(''); setChosenTime(time)
        requestAnimationFrame(() => chartRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
      }} />
    <div ref={chartRef} style={{ scrollMarginTop: '4rem' }}>
    <ChartContextStatus {...extra} includeAfter={includeAfter} onRefresh={extra.refresh} />
    {selectionNotice && <p role="status" className="mc-help">{selectionNotice}</p>}
    <Suspense fallback={<p className="ss-help" role="status">Loading market chart…</p>}>
      <MarketChart snapshot={extra.chart} evaluation={evaluation} selectedTime={selectedTime} onSelect={setChosenTime}
        zoneOverlay={selectedZone} showZoneCloses={showCloses} showZonePatterns={showPatterns} frozen={setupZones !== undefined} />
    </Suspense>
    </div>
    <StrategyScores evaluation={evaluation} snapshot={snapshot} selectedTime={selectedTime} onSelectCandle={setChosenTime} />
  </>
}
