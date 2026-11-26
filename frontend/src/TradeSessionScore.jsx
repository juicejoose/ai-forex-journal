import { useId } from 'react'
import useTodayView from './useTodayView.js'
import { formatDay } from './journalCalendar.js'
import { signedScore, sessionScoreReadout } from './tradeScores.js'

const newYorkTime = new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York', month:'short', day:'numeric',
  hour:'numeric', minute:'2-digit', timeZoneName:'short'})
const sessionTime = value => newYorkTime.format(new Date(value))

export default function TradeSessionScore({active, refreshKey}) {
  const {view, fetching, dataError, refresh, fresh} = useTodayView(active, refreshKey)
  const titleId = useId()
  const score = view && sessionScoreReadout(view)
  return <div className="trade-session-score" aria-labelledby={titleId}>
    <div className="trade-score-heading"><h4 id={titleId}>Today’s session score</h4></div>
    {dataError ? <><p role="alert" className="trade-error">{dataError}</p>
      <button type="button" disabled={fetching} onClick={refresh}>Retry session score</button></> :
      !view ? <p role="status">Loading session score…</p> : <>
        <strong>{score.headline}</strong>
        <p>{score.coverage}</p>
        {score.detail && <small>{score.detail}</small>}
        {!fresh && <small>Refresh needed · Last checked {sessionTime(view.as_of)}</small>}
        <details className="trade-session-evidence"><summary>Session evidence</summary>
          <p>{formatDay(view.journal_date)} · New York{view.rule_evaluation && ` · Four-factor v${view.rule_evaluation.rule_set.version}`}</p>
          <p>{sessionTime(view.session.start)} – {sessionTime(view.session.end)}</p>
          <p>Equal weight per completed H4 candle, including closes before trade entry.</p>
          {view.rule_evaluation && <ol>{view.rule_evaluation.candles.map(row=><li key={row.candle_id}>
            {sessionTime(row.close_time)} · Net {row.direction === 'insufficient_data' ? 'unavailable' : signedScore(row.net_score)}
          </li>)}</ol>}
          <small>Checked · {sessionTime(view.as_of)}</small>
        </details>
        {view.market_state === 'weekend_closed' && <small>Market closed · Friday session</small>}
      </>}
  </div>
}
