import { lazy, Suspense, useRef, useState } from 'react'
import MarketEvidence from './MarketEvidence.jsx'
import StrategyScores from './StrategyScores.jsx'
import { chartTime } from './marketChartData.js'
import SetupZoneHistory from './SetupZoneHistory.jsx'

const MarketChart = lazy(() => import('./MarketChart.jsx'))

export default function MarketReview({ snapshot, evaluation, setupZones }) {
  const [chosenTime, setChosenTime] = useState(null)
  const [zoneId, setZoneId] = useState(null)
  const [showCloses, setShowCloses] = useState(false)
  const chartRef = useRef(null)
  const selectedZone = setupZones?.find(zone => zone.id === zoneId) ?? setupZones?.[0]
  const available = [...(snapshot?.chart_context?.candles ?? snapshot?.previous_candles ?? []), ...(snapshot?.candles ?? [])]
  const selectedTime = available.some(candle => chartTime(candle.open_time) === chosenTime)
    ? chosenTime : chartTime(snapshot?.candles?.at(-1)?.open_time)
  return <>
    <MarketEvidence snapshot={snapshot} />
    <SetupZoneHistory zones={setupZones} selectedZone={selectedZone} onZoneChange={setZoneId}
      showCloses={showCloses} onShowCloses={setShowCloses} onSelect={time => {
        setChosenTime(time)
        requestAnimationFrame(() => chartRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
      }} />
    <div ref={chartRef} style={{ scrollMarginTop: '4rem' }}>
    <Suspense fallback={<p className="ss-help" role="status">Loading market chart…</p>}>
      <MarketChart snapshot={snapshot} evaluation={evaluation} selectedTime={selectedTime} onSelect={setChosenTime}
        zoneOverlay={selectedZone} showZoneCloses={showCloses} frozen={setupZones !== undefined} />
    </Suspense>
    </div>
    <StrategyScores evaluation={evaluation} snapshot={snapshot} selectedTime={selectedTime} onSelectCandle={setChosenTime} />
  </>
}
