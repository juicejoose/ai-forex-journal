import { useState } from 'react'
import { setupTime } from './setupEvaluation.js'
import { factorDescription } from './strategyDescriptions.js'
import { setupChartSnapshot } from './setupHistory.js'
import MarketReview from './MarketReview.jsx'
import { relationLabels, pointText, evidenceAge, scopeLabel } from './tradeAlignment.js'
import './TradeAlignment.css'

function Status({ value }) {
  return <span className={`ta-status ta-${value}`}>{relationLabels[value] || 'Unavailable'}</span>
}

export default function TradeAlignment({ record, source, onSourceChange, onAnalyze, busy, active }) {
  const [showMarket, setShowMarket] = useState(false)
  const saved = record.strategy_analyses?.find(item => item.source === source)
  const analysis = saved?.analysis
  const snapshot = source === 'saved_setup' ? record.context?.setup?.snapshot : analysis?.reconstructed_snapshot
  const coverage = analysis?.coverage
  const latest = analysis?.factors[0]?.latest
  return <section className="trade-card trade-alignment" aria-label="Four-factor trade comparison">
    <div className="trade-row"><h3>Four-factor trade comparison</h3><span className="trade-badge">{record.entry.direction === 'long' ? 'Long' : 'Short'} entry</span></div>
    <p className="trade-help">Supporting means the factor agrees with your recorded direction; conflicting means it points the other way. Existing point weights and reductions are preserved.</p>
    <div className="ta-sources" role="group" aria-label="Comparison evidence source">
      {record.context?.setup && <button type="button" aria-pressed={source === 'saved_setup'} disabled={busy} onClick={() => onSourceChange('saved_setup')}>Saved setup evidence</button>}
      <button type="button" aria-pressed={source === 'entry_time'} disabled={busy} onClick={() => onSourceChange('entry_time')}>At entry · reconstructed</button>
    </div>
    {!analysis ? <div className="trade-notice">
      <p>{source === 'saved_setup' ? 'Compare the evidence already saved with this trade. No market refresh is needed.'
        : 'Retrieve historical market data up to your recorded entry time and calculate the current four-factor strategy. Only completed H4 candles qualify. The result is saved separately from the original setup.'}</p>
      {source === 'entry_time' && <p>This is a retrospective reconstruction. It does not establish what data or rules you actually used at entry.</p>}
      <button type="button" className="trade-primary" disabled={busy} onClick={() => onAnalyze(source)}>{source === 'saved_setup' ? 'Compare saved setup' : 'Reconstruct at entry'}</button>
    </div> : <>
      <p className="ta-version">Four-factor v{analysis.rule_set.version}{analysis.rule_set.revision != null && ` · revision ${analysis.rule_set.revision}`} · Saved {setupTime(saved.created_at)}</p>
      <p className="trade-notice">{source === 'entry_time'
        ? `Retrospective reconstruction using four-factor v${analysis.rule_set.version} at reconstruction time. It does not prove what you knew or which rules you used at entry. The original setup remains unchanged.`
        : coverage.timing === 'captured_before_entry' ? 'This setup was captured before entry. Its saved calculations are compared with your actual trade direction.'
          : 'Retrospective setup context. The original setup was reconstructed historically or saved after entry; it does not establish what you knew then.'}</p>
      <dl className="ta-timing"><div><dt>Trade entry</dt><dd>{setupTime(coverage.entry_at)}</dd></div><div><dt>Evidence cutoff</dt><dd>{setupTime(coverage.cutoff_at)}</dd></div>
        <div><dt>Last completed candle</dt><dd>{setupTime(coverage.data_through)}</dd></div><div><dt>Last close was</dt><dd>{coverage.last_close_age_seconds === 0 ? 'At entry time' : `${evidenceAge(coverage.last_close_age_seconds)} before entry`}</dd></div></dl>
      {!coverage.covers_latest_scheduled_close && <p className="ta-warning">This evidence stops before the latest scheduled H4 close at entry ({setupTime(coverage.latest_scheduled_close)}). It may miss intervening candles. Use the entry reconstruction for a comparison at the recorded time; provider gaps or holiday closures can still prevent it.</p>}
      {coverage.earlier_session && <p className="ta-warning">These results belong to an earlier session ({coverage.journal_date}). {coverage.covers_latest_scheduled_close ? 'The entry session had no completed H4 candles, so the previous completed session supplies context.' : 'They do not describe the session containing your entry.'}</p>}
      <div className="ta-summary"><div><h4>{scopeLabel(analysis)}</h4><Status value={analysis.summary.relation} /><p>{coverage.candle_count} of {coverage.expected_candle_count} completed candles in the reviewed session.</p></div>
        <dl><div><dt>Supporting points</dt><dd>{pointText(analysis.summary.supporting_points)} <small>/ {analysis.summary.max_points}</small></dd></div><div><dt>Conflicting points</dt><dd>{pointText(analysis.summary.conflicting_points)} <small>/ {analysis.summary.max_points}</small></dd></div></dl></div>
      <p className="trade-help">No minimum score or pass/fail rule is configured. These comparisons do not grade discipline or estimate the probability of a profitable trade.</p>
      <div className="ta-table-scroll" tabIndex={0} role="region" aria-label="Four-factor comparison table">
        <table><caption>Latest completed H4 candle: {setupTime(latest.close_time)}. Averages use all {coverage.candle_count} reviewed candles; pending candles do not count as zero.</caption>
          <thead><tr><th scope="col">Factor</th><th scope="col">Latest candle</th><th scope="col">Avg. supporting pts</th><th scope="col">Avg. conflicting pts</th></tr></thead>
          <tbody>{analysis.factors.map(factor => <tr key={factor.id}><th scope="row">{factor.name}<small>Up to {factor.max_points} {factor.max_points === 1 ? 'point' : 'points'}</small></th>
            <td><Status value={factor.latest.relation} /><span className="ta-description">{factorDescription(factor.latest.result)}</span>
              <small>{factor.latest.relation === 'unavailable' ? 'Points withheld' : `${pointText(factor.latest.supporting_points)} supporting / ${pointText(factor.latest.conflicting_points)} conflicting`}</small></td>
            <td>{pointText(factor.average_supporting_points)}</td><td>{pointText(factor.average_conflicting_points)}</td></tr>)}</tbody>
        </table></div>
      <p className="trade-help">A factor can support some candles and conflict on others. An unavailable reading withholds that factor’s average and the overall average; it is never treated as neutral or zero.</p>
      <details className="ta-details"><summary>Per-candle comparison and reasons</summary>{analysis.factors.map(factor => <div key={factor.id}>
        <h4>{factor.name}</h4><p>{factor.counts.supporting} supporting · {factor.counts.conflicting} conflicting · {factor.counts.neutral} neutral · {factor.counts.unavailable} unavailable</p>
        <ul>{factor.candles.map(candle => <li key={candle.candle_id}><strong>{candle.candle_id} · {setupTime(candle.close_time)}</strong><Status value={candle.relation} /><p>{candle.result.reason}</p></li>)}</ul>
      </div>)}</details>
    </>}
    {snapshot && <><button type="button" className="ta-evidence-toggle" aria-expanded={showMarket} onClick={() => setShowMarket(value => !value)}>{showMarket ? 'Hide comparison market evidence' : 'View comparison market evidence'}</button>
      {active && showMarket && <MarketReview includeAfter snapshot={setupChartSnapshot(snapshot)} evaluation={snapshot.rule_evaluation} setupZones={snapshot.zones} />}</>}
  </section>
}
