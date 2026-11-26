import { setupTime } from './setupEvaluation.js'
import { scoreNumber,signedScore,scoreDirection } from './tradeScores.js'
import { factorDescription } from './strategyDescriptions.js'
import './TradeScores.css'

export function TradeScoreCards({scores,record,evidenceIds,onShowEvidence,sessionCard,coach}) {
  const {value,error,loading,refresh}=scores
  const entry=value?.entry_score.summary, full=value?.full_trade.summary
  return <div className="trade-score-panel" aria-label="Trade scores and coach">
    {error && <p className="trade-error" role="alert">{error} {value && (value.full_trade.error ? 'The saved entry score is retained.' : 'Showing previously calculated scores; the trade average may be outdated.')} <button type="button" disabled={loading} onClick={refresh}>Retry scores</button></p>}
    {!value && !error && <p className="trade-help" role="status">Calculating entry alignment and the trade average…</p>}
    <div className="trade-score-cards">{value && <>
      <div><div className="trade-score-heading"><h4>Entry score</h4><button type="button" className="trade-score-evidence-link" aria-label="View entry score evidence" aria-controls={evidenceIds.entry} onClick={()=>onShowEvidence('entry')}>Evidence <span aria-hidden="true">↓</span></button></div><strong>{scoreNumber(entry.supporting_points)}{entry.supporting_points !== null && ` / ${entry.max_points} aligned`}</strong>
        <p>{record.entry.direction === 'long' ? 'Long' : 'Short'} entry · {scoreNumber(entry.conflicting_points)} conflicting</p>
        <small>{scoreDirection(entry.direction)} · Net {signedScore(entry.net_score)} · Last completed H4</small></div>
      <div><div className="trade-score-heading"><h4>{record.status==='closed' ? 'Full trade score' : 'Trade-to-date score'}</h4><button type="button" className="trade-score-evidence-link" aria-label={record.status==='closed' ? 'View full trade score evidence' : 'View trade-to-date score evidence'} aria-controls={evidenceIds.full} onClick={()=>onShowEvidence('full')}>Evidence <span aria-hidden="true">↓</span></button></div><strong>{!full ? 'Unavailable' : full.candle_count ? `Avg. net ${signedScore(full.net_score)}` : 'No completed closes'}</strong>
        {full ? <><p>{scoreDirection(full.direction)} · {full.candle_count} completed {full.candle_count===1 ? 'candle' : 'candles'}</p>
        <small>Bull {scoreNumber(full.bullish_points)} · Bear {scoreNumber(full.bearish_points)} · / {full.max_points}</small></> : <p>Trade-period data unavailable · retry above</p>}</div>
    </>}{sessionCard}{coach}</div>{value && <p className="trade-score-footnote">Four-factor v{value.rule_set.version}{value.rule_set.revision!=null && ` · revision ${value.rule_set.revision}`} · Rule alignment, not profit or win probability.{loading ? ' Updating…' : value.saved_at ? ' Full-trade score saved.' : value.full_trade.error ? ' Entry score remains saved.' : ' Average updates after completed H4 closes.'}</p>}
  </div>
}

export function TradeScoreDetails({value,evidenceRef,entryRef,fullRef,evidenceIds}) {
  if(!value) return null
  const full=value.full_trade, entry=value.entry_score
  return <details className="trade-score-details" ref={evidenceRef}><summary>Entry & full-trade score evidence</summary>
    <h4 className="trade-score-evidence-heading" id={evidenceIds.entry} ref={entryRef} tabIndex={-1}>Entry score evidence</h4>
    <p className="trade-help">Entry score uses only the H4 candle completed at {setupTime(entry.data_through)}, before or exactly at your entry ({setupTime(value.entry_at)}). It is a saved retrospective reconstruction, not proof of what you knew then.</p>
    {!entry.covers_latest_scheduled_close && <p className="trade-error">Entry evidence is older than the latest scheduled H4 close ({setupTime(entry.latest_scheduled_close)}).</p>}
    <div className="trade-score-table" tabIndex={0} role="region" aria-label="Entry factor scores"><table><caption>Entry alignment · latest completed H4 candle</caption>
      <thead><tr><th>Factor</th><th>Bull</th><th>Bear</th><th>Condition</th></tr></thead><tbody>{entry.candle.factors.map(f=><tr key={f.factor_id}><th>{f.name}</th><td>{f.outcome==='unavailable' ? 'Unavailable' : scoreNumber(f.bullish_points)}</td><td>{f.outcome==='unavailable' ? 'Unavailable' : scoreNumber(f.bearish_points)}</td><td>{factorDescription(f)}</td></tr>)}</tbody></table></div>
    <h4 className="trade-score-evidence-heading" id={evidenceIds.full} ref={fullRef} tabIndex={-1}>{value.exit_at ? 'Full trade score evidence' : 'Trade-to-date score evidence'}</h4>
    {full.error ? <p className="trade-error">{full.error} No final score was saved; the entry score is retained.</p> : <>
    <p className="trade-help">The trade average gives equal weight to every H4 candle with a close strictly after entry and at or before {value.exit_at ? 'exit' : 'the latest refresh'} ({setupTime(full.cutoff_at)}). It is separate from the pre-entry session average. Bullish and bearish points are averaged separately; net is bullish minus bearish. Positive means bullish and negative means bearish, regardless of the trade direction.</p>
    {full.entry_candle_includes_pre_entry_prices && <p className="trade-help">The first included candle opened before entry but closed while you held the trade. Its full H4 prices are used only in this retrospective average.</p>}
    {full.exit_candle_excluded && <p className="trade-help">The exit candle closed after your exit and is excluded from this score, even though it remains visible on the chart.</p>}
    {!full.summary.candle_count && <p className="trade-help">No H4 candle closed during this trade interval. Its full-trade score is unavailable, not zero.</p>}
    <p className="trade-help">Forming candles, preceding chart history and post-exit review candles receive no points in this average. Missing inputs withhold the score. {value.saved_at ? `Final score saved ${setupTime(value.saved_at)}; reopening uses that snapshot.` : `Trade-to-date calculation checked ${setupTime(value.as_of)}.`}</p>
    {full.candles.length>0 && <div className="trade-score-table" tabIndex={0} role="region" aria-label="Full-trade candle scores"><table><caption>All completed candles included in the trade average</caption><thead><tr><th>H4 close · New York</th><th>Bull</th><th>Bear</th><th>Net</th><th>Direction</th></tr></thead>
      <tbody>{full.candles.map(c=><tr key={c.open_time}><th>{setupTime(c.close_time)}</th><td>{c.direction==='insufficient_data' ? 'Unavailable' : scoreNumber(c.bullish_points)}</td><td>{c.direction==='insufficient_data' ? 'Unavailable' : scoreNumber(c.bearish_points)}</td><td>{c.direction==='insufficient_data' ? 'Unavailable' : signedScore(c.net_score)}</td><td>{scoreDirection(c.direction)}</td></tr>)}</tbody></table></div>}
    </>}
  </details>
}
