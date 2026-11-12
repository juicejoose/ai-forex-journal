import { factorDescription, paceLabels } from './strategyDescriptions.js'
import { useState } from 'react'
import './StrategyScores.css'
import StrategyRuleHelp from './StrategyRuleHelp.jsx'
import { changeTone, formatChange } from './journalCalendar.js'
import { chartTime } from './marketChartData.js'

const clock = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })
const day = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' })
const labels = { bullish: 'Bullish lean', bearish: 'Bearish lean', mixed: 'Mixed', neutral: 'Neutral', insufficient_data: 'Insufficient data' }

const outcomeLabel = (factor) => ({
  bullish: `+${factor.bullish_points} Bull`, bearish: `+${factor.bearish_points} Bear`,
  neutral: 'Neither', unavailable: 'Unavailable',
})[factor.outcome]
const stamp = (value, format = clock) => format.format(new Date(value))
const number = (name, value) => Number.isFinite(value) ? value.toFixed(['rsi14', 'rsi14_sma14'].includes(name) ? 2 : 5) : 'unavailable'


function priceChange(candle) {
  if (!Number.isFinite(candle?.open) || !Number.isFinite(candle?.close) || candle.open <= 0) return null
  const value = (candle.close - candle.open) / candle.open * 100
  return Number.isFinite(value) ? value : null
}

