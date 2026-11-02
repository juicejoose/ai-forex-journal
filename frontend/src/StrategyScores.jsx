import { useState } from 'react'
import './StrategyScores.css'
import StrategyRuleHelp from './StrategyRuleHelp.jsx'
import { changeTone, formatChange } from './journalCalendar.js'

const clock = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })
const day = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' })
const labels = { bullish: 'Bullish lean', bearish: 'Bearish lean', mixed: 'Mixed', neutral: 'Neutral', insufficient_data: 'Insufficient data' }
const paceLabels = { slowing: 'Slowing', accelerating: 'Accelerating', steady: 'Steady pace', transition: 'Zero-crossing reset', new_move: 'New directional move', not_directional: 'No directional point', unavailable: 'Insufficient history' }
const outcomeLabel = (factor) => ({
  bullish: `+${factor.bullish_points} Bull`, bearish: `+${factor.bearish_points} Bear`,
  neutral: 'Neither', unavailable: 'Unavailable',
})[factor.outcome]
const stamp = (value, format = clock) => format.format(new Date(value))
const number = (name, value) => Number.isFinite(value) ? value.toFixed(name === 'rsi14' ? 2 : 5) : 'unavailable'

function factorDescription(factor) {
  if (factor.outcome === 'unavailable') return 'Insufficient data'
  if (factor.factor_id === 'momentum' && factor.momentum_change) {
    return paceLabels[factor.momentum_change.pace] || 'Review evidence'
  }
  const descriptions = {
    two_closes_ema: { bullish: 'Both above EMA20', bearish: 'Both below EMA20', neutral: 'Mixed or at EMA20' },
    ema_sma: { bullish: 'EMA20 above SMA190', bearish: 'EMA20 below SMA190', neutral: 'EMA20 equals SMA190' },
    rsi_extreme: { bullish: 'Oversold', bearish: 'Overbought', neutral: 'Between thresholds' },
    momentum: { bullish: 'Positive and rising', bearish: 'Negative and falling', neutral: 'Sign / change not met' },
  }
  return descriptions[factor.factor_id]?.[factor.outcome] || 'Review evidence'
}

function priceChange(candle) {
  if (!Number.isFinite(candle?.open) || !Number.isFinite(candle?.close) || candle.open <= 0) return null
  const value = (candle.close - candle.open) / candle.open * 100
  return Number.isFinite(value) ? value : null
}

