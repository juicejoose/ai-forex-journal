import test from 'node:test'
import assert from 'node:assert/strict'
import { buildChartData, chartTime, chartStamp, chartTick, indicatorSeries } from '../src/marketChartData.js'

const candle = (hour, indicators = {}) => ({
  open_time: `2026-10-20T${String(hour).padStart(2, '0')}:00:00+00:00`,
  close_time: `2026-10-20T${String(hour + 4).padStart(2, '0')}:00:00+00:00`,
  open: 1.1, high: 1.12, low: 1.09, close: 1.11, indicators,
})

test('chart history is bounded to the period before review and never earns scores', () => {
  const earlier = candle(1), first = candle(5), second = candle(9)
  const snapshot = { candles: [first, second], chart_context: { candles: [candle(13), first, earlier, earlier] } }
  const evaluation = { candles: [ { ...earlier, candle_id: 'wrong' }, { ...first, candle_id: 'C1' } ] }
  const before = structuredClone(snapshot)
  const result = buildChartData(snapshot, evaluation)
  assert.deepEqual(result.rows.map(row => row.time), [1, 5, 9].map(hour => chartTime(candle(hour).open_time)))
  assert.equal(result.startIndex, 1)
  assert.equal(result.rows[0].score, undefined)
  assert.equal(result.rows[1].score.candle_id, 'C1')
  assert.deepEqual(snapshot, before)
})

test('legacy snapshots use only saved history and never invent RSI MA readings', () => {
  const result = buildChartData({ candles: [candle(5, { rsi14: 42 })], previous_candle: candle(1) }, null)
  assert.equal(result.startIndex, 1)
  assert.equal(result.hasRsiMa, false)
  assert.deepEqual(indicatorSeries(result.rows, values => values.rsi14_sma14), result.rows.map(row => ({ time: row.time })))
  assert.deepEqual(buildChartData(null).rows, [])
})

test('invalid prices are omitted and mismatched score timestamps are not attached', () => {
  const first = candle(5)
  const result = buildChartData({ candles: [{ ...candle(1), close: NaN }, first] },
    { candles: [{ ...first, close_time: candle(9).close_time, candle_id: 'C2' }] })
  assert.equal(result.rows.length, 1)
  assert.equal(result.rows[0].score, null)
})

test('missing indicators remain gaps while a true zero momentum is retained', () => {
  const result = buildChartData({ candles: [candle(1, { squeeze: { momentum: 0 } }), candle(5), candle(9, { squeeze: { momentum: -.001 } })] })
  const values = indicatorSeries(result.rows, row => row.squeeze?.momentum)
  assert.equal(values[0].value, 0)
  assert.equal(Object.hasOwn(values[1], 'value'), false)
  assert.equal(values[2].value, -.001)
})

test('RSI guide levels follow saved rule versions and proximity settings', () => {
  const snapshot = { candles: [candle(1, { rsi14_sma14: 51 })] }
  const version1 = { rule_set: { version: 1, factors: [{ id: 'rsi_extreme' }] } }
  assert.deepEqual(buildChartData(snapshot, version1).guides.map(guide => guide.value), [30, 70])
  const version7 = { rule_set: { version: 7, factors: [{ id: 'rsi_extreme', source: 'rsi14_sma14',
    trend: { lower_threshold: 40, upper_threshold: 60 }, trend_reduction: { bearish_max: 44, bullish_min: 56 } }] } }
  const result = buildChartData(snapshot, version7)
  assert.equal(result.rsiSource, 'RSI MA')
  assert.deepEqual(result.guides.map(guide => guide.value), [40, 60, 44, 56])
  assert.deepEqual(buildChartData(snapshot, null).guides, [])
})

test('chart labels use New York opening times across DST, preserving real UTC ordering', () => {
  const summer = chartTime('2026-10-30T21:00:00+00:00')
  const winter = chartTime('2026-11-01T22:00:00+00:00')
  assert.match(chartStamp(summer), /5:00 PM EDT/)
  assert.match(chartStamp(winter), /5:00 PM EST/)
  assert.equal(chartTick(summer, 3), '5:00 PM')
  assert.equal(chartTick(winter, 3), '5:00 PM')
  assert.equal(winter - summer, 49 * 3600)
})
