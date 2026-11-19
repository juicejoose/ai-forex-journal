import test from 'node:test'
import assert from 'node:assert/strict'
import { validTradeScores,scoreNumber,signedScore,scoreDirection } from '../src/tradeScores.js'

const entryAt='2026-11-09T15:00:00Z', exitAt='2026-11-09T20:00:00Z'
const record=()=>({id:'trade',status:'closed',entry:{entry_at:entryAt,direction:'long'},exit:{exit_at:exitAt}})
const view=()=>({schema_version:1,version:'trade_scores_v1',trade_id:'trade',trade_direction:'long',status:'closed',
  entry_at:entryAt,exit_at:exitAt,as_of:'2026-11-10T16:00:00Z',rule_set:{version:7,max_points:5},
  entry_analysis_id:'analysis',entry_analysis:{id:'analysis',source:'entry_time',analysis:{}},
  entry_score:{cutoff_at:entryAt,data_through:'2026-11-09T14:00:00Z',summary:{method:'latest_completed_at_entry'},
    candle:{close_time:'2026-11-09T14:00:00Z',factors:[{},{},{},{}]}},
  full_trade:{cutoff_at:exitAt,summary:{method:'full_trade_average',candle_count:1},
    candles:[{open_time:'2026-11-09T14:00:00Z',close_time:'2026-11-09T18:00:00Z'}]}})

test('closed scores allow the entry-containing candle only when its close is during the trade',()=>{
  assert.equal(validTradeScores(view(),record()),true)
  for(const close of [entryAt,'2026-11-09T22:00:00Z']){
    const data=view();data.full_trade.candles[0].close_time=close
    assert.equal(validTradeScores(data,record()),false)
  }
  const data=view();data.full_trade.candles[0].close_time=exitAt
  assert.equal(validTradeScores(data,record()),true)
})

test('open responses cannot be rendered for a closed trade and must use a live cutoff',()=>{
  const data=view(),trade=record();data.status=trade.status='open';data.exit_at=trade.exit=null
  data.full_trade.summary.method='trade_to_date_average'
  assert.equal(validTradeScores(data,trade),true)
  assert.equal(validTradeScores(data,record()),false)
  data.full_trade.cutoff_at='2026-11-11T20:00:00Z'
  assert.equal(validTradeScores(data,trade),false)
})

test('entry evidence needs a completed pre-entry candle and an entry-time analysis',()=>{
  for(const through of [null,'bad','2026-11-09T18:00:00Z']) {
    const data=view();data.entry_score.data_through=through
    assert.equal(validTradeScores(data,record()),false)
  }
  const data=view();data.entry_analysis.source='saved_setup'
  assert.equal(validTradeScores(data,record()),false)
  data.entry_analysis.source='entry_time';data.entry_score.candle.factors=[]
  assert.equal(validTradeScores(data,record()),false)
})

test('scores for a different trade, direction or exit are rejected',()=>{
  for(const [key,value] of [['trade_id','other'],['trade_direction','short'],['exit_at',entryAt]]){
    const data=view();data[key]=value
    assert.equal(validTradeScores(data,record()),false)
  }
  const data=view();data.full_trade.cutoff_at=data.as_of
  assert.equal(validTradeScores(data,record()),false)
})

test('failed period data preserves valid entry evidence without claiming a final average',()=>{
  const data=view();data.full_trade={error:'Missing candle; retry',summary:null,candles:[]}
  assert.equal(validTradeScores(data,record()),true)
  data.full_trade.summary={net_score:0}
  assert.equal(validTradeScores(data,record()),false)
})

test('duplicate and out-of-order closes or inconsistent candle counts are rejected',()=>{
  const data=view();data.full_trade.candles.push(data.full_trade.candles[0])
  assert.equal(validTradeScores(data,record()),false)
  data.full_trade.summary.candle_count=2
  assert.equal(validTradeScores(data,record()),false)
})

test('no completed closes is valid; missing scores display differently from zero',()=>{
  const data=view();data.full_trade.candles=[];data.full_trade.summary.candle_count=0
  assert.equal(validTradeScores(data,record()),true)
  assert.equal(scoreNumber(null),'Unavailable');assert.equal(signedScore(undefined),'Unavailable')
  assert.equal(scoreNumber(0),'0.00');assert.equal(signedScore(0),'0.00')
  assert.equal(signedScore(0.5),'+0.50');assert.equal(signedScore(-1.25),'-1.25')
  assert.equal(scoreDirection('bearish'),'Bearish');assert.equal(scoreDirection('insufficient_data'),'Unavailable')
})