export default function StrategyScores({ evaluation, snapshot, selectedTime, onSelectCandle }) {
  const [activeHelp, setActiveHelp] = useState(null)
  const customRange = evaluation?.analysis_kind === 'custom_range'
  const intraday = evaluation?.analysis_kind === 'intraday'
  const partial = intraday && evaluation?.summary?.method === 'session_to_date'
  if (!evaluation) return null
  if (evaluation.schema_version !== 1 || (!Array.isArray(evaluation.candles) || (intraday ? evaluation.candles.length < 1 || evaluation.candles.length > 6 : customRange ? evaluation.candles.length < 6 || evaluation.candles.length % 6 !== 0 : evaluation.candles.length !== 6)) || !evaluation.summary || !evaluation.rule_set?.factors) {
    return <p className="jv-error">This strategy score format is unavailable in this version of the app.</p>
  }
  const { summary, candles, rule_set: ruleSet } = evaluation
  const averaged = ['session_average', 'range_average', 'session_to_date'].includes(summary.method)
  const periodLabel = partial ? 'Session-to-date' : customRange ? 'Range' : 'Session'
  const endLabel = partial ? 'Latest completed candle' : `${periodLabel}-end`
  const pending = partial ? Array.from({ length: 6 - evaluation.candles.length }, (_, index) => {
    const slot = evaluation.candles.length + index
    const start = new Date(snapshot.session.start_utc).getTime() + slot * 14400000
    return { open: new Date(start).toISOString(), close: new Date(start + 14400000).toISOString() }
  }) : []
  const finalCandle = candles.at(-1)
  const countLabel = customRange || partial ? String(candles.length) : 'six'
  const sessionEnd = evaluation.session_end
  const summaryNumber = (value, signed = false) => Number.isFinite(value)
    ? `${signed && value > 0 ? '+' : ''}${averaged ? value.toFixed(2) : value}` : '—'
  const biasLabel = averaged && summary.direction === 'insufficient_data' ? 'Incomplete' : labels[summary.direction]
  const marketCandles = Array.isArray(snapshot?.candles) ? snapshot.candles : []
  return <section className={`strategy-scores${customRange ? ' ss-range' : ''}`} aria-labelledby="strategy-score-heading">
    <header className="ss-heading">
      <div><p className="jv-eyebrow">CALCULATED STRATEGY RESULTS</p><h3 id="strategy-score-heading">{ruleSet.name} <span>v{ruleSet.version}</span></h3></div>
      <div className="ss-bias-group">
        <span className={`ss-bias ss-${summary.direction}`}>{averaged ? `${periodLabel} average · ` : ''}{biasLabel}</span>
        {averaged && sessionEnd && <span className="ss-session-end">{endLabel} bias: <span className={`ss-${sessionEnd.direction}`}>{labels[sessionEnd.direction]}</span></span>}
      </div>
    </header>
    <p className="ss-help">{averaged
      ? partial ? `Provisional average of ${candles.length} completed candles out of 6. Pending candles have no scores and are excluded from this average.` : `${periodLabel} averages give all ${countLabel} H4 candles equal weight. ${periodLabel}-end bias shows only the final candle, ending ${stamp(finalCandle.close_time, day)} at ${stamp(finalCandle.close_time)} New York time.`
      : `Session-end bias uses the final candle, ending at ${stamp(finalCandle.close_time)} New York time.`}</p>
    <div className="ss-totals">
      <div className="ss-bullish"><span>{averaged ? 'Avg. bullish points' : 'Bullish points'}</span><strong>{summaryNumber(summary.bullish_points)} <small>/ {summary.max_points}</small></strong><span>{Number.isFinite(summary.bullish_alignment_percent) ? `${summaryNumber(summary.bullish_alignment_percent)}% alignment` : 'Alignment unavailable'}</span></div>
      <div className="ss-bearish"><span>{averaged ? 'Avg. bearish points' : 'Bearish points'}</span><strong>{summaryNumber(summary.bearish_points)} <small>/ {summary.max_points}</small></strong><span>{Number.isFinite(summary.bearish_alignment_percent) ? `${summaryNumber(summary.bearish_alignment_percent)}% alignment` : 'Alignment unavailable'}</span></div>
      <div><span>{averaged ? 'Avg. net score' : 'Net score'}</span><strong>{summaryNumber(summary.net_score, true)}</strong><span>{summary.evaluated_factors} / {averaged ? summary.expected_factors : ruleSet.factors.length} {averaged ? 'factor checks' : 'factors'} evaluated</span></div>
    </div>
    {averaged && !summary.complete && <p className="ss-help ss-incomplete">{periodLabel} averages are unavailable until all {summary.expected_factors} factor checks can be evaluated. Missing values are not counted as zero, and unavailable completed candles are not dropped from the average.</p>}
    <p className="ss-help">{averaged ? `Across ${countLabel} candles: ` : ''}{summary.neutral_factors} neutral · {summary.unavailable_factors} unavailable{summary.reduced_factors > 0 ? ` · ${summary.reduced_factors} with reduced points` : ''}. Alignment measures your rules, not the probability of a future move.</p>
    <p className="ss-help ss-scroll-hint">Scroll across the table to see every factor.</p>
    <div className="ss-table-scroll" role="region" aria-label={`Scores for all ${countLabel} candles`} tabIndex={0}>
      <table>
        <caption>{partial ? `${candles.length} completed + ${pending.length} pending candles` : `All ${countLabel} candles`} · {ruleSet.max_points} possible points per candle · New York time · Price change compares each candle’s open and close.</caption>
        <thead><tr><th scope="col">Candle</th>{ruleSet.factors.map((factor) => <th scope="col" key={factor.id}>
          <span className="ss-factor-heading"><span>{factor.name} · {factor.distance_weighting ? 'up to ' : ''}{factor.points} {factor.points === 1 ? 'pt' : 'pts'}</span>
            <StrategyRuleHelp factor={factor} open={activeHelp === factor.id}
              onOpen={() => setActiveHelp(factor.id)}
              onClose={() => setActiveHelp((current) => current === factor.id ? null : current)} />
          </span>
        </th>)}<th scope="col">Bull / Bear</th><th scope="col">Bias</th><th scope="col">Price change %</th></tr></thead>
        <tbody>{candles.map((candle) => {
          const prices = marketCandles.find((item) => item?.open_time === candle.open_time && item?.close_time === candle.close_time)
          const change = priceChange(prices)
          const selected = selectedTime === chartTime(candle.open_time)
          const timeLabel = <><span>{stamp(candle.open_time)} – {stamp(candle.close_time)}</span><small>{stamp(candle.open_time, day)} – {stamp(candle.close_time, day)}{candle.candle_id === finalCandle.candle_id ? ` · ${partial ? 'Latest close' : `${periodLabel} end`}` : ''}</small></>
          return <tr key={candle.candle_id} className={`${candle.candle_id === finalCandle.candle_id ? 'ss-final' : ''} ${selected ? 'ss-chart-selected' : ''}`}>
          <th scope="row">{onSelectCandle ? <button type="button" className="ss-candle-select" aria-pressed={selected}
            title="Select this candle on the market chart" onClick={() => onSelectCandle(chartTime(candle.open_time))}>{timeLabel}</button> : timeLabel}</th>
          {candle.factors.map((factor) => <td key={factor.factor_id}><span className={`ss-outcome ss-${factor.outcome}`}>{outcomeLabel(factor)}</span><small className="ss-factor-description">{factorDescription(factor)}</small></td>)}
          <td>{candle.bullish_points} / {candle.bearish_points}</td><td>{labels[candle.direction]}</td>
          <td className={`ss-price-change jv-tone-${changeTone(change)}`} title={change === null ? 'Candle prices unavailable' : '(Close − Open) ÷ Open × 100'}>{formatChange(change)}</td>
        </tr>
        })}{pending.map(slot => <tr key={slot.open} className="ss-pending"><th scope="row"><span>{stamp(slot.open)} – {stamp(slot.close)}</span><small>{stamp(slot.open, day)} – {stamp(slot.close, day)}</small></th><td colSpan={7}>Pending · no score until this candle closes</td></tr>)}</tbody>
      </table>
    </div>
    <details className="ss-details"><summary>Review factor evidence and rule definitions</summary>
      <p className="ss-help">Comparisons use unrounded values; displayed prices, momentum and deltas use five decimals. P0 is the previous completed trading candle; P-1 is the candle before P0. Both are outside the scored period. These saved results remain unchanged when you edit the journal text.</p>
      {candles.map((candle) => <section key={candle.candle_id}>
        <h4>{candle.candle_id} · {stamp(candle.open_time)} – {stamp(candle.close_time)}</h4>
        {candle.factors.map((factor) => <div className="ss-factor" key={factor.factor_id}>
          <p><strong>{factor.name}</strong> · {outcomeLabel(factor)}</p><p>{factor.reason}</p>
          {factor.ema_sma_distance && <p className="ss-values">EMA/SMA gap: {number('gap', factor.ema_sma_distance.gap_pips)} pips · Reduced-point threshold: ≤ {factor.ema_sma_distance.threshold_pips} pips. The comparison uses unrounded values; a displayed gap may be rounded.</p>}
          {factor.momentum_change && <p className="ss-values">{paceLabels[factor.momentum_change.pace]} · Previous delta: {number('momentum', factor.momentum_change.previous_delta)} · Current delta: {number('momentum', factor.momentum_change.current_delta)}. Each delta is the difference between successive momentum values.</p>}
          {factor.evidence.map((evidence) => <p className="ss-values" key={evidence.candle_id}>{evidence.candle_id} · {stamp(evidence.close_time, day)}, {stamp(evidence.close_time)}: {Object.entries(evidence.values).map(([name, value]) => `${({ rsi14: 'RSI14', rsi14_sma14: 'RSI14 SMA14' })[name] || name}: ${number(name, value)}`).join(' · ')}</p>)}
        </div>)}
      </section>)}
      <h4>Saved rule definitions</h4><p className="ss-rule-text">{ruleSet.rules}</p>
    </details>
  </section>
}
