import test from 'node:test'
import assert from 'node:assert/strict'
import {chartBoundaries,validChartContext,withChartContext} from '../src/chartContext.js'
import {buildChartData,indicatorSeries} from '../src/marketChartData.js'

const origin=Date.parse('2026-10-20T21:00:00Z')
const candle=index => ({open_time:new Date(origin+index*14400000).toISOString(),close_time:new Date(origin+(index+1)*14400000).toISOString(),
  open:1.1,high:1.12,low:1.09,close:1.11,complete:true,indicators:{ema20:1.102,sma190:1.103,rsi14:50,rsi14_sma14:48,squeeze:{momentum:.001}}})
const snapshot=()=>({candles:[candle(0),candle(1)],chart_context:{candles:[candle(-1)]},session:{complete:true}})
const context=()=>({schema_version:1,purpose:'display_only',instrument:'EUR_USD',timeframe:'H4',target_count:160,
  before_at:candle(0).open_time,after_at:candle(1).close_time,retrieved_at:candle(200).open_time,
  preceding:Array.from({length:160},(_,i)=>candle(i-160)),following:Array.from({length:160},(_,i)=>candle(i+2))})

test('review uses exact outer candles; preview requests no post-cutoff context',()=>{
  assert.deepEqual(chartBoundaries(snapshot(),true),{before:candle(0).open_time,after:candle(1).close_time})
  assert.equal(chartBoundaries(snapshot(),false).after,null)
  assert.deepEqual(chartBoundaries(null,true),{before:null,after:null})
})

test('display context preserves central evidence, original indicator pairs and input objects',()=>{
  const original=snapshot(),extra=context(),before=structuredClone(original),copy=structuredClone(extra)
  // Simulate provider revision; keep saved price/indicator pairs together.
  extra.preceding.at(-1).close=1.115; extra.preceding.at(-1).indicators.sma190=1.2
  const extended=withChartContext(original,extra)
  assert.strictEqual(extended.candles,original.candles)
  assert.strictEqual(extended.chart_context.candles.at(-1),original.chart_context.candles[0])
  assert.equal(extended.chart_context.candles.length,160)
  assert.equal(extended.chart_followup.candles.length,160)
  assert.deepEqual(original,before)
  assert.deepEqual(extra.following,copy.following)
})

test('raw legacy context receives a coherent retrieved price/indicator pair',()=>{
  const original=snapshot(),extra=context()
  delete original.chart_context.candles[0].indicators
  original.chart_context.candles[0].close=1.119
  assert.strictEqual(withChartContext(original,extra).chart_context.candles.at(-1),extra.preceding.at(-1))
})

test('all 160 earlier/later indicators plot, with scores only in original reviewed candles',()=>{
  const original=snapshot(),extra=context()
  const evaluation={candles:[...original.candles,...extra.following].map((row,i)=>({...row,candle_id:`C${i+1}`}))}
  const data=buildChartData(withChartContext(original,extra),evaluation)
  assert.equal(data.rows.length,322)
  assert.equal(data.startIndex,160); assert.equal(data.endIndex,161)
  assert.equal(data.reviewedCount,2); assert.equal(data.followingCount,160)
  assert.equal(data.rows[161].score.candle_id,'C2')
  assert.ok(data.rows.slice(162).every(row=>row.score === null && !row.analyzed && row.candle.timeline_phase === 'after_review'))
  assert.ok(indicatorSeries(data.rows,values=>values.sma190).every(row=>Number.isFinite(row.value)))
})

test('mismatched boundaries, overlapping bars, missing times and future complete bars are rejected',()=>{
  const base=context(),before=base.before_at,after=base.after_at
  assert.equal(validChartContext(base,before,after),true)
  for(const mutate of [value=>{value.before_at=candle(-1).open_time},value=>{value.preceding[0].close_time='bad'},
    value=>{value.following[0]=candle(1)},value=>{value.preceding[0].complete=false},value=>{value.following.push(candle(162))},
    value=>{value.following[0].close=NaN},value=>{value.retrieved_at=candle(160).open_time},value=>{value.following[1]=value.following[0]},
    value=>{value.instrument='GBP_USD'}]) {
    const bad=structuredClone(base); mutate(bad)
    assert.equal(validChartContext(bad,before,after),false)
  }
  assert.equal(validChartContext(base,before,null),false)
})

