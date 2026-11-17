import assert from 'node:assert/strict'
import test from 'node:test'
import { setupRequest, referencedItems, setupTime } from '../src/setupEvaluation.js'

const form = { title: ' Test ', direction: 'long', mode: 'live', includeQuote: true,
  asOf: '', observations: ' support ', zones: [{ label: ' Low ', kind: 'support', timeframe: 'H4', lower: '1.10000', upper: '1.11000' }] }

test('live capture leaves cutoff to server and preserves exact decimal input', () => {
  const body = setupRequest(form, 'uuid')
  assert.equal(body.as_of, null)
  assert.equal(body.include_quote, true)
  assert.equal(body.title, 'Test')
  assert.equal(body.zones[0].lower, '1.10000')
})
test('historical capture converts device time to explicit UTC and forbids current quote', () => {
  const body = setupRequest({ ...form, mode: 'historical', asOf: '2020-01-02T12:00' }, 'uuid')
  assert.equal(body.as_of, new Date('2020-01-02T12:00').toISOString())
  assert.equal(body.include_quote, false)
  assert.throws(() => setupRequest({ ...form, mode: 'historical', asOf: '' }, 'uuid'))
  assert.throws(() => setupRequest({ ...form, mode: 'historical', asOf: '2999-01-01T12:00' }, 'uuid'))
})
test('zone validation rejects inverted, malformed and overly precise prices', () => {
  for (const lower of ['NaN', '-1', 'Infinity', '1.123456', '1.2', '1e-1', '']) {
    assert.throws(() => setupRequest({ ...form, zones: [{ ...form.zones[0], lower }] }, 'uuid'))
  }
  assert.throws(() => setupRequest({ ...form, zones: [form.zones[0], { ...form.zones[0], label: 'low' }] }, 'uuid'))
  assert.equal(setupRequest({ ...form, zones: [{ ...form.zones[0], upper: '1.10000' }] }, 'uuid').zones.length, 1)
})
test('only stored server evidence with referenced IDs is rendered', () => {
  const facts = [{ id: 'F1', text: 'Calculated evidence' }, { id: 'F2', text: 'Other' }]
  assert.deepEqual(referencedItems(['F1', 'invented', 'F1'], facts), [facts[0]])
  assert.deepEqual(referencedItems([], facts), [])
  assert.equal(setupTime('invalid'), 'Unavailable')
})

test('saved setup pagination moves to the nearest remaining page after deletion', async () => {
  const { setupPageOffset } = await import('../src/setupEvaluation.js')
  assert.equal(setupPageOffset(10, 10), 0)
  assert.equal(setupPageOffset(20, 20), 10)
  assert.equal(setupPageOffset(10, 11), 10)
  assert.equal(setupPageOffset(0, 0), 0)
  assert.equal(setupPageOffset(20, 1), 0)
})
