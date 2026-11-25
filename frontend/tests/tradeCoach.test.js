import test from 'node:test'
import assert from 'node:assert/strict'
import {coachZones,coachRequest,newerCoachEvidence,validCoachReview,runningReview} from '../src/tradeCoach.js'
const zone=()=>({label:'Support',kind:'support',lower:'1.10000',upper:'1.10100',timeframe:'H4',originAt:''})
const form=()=>({inherit:false,zones:[zone()],observations:' Watch support '})

test('inherit and explicitly empty zones remain different; review notes are trimmed',()=>{
  assert.deepEqual(coachRequest({...form(),inherit:true}),{zones:null,observations:'Watch support'})
  assert.deepEqual(coachRequest({...form(),zones:[]}),{zones:[],observations:'Watch support'})
  assert.equal(coachRequest(form()).zones[0].origin_at,null)
  const withTime={...form(),zones:[{...zone(),originAt:'2026-11-17T09:00'}]}
  assert.equal(coachRequest(withTime).zones[0].origin_at,new Date('2026-11-17T09:00').toISOString())
})
test('zone conversion preserves absent origin and editable prices',()=>{
  const record={context:{setup:{snapshot:{zones:[{...zone(),lower:1.1,origin_at:null}]}}}}
  const draft=coachZones(record)[0];assert.equal(draft.originAt,'');assert.equal(draft.lower,'1.1')
  assert.equal(coachRequest({...form(),zones:[draft]}).zones[0].origin_at,null)
  assert.deepEqual(coachZones({}),[])
})
test('invalid, reversed, duplicate, excessive and future zones are rejected before requests',()=>{
  for (const changes of [{lower:'NaN'},{lower:'0'},{upper:'101'},{lower:'1.2'},{lower:'1.100001'},{originAt:'2040-01-01T00:00'},{label:' '}]) {
    assert.throws(()=>coachRequest({...form(),zones:[{...zone(),...changes}]},Date.parse('2026-11-19T00:00Z')))
  }
  assert.throws(()=>coachRequest({...form(),zones:[zone(),{...zone(),label:'SUPPORT'}]}))
  assert.throws(()=>coachRequest({...form(),zones:Array.from({length:9},(_,i)=>({...zone(),label:String(i)}))}))
  assert.throws(()=>coachRequest({...form(),observations:'x'.repeat(5001)}))
})
test('only newer completed candles mark an assessment stale',()=>{
  const review={data_through:'2026-11-19T14:00:00Z'}
  assert.equal(newerCoachEvidence(review,'2026-11-19T18:00:00Z'),true)
  for (const stamp of [review.data_through,'2026-11-18T14:00:00Z',null,'invalid']) assert.equal(newerCoachEvidence(review,stamp),false)
  assert.equal(newerCoachEvidence(null,review.data_through),false)
})
test('review validation separates pending from completed and rejects other trade evidence',()=>{
  const value={id:'review',trade_id:'trade',status:'completed',snapshot:{schema_version:1,trade_id:'trade',catalog:{facts:[]}},result:{assessment:'mixed'}}
  assert.equal(validCoachReview(value,'trade'),true)
  assert.equal(validCoachReview(value,'different'),false)
  assert.equal(validCoachReview({...value,snapshot:null},'trade'),false)
  assert.equal(validCoachReview({...value,result:{assessment:'guaranteed'}},'trade'),false)
  for(const status of ['capturing','pending','failed'])assert.equal(validCoachReview({...value,status,snapshot:null,result:null},'trade'),true)
  assert.equal(runningReview({status:'pending'}),true);assert.equal(runningReview({status:'completed'}),false)
})
