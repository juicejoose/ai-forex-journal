import { lazy, Suspense, useMemo, useState } from 'react'
import { setupChartSnapshot } from './setupHistory.js'
import { setupTime } from './setupEvaluation.js'
import { drawnZone, localInputTime } from './setupDrawing.js'
import useChartContext from './useChartContext.js'
import ChartContextStatus from './ChartContextStatus.jsx'
const MarketChart = lazy(() => import('./MarketChart.jsx'))

export default function SetupChartEditor({ preview, zones, onZonesChange, drawing, onDrawingChange, disabled }) {
  const [selectedTime, setSelectedTime] = useState(null)
  const market = useMemo(() => setupChartSnapshot(preview.snapshot, true), [preview.snapshot])
  const extra = useChartContext(market,false,preview.snapshot.mode === 'live' ? preview.snapshot.cutoff_at : null)
  const point = value => {
    if (disabled || !drawing) return
    if (drawing.kind === 'origin') {
      if (value.candle.complete === false) return
      onZonesChange(zones.map(zone => zone.key === drawing.key ? { ...zone, originAt: localInputTime(value.candle.open_time) } : zone))
      onDrawingChange(null)
    } else if (drawing.first === undefined) onDrawingChange({ ...drawing, first: value.price })
    else {
      const zone = drawnZone(drawing.kind, drawing.first, value.price, zones, crypto.randomUUID())
      if (zone) onZonesChange([...zones, zone])
      onDrawingChange(null)
    }
  }
  return <section className="se-chart-editor" aria-label="Draft zone chart" onKeyDown={event => {
    if (event.key === 'Escape') onDrawingChange(null)
  }}>
    <div className="se-row"><h4>Mark your zones</h4><span className="se-help">{zones.length} / 8 zones</span></div>
    <p className="se-help">Fixed at {setupTime(preview.snapshot.cutoff_at)} · Last H4 close {setupTime(preview.snapshot.data_through)}. Capture uses this exact market evidence.</p>
    {preview.snapshot.prior_session_context && <p className="se-notice">No candle has closed in this session. The chart and scores show the previous completed session.</p>}
    <div className="se-drawing-tools" role="group" aria-label="Zone drawing tools">
      <button type="button" aria-pressed={drawing?.kind === 'support'} disabled={disabled || zones.length >= 8} onClick={() => onDrawingChange({ kind: 'support' })}>Draw support</button>
      <button type="button" aria-pressed={drawing?.kind === 'resistance'} disabled={disabled || zones.length >= 8} onClick={() => onDrawingChange({ kind: 'resistance' })}>Draw resistance</button>
      {drawing && <button type="button" onClick={() => onDrawingChange(null)}>Cancel drawing</button>}
    </div>
    <p className="se-drawing-status" role="status">{drawing?.kind === 'origin'
      ? `Select a completed origin candle in the price chart for ${zones.find(zone => zone.key === drawing.key)?.label || 'this zone'}.`
      : drawing ? drawing.first === undefined ? 'Select the first price boundary on the price chart.'
        : `First boundary: ${drawing.first.toFixed(5)}. Select the second price boundary.`
        : 'Choose a drawing tool, then click or tap two price boundaries. You can refine prices and names below. Origin selection is optional and separate.'}</p>
    <ChartContextStatus {...extra} onRefresh={extra.refresh} />
    <Suspense fallback={<p role="status">Loading chart…</p>}>
      <MarketChart snapshot={extra.chart} evaluation={preview.snapshot.rule_evaluation} selectedTime={selectedTime} onSelect={setSelectedTime}
        frozen draftZones={zones} drawing={disabled ? null : drawing} onDrawingPoint={point} />
    </Suspense>
  </section>
}