export default function StrategyScores({ evaluation, snapshot }) {
  const [activeHelp, setActiveHelp] = useState(null)
  if (!evaluation) return null
  if (evaluation.schema_version !== 1 || evaluation.candles?.length !== 6 || !evaluation.summary || !evaluation.rule_set?.factors) {
    return <p className="jv-error">This strategy score format is unavailable in this version of the app.</p>
  }
  const { summary, candles, rule_set: ruleSet } = evaluation
  const averaged = summary.method === 'session_average'
  const sessionEnd = evaluation.session_end
  const summaryNumber = (value, signed = false) => Number.isFinite(value)
    ? `${signed && value > 0 ? '+' : ''}${averaged ? value.toFixed(2) : value}` : '—'
  const biasLabel = averaged && summary.direction === 'insufficient_data' ? 'Incomplete' : labels[summary.direction]
  const marketCandles = Array.isArray(snapshot?.candles) ? snapshot.candles : []
  return <section className="strategy-scores" aria-labelledby="strategy-score-heading">
    <header className="ss-heading">
      <div><p className="jv-eyebrow">CALCULATED STRATEGY RESULTS</p><h3 id="strategy-score-heading">{ruleSet.name} <span>v{ruleSet.version}</span></h3></div>
      <div className="ss-bias-group">
        <span className={`ss-bias ss-${summary.direction}`}>{averaged ? 'Session average · ' : ''}{biasLabel}</span>
        {averaged && sessionEnd && <span className="ss-session-end">Session-end bias: <span className={`ss-${sessionEnd.direction}`}>{labels[sessionEnd.direction]}</span></span>}
      </div>
    </header>
    <p className="ss-help">{averaged
      ? `Session averages give all six H4 candles equal weight. Session-end bias shows only the final candle, ending at ${stamp(candles[5].close_time)} New York time.`
      : `Session-end bias uses the final candle, ending at ${stamp(candles[5].close_time)} New York time.`}</p>
    <div className="ss-totals">
      <div className="ss-bullish"><span>{averaged ? 'Avg. bullish points' : 'Bullish points'}</span><strong>{summaryNumber(summary.bullish_points)} <small>/ {summary.max_points}</small></strong><span>{Number.isFinite(summary.bullish_alignment_percent) ? `${summaryNumber(summary.bullish_alignment_percent)}% alignment` : 'Alignment unavailable'}</span></div>
      <div className="ss-bearish"><span>{averaged ? 'Avg. bearish points' : 'Bearish points'}</span><strong>{summaryNumber(summary.bearish_points)} <small>/ {summary.max_points}</small></strong><span>{Number.isFinite(summary.bearish_alignment_percent) ? `${summaryNumber(summary.bearish_alignment_percent)}% alignment` : 'Alignment unavailable'}</span></div>
      <div><span>{averaged ? 'Avg. net score' : 'Net score'}</span><strong>{summaryNumber(summary.net_score, true)}</strong><span>{summary.evaluated_factors} / {averaged ? summary.expected_factors : ruleSet.factors.length} {averaged ? 'factor checks' : 'factors'} evaluated</span></div>
    </div>
    {averaged && !summary.complete && <p className="ss-help ss-incomplete">Session averages are unavailable until all {summary.expected_factors} factor checks can be evaluated. Missing values are not counted as zero, and fewer candles are not averaged.</p>}
    <p className="ss-help">{averaged ? 'Across six candles: ' : ''}{summary.neutral_factors} neutral · {summary.unavailable_factors} unavailable{summary.reduced_factors > 0 ? ` · ${summary.reduced_factors} with reduced points` : ''}. Alignment measures your rules, not the probability of a future move.</p>
    <p className="ss-help ss-scroll-hint">Scroll across the table to see every factor.</p>
    <div className="ss-table-scroll" role="region" aria-label="Scores for all six candles" tabIndex={0}>
      <table>
        <caption>All six candles · {ruleSet.max_points} possible points per candle · New York time · Price change compares each candle’s open and close.</caption>
        <thead><tr><th scope="col">Candle</th>{ruleSet.factors.map((factor) => <th scope="col" key={factor.id}>
          <span className="ss-factor-heading"><span>{factor.name} · {factor.points} {factor.points === 1 ? 'pt' : 'pts'}</span>
            <StrategyRuleHelp factor={factor} open={activeHelp === factor.id}
              onOpen={() => setActiveHelp(factor.id)}
              onClose={() => setActiveHelp((current) => current === factor.id ? null : current)} />
          </span>
        </th>)}<th scope="col">Bull / Bear</th><th scope="col">Bias</th><th scope="col">Price change %</th></tr></thead>
        <tbody>{candles.map((candle) => {
          const prices = marketCandles.find((item) => item?.open_time === candle.open_time && item?.close_time === candle.close_time)
          const change = priceChange(prices)
          return <tr key={candle.candle_id} className={candle.candle_id === 'C6' ? 'ss-final' : ''}>
          <th scope="row"><span>{stamp(candle.open_time)} – {stamp(candle.close_time)}</span><small>{stamp(candle.open_time, day)} – {stamp(candle.close_time, day)}{candle.candle_id === 'C6' ? ' · Session end' : ''}</small></th>
          {candle.factors.map((factor) => <td key={factor.factor_id}><span className={`ss-outcome ss-${factor.outcome}`}>{outcomeLabel(factor)}</span><small className="ss-factor-description">{factorDescription(factor)}</small></td>)}
          <td>{candle.bullish_points} / {candle.bearish_points}</td><td>{labels[candle.direction]}</td>
          <td className={`ss-price-change jv-tone-${changeTone(change)}`} title={change === null ? 'Candle prices unavailable' : '(Close − Open) ÷ Open × 100'}>{formatChange(change)}</td>
        </tr>
        })}</tbody>
      </table>
    </div>
    <details className="ss-details"><summary>Review factor evidence and rule definitions</summary>
      <p className="ss-help">Comparisons use unrounded values; displayed prices, momentum and deltas use five decimals. P0 is the previous completed trading candle; P-1 is the candle before P0. Both are outside the scored session. These saved results remain unchanged when you edit the journal text.</p>
      {candles.map((candle) => <section key={candle.candle_id}>
        <h4>{candle.candle_id} · {stamp(candle.open_time)} – {stamp(candle.close_time)}</h4>
        {candle.factors.map((factor) => <div className="ss-factor" key={factor.factor_id}>
          <p><strong>{factor.name}</strong> · {outcomeLabel(factor)}</p><p>{factor.reason}</p>
          {factor.momentum_change && <p className="ss-values">{paceLabels[factor.momentum_change.pace]} · Previous delta: {number('momentum', factor.momentum_change.previous_delta)} · Current delta: {number('momentum', factor.momentum_change.current_delta)}. Each delta is the difference between successive momentum values.</p>}
          {factor.evidence.map((evidence) => <p className="ss-values" key={evidence.candle_id}>{evidence.candle_id} · {stamp(evidence.close_time, day)}, {stamp(evidence.close_time)}: {Object.entries(evidence.values).map(([name, value]) => `${name}: ${number(name, value)}`).join(' · ')}</p>)}
        </div>)}
      </section>)}
      <h4>Saved rule definitions</h4><p className="ss-rule-text">{ruleSet.rules}</p>
    </details>
  </section>
}
