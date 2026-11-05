import test from 'node:test'
import assert from 'node:assert/strict'
import { freshTodayView, summaryIsBehind, validTodayEvidence, validTodayView } from '../src/todaySession.js'
import { isShortSummary, journalSections } from '../src/journalPresentation.js'

function view(count = 3) {
  const market_data = count ? { analysis_kind: 'intraday', candles: Array(count).fill({}), journal_date: '2026-10-23',
    data_key: 'same-evidence', data_through: '2026-10-23T09:00:00Z', session: { complete: count === 6, candle_count: count } } : null
  const rule_evaluation = count ? { analysis_kind: 'intraday', candles: Array(count).fill({}), rule_set: { id: 'four_factor_v4' },
    summary: { method: count === 6 ? 'session_average' : 'session_to_date' } } : null
  return { schema_version: 1, journal_date: '2026-10-23', as_of: '2026-10-23T10:00:00Z', snapshot_id: count ? 'snapshot' : null,
    session: { candle_count: count, expected_candle_count: 6, complete: count === 6 }, slots: Array(6).fill({}), market_data, rule_evaluation }
}
test('empty, partial and finished Today snapshots have distinct valid states', () => {
  for (let count = 0; count <= 6; count++) assert.equal(validTodayView(view(count)), true)
  const incomplete = view(); incomplete.market_data.session.complete = true
  assert.equal(validTodayView(incomplete), false)
})
test('missing or inconsistent scoring evidence is not displayed as a valid snapshot', () => {
  const bad = view(); bad.rule_evaluation.candles.pop()
  assert.equal(validTodayView(bad), false)
  assert.equal(validTodayEvidence(null, null), false)
  const wrong = view(); wrong.rule_evaluation.summary.method = 'session_average'
  assert.equal(validTodayView(wrong), false)
})
test('freshness distinguishes recent data from delayed or future-clock responses', () => {
  const current = view(); const now = Date.parse(current.as_of)
  assert.equal(freshTodayView(current, now + 119999), true)
  assert.equal(freshTodayView(current, now + 120000), false)
  assert.equal(freshTodayView(current, now - 6000), false)
  assert.equal(freshTodayView(null, now), false)
})
test('new poll alone does not make summary stale; changed candles and rollover do', () => {
  const current = view(); const preview = { market_data: structuredClone(current.market_data) }
  current.snapshot_id = 'new-poll'
  assert.equal(summaryIsBehind(preview, current), false)
  current.market_data.data_key = 'changed-evidence'
  assert.equal(summaryIsBehind(preview, current), true)
  assert.equal(summaryIsBehind(preview, view(0)), true)
  assert.equal(summaryIsBehind(null, current), false)
})
test('partial summary uses compact presentation and preserves editable text', () => {
  const text = '## Session so far\nOriginal review.\n\n## Agreement and conflict\nMixed.\n\n## Directional consensus\nProvisional.\n\n## Concerns\nPending candles.'
  const sections = journalSections(text)
  assert.equal(isShortSummary(sections), true)
  assert.equal(sections[0].body.trim(), 'Original review.')
  assert.equal(text.includes('Pending candles.'), true)
})
