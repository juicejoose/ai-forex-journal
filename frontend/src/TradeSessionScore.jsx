import TradeCandleScoreTable from './TradeCandleScoreTable.jsx'
import { useId } from 'react'
import { formatDay } from './journalCalendar.js'
import { sessionScoreReadout } from './tradeScores.js'

const newYorkTime = new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York', month:'short', day:'numeric',
  hour:'numeric', minute:'2-digit', timeZoneName:'short'})
const sessionTime = value => newYorkTime.format(new Date(value))

export default function TradeSessionScore({session, evidenceId, onShowEvidence}) {
  const {view, fetching, dataError, refresh, fresh} = session
  const titleId = useId()
  const score = view && sessionScoreReadout(view)
  return <div className="trade-session-score" aria-labelledby={titleId}>
    <div className="trade-score-heading">
      <h4 id={titleId}>Today’s session score</h4>
      <button type="button" className="trade-score-evidence-link" aria-label="View today’s session score evidence"
        aria-controls={view && !dataError ? evidenceId : undefined} disabled={!view || Boolean(dataError)} onClick={onShowEvidence}>
        Evidence <span aria-hidden="true">↓</span>
      </button>
    </div>
    {dataError ? <><p role="alert" className="trade-error">{dataError}</p>
      <button type="button" disabled={fetching} onClick={refresh}>Retry session score</button></> :
      !view ? <p role="status">Loading session score…</p> : <>
        <strong>{score.headline}</strong>
        <p>{score.coverage}</p>
        {score.detail && <small>{score.detail}</small>}
        {!fresh && <small>Refresh needed · Last checked {sessionTime(view.as_of)}</small>}
        {view.market_state === 'weekend_closed' && <small>Market closed · Friday session</small>}
      </>}
  </div>
}

export function TradeSessionEvidence({view, evidenceId, headingRef}) {
  return <details className="trade-score-details trade-session-evidence">
    <summary className="trade-score-evidence-heading" id={evidenceId} ref={headingRef}>Today’s session score evidence</summary>
    <p>{formatDay(view.journal_date)} · New York{view.rule_evaluation && ` · Four-factor v${view.rule_evaluation.rule_set.version}`}</p>
    <p>{sessionTime(view.session.start)} – {sessionTime(view.session.end)}</p>
    <p>Equal weight per completed H4 candle, including closes before trade entry.</p>
    {view.rule_evaluation?.candles.length > 0 ? <TradeCandleScoreTable label="Today's session candle scores"
      caption={`${view.session.candle_count} of 6 H4 candles closed`} candles={view.rule_evaluation.candles}
      average={view.rule_evaluation.summary} /> : <p>{view.session.candle_count === 0 ? 'Awaiting the first completed H4 candle.' : 'Candle scores are unavailable.'}</p>}
    <small>Checked · {sessionTime(view.as_of)}</small>
  </details>
}
