import test from 'node:test'
import assert from 'node:assert/strict'
import { STRATEGY_CHOICES, isRetiredRuleSet } from '../src/strategyChoices.js'

test('only v7 and written review are available for new selections', () => {
  assert.deepEqual(STRATEGY_CHOICES.map(choice => choice.value), ['four_factor_v7', ''])
  for (const choice of STRATEGY_CHOICES) assert.equal(isRetiredRuleSet(choice.value), false)
})

test('saved retired profiles require an explicit current selection, while written profiles remain usable', () => {
  for (const value of ['four_factor_v1', 'four_factor_v2', 'four_factor_v3', 'four_factor_v4', 'four_factor_v5', 'four_factor_v6', 'unknown']) {
    assert.equal(isRetiredRuleSet(value), true)
  }
  for (const value of [null, undefined, '', 'four_factor_v7']) assert.equal(isRetiredRuleSet(value), false)
})
