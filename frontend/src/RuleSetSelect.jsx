import './RuleSetSelect.css'

export default function RuleSetSelect({ id, value, onChange, definitions, error, onRetry, disabled }) {
  const loaded = definitions.length > 0
  return <div className="rule-choice">
    <label htmlFor={id}>Strategy evaluation</label>
    <select id={id} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} aria-describedby={`${id}-help`}>
      <option value="four_factor_v4" disabled={!definitions.some((item) => item.id === 'four_factor_v4')}>Four-factor strategy v4 · Session average</option>
      <option value="four_factor_v3" disabled={!definitions.some((item) => item.id === 'four_factor_v3')}>Four-factor strategy v3 · Momentum slowdown</option>
      <option value="four_factor_v2" disabled={!definitions.some((item) => item.id === 'four_factor_v2')}>Four-factor strategy v2 · Full momentum points</option>
      <option value="four_factor_v1" disabled={!definitions.some((item) => item.id === 'four_factor_v1')}>Four-factor strategy v1 · Original rules</option>
      <option value="">Written strategy · AI review</option>
    </select>
    <p id={`${id}-help`}>{value
      ? value === 'four_factor_v4'
        ? 'All six H4 candles contribute equally to the session average, out of five possible points. Keeps weighted EMA/SMA, RSI 40/60, and momentum slowdown. Session-end bias is shown separately.'
        : value === 'four_factor_v3'
        ? 'Five possible points. EMA/SMA earns two; RSI uses 40/60. Momentum earns half a point when three consecutive candles show a smaller same-direction change. The final candle sets the bias.'
        : value === 'four_factor_v2'
          ? 'Previous rules: five possible points, EMA/SMA worth two, RSI thresholds 40/60. Momentum uses only sign and change, with no slowdown reduction.'
          : 'Original rules: RSI ≤30 is bullish and RSI ≥70 is bearish; each factor earns one point. Choose v4 for weighted EMA/SMA, momentum slowdown, and a session average.'
      : 'AI interprets your written rules. This mode has no calculated strategy score.'}</p>
    {!loaded && !error && <p role="status">Loading scored strategy…</p>}
    {error && <div role="alert"><p>{error}</p><button type="button" onClick={onRetry} disabled={disabled}>Retry loading strategy</button></div>}
  </div>
}
