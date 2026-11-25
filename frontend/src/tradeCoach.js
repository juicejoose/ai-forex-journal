import { localInputTime } from './setupDrawing.js'

export const coachLabels={supported:'Supports your trade',mixed:'Mixed support',contradicted:'Opposes your trade',insufficient_evidence:'Insufficient evidence'}
export const runningReview = value => ['capturing','pending'].includes(value?.status)
export function coachZones(record) {
  return (record.context?.setup?.snapshot?.zones ?? []).map(z=>({key:crypto.randomUUID(),label:z.label,kind:z.kind,lower:String(z.lower),upper:String(z.upper),timeframe:z.timeframe,originAt:z.origin_at ? localInputTime(z.origin_at) : ''}))
}
export function coachRequest(form,now=Date.now()) {
  if (form.observations.length>5000) throw new Error('Keep review notes within 5,000 characters.')
  const zones=form.inherit ? null : form.zones.map(z=>{
    const lower=z.lower.trim(),upper=z.upper.trim()
    if(!z.label.trim() || !/^\d+(\.\d{1,5})?$/.test(lower) || !/^\d+(\.\d{1,5})?$/.test(upper) || Number(lower)<=0 || Number(upper)>100 || Number(lower)>Number(upper)) throw new Error('Each zone needs a name and positive lower/upper prices in order, with up to five decimals.')
    const origin=z.originAt ? new Date(z.originAt) : null
    if(origin && (!Number.isFinite(origin.getTime()) || origin.getTime()>now)) throw new Error('A zone origin must be a valid past time.')
    return {label:z.label.trim(),kind:z.kind,lower,upper,timeframe:z.timeframe,origin_at:origin?.toISOString() ?? null}
  })
  if(zones && (zones.length>8 || new Set(zones.map(z=>z.label.toLowerCase())).size!==zones.length)) throw new Error('Use at most eight zones with distinct names.')
  return {zones,observations:form.observations.trim()}
}
export function newerCoachEvidence(review,latestClose) {
  const captured=Date.parse(review?.data_through),latest=Date.parse(latestClose)
  return Number.isFinite(captured) && Number.isFinite(latest) && latest>captured
}
export function validCoachReview(value,tradeId) {
  return value?.trade_id===tradeId && typeof value.id==='string' && ['capturing','pending','failed','completed'].includes(value.status) &&
    (value.status!=='completed' || (value.snapshot?.schema_version===1 && value.snapshot.trade_id===tradeId &&
      Array.isArray(value.snapshot.catalog?.facts) && Object.hasOwn(coachLabels,value.result?.assessment)))
}
