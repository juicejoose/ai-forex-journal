import test from 'node:test'
import assert from 'node:assert/strict'
import { drawnZone, drawingPoint, draftBands, localInputTime } from '../src/setupDrawing.js'
import { previewRequest, setupRequest } from '../src/setupEvaluation.js'
const rows = [0,1,2].map(i => ({ time: Date.parse(`2020-01-02T0${i*4}:00:00Z`)/1000,
  candle: { open_time: `2020-01-02T0${i*4}:00:00Z` } }))
const form = { mode: 'historical', asOf:'2020-01-02T12:00:00Z', includeQuote:true, title:'', direction:'long', observations:'', zones:[] }

test('two clicked prices order boundaries, round to five places and preserve single levels', () => {
  const zone = drawnZone('support',1.125678,1.12001,[],'key')
  assert.equal(zone.lower,'1.12001'); assert.equal(zone.upper,'1.12568'); assert.equal(zone.originAt,'')
  assert.equal(drawnZone('support',1.1,1.1,[zone],'key2').label,'Support 2')
  assert.equal(drawnZone('resistance',1.1,1.1,[],'key3').lower,'1.10000')
  assert.equal(drawnZone('support',1,2,Array(8).fill(zone),'key'),null)
  assert.equal(drawnZone('support',NaN,2,[],'key'),null)
})
test('drawing accepts only a real completed candle on the price pane', () => {
  const event = { paneIndex:0, point:{x:10,y:20},time:rows[0].time }
  assert.equal(drawingPoint(event,rows,()=>1.1234567).price,1.12346)
  for (const change of [{paneIndex:1},{paneIndex:2},{point:undefined},{time:rows[0].time+99}])
    assert.equal(drawingPoint({...event,...change},rows,()=>1.1),null)
  assert.equal(drawingPoint(event,rows,()=>null),null)
})
test('bands synchronize numerical edits and explicit origin without extending beyond evidence', () => {
  const zone = { lower:'1.1',upper:'1.2',kind:'support',label:'Test',originAt:rows[1].candle.open_time }
  assert.deepEqual(draftBands([zone],rows)[0],{lower:1.1,upper:1.2,kind:'support',label:'Test',start:1,end:2})
  assert.equal(draftBands([{...zone,lower:'1.15'}],rows)[0].lower,1.15)
  for (const change of [{lower:'2'},{originAt:'invalid'},{originAt:'2021-01-01T00:00:00Z'},{lower:''}])
    assert.deepEqual(draftBands([{...zone,...change}],rows),[])
  assert.deepEqual(draftBands([],rows),[])
  assert.equal(new Date(localInputTime(rows[1].candle.open_time)).getTime(),rows[1].time*1000)
})
test('preview loading ignores incomplete zone edits but capture validates them', () => {
  const draft = {...form,zones:[{label:'',lower:'',upper:''}]}
  assert.equal(previewRequest(draft,'id').include_quote,false)
  assert.throws(()=>setupRequest(draft,'id'))
})
test('capture binds preview ID, equivalent UTC time and origin cutoff; changed selection fails', () => {
  const preview={id:'preview-id',selection:{mode:'historical',as_of:'2020-01-02T12:00:00Z',include_quote:false},snapshot:{cutoff_at:'2020-01-02T12:00:00Z'}}
  assert.equal(setupRequest(form,'id',preview).preview_id,'preview-id')
  assert.throws(()=>setupRequest({...form,asOf:'2020-01-03T12:00:00Z'},'id',preview))
  const live={...form,mode:'live',asOf:'',includeQuote:false}
  const livePreview={...preview,selection:{mode:'live',as_of:null,include_quote:false}}
  const zone={...drawnZone('support',1.1,1.2,[],'key'),originAt:'2020-01-02T13:00:00Z'}
  assert.throws(()=>setupRequest({...live,zones:[zone]},'id',livePreview))
})


test('zone renderer spans bar edges using integer chart coordinates and updates after zoom', async () => {
  const { ZoneBands } = await import('../src/ZoneBands.js')
  const primitive = new ZoneBands()
  let spacing = 10
  const rects = []
  primitive.attached({ chart: { timeScale: () => ({ logicalToCoordinate: index => Number.isInteger(index) ? 10+index*spacing : 0 }) },
    series: { priceToCoordinate: price => 200-price*100 }, requestUpdate: () => {} })
  primitive.setBands([{ lower:1, upper:1.2, start:0, end:2, label:'Support', kind:'support' }])
  const target = { useMediaCoordinateSpace: callback => callback({ mediaSize:{width:500,height:250},
    context:{save(){},restore(){},fillRect(...values){rects.push(values)},strokeRect(){},fillText(){}} }) }
  primitive.paneViews()[0].renderer().draw(target)
  assert.deepEqual(rects[0], [5,80,30,20])
  spacing = 20
  primitive.paneViews()[0].renderer().draw(target)
  assert.deepEqual(rects[1], [0,80,60,20])
  primitive.setBands([])
  primitive.paneViews()[0].renderer().draw(target)
  assert.equal(rects.length,2)
})
