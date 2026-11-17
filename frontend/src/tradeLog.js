export const disciplineLabels = { not_reviewed: 'Not reviewed', followed: 'Followed my plan', deviated: 'Deviated from my plan' }
export const blankTrade = () => ({ title: '', direction: 'long', entryPrice: '', entryAt: '', stopLoss: '', takeProfit: '', reason: '', observations: '', setupId: null })
export const blankExit = () => ({ price: '', at: '', notes: '' })

export function formFromSetup(record) {
  const plan = record?.snapshot?.trade_plan
  return { ...blankTrade(), setupId: record?.id ?? null, title: record?.snapshot?.entry?.title ?? '',
    direction: record?.snapshot?.entry?.direction ?? 'long', entryPrice: plan?.entry_price ?? '',
    stopLoss: plan?.stop_loss ?? '', takeProfit: plan?.take_profit ?? '' }
}

function price(value, label, optional = false) {
  const text = value.trim()
  if (!text && optional) return null
  if (!/^\d+(\.\d{1,5})?$/.test(text) || Number(text) <= 0 || Number(text) > 100) {
    throw new Error(`${label} must be positive, no more than 100, and have up to five decimal places.`)
  }
  return text
}
function instant(value, label, now) {
  const date = new Date(value)
  if (!value || !Number.isFinite(date.getTime()) || date.getTime() > now) throw new Error(`Choose a valid ${label.toLowerCase()} that is not in the future.`)
  return date.toISOString()
}
export function tradeRequest(form, now = Date.now()) {
  const entry = price(form.entryPrice, 'Entry price')
  const stop = price(form.stopLoss, 'Stop loss', true), target = price(form.takeProfit, 'Take profit', true)
  if (!['long','short'].includes(form.direction)) throw new Error('Choose long or short.')
  if (stop !== null && (form.direction === 'long' ? Number(stop) >= Number(entry) : Number(stop) <= Number(entry))) throw new Error('Place the initial stop below a long entry or above a short entry, or leave it blank if none was used.')
  if (target !== null && (form.direction === 'long' ? Number(target) <= Number(entry) : Number(target) >= Number(entry))) throw new Error('Place the initial target above a long entry or below a short entry, or leave it blank if none was used.')
  if (!form.reason.trim()) throw new Error('Record your reason for entering the trade.')
  return { title: form.title.trim(), direction: form.direction, instrument: 'EUR_USD', timeframe: 'H4',
    entry_price: entry, entry_at: instant(form.entryAt, 'Entry time', now),
    initial_stop_loss: stop, initial_take_profit: target, entry_reason: form.reason.trim(),
    entry_observations: form.observations.trim(), setup_id: form.setupId }
}
export function exitRequest(form, entryAt, now = Date.now()) {
  const at = instant(form.at, 'Exit time', now)
  if (Date.parse(at) < Date.parse(entryAt)) throw new Error('Exit time cannot be before entry time.')
  return { exit_price: price(form.price, 'Exit price'), exit_at: at, exit_notes: form.notes.trim() }
}
export function reviewChanged(draft, saved) {
  return draft.discipline !== saved.discipline || draft.notes.trim() !== saved.notes
}
