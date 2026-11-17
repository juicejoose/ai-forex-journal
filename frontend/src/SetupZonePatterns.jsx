import { chartStamp, chartTime } from './marketChartData.js'
import { patternLabel, retestLabels } from './setupPatterns.js'

const stamp = value => chartTime(value) === null ? 'Unavailable' : chartStamp(chartTime(value))
const statusText = {
  not_requested: 'Add an origin time when capturing a new setup to evaluate these rules.',
  no_completed_candles: 'No whole completed H4 candles are available after the origin.',
  insufficient_data: 'At least two consecutive completed candles are needed to establish the approach and the pattern.',
}

export default function SetupZonePatterns({ patterns, onSelect, showPatterns, onShowPatterns }) {
  if (!patterns) return <p className="zh-notice">This older snapshot has no saved rejection, breakout or retest analysis. Capture a new setup to use the current rules.</p>
  const latest = patterns.breakouts?.at(-1)
  const recent = patterns.events?.at(-1)
  const unknown = statusText[patterns.status]
  return <section className="zp-panel" aria-label="Price-action rules">
    <div className="zp-heading"><h4>Price-action rules</h4><span>{patterns.version.replaceAll('_', ' ')}</span></div>
    <p className="zh-help">Completed H4 candles · exact zone edges · separate from four-factor points</p>
    {unknown ? <p className="zh-notice">{unknown}</p> : <>
      {patterns.status === 'partial_history' && <p className="zh-notice">Partial history. Counts cover observed candles only; missing candles interrupt pattern sequences.</p>}
      <div className="zp-overview">
        <div><span>Latest observed match</span>{recent ? <>
          <button type="button" className={`zp-event zp-${recent.kind === 'retest_invalidated' ? 'neutral' : recent.direction}`} onClick={() => onSelect(chartTime(recent.open_time))}>{patternLabel(recent)}</button>
          <small>{stamp(recent.close_time)}</small>
        </> : <strong>No rule matched in this window</strong>}</div>
        <div><span>Latest breakout’s retest</span>{latest ? <>
          <strong>{retestLabels[latest.status] ?? 'Unavailable'}</strong>
          <small>{latest.observed_candles} / {patterns.rules.retest_window_candles} later candles observed</small>
          <small>Breakout: {stamp(latest.breakout.close_time)}</small>
          <small>Assessed through {stamp(latest.assessed_through.close_time)}</small>
        </> : <strong>No observed breakout</strong>}</div>
      </div>
      <p className="zh-help">Observed rule matches: {patterns.counts.rejection} rejection(s) · {patterns.counts.breakout} breakout(s) · {patterns.counts.retest_held} held retest(s). A past match does not establish current confirmation.</p>
      <label className="zh-toggle"><input type="checkbox" checked={showPatterns} onChange={event => onShowPatterns(event.target.checked)} />Show pattern events on chart</label>
      <p className="zh-help">REJ = rejection · BRK = breakout · RT = retest held · RT ended = attempt invalidated. Select an event to inspect its candle.</p>
      <details><summary>Pattern events &amp; candle evidence ({patterns.events.length})</summary>
        <div className="zp-events">{[...patterns.events].reverse().map(event => <article key={event.id}>
          <button type="button" className={`zp-event zp-${event.kind === 'retest_invalidated' ? 'neutral' : event.direction}`} onClick={() => onSelect(chartTime(event.open_time))}>{patternLabel(event)}</button>
          <p className="zh-help">{stamp(event.close_time)} · {event.id}</p>
          <p>{event.reason ?? event.description}</p>
          <div className="zp-candles">{event.evidence.map((candle, index) => <button type="button" key={candle.candle_id} onClick={() => onSelect(chartTime(candle.open_time))}>
            <strong>{index === 0 ? 'Previous candle' : 'Event candle'}</strong><span>{stamp(candle.close_time)}</span>
            <span>O {candle.open.toFixed(5)} · H {candle.high.toFixed(5)}</span><span>L {candle.low.toFixed(5)} · C {candle.close.toFixed(5)}</span>
          </button>)}</div>
        </article>)}</div>
      </details>
      {patterns.breakouts.length > 0 && <details><summary>Retest attempts ({patterns.breakouts.length})</summary>
        <ul className="zp-attempts">{[...patterns.breakouts].reverse().map(attempt => <li key={attempt.id}>
          <button type="button" onClick={() => onSelect(chartTime(attempt.breakout.open_time))}>{attempt.direction === 'bullish' ? 'Bullish' : 'Bearish'} breakout · {stamp(attempt.breakout.close_time)}</button>
          <strong>{retestLabels[attempt.status]}</strong><span>{attempt.observed_candles} / {patterns.rules.retest_window_candles} later candles observed · through {stamp(attempt.assessed_through.close_time)}</span>
        </li>)}</ul>
      </details>}
    </>}
    <details className="zh-definitions"><summary>Exact pattern rules</summary>
      <p><strong>Rejection:</strong> {patterns.rules.rejection}</p>
      <p><strong>Breakout:</strong> {patterns.rules.breakout}</p>
      <p><strong>Retest:</strong> {patterns.rules.retest}</p>
      <p><strong>Attempt invalidation:</strong> {patterns.rules.invalidation}</p>
      <p>{patterns.rules.boundaries}</p>
      <p>Inside closes keep the attempt open. Returning outside from an inside close does not itself count as a held retest or restart the six-candle window. Expiry means the window ended without a hold; it is not a trade loss. Normal market weekends do not consume candles.</p>
    </details>
  </section>
}
