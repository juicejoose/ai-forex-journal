const validPrice = value => /^\d+(\.\d{1,5})?$/.test(value) && Number(value) > 0 && Number(value) <= 100

export function tradePlanRequest(plan, direction) {
  const entry = (plan?.entryPrice ?? '').trim()
  const stop = (plan?.stopLoss ?? '').trim()
  const target = (plan?.takeProfit ?? '').trim()
  if (![entry, stop, target].some(Boolean)) return null
  if (![entry, stop, target].every(Boolean)) throw new Error('Enter entry, stop loss, and take profit together, or clear all three to omit the trade plan.')
  if (![entry, stop, target].every(validPrice)) throw new Error('Trade-plan prices must be positive, no more than 100, and have up to five decimal places.')
  const ordered = direction === 'long' ? Number(stop) < Number(entry) && Number(entry) < Number(target)
    : direction === 'short' && Number(target) < Number(entry) && Number(entry) < Number(stop)
  if (!ordered) throw new Error(direction === 'long'
    ? 'For a long plan, stop loss must be below entry and take profit above entry.'
    : 'For a short plan, take profit must be below entry and stop loss above entry.')
  return { entry_price: entry, stop_loss: stop, take_profit: target }
}

export function previewRequest(form, requestId) {
  let asOf = null
  if (form.mode === 'historical') {
    const date = new Date(form.asOf)
    if (!form.asOf || !Number.isFinite(date.getTime()) || date.getTime() > Date.now()) {
      throw new Error('Choose a valid past cutoff in your device’s timezone.')
    }
    asOf = date.toISOString()
  }
  return { request_id: requestId, mode: form.mode, as_of: asOf, include_quote: form.mode === 'live' && form.includeQuote }
}

export function setupRequest(form, requestId, preview = null) {
  const selection = previewRequest(form, requestId)
  const asOf = selection.as_of
  if (preview && ['mode', 'as_of', 'include_quote'].some(key => (key === 'as_of' ? (selection[key] ? Date.parse(selection[key]) : null) !== (preview.selection[key] ? Date.parse(preview.selection[key]) : null) : selection[key] !== preview.selection[key]))) {
    throw new Error('Reload the chart after changing the time settings.')
  }
  const labels = new Set()
  const zones = form.zones.map(zone => {
    const label = zone.label.trim()
    const lower = zone.lower.trim(), upper = zone.upper.trim()
    if (!label || labels.has(label.toLowerCase())) throw new Error('Give each zone a distinct name.')
    if (!validPrice(lower) || !validPrice(upper) || Number(lower) > Number(upper)) {
      throw new Error('Enter positive zone prices with up to five decimal places. Lower must not exceed upper.')
    }
    labels.add(label.toLowerCase())
    let origin = null
    if (zone.originAt) {
      const date = new Date(zone.originAt)
      const cutoff = preview ? Date.parse(preview.snapshot.cutoff_at) : asOf ? Date.parse(asOf) : Date.now()
      if (!Number.isFinite(date.getTime()) || date.getTime() > cutoff) {
        throw new Error('Each zone origin must be a valid time at or before the evaluation cutoff.')
      }
      origin = date.toISOString()
    }
    return { label, kind: zone.kind, lower, upper, timeframe: zone.timeframe, ...(origin ? { origin_at: origin } : {}) }
  })
  const plan = tradePlanRequest(form.tradePlan, form.direction)
  return { request_id: requestId, title: form.title.trim(), direction: form.direction,
    mode: form.mode, as_of: asOf, include_quote: form.mode === 'live' && form.includeQuote,
    observations: form.observations.trim(), zones, ...(preview ? { preview_id: preview.id } : {}),
    ...(plan ? { trade_plan: plan } : {}) }
}

export function referencedItems(ids, items) {
  const wanted = new Set(ids ?? [])
  return (items ?? []).filter(item => wanted.has(item.id))
}

export function setupTime(value) {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date.toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZoneName: 'short',
  }) : 'Unavailable'
}

// Keep the nearest remaining page when its last saved setup is deleted.
export function setupPageOffset(offset, total, pageSize = 10) {
  return Math.min(offset, Math.max(0, Math.ceil(total / pageSize) - 1) * pageSize)
}
