import test from 'node:test'
import assert from 'node:assert/strict'
import { factorDescription } from '../src/strategyDescriptions.js'

test('new RSI trend outcomes are not mislabeled as threshold extremes', () => {
  for (const [basis, label] of [['rising', 'RSI rising'], ['falling', 'RSI falling'], ['oversold', 'Oversold · threshold'], ['overbought', 'Overbought · threshold'], ['mixed_or_flat', 'Mixed or flat RSI']]) {
    assert.equal(factorDescription({ factor_id: 'rsi_extreme', outcome: 'bullish', rsi_signal: { basis } }), label)
  }
})
test('new momentum descriptions identify the movement as well as its pace', () => {
  for (const movement of ['rising', 'falling']) {
    const text = factorDescription({ factor_id: 'momentum', outcome: 'bearish', momentum_change: { movement, pace: 'slowing' } })
    assert.equal(text, `${movement[0].toUpperCase()}${movement.slice(1)} · slowing`)
  }
  assert.equal(factorDescription({ factor_id: 'momentum', outcome: 'neutral', momentum_change: { movement: 'unchanged', pace: 'not_directional' } }), 'Unchanged')
})
test('historical factor labels still use their saved metadata', () => {
  assert.equal(factorDescription({ factor_id: 'rsi_extreme', outcome: 'bullish' }), 'Oversold')
  assert.equal(factorDescription({ factor_id: 'rsi_extreme', outcome: 'neutral' }), 'Between thresholds')
  assert.equal(factorDescription({ factor_id: 'momentum', outcome: 'bullish', momentum_change: { pace: 'slowing' } }), 'Slowing')
})
test('missing inputs cannot be described as a directional signal', () => {
  for (const factor_id of ['rsi_extreme', 'momentum']) {
    assert.equal(factorDescription({ factor_id, outcome: 'unavailable', rsi_signal: { basis: 'rising' }, momentum_change: { movement: 'rising', pace: 'slowing' } }), 'Insufficient data')
  }
})

test('v6 badges distinguish MA thresholds and trends from raw RSI', () => {
  for (const [basis, label] of [['rising', 'RSI MA rising'], ['falling', 'RSI MA falling'], ['oversold', 'Oversold MA · threshold'], ['overbought', 'Overbought MA · threshold'], ['mixed_or_flat', 'Mixed or flat RSI MA']]) {
    assert.equal(factorDescription({ factor_id: 'rsi_extreme', outcome: 'bullish', rsi_signal: { basis, source: 'rsi14_sma14' } }), label)
  }
})

test('v7 reduced RSI trend labels explain threshold proximity', () => {
  for (const [basis, outcome, proximity, label] of [
    ['rising', 'bullish', 'overbought', 'RSI MA rising · near overbought'],
    ['falling', 'bearish', 'oversold', 'RSI MA falling · near oversold'],
  ]) {
    assert.equal(factorDescription({factor_id:'rsi_extreme', outcome,
      rsi_signal:{source:'rsi14_sma14', basis, reduced:true, proximity}}), label)
  }
})
test('v7 threshold and unavailable labels never imply reduced trend points', () => {
  for (const [basis, label] of [['oversold', 'Oversold MA · threshold'], ['overbought', 'Overbought MA · threshold']]) {
    assert.equal(factorDescription({factor_id:'rsi_extreme', outcome:'bullish',
      rsi_signal:{source:'rsi14_sma14', basis, reduced:false, proximity:null}}), label)
  }
  assert.equal(factorDescription({factor_id:'rsi_extreme', outcome:'unavailable',
    rsi_signal:{source:'rsi14_sma14', basis:'unavailable', reduced:false}}),'Insufficient data')
})