test('a current forming later candle is accepted and remains unscored',()=>{
  const extra=context(); extra.following=[{...candle(2),complete:false}]
  extra.retrieved_at=new Date(origin+2.5*14400000).toISOString()
  assert.equal(validChartContext(extra,extra.before_at,extra.after_at),true)
  assert.equal(buildChartData(withChartContext(snapshot(),extra)).rows.at(-1).score,null)
})

test('failed context loads retain bounded saved history without fabricating indicators or later bars',()=>{
  const original=snapshot(); original.chart_context.candles=Array.from({length:300},(_,i)=>candle(i-300))
  const view=withChartContext(original,null)
  assert.equal(view.chart_context.candles.length,160)
  assert.deepEqual(view.chart_followup.candles,[])
  assert.strictEqual(view.candles,original.candles)
  assert.equal(withChartContext(null,null),null)
})

test('live forming context is validated separately, never as a completed or historical bar',()=>{
  const extra=context(); extra.following=[]; extra.after_at=null
  extra.forming_candle={...candle(2),complete:false}; extra.forming_at=new Date(origin+2.2*14400000).toISOString()
  extra.retrieved_at=new Date(origin+2.5*14400000).toISOString()
  assert.equal(validChartContext(extra,extra.before_at,null,extra.forming_at),true)
  for(const mutate of [value=>{value.forming_candle.complete=true},value=>{value.forming_candle=candle(3)},
    value=>{value.forming_candle={...candle(1),complete:false}},value=>{value.retrieved_at=candle(4).open_time}]) {
    const bad=structuredClone(extra); mutate(bad)
    assert.equal(validChartContext(bad,extra.before_at,null,extra.forming_at),false)
  }
  assert.equal(validChartContext(extra,extra.before_at,null,null),false)
})

test('forming chart-only indicators have no score or effect on the reviewed interval',()=>{
  const original=snapshot(),extra=context(); extra.following=[]
  extra.forming_candle={...candle(2),complete:false}
  const evaluation={candles:[...original.candles,{...candle(2),candle_id:'must-not-attach'}]}
  const chart=withChartContext(original,extra)
  const data=buildChartData(chart,evaluation)
  assert.equal(data.rows.length,163)
  assert.equal(data.reviewedCount,2); assert.equal(data.endIndex,161); assert.equal(data.historyCount,160)
  assert.equal(data.rows.at(-1).score,null)
  assert.equal(data.rows.at(-1).analyzed,false)
  assert.equal(data.rows.at(-1).candle.timeline_phase,'forming')
  assert.strictEqual(chart.candles,original.candles)
})

test('before the first close the chart shows earlier history plus a forming bar with zero reviewed candles',()=>{
  const empty={analysis_kind:'intraday',session:{start_utc:candle(0).open_time},candles:[]}
  const extra=context(); extra.following=[]; extra.forming_candle={...candle(0),complete:false}
  assert.equal(chartBoundaries(empty,false).before,candle(0).open_time)
  const data=buildChartData(withChartContext(empty,extra))
  assert.equal(data.rows.length,161); assert.equal(data.historyCount,160)
  assert.equal(data.reviewedCount,0); assert.equal(data.endIndex,-1)
  assert.ok(data.rows.every(row=>!row.analyzed))
})

test('a completed refresh supersedes stale forming data without a duplicate or altered saved price',()=>{
  const original=snapshot(),extra=context(); extra.following=[]
  original.candles.push(candle(2)); extra.forming_candle={...candle(2),close:1.119,complete:false}
  const data=buildChartData(withChartContext(original,extra))
  assert.equal(data.rows.length,163)
  assert.equal(data.rows.at(-1).candle.close,1.11)
  assert.equal(data.rows.at(-1).candle.complete,true)
  assert.equal(data.reviewedCount,3)
})
