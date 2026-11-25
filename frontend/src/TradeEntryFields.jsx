export default function TradeEntryFields({form, edit, timezone}) {
  return <>
    <label>Trade name <span>(optional)</span><input value={form.title} maxLength={120} onChange={e => edit({ title: e.target.value })} placeholder="e.g. London support reaction" /></label>
    <label>Direction<select value={form.direction} onChange={e => edit({ direction: e.target.value })}><option value="long">Long</option><option value="short">Short</option></select></label>
    <label>Actual entry price<input required inputMode="decimal" value={form.entryPrice} onChange={e => edit({ entryPrice: e.target.value })} placeholder="1.10000" /></label>
    <label>Entry time · {timezone}<input required type="datetime-local" value={form.entryAt} onChange={e => edit({ entryAt: e.target.value })} /></label>
    <label>Initial stop loss <span>(optional)</span><input inputMode="decimal" value={form.stopLoss} onChange={e => edit({ stopLoss: e.target.value })} placeholder="No initial stop" /></label>
    <label>Initial take profit <span>(optional)</span><input inputMode="decimal" value={form.takeProfit} onChange={e => edit({ takeProfit: e.target.value })} placeholder="No initial target" /></label>
    <label className="trade-wide">Reason for entry<textarea required maxLength={5000} rows={3} value={form.reason} onChange={e => edit({ reason: e.target.value })} placeholder="What supported your decision at entry?" /></label>
    <label className="trade-wide">Support/resistance and entry observations <span>(optional)</span><textarea maxLength={5000} rows={2} value={form.observations} onChange={e => edit({ observations: e.target.value })} /></label>
  </>
}
