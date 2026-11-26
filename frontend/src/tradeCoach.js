import { savedTradeZones, zoneInputs } from './tradeZones.js'
import { localInputTime } from './setupDrawing.js'

export const coachLabels={supported:'Supports your trade',mixed:'Mixed support',contradicted:'Opposes your trade',insufficient_evidence:'Insufficient evidence'}
const alignmentLabels = {
  supported: direction => `Favors your ${direction}`, contradicted: direction => `Opposes your ${direction}`,
  balanced: () => 'Balanced', insufficient_evidence: () => 'Insufficient evidence',
}
const priceActionLabels = {
  supports: 'Supports your direction', opposes: 'Conflicts with your direction', mixed: 'Mixed zone signals',
  no_match: 'No directional zone pattern on this close', limited_history: 'Zone evidence incomplete',
  no_zones: 'No zones supplied', awaiting_close: 'Awaiting an in-trade close', unavailable: 'Latest close unavailable',
}

export function coachReadoutLabels(snapshot) {
  const readout = snapshot?.catalog?.readout
  if (!readout || !Object.hasOwn(alignmentLabels, readout.strategy_alignment) ||
      !Object.hasOwn(priceActionLabels, readout.price_action?.status) ||
      !Array.isArray(readout.price_action.matches) || !Array.isArray(readout.factor_history) ||
      !Number.isInteger(readout.hold_closes) || readout.hold_closes < 0 ||
      !['long','short'].includes(snapshot.trade?.direction)) return null
  const alignment = alignmentLabels[readout.strategy_alignment](snapshot.trade.direction)
  const atEntry = readout.hold_closes === 0
  return {headline: atEntry ? 'No new H4 close since entry' : alignment, alignment, atEntry,
          priceAction: priceActionLabels[readout.price_action.status]}
}
export const runningReview = value => ['capturing','pending'].includes(value?.status)
export function coachZones(record) {
  return savedTradeZones(record.context).map(z=>({key:crypto.randomUUID(),label:z.label,kind:z.kind,lower:String(z.lower),upper:String(z.upper),timeframe:z.timeframe,originAt:z.origin_at ? localInputTime(z.origin_at) : ''}))
}
export function coachRequest(form,now=Date.now()) {
  if (form.observations.length>5000) throw new Error('Keep review notes within 5,000 characters.')
  const zones = form.inherit ? null : zoneInputs(form.zones, now, 'review time')
  return {zones,observations:form.observations.trim()}
}
export function newerCoachEvidence(review,latestClose) {
  const captured=Date.parse(review?.data_through),latest=Date.parse(latestClose)
  return Number.isFinite(captured) && Number.isFinite(latest) && latest>captured
}
export function validCoachReview(value,tradeId) {
  if (value?.trade_id !== tradeId || typeof value.id !== 'string') return false
  if (value.status !== 'completed') return ['capturing','pending','failed'].includes(value.status)
  const snapshot = value.snapshot
  if (snapshot?.schema_version !== 1 || snapshot.trade_id !== tradeId || !Array.isArray(snapshot.catalog?.facts)) return false
  if (snapshot.version === 'trade_coach_evidence_v2') {
    const labels = coachReadoutLabels(snapshot)
    return Boolean(labels && value.result?.assessment === (labels.atEntry ? 'no_new_close' : snapshot.catalog.readout.strategy_alignment))
  }
  return Object.hasOwn(coachLabels,value.result?.assessment)
}
