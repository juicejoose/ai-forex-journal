import { localInputTime } from '../src/setupDrawing.js'
import test from 'node:test'
import assert from 'node:assert/strict'
import { blankTrade, formFromSetup, tradeRequest, tradeEditRequest, exitRequest, reviewChanged, disciplineLabels, tradeDuration } from '../src/tradeLog.js'
const now=Date.parse('2026-11-01T12:00:00Z')
const form={...blankTrade(),entryPrice:'1.10000',stopLoss:'1.09800',takeProfit:'1.10400',entryAt:'2026-10-20T09:00:00-04:00',reason:'Entered at support.'}

test('setup handoff prefills proposed prices but requires an explicit actual entry time and reason',()=>{
 const record={id:'setup-id',snapshot:{entry:{title:'Support',direction:'long'},trade_plan:{entry_price:'1.1',stop_loss:'1.098',take_profit:'1.104'}}}
 const before=structuredClone(record), draft=formFromSetup(record)
 assert.equal(draft.setupId,'setup-id'); assert.equal(draft.entryPrice,'1.1'); assert.equal(draft.entryAt,''); assert.equal(draft.reason,'')
 assert.throws(()=>tradeRequest(draft,now)); assert.deepEqual(record,before)
})
test('entry sends decimal input and setup identifier, never client-supplied evidence or results',()=>{
 const body=tradeRequest({...form,setupId:'setup-id',context:{invented:true}},now)
 assert.equal(body.entry_price,'1.10000'); assert.equal(body.entry_at,'2026-10-20T13:00:00.000Z'); assert.equal(body.setup_id,'setup-id')
 assert.equal('context' in body,false); assert.equal('result' in body,false)
})
test('manual missing initial levels stay absent rather than becoming zero',()=>{
 const body=tradeRequest({...form,stopLoss:' ',takeProfit:''},now)
 assert.equal(body.initial_stop_loss,null); assert.equal(body.initial_take_profit,null); assert.equal(body.setup_id,null)
})
test('invalid actual prices, wrong-side levels, missing reason and future entry are rejected',()=>{
 for (const change of [{entryPrice:'0'},{entryPrice:'NaN'},{entryPrice:'1e0'},{entryPrice:'1.123456'},{stopLoss:'1.1'},{takeProfit:'1.1'},{reason:' '},{entryAt:'invalid'},{entryAt:'2030-01-01T12:00:00Z'}]) assert.throws(()=>tradeRequest({...form,...change},now))
 assert.throws(()=>tradeRequest({...form,direction:'short'},now))
 assert.equal(tradeRequest({...form,direction:'short',stopLoss:'1.102',takeProfit:'1.096'},now).direction,'short')
})
test('exit preserves actual fill and respects explicit timezone ordering across daylight saving',()=>{
 const entry='2026-11-01T01:30:00-04:00'
 const body=exitRequest({price:'1.09900',at:'2026-11-01T01:15:00-05:00',notes:'Full exit'},entry,now)
 assert.equal(body.exit_at,'2026-11-01T06:15:00.000Z'); assert.equal(body.exit_price,'1.09900'); assert.equal('result' in body,false)
 assert.throws(()=>exitRequest({price:'1.1',at:'2026-11-01T01:15:00-04:00',notes:''},entry,now))
})
test('discipline is explicit self-report and remains independent of outcome fields',()=>{
 const saved={discipline:'followed',notes:'Followed my plan.',result:{outcome:'negative'}}
 assert.equal(reviewChanged({discipline:'followed',notes:' Followed my plan. '},saved),false)
 assert.equal(reviewChanged({discipline:'deviated',notes:saved.notes},saved),true)
 assert.equal(disciplineLabels.followed,'Followed my plan')
})


test('closed duration uses the fixed exit and counts full days and remaining hours',()=>{
 assert.equal(tradeDuration('2026-11-10T14:00:00Z','2026-11-12T19:45:00Z',0),'2d 5h')
 assert.equal(tradeDuration('2026-11-10T14:00:00Z','2026-11-10T14:00:00Z'),'0d 0h')
 assert.equal(tradeDuration('2026-11-10T14:00:00Z','2026-11-10T14:59:59Z'),'<1 hour')
})
test('open duration advances with time while invalid or future timestamps stay unavailable',()=>{
 const entry='2026-11-10T14:00:00Z', now=Date.parse('2026-11-11T15:00:00Z')
 assert.equal(tradeDuration(entry,null,now),'1d 1h')
 assert.equal(tradeDuration(entry,undefined,now+3600000),'1d 2h')
 assert.equal(tradeDuration(entry,null,0),'Unavailable')
 assert.equal(tradeDuration('bad',null,now),'Unavailable')
 assert.equal(tradeDuration(entry,'bad',now),'Unavailable')
})
test('duration measures elapsed hours across daylight saving and market weekends',()=>{
 assert.equal(tradeDuration('2026-11-01T01:30:00-04:00','2026-11-01T01:30:00-05:00'),'0d 1h')
 assert.equal(tradeDuration('2026-10-30T17:00:00-04:00','2026-11-02T17:00:00-05:00'),'3d 1h')
})

test('edits preserve exact saved times including seconds during the DST fallback', () => {
  const entered = '2026-11-01T01:15:42.100588-05:00', exited = '2026-11-01T01:45:21-05:00'
  const record = {entry:{entry_at:entered},exit:{exit_at:exited},revision:2}
  const draft = {...form,entryAt:localInputTime(entered),setupId:'original'}
  const exit = {at:localInputTime(exited),price:'1.109',notes:'Updated exit'}
  const body = tradeEditRequest(record,draft,exit,now)
  assert.equal(body.entry.entry_at, entered)
  assert.equal(body.exit.exit_at, exited)
  assert.equal(body.expected_revision, 2)
  assert.equal('setup_id' in body.entry, false)
  assert.throws(() => tradeEditRequest(record,draft,{...exit,at:'2026-10-29T01:00Z'},now))
  assert.equal(tradeEditRequest({...record,exit:null},draft,null,now).exit,null)
})
