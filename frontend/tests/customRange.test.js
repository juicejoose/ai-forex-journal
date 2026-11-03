import test from 'node:test'
import assert from 'node:assert/strict'
import { customRangeDetails, rangePreview, validRangePreview } from '../src/customRange.js'
import { isShortSummary, journalSections } from '../src/journalPresentation.js'

test('full inclusive week has thirty candles and the preceding Sunday opening', () => {
  const result = customRangeDetails('2026-10-19', '2026-10-23')
  assert.equal(result.candleCount, 30)
  assert.equal(result.dates.length, 5)
  assert.equal(result.firstOpenDate, '2026-10-18')
  assert.equal(result.lastCloseDate, '2026-10-23')
})

test('weekends, DST boundaries and same-day ranges retain full trading sessions', () => {
  assert.equal(customRangeDetails('2026-10-17', '2026-10-25').candleCount, 30)
  assert.equal(customRangeDetails('2026-10-30', '2026-11-02').candleCount, 12)
  assert.equal(customRangeDetails('2026-03-06', '2026-03-09').candleCount, 12)
  assert.equal(customRangeDetails('2026-10-20', '2026-10-20').candleCount, 6)
  assert.equal(customRangeDetails('2026-10-01', '2026-10-31').candleCount, 132)
})

test('empty, invalid, reversed, weekend-only and oversized ranges show a useful error', () => {
  for (const [start, end] of [['', ''], ['2026-02-30', '2026-03-01'], ['0001-01-01', '0001-01-01'],
    ['2026-10-23', '2026-10-19'], ['2026-10-17', '2026-10-18'], ['2026-10-01', '2026-11-01']]) {
    assert.equal(typeof customRangeDetails(start, end).error, 'string')
  }
})

test('saved range mapping preserves immutable evidence and rejects incomplete previews', () => {
  const market = { analysis_kind: 'custom_range', session: { complete: true },
    range: { start_date: '2026-10-19', end_date: '2026-10-23' }, candles: Array(30).fill({}) }
  const evaluation = { analysis_kind: 'custom_range', summary: { method: 'range_average' }, candles: Array(30).fill({}) }
  const journal = { pair: 'EURUSD', timeframe: '4h', start_date: '2026-10-19', end_date: '2026-10-23',
    original_draft: 'Original summary', edited_draft: 'My edits', notes: '', strategy: 'Fixed rules',
    generation_id: 'sample-id', rule_set_id: 'four_factor_v4', market_data: market, rule_evaluation: evaluation }
  const preview = rangePreview(journal)
  assert.equal(preview.draft, 'Original summary')
  assert.equal(preview.market_data, market)
  assert.equal(preview.rule_evaluation, evaluation)
  assert.equal(validRangePreview(preview), true)
  assert.equal(validRangePreview({ ...preview, market_data: { ...market, candles: [] } }), false)
  assert.equal(validRangePreview({ ...preview, rule_evaluation: { ...evaluation, summary: { method: 'final_candle' } } }), false)
  assert.equal(validRangePreview(null), false)
})

test('range summaries use the short layout while preserving user text', () => {
  const text = '## Range recap\nRange facts.\n\n## Agreement and conflict\nFactor review.\n\n## Directional consensus\nRange bias.\n\n## Concerns\nNotes.'
  const sections = journalSections(text)
  assert.equal(isShortSummary(sections), true)
  assert.equal(sections.map(({title, body}) => '## ' + title + '\n' + body).join('\n'), text)
  assert.equal(isShortSummary(journalSections(text + '\n\n## My notes\nExtra.')), false)
})
