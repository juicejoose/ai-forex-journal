import assert from 'node:assert/strict'
import test from 'node:test'
import { setupChartSnapshot, zoneChartMarkers, zoneLineData, zoneEventLabel } from '../src/setupHistory.js'
import { buildChartData, chartTime } from '../src/marketChartData.js'
import { setupRequest } from '../src/setupEvaluation.js'

const candle = hour => ({ open_time: `2020-10-20T${String(hour).padStart(2,'0')}:00:00Z`,
  close_time: `2020-10-20T${String(hour+4).padStart(2,'0')}:00:00Z`, open: 1.1, high: 1.12, low: 1.09, close: 1.11 })
const old = candle(1), recent = { ...candle(5), indicators: { ema20: 1.1 } }, current = candle(9), future = candle(13)
const zone = { id: 'Z1', lower: '1.10000', upper: '1.10100',
  history: { origin_at: old.open_time, coverage_start: old.open_time, coverage_end: current.close_time, events: [
    { id: 'Z1-V1', kind: 'visit_start', visit_number: 1, boundary_start: true, ...old },
    { id: 'Z1-C2', kind: 'close_position', position: 'above', previous_position: 'inside', ...recent },
    { id: 'Z1-C4', kind: 'close_position', position: 'below', ...future },
  ] } }

test('setup charts extend only from saved past candles and preserve recent indicators and scoring scope', () => {
  const market = { candles: [current], chart_context: { candles: [recent] } }
  const setup = { market_data: market, cutoff_at: current.close_time, source_candles: [old, candle(5), current, future], zones: [zone] }
  const before = structuredClone(setup)
  const projected = setupChartSnapshot(setup)
  assert.deepEqual(projected.chart_context.candles, [old, recent])
  assert.deepEqual(projected.candles, market.candles)
  const model = buildChartData(projected, { candles: [{ ...old, candle_id: 'wrong' }, { ...current, candle_id: 'C1' }] })
  assert.equal(model.rows[0].score, undefined)
  assert.equal(model.rows[0].candle.indicators, undefined)
  assert.equal(model.rows[1].candle.indicators.ema20, 1.1)
  assert.equal(model.rows[2].score.candle_id, 'C1')
  assert.deepEqual(setup, before)
})
test('legacy and undated setups retain their original chart history', () => {
  const market = { candles: [current], chart_context: { candles: [recent] } }
  assert.equal(setupChartSnapshot({ market_data: market, source_candles: [old], zones: [{ id: 'Z1' }] }), market)
  assert.equal(setupChartSnapshot(undefined), undefined)
})
test('markers use saved visible candle events, optional close changes and boundary labels', () => {
  const rows = buildChartData({ candles: [current], chart_context: { candles: [old, recent] } }).rows
  assert.deepEqual(zoneChartMarkers(zone, rows).map(m => m.text), ['V1*','Zone history'])
  assert.deepEqual(zoneChartMarkers(zone, rows, true).map(m => m.text), ['V1*','Zone history','above'])
  assert.equal(zoneChartMarkers(zone, rows, true)[2].time, chartTime(recent.open_time))
  assert.equal(zoneChartMarkers({ history: { events: [{ ...zone.history.events[0], close_time: future.close_time }] } }, rows).length, 0)
})
test('zone price lines cover the observed window and never add future chart candles', () => {
  const rows = buildChartData({ candles: [current], chart_context: { candles: [old, recent] } }).rows
  assert.deepEqual(zoneLineData(zone, rows, 'lower'), [{ time: chartTime(old.open_time), value: 1.1 }, { time: chartTime(current.open_time), value: 1.1 }])
  assert.deepEqual(zoneLineData({ ...zone, history: {} }, rows, 'lower'), [])
  assert.deepEqual(zoneLineData({ ...zone, lower: 'NaN' }, rows, 'lower'), [])
})
test('event descriptions distinguish initial states and gaps from a close-position change', () => {
  assert.equal(zoneEventLabel(zone.history.events[0]), 'Visit V1 · boundary group')
  assert.equal(zoneEventLabel(zone.history.events[1]), 'Close changed to above')
  assert.equal(zoneEventLabel({ kind: 'close_position', position: 'inside', previous_position: null }), 'First observed close inside')
  assert.equal(zoneEventLabel({ kind: 'close_position', position: 'below', after_gap: true }), 'First close after gap below')
})
test('origin timestamps are explicit and cannot be after the historical cutoff', () => {
  const form = { title: '', direction: 'long', mode: 'historical', asOf: '2020-10-20T10:00',
    observations: '', zones: [{ label: 'Support', kind: 'support', timeframe: 'H4', lower: '1.1', upper: '1.2', originAt: '2020-10-10T17:00' }] }
  assert.equal(setupRequest(form, 'id').zones[0].origin_at, new Date('2020-10-10T17:00').toISOString())
  assert.throws(() => setupRequest({ ...form, zones: [{ ...form.zones[0], originAt: '2020-10-20T11:00' }] }, 'id'), /origin/)
  assert.throws(() => setupRequest({ ...form, zones: [{ ...form.zones[0], originAt: 'bad' }] }, 'id'), /origin/)
})
