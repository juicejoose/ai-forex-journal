import test from 'node:test'
import assert from 'node:assert/strict'
import { patternLabel, patternMarkers, retestLabels } from '../src/setupPatterns.js'
import { zoneChartMarkers } from '../src/setupHistory.js'

const candle = { open_time:'2020-01-02T01:00:00Z', close_time:'2020-01-02T05:00:00Z' }
const rows = [{time:Date.parse(candle.open_time)/1000,candle}]
const event = {...candle,id:'Z1-P1',kind:'breakout',direction:'bullish'}

test('pattern names separate historical rule matches from invalidated attempts', () => {
  assert.equal(patternLabel(event),'Bullish breakout · rule met')
  assert.equal(patternLabel({...event,kind:'rejection',direction:'bearish'}),'Bearish rejection · rule met')
  assert.equal(patternLabel({...event,kind:'retest_held'}),'Bullish retest held · rule met')
  assert.equal(patternLabel({...event,kind:'retest_invalidated'}),'Bullish breakout · retest attempt invalidated')
  assert.notEqual(retestLabels.expired,retestLabels.invalidated)
  assert.notEqual(retestLabels.pending,retestLabels.insufficient_data)
})
test('pattern markers are optional and only attach to matching saved candle intervals', () => {
  const zone={patterns:{events:[event,{...event,open_time:'2020-01-03T01:00:00Z'},{...event,close_time:'2020-01-02T09:00:00Z'}]}}
  assert.deepEqual(zoneChartMarkers(zone,rows),[])
  assert.deepEqual(zoneChartMarkers(zone,rows,false,true),[
    {time:rows[0].time,position:'belowBar',shape:'arrowUp',color:'#249c79',text:'BRK'}])
  assert.deepEqual(patternMarkers(undefined,rows),[])
  assert.deepEqual(patternMarkers({events:[{...event,kind:'invented'}]},rows),[])
})
test('bearish matches and invalidations have distinct markers', () => {
  const marker=patternMarkers({events:[{...event,direction:'bearish',kind:'retest_held'}]},rows)[0]
  assert.equal(marker.shape,'arrowDown')
  assert.equal(marker.text,'RT')
  const ended=patternMarkers({events:[{...event,kind:'retest_invalidated'}]},rows)[0]
  assert.equal(ended.shape,'square')
  assert.equal(ended.text,'RT ended')
  assert.notEqual(ended.color,marker.color)
})
