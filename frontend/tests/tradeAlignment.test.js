import test from 'node:test'
import assert from 'node:assert/strict'
import { evidenceAge, pointText, preferredAnalysis, relationLabels, scopeLabel } from '../src/tradeAlignment.js'

test('missing points never display as zero and fractional support stays visible', () => {
  assert.equal(pointText(null), 'Unavailable'); assert.equal(pointText(undefined), 'Unavailable')
  assert.equal(pointText(0), '0.00'); assert.equal(pointText(.5), '0.50'); assert.equal(pointText(1/3), '0.33')
  assert.notEqual(relationLabels.neutral, relationLabels.unavailable)
})
test('evidence age includes weekend gaps without inventing a stale threshold', () => {
  assert.equal(evidenceAge(0), 'Less than 1 minute'); assert.equal(evidenceAge(60), '1m')
  assert.equal(evidenceAge(3660), '1h 1m'); assert.equal(evidenceAge(49*3600), '2d 1h')
  assert.equal(evidenceAge(-1), 'Unknown'); assert.equal(evidenceAge(null), 'Unknown')
})
test('source selection handles old records, manual trades, and retained reconstructions', () => {
  assert.equal(preferredAnalysis({context:{setup:{}}}), 'saved_setup')
  assert.equal(preferredAnalysis({context:{setup:null}}), 'entry_time')
  assert.equal(preferredAnalysis({context:{setup:{}},strategy_analyses:[{source:'entry_time'}]}), 'entry_time')
})
test('partial, previous-session and legacy summaries are never labeled full-session at entry', () => {
  const value={summary:{method:'session_to_date'},coverage:{session_complete:false,earlier_session:false}}
  assert.equal(scopeLabel(value), 'Session-to-cutoff average')
  assert.equal(scopeLabel({...value,coverage:{session_complete:true,earlier_session:true}}), 'Earlier-session average')
  assert.equal(scopeLabel({...value,coverage:{session_complete:true,earlier_session:false}}), 'Session average')
  assert.equal(scopeLabel({...value,summary:{method:'final_candle'}}), 'Saved final-candle summary')
})
