import test from 'node:test'
import assert from 'node:assert/strict'
import { journalSections } from '../src/journalPresentation.js'

test('old free-form journals keep every line, including ordinary numbered rules', () => {
  const text = 'My original journal\n\n1. Check EMA20\n2. Wait for confirmation\n\nNotes: price stayed below 1.12345.'
  assert.deepEqual(journalSections(text), [{ title: '', body: text }])
})

test('generated headings separate sections without changing facts, rule quotes, or references', () => {
  const text = '1. Market summary\nOpen 1.12096; close 1.12374. Change 27.8 pips (0.25%).\n\n2. Bullish factors\nRule (your strategy): "RSI14 > 50."\nAI assessment: met. The cited close supported the factor. [2]\n\nCandle evidence — New York time; indicators at candle close\n[2] 2026-10-19 9:00 PM EDT → 2026-10-20 1:00 AM EDT: Momentum 0.00240.'
  const sections = journalSections(text)
  assert.equal(sections.length, 3)
  assert.equal(sections.map(({ title, body }) => title + '\n' + body).join('\n'), text)
})

test('user headings and markup remain literal text, with no interpretation as links or HTML', () => {
  const text = 'Personal preface\r\n\r\n## My notes\r\n<img src=x onerror=alert(1)>\r\n[click](javascript:alert(1))\r\n**literal emphasis**'
  const sections = journalSections(text)
  assert.equal(sections[0].body, 'Personal preface\n')
  assert.equal(sections[1].title, 'My notes')
  assert.equal(sections[1].body, '<img src=x onerror=alert(1)>\n[click](javascript:alert(1))\n**literal emphasis**')
})

test('empty edits and long journal text remain safe to display', () => {
  assert.deepEqual(journalSections(' \n\t\n'), [])
  const text = 'x'.repeat(20000)
  assert.equal(journalSections(text)[0].body, text)
})
