import test from 'node:test'
import assert from 'node:assert/strict'
import {alignmentChange,coachReadoutLabels,coachZones,coachRequest,holdAlignmentText,newerCoachEvidence,validCoachReview,runningReview} from '../src/tradeCoach.js'
const zone=()=>({label:'Support',kind:'support',lower:'1.10000',upper:'1.10100',timeframe:'H4',originAt:''})
const form=()=>({inherit:false,zones:[zone()],observations:' Watch support '})

test('coach explains the reversal across the whole review and labels market nets',()=>{
  const history = {total:9, counts:{supportive:5,opposing:4,balanced:0,unavailable:0}, average_net:-5/9,
    latest_run:{status:'opposing',count:4}, previous_run:{status:'supportive',count:5}, recent_nets:[-3,-4]}
  assert.deepEqual(holdAlignmentText(history,'long',true),{
    headline:'Last 4 H4 closes opposed your long',context:'First 5 H4 closes supported your long. Last recorded market nets: -3 → -4',
    coverage:'Across 9 closes · 5 supportive · 4 opposing · Average net -0.56'})
  assert.equal(holdAlignmentText(history,'long',false).headline,'Latest scheduled H4 close unavailable')
})

test('a single close, balanced streaks, and missing readings stay distinct',()=>{
  assert.equal(holdAlignmentText(null,'short',true),null)
  const history={total:1,counts:{supportive:1},latest_run:{status:'supportive',count:1},previous_run:null,recent_nets:[-2],average_net:-2}
  assert.match(holdAlignmentText(history,'short',true).headline,/Latest H4 close supported your short/)
  const gap={...history,total:4,latest_run:{status:'unavailable',count:1},previous_run:{status:'balanced',count:2},
    recent_nets:[0,null],counts:{opposing:1,balanced:2,unavailable:1},average_net:null}
  const text=holdAlignmentText(gap,'short',true)
  assert.match(text.context,/Preceding 2 H4 closes were balanced.*0 → Unavailable/)
  assert.match(text.coverage,/1 unavailable · Average net Unavailable/)
})

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

test('new reviews show weighted alignment and independent zone evidence, including before the first close',()=>{
  const readout={strategy_alignment:'supported',hold_closes:3,price_action:{status:'opposes',matches:[]},factor_history:[]}
  const snapshot={schema_version:1,trade_id:'trade',version:'trade_coach_evidence_v2',trade:{direction:'long'},catalog:{facts:[],readout}}
  const review={id:'id',trade_id:'trade',status:'completed',snapshot,result:{assessment:'supported'}}
  assert.equal(validCoachReview(review,'trade'),true)
  assert.equal(coachReadoutLabels(snapshot).alignment,'Favors your long')
  assert.equal(coachReadoutLabels(snapshot).priceAction,'Conflicts with your direction')
  assert.equal(validCoachReview({...review,result:{assessment:'contradicted'}},'trade'),false)
  readout.hold_closes=0
  readout.price_action.status='awaiting_close'
  assert.equal(coachReadoutLabels(snapshot).headline,'No new H4 close since entry')
  assert.equal(validCoachReview({...review,result:{assessment:'no_new_close'}},'trade'),true)
  readout.strategy_alignment='balanced'
  assert.equal(coachReadoutLabels(snapshot).alignment,'Balanced')
  readout.price_action.status='unknown'
  assert.equal(validCoachReview(review,'trade'),false)
})

test('premise reviews require their saved evidence and checks while older reviews still open',()=>{
  const readout={strategy_alignment:'supported',hold_closes:1,price_action:{status:'no_match',matches:[]},factor_history:[]}
  const snapshot={schema_version:1,trade_id:'trade',trade:{direction:'long'},version:'trade_coach_evidence_v3',
    covers_latest_close:true,entry_score:{covers_latest_scheduled_close:true},directional_net_change:-0.5,catalog:{facts:[],readout},premise_evidence:[]}
  const check={window:'since_entry',source:'entry_reason',status:'unverifiable',excerpt:'My plan',explanation:'No measurable condition.',evidence_ids:[]}
  const value={id:'r',trade_id:'trade',status:'completed',snapshot,result:{assessment:'supported',premise_checks:[check]}}
  assert.equal(validCoachReview(value,'trade'),true)
  assert.equal(validCoachReview({...value,result:{assessment:'supported'}},'trade'),false)
  assert.equal(validCoachReview({...value,snapshot:{...snapshot,version:'trade_coach_evidence_v2'},result:{assessment:'supported'}},'trade'),true)
  assert.equal(alignmentChange(snapshot),'Weakened by 0.5 points')
  assert.equal(alignmentChange({...snapshot,directional_net_change:1}),'Strengthened by 1 point')
  assert.equal(alignmentChange({...snapshot,directional_net_change:0}),'Net alignment is unchanged')
  assert.equal(alignmentChange({...snapshot,covers_latest_close:false}),null)
  assert.equal(alignmentChange({...snapshot,catalog:{readout:{hold_closes:0}}}),null)
})
