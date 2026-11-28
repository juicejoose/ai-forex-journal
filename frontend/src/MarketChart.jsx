import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { CandlestickSeries, LineSeries, HistogramSeries, LineStyle, CrosshairMode, createChart, createSeriesMarkers } from 'lightweight-charts'
import { buildChartData, candleLabel, chartNumber, chartStamp, chartTick, indicatorSeries } from './marketChartData.js'
import { factorDescription } from './strategyDescriptions.js'
import { formatChange, changeTone } from './journalCalendar.js'
import { zoneChartMarkers, zoneLineData } from './setupHistory.js'
import { ZoneBands } from './ZoneBands.js'
import { draftBands, drawingPoint } from './setupDrawing.js'
import { tradeTimelineMarkers, timelineCandleState } from './tradeTimeline.js'
import './MarketChart.css'

const colors = { up: '#249c79', down: '#d65e70', ema: '#598cec', sma: '#249c79', ma: '#ab78e5', raw: '#84949d' }
const momentumColors = { lime: '#2bbf91', green: '#217e68', red: '#e36578', maroon: '#9e4a63' }
const directions = { bullish: 'Bullish lean', bearish: 'Bearish lean', mixed: 'Mixed', neutral: 'Neutral', insufficient_data: 'Insufficient data' }
const points = value => Number.isFinite(value) ? String(value) : '—'
const rightOffset = 2
const zoomOutStep = 1.4

function zoomedRange(range, multiplier) {
  const middle = (range.from + range.to) / 2
  const half = Math.max(3, (range.to - range.from) * multiplier / 2)
  return { from: middle - half, to: middle + half }
}

function SelectedCandle({ row, hasEvaluation, tradeTimeline, entryChart }) {
  if (!row) return null
  const { candle, score } = row
  const indicators = candle.indicators ?? {}
  const squeeze = indicators.squeeze ?? {}
  const change = (candle.close - candle.open) / candle.open * 100
  return <div className="mc-selection">
    <div className="mc-selection-heading">
      <div><p className="jv-eyebrow">{entryChart || tradeTimeline || candle.complete === false || candle.timeline_phase === 'after_review' ? timelineCandleState(candle).toUpperCase() : row.analyzed ? 'SELECTED CANDLE' : 'EARLIER CONTEXT · OUTSIDE REVIEW'}</p>
        <h4>{score?.candle_id ? `${score.candle_id} · ` : ''}{candleLabel(candle)}</h4></div>
      <strong className={`jv-tone-${changeTone(change)}`}>{formatChange(change)}</strong>
    </div>
    <dl className="mc-values">
      {['open', 'high', 'low', 'close'].map(key => <div key={key}><dt>{key === 'close' && candle.complete === false ? 'Latest' : key}</dt><dd>{chartNumber(candle[key])}</dd></div>)}
      <div><dt>EMA20</dt><dd>{chartNumber(indicators.ema20)}</dd></div>
      <div><dt>SMA190</dt><dd>{chartNumber(indicators.sma190)}</dd></div>
      <div><dt>RSI14</dt><dd>{chartNumber(indicators.rsi14, 2)}</dd></div>
      <div><dt>RSI MA · SMA14</dt><dd>{chartNumber(indicators.rsi14_sma14, 2)}</dd></div>
      <div><dt>Momentum</dt><dd>{chartNumber(squeeze.momentum)}</dd></div>
      <div><dt>Squeeze</dt><dd>{squeeze.state ?? 'Unavailable'}{squeeze.released ? ' · Released' : ''}</dd></div>
    </dl>
    {score ? <>
      <div className="mc-score-line"><strong>{directions[score.direction] ?? 'Unavailable'}</strong>
        <span><b className="ss-bullish">{points(score.bullish_points)} bull</b> / <b className="ss-bearish">{points(score.bearish_points)} bear</b></span>
        <span>Net {score.direction === 'insufficient_data' ? 'unavailable' : points(score.net_score)}</span></div>
      <div className="mc-factors">{score.factors.map(factor => <div key={factor.factor_id}>
        <span>{factor.name}</span><strong className={`ss-${factor.outcome}`}>{factor.outcome === 'bullish' ? `+${factor.bullish_points} Bull`
          : factor.outcome === 'bearish' ? `+${factor.bearish_points} Bear` : factor.outcome === 'neutral' ? 'Neither' : 'Unavailable'}</strong>
        <small>{factorDescription(factor)}</small></div>)}</div>
    </> : !entryChart && <p className="mc-help">{candle.complete === false ? 'Forming candle: prices and indicators are provisional. It has no strategy score and is excluded from saved AI analysis.' : candle.timeline_phase === 'after_review' ? 'Later candles are chart context only. They do not contribute to the saved review or its strategy scores.' : tradeTimeline ? 'Timeline indicators are market context only. The entry assessment uses its own frozen evidence.' : !row.analyzed ? 'Earlier candles provide chart context and do not contribute to this review’s scores.'
      : hasEvaluation ? 'Strategy results are unavailable for this candle.' : 'Written strategy review · this journal has no Python factor scores.'}</p>}
  </div>
}

