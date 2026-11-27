import { useState } from 'react'
import { setupTime } from './setupEvaluation.js'

const names = { ema20: 'EMA20', sma190: 'SMA190', rsi14: 'RSI14', rsi14_sma14: 'RSI14 SMA14', entry_reason: 'Reason for entry',
  ema_sma_distance: 'EMA/SMA distance', rsi_signal: 'RSI signal', factor_id: 'Factor ID',
  net_score: 'Market net', result: 'Score details', readout: 'Strategy and price action' }
const enums = new Set(['scope', 'role', 'outcome', 'direction', 'kind', 'method', 'relation', 'status',
  'source', 'basis', 'pace', 'strategy_alignment', 'price_position', 'window', 'zone_source'])
const isoStamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/
const decimal = new Intl.NumberFormat('en-US', { maximumFractionDigits: 5 })
const label = key => names[key] ?? key.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase())
const nested = value => value !== null && typeof value === 'object'

function SavedValue({field, value}) {
  if (value == null || value === '') return 'Not recorded'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') {
    const text = field.endsWith('_percent') ? `${Number(value.toFixed(2))}%`
      : value !== 0 && Math.abs(value) < 0.00001 ? String(value) : decimal.format(value)
    const tone = value > 0 && field === 'bearish_points' ? 'trade-negative'
      : value > 0 && field === 'bullish_points' ? 'trade-positive'
      : field === 'net_score' && value !== 0 ? (value > 0 ? 'trade-positive' : 'trade-negative') : undefined
    return <span className={tone} title={String(value)}>{text}</span>
  }
  if (isoStamp.test(value)) return <time dateTime={value} title={value}>{setupTime(value)}</time>
  return enums.has(field) ? label(value) : value
}

export function EvidenceDisclosure({summary, children}) {
  const [expanded, setExpanded] = useState(false)
  return <details className="coach-disclosure" onToggle={event => setExpanded(event.currentTarget.open)}>
    <summary>{summary}</summary>{expanded && children}
  </details>
}

function EvidenceFields({value}) {
  if (Array.isArray(value)) {
    if (!value.length) return <p className="trade-help">None recorded</p>
    if (value.every(item => item?.candle_id && item.open_time && item.close_time && item.values &&
        Object.keys(item).every(key => ['candle_id', 'open_time', 'close_time', 'values'].includes(key)) &&
        Object.values(item.values).every(v => !nested(v)))) {
      const indicators = [...new Set(value.flatMap(row => Object.keys(row.values)))]
      return <div className="trade-score-table" role="region" aria-label="Saved indicator readings" tabIndex={0}>
        <table><caption>Indicator readings used for this factor</caption>
          <thead><tr>{['Candle', 'Opened', 'Closed', ...indicators.map(label)].map(title => <th key={title} scope="col">{title}</th>)}</tr></thead>
          <tbody>{value.map(row => <tr key={row.candle_id}><th scope="row">{row.candle_id}</th>
            <td><SavedValue field="open_time" value={row.open_time} /></td><td><SavedValue field="close_time" value={row.close_time} /></td>
            {indicators.map(key => <td key={key}><SavedValue field={key} value={row.values[key]} /></td>)}
          </tr>)}</tbody>
        </table></div>
    }
    return <ul className="coach-field-list">{value.map((item, index) => <li key={index}>
      {nested(item) ? <EvidenceDisclosure summary={item.name || item.label || item.candle_id || item.id || `Item ${index + 1}`}>
        <EvidenceFields value={item} /></EvidenceDisclosure> : <SavedValue field="" value={item} />}
    </li>)}</ul>
  }
  const fields = Object.entries(value)
  if (!fields.length) return <p className="trade-help">None recorded</p>
  const scalars = fields.filter(([, item]) => !nested(item))
  return <>{scalars.length > 0 && <dl className="coach-fields">{scalars.map(([key, item]) =>
    <div key={key}><dt>{label(key)}</dt><dd><SavedValue field={key} value={item} /></dd></div>)}</dl>}
    {fields.filter(([, item]) => nested(item)).map(([key, item]) =>
      <EvidenceDisclosure key={key} summary={label(key) + (Array.isArray(item) ? ` (${item.length})` : '')}>
        <EvidenceFields value={item} /></EvidenceDisclosure>)}
  </>
}

function FactDetails({evidence}) {
  const { result, ...metadata } = evidence
  return <>{Object.keys(metadata).length > 0 && <EvidenceFields value={metadata} />}
    {result?.direction === 'insufficient_data' && <p className="trade-help">Factor coverage is incomplete. The recorded subtotals are excluded from the alignment score.</p>}
    {result && <EvidenceFields value={result} />}</>
}

export function EvidenceList({title, ids, catalog, conditions=false}) {
  const entries = conditions ? catalog.conditions : catalog.facts
  return ids?.length > 0 && <section><h4>{title}</h4><ul className="coach-evidence-list">{ids.map(id => {
    const item = entries.find(value => value.id === id)
    return <li key={id}><p>{item?.text ?? 'Evidence unavailable'}</p>
      {item?.evidence && Object.keys(item.evidence).length > 0 &&
        <EvidenceDisclosure summary={`Saved evidence · ${id}`}><FactDetails evidence={item.evidence} /></EvidenceDisclosure>}
    </li>
  })}</ul></section>
}

export function CapturedEvidence({snapshot}) {
  const { facts, conditions, limitations, ...other } = snapshot.catalog
  const zones = { saved_entry_setup: 'Saved entry setup', trade_entry_zones: 'Recorded with the trade',
    setup_and_trade_entry_zones: 'Linked setup and trade entry', review_annotations: 'Supplied at this review' }
  return <EvidenceDisclosure summary="All captured facts and original review inputs">
    <h4>Review inputs</h4>
    <EvidenceFields value={{ entry_reason: snapshot.trade.entry_reason, entry_observations: snapshot.trade.entry_observations,
      review_observations: snapshot.review_observations, zones: zones[snapshot.zone_source] ?? snapshot.zone_source }} />
    <h4>Captured facts ({facts.length})</h4>
    {facts.map(({id, text, evidence, ...metadata}) => <EvidenceDisclosure key={id} summary={`${id} · ${text}`}>
      <EvidenceFields value={metadata} />{evidence && <FactDetails evidence={evidence} />}
    </EvidenceDisclosure>)}
    <h4>Conditions</h4>
    {(conditions ?? []).map(({id, text, ...metadata}) => <EvidenceDisclosure key={id} summary={`${id} · ${text}`}>
      <EvidenceFields value={metadata} /></EvidenceDisclosure>)}
    {Object.keys(other).length > 0 && <EvidenceFields value={other} />}
    {limitations?.length > 0 && <EvidenceDisclosure summary="Saved limitations"><ul>{limitations.map(text => <li key={text}>{text}</li>)}</ul></EvidenceDisclosure>}
  </EvidenceDisclosure>
}
