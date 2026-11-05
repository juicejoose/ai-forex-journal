import test from 'node:test'
import assert from 'node:assert/strict'
import { journalName, journalEditsSaved } from '../src/journalNames.js'

test('named and older unnamed entries retain useful display labels', () => {
  assert.equal(journalName({ id: 7, title: '  London session  ' }), 'London session')
  for (const title of ['', '   ', null, undefined]) {
    assert.equal(journalName({ id: 7, title }), 'Journal #7')
    assert.equal(journalName({ id: 7, title }, true), 'Custom journal #7')
  }
  assert.equal(journalName({ id: 7, title: '<b>Literal name</b>' }), '<b>Literal name</b>')
})

test('renaming or clearing a title counts as an unsaved edit even when text matches', () => {
  const saved = { title: 'Original', edited_draft: 'Review' }
  assert.equal(journalEditsSaved(saved, 'Review', 'Original'), true)
  assert.equal(journalEditsSaved(saved, 'Review', 'Renamed'), false)
  assert.equal(journalEditsSaved(saved, 'Review', ''), false)
  assert.equal(journalEditsSaved(saved, 'Edited', 'Original'), false)
  assert.equal(journalEditsSaved(saved, ' Review ', ' Original '), true)
})

test('new drafts and older unnamed records have the correct saved state', () => {
  assert.equal(journalEditsSaved(null, 'Review', ''), false)
  assert.equal(journalEditsSaved({ edited_draft: 'Review' }, 'Review', ''), true)
  assert.equal(journalEditsSaved({ edited_draft: 'Review' }, 'Review', 'New name'), false)
})
