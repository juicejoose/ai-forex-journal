export function TradePlanFields({ value, direction, onChange }) {
  const filled = Object.values(value).some(item => item.trim())
  return <section className="se-plan-input" aria-label="Optional trade plan">
    <div className="se-row"><h4>Trade plan <span className="se-help">(optional)</span></h4>
      {filled && <button type="button" onClick={() => onChange({ entryPrice: '', stopLoss: '', takeProfit: '' })}>Clear trade plan</button>}
    </div>
    <p className="se-help">Enter all three planned prices, or leave them blank. Pip distances and reward-to-risk are calculated when you capture the setup.</p>
    <div className="se-fields se-plan-fields">
      <label>Planned entry<input inputMode="decimal" value={value.entryPrice} placeholder="1.10000" onChange={event => onChange({ ...value, entryPrice: event.target.value })} /></label>
      <label>Stop loss<input inputMode="decimal" value={value.stopLoss} placeholder={direction === 'long' ? '1.09800' : '1.10200'} onChange={event => onChange({ ...value, stopLoss: event.target.value })} /></label>
      <label>Take profit<input inputMode="decimal" value={value.takeProfit} placeholder={direction === 'long' ? '1.10400' : '1.09600'} onChange={event => onChange({ ...value, takeProfit: event.target.value })} /></label>
    </div>
    <p className="se-help">{direction === 'long' ? 'Long: stop loss below entry, take profit above entry.' : 'Short: take profit below entry, stop loss above entry.'} These are your proposed levels; capture saves the plan for review.</p>
  </section>
}

export default function SavedTradePlan({ plan }) {
  if (!plan) return null
  return <section className="se-plan-result" aria-label="Saved trade plan">
    <div className="se-row"><h4>Saved trade plan</h4><span className="se-help">{plan.direction === 'long' ? 'Long' : 'Short'} · User-entered levels</span></div>
    <dl className="se-plan-metrics">
      <div><dt>Planned entry</dt><dd>{plan.entry_price}</dd></div>
      <div><dt>Stop loss</dt><dd>{plan.stop_loss}</dd></div>
      <div><dt>Take profit</dt><dd>{plan.take_profit}</dd></div>
      <div><dt>Risk distance</dt><dd>{plan.risk_pips} <small>pips</small></dd></div>
      <div><dt>Potential reward</dt><dd>{plan.reward_pips} <small>pips</small></dd></div>
      <div><dt>Reward / risk</dt><dd>{plan.reward_to_risk_display} <small>: 1</small></dd></div>
    </dl>
    <p className="se-help">{plan.assumptions}</p>
    {plan.zone_positions.length > 0 && <details><summary>Planned levels relative to your zones</summary>
      <div className="se-plan-table" role="region" aria-label="Trade-plan zone comparisons" tabIndex={0}>
        <table><thead><tr><th>Zone</th><th>Entry</th><th>Stop</th><th>Target</th></tr></thead>
          <tbody>{plan.zone_positions.map(zone => <tr key={zone.zone_id}><th scope="row">{zone.label}<small>{zone.kind}</small></th>
            <td>{zone.entry_position}</td><td>{zone.stop_position}</td><td>{zone.target_position}</td></tr>)}</tbody>
        </table>
      </div>
      <p className="se-help">Positions use your exact zone boundaries. A level on an edge is inside the zone. These comparisons do not grade level placement or predict execution.</p>
    </details>}
  </section>
}
