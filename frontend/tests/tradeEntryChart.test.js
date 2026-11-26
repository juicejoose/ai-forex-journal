import test from 'node:test'
import assert from 'node:assert/strict'
import {entryChartWindow,pickTradeField} from '../src/tradeEntryChart.js'
import {drawnZone, draftBands} from '../src/setupDrawing.js'
import {tradeRequest,blankTrade} from '../src/tradeLog.js'
import {chartZones,savedTradeZones} from '../src/tradeZones.js'
import {buildChartData} from '../src/marketChartData.js'

const start='2026-11-20T14:00:00Z'
const candle={open_time:start,close_time:'2026-11-20T18:00:00Z',open:1.1,high:1.12,low:1.09,close:1.105,complete:false}
const previous={...candle,open_time:'2026-11-20T10:00:00Z',close_time:start,complete:true}
const context={schema_version:1,purpose:'display_only',instrument:'EUR_USD',timeframe:'H4',target_count:160,
  before_at:start,after_at:start,retrieved_at:'2026-11-20T15:00:00Z',preceding:[previous],following:[{...candle,timeline_phase:'after_review'}]}

test('only stop and target can be picked from a chart price',()=>{
  for(const field of ['stopLoss','takeProfit']){
    assert.deepEqual(pickTradeField(field,1.123456),{[field]:'1.12346'})
    assert.deepEqual(pickTradeField(field,1.1),{[field]:'1.10000'})
  }
  for(const price of [NaN,0,-1,0.000001]) assert.throws(()=>pickTradeField('stopLoss',price))
  for(const field of ['entryPrice','entryAt','direction']) assert.throws(()=>pickTradeField(field,1.1))
})

test('two boundaries become ordered, distinctly named saved zones without changing execution fields',()=>{
  const linked = [{label:'Support 1',kind:'support',lower:'1.08000',upper:'1.09000',origin_at:null}]
  const drafted = drawnZone('support',1.092,1.091,linked,'draft')
  const form = {...blankTrade(),entryAt:start,entryPrice:'1.10000',reason:'Manual fill',entryZones:[drafted]}
  const body = tradeRequest(form, Date.parse(start), linked)
  assert.equal(body.entry_price,'1.10000')
  assert.equal(Date.parse(body.entry_at),Date.parse(start))
  assert.deepEqual(body.entry_zones,[{label:'Support 2',kind:'support',lower:'1.09100',upper:'1.09200',timeframe:'H4',origin_at:null}])
  const saved = savedTradeZones({setup:{snapshot:{zones:linked}},entry_zones:body.entry_zones})
  assert.deepEqual(draftBands(chartZones(saved),[{time:Date.parse(start)/1000}]).map(b=>b.label),['Support 1','Support 2'])
  assert.throws(()=>tradeRequest({...form,zoneBoundary:1.09}),/Finish drawing/)
  assert.throws(()=>tradeRequest(form,Date.parse(start),[{label:'support 2'}]),/distinct names/)
  assert.throws(()=>tradeRequest({...form,entryZones:[{...drafted,originAt:'2026-11-20T15:00:00Z'}]},Date.parse(start)),/entry time/)
})

test('display window selects the requested candle including a forming bar and never marks rows as scored',()=>{
  const {snapshot,selected}=entryChartWindow(context,null)
  assert.equal(selected,Date.parse(start)/1000)
  assert.equal(snapshot.candles.length,2)
  assert.equal(snapshot.candles[1].complete,false)
  assert.notEqual(snapshot.candles[1].timeline_phase,'after_review')
  assert.equal(buildChartData(snapshot).reviewedCount,0)
  assert.equal(entryChartWindow(context,previous.open_time).selected,Date.parse(previous.open_time)/1000)
  assert.throws(()=>entryChartWindow({...context,purpose:'evidence'},null))
})
