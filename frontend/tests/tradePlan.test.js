import test from 'node:test'
import assert from 'node:assert/strict'
import { tradePlanRequest, setupRequest, previewRequest } from '../src/setupEvaluation.js'

const plan={entryPrice:'1.10000',stopLoss:'1.09800',takeProfit:'1.10400'}
const form={title:'',direction:'long',mode:'historical',asOf:'2020-01-02T12:00:00Z',includeQuote:false,observations:'',zones:[]}

test('blank and old forms omit the optional plan without changing request identity',()=>{
  assert.equal(tradePlanRequest(undefined,'long'),null)
  assert.equal(tradePlanRequest({entryPrice:' ',stopLoss:'',takeProfit:''},'long'),null)
  assert.deepEqual(setupRequest(form,'id'),setupRequest({...form,tradePlan:{entryPrice:'',stopLoss:'',takeProfit:''}},'id'))
  assert.equal('trade_plan' in setupRequest(form,'id'),false)
})
test('valid long and short plans preserve decimal input and submit no calculated metrics',()=>{
  const body=setupRequest({...form,tradePlan:plan},'id')
  assert.deepEqual(body.trade_plan,{entry_price:'1.10000',stop_loss:'1.09800',take_profit:'1.10400'})
  const short={entryPrice:'1.10000',stopLoss:'1.10200',takeProfit:'1.09600'}
  assert.equal(tradePlanRequest(short,'short').stop_loss,'1.10200')
  assert.equal(Object.keys(body.trade_plan).length,3)
})
test('incomplete, equal, reversed, nonfinite and excessive-precision prices are rejected',()=>{
  for (const change of [{entryPrice:''},{stopLoss:''},{takeProfit:''},{entryPrice:'NaN'},{stopLoss:'0'},
    {entryPrice:'Infinity'},{entryPrice:'1e0'},{entryPrice:'1.123456'},{entryPrice:'101'},
    {stopLoss:'1.10000'},{takeProfit:'1.10000'},{stopLoss:'1.10100'},{takeProfit:'1.09900'}]) {
    assert.throws(()=>tradePlanRequest({...plan,...change},'long'))
  }
  assert.throws(()=>tradePlanRequest(plan,'short'),/short/)
})
test('loading a chart ignores incomplete plans while capture validates them against chosen direction',()=>{
  const draft={...form,tradePlan:{entryPrice:'1.1',stopLoss:'',takeProfit:''}}
  assert.deepEqual(previewRequest(draft,'id'),previewRequest(form,'id'))
  assert.throws(()=>setupRequest(draft,'id'),/together/)
})
test('editing a plan preserves preview binding and its explicit cutoff',()=>{
  const preview={id:'preview-id',selection:{mode:'historical',as_of:'2020-01-02T12:00:00Z',include_quote:false},snapshot:{cutoff_at:'2020-01-02T12:00:00Z'}}
  const before=structuredClone(preview)
  const request=setupRequest({...form,tradePlan:plan},'id',preview)
  assert.equal(request.preview_id,'preview-id')
  assert.equal(request.as_of,'2020-01-02T12:00:00.000Z')
  assert.deepEqual(preview,before)
  assert.equal('trade_plan' in previewRequest({...form,tradePlan:plan},'id'),false)
})