export default function MarketChart({ snapshot, evaluation, guideRuleSet, selectedTime, onSelect, zoneOverlay, showZoneCloses = false, showZonePatterns = false, frozen = false, draftZones, drawing, onDrawingPoint, tradeTimeline = false, priceLevels }) {
  const id = useId()
  const hostRef = useRef(null)
  const shadeRef = useRef(null)
  const apiRef = useRef(null)
  const selectRef = useRef(onSelect)
  const drawingRef = useRef(null)
  const [rawRsi, setRawRsi] = useState(true)
  const [hovered, setHovered] = useState(null)
  const model = useMemo(() => buildChartData(snapshot, evaluation, guideRuleSet), [snapshot, evaluation, guideRuleSet])
  const hasRows = model.rows.length > 0
  const formingRow = model.rows.find(row => row.candle.complete === false)
  const formingAsOf = formingRow?.candle.as_of ?? snapshot?.as_of ?? snapshot?.chart_followup?.as_of
  const showRaw = rawRsi || !model.hasRsiMa || model.rsiSource === 'RSI14'
  const selected = model.rows.find(row => row.time === selectedTime) ?? model.rows.at(-1)
  const selectedIndex = model.rows.indexOf(selected)
  const inspected = (!drawing && model.rows.find(row => row.time === hovered)) || selected
  const entryChart = snapshot?.analysis_kind === 'trade_entry_chart'
  const period = tradeTimeline ? 'Trade' : snapshot?.analysis_kind === 'custom_range' ? 'Range' : 'Session'
  const partial = snapshot?.analysis_kind === 'intraday' && !snapshot.session?.complete
  const identity = tradeTimeline ? `trade-${snapshot.trade_id}` : `${snapshot?.analysis_kind ?? 'daily'}-${snapshot?.session?.start_utc}-${snapshot?.session?.end_utc}`

  useEffect(() => { selectRef.current = onSelect }, [onSelect])

  useEffect(() => { drawingRef.current = drawing ? onDrawingPoint : null }, [drawing, onDrawingPoint])

  // Create once per review. Subsequent Today polls replace data without resetting zoom.
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const theme = () => {
      const style = getComputedStyle(host)
      return { background: { color: style.getPropertyValue('--bg').trim() },
        textColor: style.getPropertyValue('--text').trim() }
    }
    const chart = createChart(host, {
      autoSize: true, height: 610, layout: { ...theme(), fontSize: 11, attributionLogo: true,
        panes: { enableResize: false, separatorColor: 'rgba(130,130,150,0.15)' } },
      grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(130,130,150,0.12)' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false, minimumWidth: 76 },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, tickMarkFormatter: chartTick,
        rightOffset, shiftVisibleRangeOnNewBar: false },
      localization: { locale: 'en-US', timeFormatter: chartStamp },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
    })
    const priceFormat = { type: 'price', precision: 5, minMove: 0.00001 }
    const lineOptions = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: true, priceFormat }
    const candles = chart.addSeries(CandlestickSeries, { upColor: colors.up, downColor: colors.down,
      wickUpColor: colors.up, wickDownColor: colors.down, borderVisible: false, priceLineVisible: false, priceFormat })
    const ema = chart.addSeries(LineSeries, { ...lineOptions, color: colors.ema, lineWidth: 2 })
    const sma = chart.addSeries(LineSeries, { ...lineOptions, color: colors.sma, lineWidth: 2 })
    const zoneOptions = { ...lineOptions, color: '#d8a64b', lineWidth: 1, lineStyle: LineStyle.Dashed,
      crosshairMarkerVisible: false, autoscaleInfoProvider: () => null }
    const zoneLower = chart.addSeries(LineSeries, zoneOptions)
    const zoneUpper = chart.addSeries(LineSeries, zoneOptions)
    const rsiMa = chart.addSeries(LineSeries, { ...lineOptions, color: colors.ma, lineWidth: 2,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 } }, 1)
    const rsi = chart.addSeries(LineSeries, { ...lineOptions, color: colors.raw, lineWidth: 1,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 } }, 1)
    rsiMa.priceScale().applyOptions({ autoScale: true, scaleMargins: { top: 0.05, bottom: 0.05 } })
    const momentum = chart.addSeries(HistogramSeries, { ...lineOptions, base: 0 }, 2)
    // Set price padding after creating the panes so the indicators keep their own scales.
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.14, bottom: 0.08 } })
    momentum.createPriceLine({ price: 0, color: '#87919d', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false })
    chart.panes()[0].setStretchFactor(2.3)
    chart.panes()[1].setStretchFactor(1)
    chart.panes()[2].setStretchFactor(1)
    const markers = createSeriesMarkers(candles, [])
    const zoneBands = new ZoneBands()
    candles.attachPrimitive(zoneBands)
    const state = { chart, candles, ema, sma, zoneLower, zoneUpper, rsiMa, rsi, momentum, markers, zoneBands, rows: [], guides: [], levels: [], initialized: false }
    function shade() {
      const overlay = shadeRef.current
      const analyzed = state.rows.filter(row => row.analyzed)
      if (!overlay) return
      if (!analyzed.length) { overlay.style.display = 'none'; return }
      const scale = chart.timeScale()
      const width = scale.width()
      const start = scale.timeToCoordinate(analyzed[0].time)
      const end = scale.timeToCoordinate(analyzed.at(-1).time)
      if (start === null || end === null) { overlay.style.display = 'none'; return }
      const halfBar = Math.abs((scale.logicalToCoordinate(1) ?? 0) - (scale.logicalToCoordinate(0) ?? 0)) / 2
      const left = Math.max(0, start - halfBar)
      const right = Math.min(width, end + halfBar)
      overlay.style.display = right > left ? 'block' : 'none'
      overlay.style.left = `${left}px`
      overlay.style.width = `${Math.max(0, right - left)}px`
    }
    state.shade = shade
    apiRef.current = state
    const handleClick = event => {
      if (drawingRef.current) {
        const point = drawingPoint(event, state.rows, y => candles.coordinateToPrice(y))
        if (point) drawingRef.current(point)
        return
      }
      if (typeof event.time === 'number' && state.rows.some(row => row.time === event.time)) selectRef.current?.(event.time)
    }
    const handleHover = event => setHovered(typeof event.time === 'number' ? event.time : null)
    chart.subscribeClick(handleClick)
    chart.subscribeCrosshairMove(handleHover)
    chart.timeScale().subscribeVisibleLogicalRangeChange(shade)
    chart.timeScale().subscribeSizeChange(shade)
    const preference = window.matchMedia('(prefers-color-scheme: dark)')
    const updateTheme = () => chart.applyOptions({ layout: theme() })
    preference.addEventListener('change', updateTheme)
    return () => {
      preference.removeEventListener('change', updateTheme)
      chart.unsubscribeClick(handleClick)
      chart.unsubscribeCrosshairMove(handleHover)
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(shade)
      chart.timeScale().unsubscribeSizeChange(shade)
      chart.remove()
      apiRef.current = null
    }
  }, [identity, hasRows])

  useEffect(() => {
    const api = apiRef.current
    if (!api || !model.rows.length) return
    const { rows } = model
    const range = api.chart.timeScale().getVisibleLogicalRange()
    const previousFirst = api.rows?.[0]?.time
    const shiftedBy = previousFirst === undefined ? 0 : Math.max(0, rows.findIndex(row => row.time === previousFirst))
    const expandedContext = snapshot?.chart_context?.reconstructed_context === true
    api.rows = rows
    api.candles.setData(rows.map(({ time, candle }) => ({ time, open: candle.open, high: candle.high, low: candle.low, close: candle.close, ...(candle.complete === false ? {borderVisible:true,borderColor:'#d8a64b',wickColor:'#d8a64b'} : {}) })))
    api.ema.setData(indicatorSeries(rows, values => values.ema20))
    api.sma.setData(indicatorSeries(rows, values => values.sma190))
    api.rsiMa.setData(indicatorSeries(rows, values => values.rsi14_sma14))
    api.rsi.setData(indicatorSeries(rows, values => values.rsi14))
    api.momentum.setData(indicatorSeries(rows, values => values.squeeze?.momentum).map((point, index) => ({
      ...point, color: momentumColors[rows[index].candle.indicators?.squeeze?.histogram_color] ?? colors.raw,
    })))
    for (const guide of api.guides) guide.series.removePriceLine(guide.line)
    const guideSeries = model.rsiSource === 'RSI MA' ? api.rsiMa : api.rsi
    // Fit both the visible readings and their strategy thresholds in the RSI pane.
    const levels = model.guides.map(guide => guide.value)
    const fitThresholds = original => {
      const info = original()
      if (!info?.priceRange) return info
      return { ...info, priceRange: {
        minValue: Math.min(info.priceRange.minValue, ...levels),
        maxValue: Math.max(info.priceRange.maxValue, ...levels),
      } }
    }
    for (const series of [api.rsiMa, api.rsi]) {
      series.applyOptions({ autoscaleInfoProvider: series === guideSeries && levels.length ? fitThresholds : null })
    }
    api.guides = model.guides.map(guide => ({ series: guideSeries, line: guideSeries.createPriceLine({
      price: guide.value, color: guide.proximity ? '#94808b' : '#78659b', lineWidth: 1,
      lineStyle: guide.proximity ? LineStyle.Dotted : LineStyle.Dashed, axisLabelVisible: true,
    }) }))
    if (!api.initialized || (expandedContext && !api.contextExpanded)) {
      // Match All history followed by one Zoom out, without waiting for fitContent's deferred redraw.
      const fullHistory = { from: 0, to: rows.length - 1 + rightOffset }
      api.chart.timeScale().setVisibleLogicalRange(zoomedRange(fullHistory, zoomOutStep))
      api.initialized = true
    } else if (range) api.chart.timeScale().setVisibleLogicalRange({from:range.from+shiftedBy,to:range.to+shiftedBy})
    api.contextExpanded = expandedContext
    api.shade()
  }, [model, identity, snapshot?.chart_context?.reconstructed_context])

  useEffect(() => { apiRef.current?.rsi.applyOptions({ visible: showRaw }) }, [showRaw, identity])

  useEffect(() => {
    const api = apiRef.current
    if (!api) return
    api.zoneLower.setData(zoneLineData(zoneOverlay, model.rows, 'lower'))
    api.zoneUpper.setData(zoneLineData(zoneOverlay, model.rows, 'upper'))
  }, [zoneOverlay, model, identity])

  useEffect(() => {
    const api = apiRef.current
    if (!api || !entryChart) return
    for (const line of api.levels) api.candles.removePriceLine(line)
    api.levels = (priceLevels ?? []).map(level=>api.candles.createPriceLine({
      ...level, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,
    }))
  }, [entryChart, priceLevels, identity, hasRows])

  useEffect(() => {
    const api = apiRef.current
    if (!api || !selected) return
    const first = model.rows[model.startIndex]
    const markers = tradeTimeline ? tradeTimelineMarkers(snapshot, model.rows) : first ? [{ time: first.time, position: 'belowBar', shape: 'circle', color: colors.ma, text: `${period} start` }] : []
    markers.push({ time: selected.time, position: 'aboveBar', shape: 'arrowDown', color: colors.ma, text: selected.score?.candle_id ?? 'Selected' })
    if (!tradeTimeline && formingRow) markers.push({time:formingRow.time,position:'aboveBar',shape:'circle',color:'#d8a64b',text:'Forming'})
    markers.push(...zoneChartMarkers(zoneOverlay, model.rows, showZoneCloses, showZonePatterns))
    api.markers.setMarkers(markers.sort((a, b) => a.time - b.time))
    const range = api.chart.timeScale().getVisibleLogicalRange()
    if (api.lastSelection !== selected.time && range && (selectedIndex < range.from || selectedIndex > range.to)) {
      const span = range.to - range.from
      api.chart.timeScale().setVisibleLogicalRange({ from: selectedIndex - span / 2, to: selectedIndex + span / 2 })
    }
    api.lastSelection = selected.time
  }, [selected, selectedIndex, model, identity, period, zoneOverlay, showZoneCloses, showZonePatterns, tradeTimeline, snapshot, formingRow])

  useEffect(() => {
    const api = apiRef.current
    if (!api) return
    const bands = draftBands(draftZones ?? [], model.rows)
    if (Number.isFinite(drawing?.first) && model.rows.length) bands.push({
      lower: drawing.first, upper: drawing.first, start: 0, end: model.rows.length-1, kind: drawing.kind, label: 'First boundary',
    })
    api.zoneBands.setBands(bands)
    api.chart.applyOptions({ handleScroll: { pressedMouseMove: !drawing, horzTouchDrag: !drawing },
      handleScale: { pinch: !drawing, axisPressedMouseMove: !drawing } })
  }, [draftZones, drawing, model, identity])

  function focusPeriod() {
    if (tradeTimeline && model.endIndex >= 0) onSelect?.(model.rows[model.endIndex].time)
    const padding = tradeTimeline ? Math.max(3, model.reviewedCount * 0.08) : 0
    apiRef.current?.chart.timeScale().setVisibleLogicalRange({ from: model.startIndex - 0.5 - padding, to: model.endIndex + 0.8 + padding })
  }
  function focusZone() {
    const data = zoneLineData(zoneOverlay, model.rows, 'lower')
    if (!data.length) return
    const first = model.rows.findIndex(row => row.time === data[0].time)
    const last = model.rows.findIndex(row => row.time === data.at(-1).time)
    apiRef.current?.chart.timeScale().setVisibleLogicalRange({ from: first - 2, to: last + 2 })
  }
  function zoom(multiplier) {
    const scale = apiRef.current?.chart.timeScale()
    const range = scale?.getVisibleLogicalRange()
    if (!range) return
    scale.setVisibleLogicalRange(zoomedRange(range, multiplier))
  }
  if (!model.rows.length) return null
  return <section className={`market-chart${drawing ? ' mc-drawing' : ''}`} aria-labelledby={`${id}-heading`}>
    <header className="mc-header"><div><h3 id={`${id}-heading`}>{tradeTimeline ? 'Trade market chart' : 'Market chart'}</h3>
      <p>EUR/USD · H4 · New York time</p></div>
      <div className="mc-toolbar" role="group" aria-label="Chart view">
        {!entryChart && <button type="button" onClick={focusPeriod} disabled={model.startIndex >= model.rows.length}>{tradeTimeline ? 'Focus trade' : `${period} only`}</button>}
        {zoneOverlay?.history?.coverage_start && <button type="button" onClick={focusZone}>Zone window</button>}
        <button type="button" onClick={() => apiRef.current?.chart.timeScale().fitContent()}>All history</button>
        <span className="mc-zoom">
          <button type="button" aria-label="Zoom in" onClick={() => zoom(0.7)}>+</button>
          <button type="button" aria-label="Zoom out" onClick={() => zoom(zoomOutStep)}>−</button>
        </span>
      </div>
    </header>
    <div className="mc-legend"><span style={{ '--series-color': colors.ema }}>EMA20</span><span style={{ '--series-color': colors.sma }}>SMA190</span>
      {model.hasRsiMa && <span style={{ '--series-color': colors.ma }}>RSI MA · SMA14</span>}
      {showRaw && <span style={{ '--series-color': colors.raw }}>RSI14</span>}
      {!entryChart && <span className="mc-period-key">{tradeTimeline ? 'candles during trade' : `${period.toLowerCase()} under review`}</span>}
      {zoneOverlay?.history?.coverage_start && <span style={{ '--series-color': '#d8a64b' }}>User zone · {zoneOverlay.label}</span>}</div>
    <p className="mc-readout">{inspected && <>{candleLabel(inspected.candle)}{(tradeTimeline || inspected.candle.complete === false || inspected.candle.timeline_phase === 'after_review') && ` · ${timelineCandleState(inspected.candle)}`} · {inspected.candle.complete === false ? 'Latest' : 'Close'} <b>{chartNumber(inspected.candle.close)}</b> · {model.hasRsiMa ? 'RSI MA' : 'RSI14'} <b>{chartNumber(inspected.candle.indicators?.[model.hasRsiMa ? 'rsi14_sma14' : 'rsi14'], 2)}</b> · Momentum <b>{chartNumber(inspected.candle.indicators?.squeeze?.momentum)}</b></>}</p>
    {formingRow && <p className="mc-forming-note"><strong>◐ Forming H4</strong> · provisional prices and indicators · no strategy points{formingAsOf && ` · updated ${chartStamp(Date.parse(formingAsOf)/1000)}`}{frozen && ' · live context outside the captured assessment'}</p>}
    <div className="mc-plot-wrap">
      <div ref={hostRef} className="mc-plot" aria-label="Interactive price, RSI and momentum chart. Use the candle selector below for keyboard access." />
      <div ref={shadeRef} className="mc-period-shade" aria-hidden="true" />
      <div className="mc-pane-label mc-price-label">PRICE · EMA20 / SMA190</div>
      <div className="mc-pane-label mc-rsi-label">{model.hasRsiMa ? 'RSI · SMA14 SMOOTHING' : 'RSI14'}</div>
      <div className="mc-pane-label mc-momentum-label">SQUEEZE MOMENTUM</div>
    </div>
    <div className="mc-chart-footer">
      <label><input type="checkbox" checked={showRaw} disabled={!model.hasRsiMa || model.rsiSource === 'RSI14'} onChange={event => setRawRsi(event.target.checked)} /> Show raw RSI14</label>
      <span>{model.guides.length ? `${model.rsiSource} levels · ${[...model.guides].sort((a,b) => a.value-b.value).map(guide => `${guide.value} ${guide.label.toLowerCase()}`).join(' · ')}` : 'RSI shown as market context'}</span>
    </div>
    {!entryChart && <><p className="mc-help">Click or tap a candle to select it. Drag sideways to explore; pinch or use + / − to zoom. The purple band marks {tradeTimeline ? 'candles overlapping the trade' : 'the reviewed candles'}.</p>
    <p className="mc-help">{model.historyCount} earlier candles for context · {model.reviewedCount} {tradeTimeline ? 'trade candles' : 'reviewed candles'}.{model.followingCount > 0 && ` ${model.followingCount} candles after ${tradeTimeline ? 'exit' : 'review'}.`}
      {partial && (frozen ? ` ${6 - model.reviewedCount} pending at capture; this saved snapshot stays fixed.`
        : ` ${6 - model.reviewedCount} pending; the chart updates after completed-candle refreshes.`)}
      {!snapshot.chart_context && ' This older snapshot has limited saved history.'}</p></>}
    {snapshot.chart_context?.extended_zone_history && <p className="mc-help">Extended history uses saved OHLC candles. Saved indicator lines cover the available saved context candles and reviewed session; older readings remain unavailable. Zone markers describe observations, not trade signals.</p>}
    <div className="mc-picker"><label htmlFor={`${id}-candle`}>Selected candle</label>
      <div><button type="button" aria-label="Previous candle" disabled={selectedIndex <= 0} onClick={() => onSelect(model.rows[selectedIndex - 1].time)}>←</button>
        <select id={`${id}-candle`} value={selected?.time ?? ''} onChange={event => onSelect(Number(event.target.value))}>
          {model.rows.map(row => <option key={row.time} value={row.time}>{(entryChart || row.candle.complete === false || ['after_exit','after_review'].includes(row.candle.timeline_phase)) ? timelineCandleState(row.candle) : row.analyzed ? row.score?.candle_id ?? (tradeTimeline ? timelineCandleState(row.candle) : 'Review') : 'Context'} · {candleLabel(row.candle)}</option>)}
        </select>
        <button type="button" aria-label="Next candle" disabled={selectedIndex >= model.rows.length - 1} onClick={() => onSelect(model.rows[selectedIndex + 1].time)}>→</button>
      </div>
    </div>
    <SelectedCandle row={selected} hasEvaluation={Boolean(evaluation)} tradeTimeline={tradeTimeline} entryChart={entryChart} />
    <p className="mc-attribution">TradingView Lightweight Charts™ · Copyright (с) 2025 <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView, Inc.</a></p>
  </section>
}
