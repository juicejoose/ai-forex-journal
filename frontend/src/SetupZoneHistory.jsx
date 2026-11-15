import { useId } from 'react'
import { chartStamp, chartTime } from './marketChartData.js'
import { zoneEventLabel } from './setupHistory.js'
import './SetupZoneHistory.css'

const stamp = value => chartTime(value) === null ? 'Unavailable' : chartStamp(chartTime(value))
const pips = (value, reason) => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(1)} pips` : reason === 'data_gap' ? 'Unavailable' : 'Pending'
const statuses = { covered: 'History covered', partial_history: 'Partial history', not_requested: 'Origin not set', no_completed_candles: 'No completed candles' }
const windowLabels = { complete: 'Full window', cutoff: 'Cutoff reached', next_visit: 'Next visit started', data_gap: 'Stopped at data gap' }

export default function SetupZoneHistory({ zones, selectedZone, onZoneChange, onSelect, showCloses, onShowCloses }) {
  const id = useId()
  if (!zones?.length) return null
  const zone = selectedZone ?? zones[0]
  const history = zone.history
  return <section className="zone-history" aria-labelledby={`${id}-heading`}>
    <div className="zh-heading"><div><h3 id={`${id}-heading`}>Zone history</h3>
      <p>Completed H4 observations · New York time · separate from strategy points</p></div>
      <label htmlFor={`${id}-zone`}>Zone on chart<select id={`${id}-zone`} value={zone.id} onChange={event => onZoneChange(event.target.value)}>
        {zones.map(item => <option key={item.id} value={item.id}>{item.label} · {item.kind}</option>)}
      </select></label></div>
    {!history ? <p className="zh-notice">This older snapshot has no saved zone-history analysis. Capture a new setup with an origin time to include it.</p> : <>
      <div className="zh-scope"><strong>{statuses[history.status] ?? 'Unavailable'}</strong>
        <span>Zone {zone.lower}–{zone.upper} · {zone.timeframe} annotation; analyzed with H4 candles</span>
        {history.origin_at && <span>Origin supplied: {stamp(history.origin_at)}</span>}</div>
      {history.status === 'not_requested' && <p className="zh-notice">No origin time was supplied. Historical interactions are unknown for this zone. Capture a new setup with an origin to analyze them.</p>}
      {history.status === 'no_completed_candles' && <p className="zh-notice">No whole H4 candle opening at or after the origin has completed within the saved history and cutoff.</p>}
      {history.coverage_start && <>
        <p className="zh-coverage">Observed window: {stamp(history.coverage_start)} – {stamp(history.coverage_end)} · {history.candle_count} completed candles</p>
        {history.origin_before_history && <p className="zh-notice">The origin is older than the earliest saved candle, {stamp(history.available_from)}. Counts cover the displayed window only.</p>}
        {history.gap_count > 0 && <p className="zh-notice">{history.gap_count} unexpected gap(s) in the observed window. Groups on either side of a gap may be part of the same visit; followup movement stops at gaps.</p>}
        <dl className="zh-metrics">
          <div><dt>Observed visit groups</dt><dd>{history.visit_count}</dd></div>
          <div><dt>Overlapping candles</dt><dd>{history.overlap_candles}</dd></div>
          <div><dt>Closes above / inside / below</dt><dd>{history.close_counts.above} / {history.close_counts.inside} / {history.close_counts.below}</dd></div>
        </dl>
        <label className="zh-toggle"><input type="checkbox" checked={showCloses} onChange={event => onShowCloses(event.target.checked)} />Show close-position changes on chart</label>
        <p className="zh-help">Gold circles mark visit starts. V* marks a group already overlapping at the history boundary or after a gap. Zone lines begin with the observed window. Select an event below to inspect its candle.</p>
        <details><summary>Visit groups ({history.visit_count})</summary>
          {history.visits.length ? <div className="zh-table-scroll" role="region" aria-label="Zone visit groups" tabIndex={0}>
            <table><thead><tr><th>Visit</th><th>Overlap window</th><th>Last overlap close</th><th>Following movement</th><th>Window status</th></tr></thead>
              <tbody>{[...history.visits].reverse().map(visit => <tr key={visit.id}>
                <td><button type="button" onClick={() => onSelect(chartTime(visit.first_candle.open_time))}>{visit.id.replace(`${zone.id}-`, '')}{visit.boundary_start ? '*' : ''}</button><small>{visit.overlap_candles} candle(s)</small></td>
                <td>{stamp(visit.first_candle.open_time)}<small>through {stamp(visit.last_candle.close_time)}</small></td>
                <td><button type="button" onClick={() => onSelect(chartTime(visit.last_candle.open_time))}>{visit.last_candle.close.toFixed(5)}</button><small>{visit.last_close_position}</small></td>
                <td>{pips(visit.followup.close_change_pips, visit.followup.stop_reason)}<small>{visit.followup.candle_count} of up to {history.followup_candles} following candles</small>
                  {visit.followup.last_candle && <small>through {stamp(visit.followup.last_candle.close_time)}</small>}
                  {visit.followup.candle_count > 0 && <small>High above / low below last overlap close: {visit.followup.high_above_last_overlap_close_pips.toFixed(1)} / {visit.followup.low_below_last_overlap_close_pips.toFixed(1)} pips</small>}</td>
                <td>{visit.end_status === 'overlapping_at_cutoff' ? 'Overlap ongoing at cutoff' : windowLabels[visit.followup.stop_reason]}
                  {visit.boundary_start && <small>Start may precede observed history</small>}</td>
              </tr>)}</tbody></table>
          </div> : <p className="zh-help">No overlapping candle ranges were observed in this window.</p>}
        </details>
        <details><summary>Close-position changes ({history.events.filter(event => event.kind === 'close_position').length})</summary>
          <ul className="zh-events">{[...history.events].reverse().filter(event => event.kind === 'close_position').map(event =>
            <li key={event.id}><button type="button" onClick={() => onSelect(chartTime(event.open_time))}>
              <strong>{zoneEventLabel(event)}</strong><span>{stamp(event.close_time)} · {event.close.toFixed(5)}</span>
            </button></li>)}</ul>
        </details>
        <details className="zh-definitions"><summary>How these observations are counted</summary>
          <p>A visit groups consecutive H4 candles whose high–low ranges overlap the zone, including its edges. It does not count individual intrabar touches. Normal weekend closures do not split consecutive trading candles.</p>
          <p>Followup starts from the last overlapping candle’s close and covers up to three following completed, non-overlapping candles. It stops at a new visit, an unexpected data gap, or the cutoff. Positive/negative movement describes price change, not a trade outcome.</p>
          <p>The origin is your annotation. These observations do not independently establish when a zone formed, its strength, or a confirmed breakout, rejection or retest.</p>
        </details>
      </>}
    </>}
  </section>
}
