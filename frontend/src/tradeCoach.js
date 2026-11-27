import { savedTradeZones, zoneInputs } from './tradeZones.js'
import { localInputTime } from './setupDrawing.js'
import { signedScore } from './tradeScores.js'

export const coachLabels={supported:'Supports your trade',mixed:'Mixed support',contradicted:'Opposes your trade',insufficient_evidence:'Insufficient evidence'}
export const premiseStatus = {supported:'Supported', challenged:'Challenged', awaiting_confirmation:'Awaiting confirmation', unverifiable:'Cannot verify'}

const marketNet = new Intl.NumberFormat('en-US', { signDisplay: 'exceptZero', maximumFractionDigits: 2 })

export function holdAlignmentText(history, direction, coversLatest) {
  if (!history?.total) return null
  const { total, counts, latest_run: latest, previous_run: previous, recent_nets: nets } = history
  function describeRun(run, prefix) {
    const one = run.count === 1
    const subject = one ? `${prefix} H4 close` : `${prefix} ${run.count} H4 closes`
    const finding = { supportive: `supported your ${direction}`, opposing: `opposed your ${direction}`,
      balanced: one ? 'was balanced' : 'were balanced', unavailable: one ? 'had no score' : 'had no scores' }
    return `${subject} ${finding[run.status]}`
  }
  const first = previous && previous.count + latest.count === total
  const headline = coversLatest ? describeRun(latest, latest.count === 1 ? 'Latest' : 'Last') : 'Latest scheduled H4 close unavailable'
  const context = []
  if (coversLatest && previous) context.push(describeRun(previous, first ? 'First' : 'Preceding') + '.')
  const scores = nets.map(net => Number.isFinite(net) ? marketNet.format(net) : 'Unavailable')
  context.push(`Last recorded market ${nets.length === 1 ? 'net' : 'nets'}: ${scores.join(' → ')}`)
  const totals = Object.entries(counts).filter(([, count]) => count > 0).map(([name, count]) => `${count} ${name}`)
  return { headline, context: context.join(' '),
    coverage: [`Across ${total} ${total === 1 ? 'close' : 'closes'}`, ...totals, `Average net ${signedScore(history.average_net)}`].join(' · ') }
}

export function alignmentChange(snapshot) {
  const change = snapshot?.directional_net_change
  if (!snapshot?.covers_latest_close || !snapshot.entry_score?.covers_latest_scheduled_close || !snapshot.catalog?.readout?.hold_closes || !Number.isFinite(change)) return null
  if (change === 0) return 'Net alignment is unchanged'
  const points = Math.abs(change)
  return (change > 0 ? 'Strengthened' : 'Weakened') + ' by ' + points + (points === 1 ? ' point' : ' points')
}

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
  if (snapshot.version === 'trade_coach_evidence_v3') {
    const checks = value.result?.premise_checks
    if (!Array.isArray(snapshot.premise_evidence) || !Array.isArray(checks) || !checks.length ||
        !checks.every(c => c && Object.hasOwn(premiseStatus,c.status) && typeof c.excerpt === 'string' &&
          typeof c.explanation === 'string' && Array.isArray(c.evidence_ids))) return false
  }
  if (['trade_coach_evidence_v2','trade_coach_evidence_v3'].includes(snapshot.version)) {
    const labels = coachReadoutLabels(snapshot)
    return Boolean(labels && value.result?.assessment === (labels.atEntry ? 'no_new_close' : snapshot.catalog.readout.strategy_alignment))
  }
  return Object.hasOwn(coachLabels,value.result?.assessment)
}
