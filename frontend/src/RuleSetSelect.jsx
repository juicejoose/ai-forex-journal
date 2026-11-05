import './RuleSetSelect.css'
import { STRATEGY_CHOICES, isRetiredRuleSet } from './strategyChoices.js'

export default function RuleSetSelect({ id, value, onChange, definitions, error, onRetry, disabled }) {
  const loaded = definitions.length > 0
  const retired = isRetiredRuleSet(value)
  return <div className="rule-choice">
    <label htmlFor={id}>Strategy evaluation</label>
    <select id={id} value={retired ? 'retired' : value} onChange={(event) => onChange(event.target.value)} disabled={disabled} aria-describedby={`${id}-help`}>
      {retired && <option value="retired" disabled hidden>Choose a current evaluation</option>}
      {STRATEGY_CHOICES.map((choice) => <option key={choice.value} value={choice.value}
        disabled={Boolean(choice.value) && !definitions.some((item) => item.id === choice.value)}>{choice.label}</option>)}
    </select>
    <p id={`${id}-help`}>{retired
      ? 'This profile uses an older scoring method. Choose v7 or Written strategy before saving or reusing it. Past journals keep their saved scores.'
      : value
        ? 'All six H4 candles contribute equally to the session average, out of five possible points. EMA/SMA earns 1 point when its gap is 60 pips or less, and 2 when larger; equal values earn zero. RSI-based MA (SMA14 of RSI14) uses thresholds 40/60 first, then a three-reading MA trend between them. Rising MA from 56 to below 60 earns 0.5 bullish points; falling MA above 40 through 44 earns 0.5 bearish points. Rising momentum is bullish and falling is bearish on either side of zero, with half points for a qualifying slowdown. Session-end bias is shown separately.'
      : 'AI interprets your written rules. This mode has no calculated strategy score.'}</p>
    {!loaded && !error && <p role="status">Loading scored strategy…</p>}
    {error && <div role="alert"><p>{error}</p><button type="button" onClick={onRetry} disabled={disabled}>Retry loading strategy</button></div>}
  </div>
}
