import test from 'node:test'
import assert from 'node:assert/strict'
import { calendarCells, changeTone, formatChange, formatAverageNet, formatDay, isDateKey, isMonthKey, newYorkToday, shiftDate, shiftMonth } from '../src/journalCalendar.js'

test('October 2026 starts on Thursday and has 31 dates', () => {
  const cells = calendarCells('2026-10')
  assert.equal(cells.length, 42)
  assert.deepEqual(cells.slice(0, 4), [null, null, null, null])
  assert.equal(cells[4], '2026-10-01')
  assert.equal(cells.filter(Boolean).length, 31)
  assert.equal(cells[34], '2026-10-31')
})

test('February follows leap-year rules including century exceptions', () => {
  for (const [year, days] of [[2024, 29], [2026, 28], [2000, 29], [2100, 28]]) {
    assert.equal(calendarCells(`${year}-02`).filter(Boolean).length, days)
  }
})

test('month and day navigation cross years and clamp supported bounds', () => {
  assert.equal(shiftMonth('2026-12', 1), '2027-01')
  assert.equal(shiftMonth('2026-01', -1), '2025-12')
  assert.equal(shiftMonth('0001-01', -1), '0001-01')
  assert.equal(shiftMonth('9999-12', 1), '9999-12')
  assert.equal(shiftDate('2024-02-28', 1), '2024-02-29')
  assert.equal(shiftDate('2026-12-31', 1), '2027-01-01')
  assert.equal(shiftDate('0001-01-01', -1), '0001-01-01')
})

test('New York today respects midnight and both daylight-saving offsets', () => {
  assert.equal(newYorkToday(new Date('2026-10-28T02:00:00Z')), '2026-10-27')
  assert.equal(newYorkToday(new Date('2026-10-28T04:00:00Z')), '2026-10-28')
  assert.equal(newYorkToday(new Date('2026-12-28T04:30:00Z')), '2026-12-27')
  assert.equal(newYorkToday(new Date('2026-12-28T05:00:00Z')), '2026-12-28')
  assert.equal(shiftDate('2026-03-08', 1), '2026-03-09')
  assert.equal(shiftDate('2026-11-01', 1), '2026-11-02')
})

test('date labels retain the session date and invalid input is rejected', () => {
  assert.equal(formatDay('2026-10-20'), 'Tuesday, October 20, 2026')
  for (const value of ['2026-02-30', '0000-01-01', '2026-13-01', '', null]) assert.equal(isDateKey(value), false)
  assert.equal(isDateKey('0001-01-01'), true)
  assert.equal(isDateKey('2024-02-29'), true)
  assert.equal(isMonthKey('2026-10'), true)
  assert.equal(isMonthKey('2026-10-20'), false)
})

test('positive, negative, flat and missing changes have distinct meanings', () => {
  assert.equal(changeTone(0.25), 'up')
  assert.equal(changeTone(-0.25), 'down')
  assert.equal(changeTone(0), 'flat')
  for (const value of [null, undefined, NaN, Infinity]) assert.equal(changeTone(value), 'unknown')
  assert.equal(formatChange(0.248), '+0.25%')
  assert.equal(formatChange(-0.248), '−0.25%')
  assert.equal(formatChange(0), '0.00%')
  assert.equal(formatChange(null), '—')
})

test('tiny returns never display a misleading signed zero', () => {
  assert.equal(formatChange(0.0001), '+<0.01%')
  assert.equal(formatChange(-0.0001), '−<0.01%')
})

test('average net scores show signed points with two decimals, without a percent sign', () => {
  assert.equal(formatAverageNet(11 / 6), '+1.83')
  assert.equal(formatAverageNet(-11 / 6), '−1.83')
  assert.equal(formatAverageNet(0), '0.00')
  assert.equal(formatAverageNet(-0), '0.00')
  assert.equal(formatAverageNet(0.5), '+0.50')
  assert.equal(formatAverageNet(0.0001), '+<0.01')
  assert.equal(formatAverageNet(-0.0001), '−<0.01')
})

test('unavailable net scores never display as zero', () => {
  for (const value of [undefined, null, NaN, Infinity, -Infinity, '1.83', true]) {
    assert.equal(formatAverageNet(value), '—')
  }
})
