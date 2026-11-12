import { lazy, Suspense, useState } from 'react'
import MarketEvidence from './MarketEvidence.jsx'
import StrategyScores from './StrategyScores.jsx'
import { chartTime } from './marketChartData.js'

const MarketChart = lazy(() => import('./MarketChart.jsx'))

export default function MarketReview({ snapshot, evaluation }) {
  const [chosenTime, setChosenTime] = useState(null)
  const available = [...(snapshot?.chart_context?.candles ?? snapshot?.previous_candles ?? []), ...(snapshot?.candles ?? [])]
  const selectedTime = available.some(candle => chartTime(candle.open_time) === chosenTime)
    ? chosenTime : chartTime(snapshot?.candles?.at(-1)?.open_time)
  return <>
    <MarketEvidence snapshot={snapshot} />
    <Suspense fallback={<p className="ss-help" role="status">Loading market chart…</p>}>
      <MarketChart snapshot={snapshot} evaluation={evaluation} selectedTime={selectedTime} onSelect={setChosenTime} />
    </Suspense>
    <StrategyScores evaluation={evaluation} snapshot={snapshot} selectedTime={selectedTime} onSelectCandle={setChosenTime} />
  </>
}
