import test from 'node:test'
import assert from 'node:assert/strict'
import { buildChartData, chartTime } from '../src/marketChartData.js'
import { validTradeTimeline, tradeTimelineMarkers, timelineCandleState } from '../src/tradeTimeline.js'

const candle = hour => ({open_time: `2026-11-10T${hour}:00:00Z`, close_time: `2026-11-10T${Number(hour)+4}:00:00Z`,
  open: 1.1, high: 1.102, low: 1.099, close: 1.101, complete: true, indicators: {rsi14_sma14: 52}})
const first = candle('10'), second = {...candle('14'), complete: false}
const event = (kind, at, row) => ({kind, at, price: '1.10000', candle_open_time: row?.open_time ?? null})
const view = () => ({schema_version:1, analysis_kind:'trade_timeline', trade_id:'a', status:'open',
  as_of:'2026-11-10T16:00:00Z', entry_at:'2026-11-10T11:00:00Z', exit_at:null,
  candles:[first,second], chart_context:{candles:[]}, coverage:{missing_candle_count:0},
  events:[event('entry','2026-11-10T11:00:00Z',first)]})

test('timeline rows never acquire strategy scores, including forming candles', () => {
  const scores = {candles:[{...first, candle_id:'C1', bullish_points:5}],rule_set:{factors:[{id:'rsi_extreme'}]}}
  const result = buildChartData(view(),scores)
  assert.equal(result.rows.length,2)
  assert.ok(result.rows.every(row => !row.score))
  assert.deepEqual(result.guides,[])
})

test('a trade entered over the weekend can show context without trade candles', () => {
  const data = {...view(),entry_at:'2026-11-14T14:00:00Z',candles:[],chart_context:{candles:[first,second]}}
  const result = buildChartData(data)
  assert.equal(result.rows.length,2)
  assert.equal(result.startIndex,2)
  assert.ok(result.rows.every(row => !row.analyzed))
  assert.deepEqual(buildChartData({...data,analysis_kind:'daily'}).rows,[])
})

test('entry, exit and forming markers anchor only to the supplied containing candles', () => {
  const data = view()
  data.events.push(event('exit','2026-11-10T15:23:00Z',second))
  const markers = tradeTimelineMarkers(data,buildChartData(data).rows)
  assert.deepEqual(markers.map(m => m.text),['Entry 1.10000','Exit 1.10000','Forming'])
  assert.equal(markers[1].time,chartTime(second.open_time))
  assert.equal(markers[0].shape,'arrowUp')
  assert.equal(markers[1].shape,'arrowDown')
})

test('same-candle round trip keeps both markers and absent events are not moved to another bar', () => {
  const data = view()
  data.events.push(event('exit','2026-11-10T12:00:00Z',first))
  const rows = buildChartData(data).rows
  const markers = tradeTimelineMarkers(data,rows)
  assert.equal(markers[0].time,markers[1].time)
  assert.equal(tradeTimelineMarkers({...data,events:[event('entry','2026-11-14T12:00:00Z',null)]},rows).length,1)
})

test('response validation prevents rendering another trade or stale open state after exit', () => {
  assert.ok(validTradeTimeline(view(),'a',null))
  assert.equal(validTradeTimeline(view(),'b',null),false)
  assert.equal(validTradeTimeline(view(),'a','2026-11-10T15:00:00Z'),false)
  assert.equal(validTradeTimeline({...view(),as_of:'bad'},'a',null),false)
  assert.equal(validTradeTimeline({...view(),events:[]},'a',null),false)
})

test('forming and post-exit candle labels remain explicit', () => {
  assert.equal(timelineCandleState(first),'Completed')
  assert.equal(timelineCandleState(second),'Forming · provisional')
  assert.match(timelineCandleState({...first,contains_post_exit_prices:true}),/Includes prices after exit/)
})


test('post-exit candles remain visible outside the shaded trade period and scoring', () => {
  const after = {...second, timeline_phase:'after_exit'}
  const data = {...view(), candles:[{...first,timeline_phase:'trade'},after]}
  const result = buildChartData(data)
  assert.equal(result.rows.length,2)
  assert.equal(result.reviewedCount,1)
  assert.equal(result.startIndex,0)
  assert.equal(result.endIndex,0)
  assert.equal(result.rows[1].analyzed,false)
  assert.equal(result.rows[1].score,null)
  assert.match(timelineCandleState(after),/^After exit · Forming/)
})

test('post-exit context alone cannot create a trade shading interval', () => {
  const data = {...view(),candles:[{...first,timeline_phase:'after_exit'}]}
  const result = buildChartData(data)
  assert.equal(result.reviewedCount,0)
  assert.equal(result.endIndex,-1)
  assert.equal(result.startIndex,result.rows.length)
})
