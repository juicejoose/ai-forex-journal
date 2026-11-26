export function savedTradeZones(context) {
  return [...(context?.setup?.snapshot?.zones ?? []), ...(context?.entry_zones ?? [])]
}

export function chartZones(zones) {
  return zones.map(zone => ({...zone, originAt:zone.origin_at ?? ''}))
}

export function zoneInputs(drafts, cutoff, cutoffLabel, linkedZones = []) {
  const zones = drafts.map(z=>{
    const lower=z.lower.trim(),upper=z.upper.trim()
    if(!z.label.trim() || !/^\d+(\.\d{1,5})?$/.test(lower) || !/^\d+(\.\d{1,5})?$/.test(upper) || Number(lower)<=0 || Number(upper)>100 || Number(lower)>Number(upper)) throw new Error('Each zone needs a name and positive lower/upper prices in order, with up to five decimals.')
    const origin=z.originAt ? new Date(z.originAt) : null
    if(origin && (!Number.isFinite(origin.getTime()) || origin.getTime()>cutoff)) throw new Error('Choose a valid zone origin at or before the ' + cutoffLabel + '.')
    return {label:z.label.trim(),kind:z.kind,lower,upper,timeframe:z.timeframe,origin_at:origin?.toISOString() ?? null}
  })
  const labels = [...linkedZones, ...zones].map(z => z.label.trim().toLowerCase())
  if (labels.length > 8 || new Set(labels).size !== labels.length) throw new Error('Use at most eight zones with distinct names, including any linked setup zones.')
  return zones
}
