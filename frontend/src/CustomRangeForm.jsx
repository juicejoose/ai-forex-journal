import { customRangeDetails } from './customRange.js'
import { formatDay, newYorkToday } from './journalCalendar.js'
import './GenerateJournalForm.css'

export default function CustomRangeForm({ start, end, notes, options, optionsError, onRetry,
  onStart, onEnd, onNotes, onSubmit, busy, loading, error }) {
  const details = customRangeDetails(start, end, options?.max_calendar_days ?? 31)
  return <section className="generate-form" aria-labelledby="custom-heading">
    <header className="gf-heading"><p className="gf-eyebrow">CUSTOM DATE RANGE</p>
      <h2 id="custom-heading">Review the bigger picture</h2>
      <p>Compare a complete date range with your strategy, using the same four-hour candles.</p></header>
    <form onSubmit={onSubmit}>
      <div className="gf-layout">
        <div className="gf-session-column">
          <section className="gf-card"><header className="gf-card-header"><span className="gf-step">01</span><h3>Date range</h3></header>
            <div className="cr-date-fields">
              <div className="gf-field"><label htmlFor="custom-start">Start date</label><input id="custom-start" type="date" value={start} onChange={e => onStart(e.target.value)} min="0001-01-02" max={newYorkToday()} required disabled={busy} /></div>
              <div className="gf-field"><label htmlFor="custom-end">End date</label><input id="custom-end" type="date" value={end} onChange={e => onEnd(e.target.value)} min={start || '0001-01-02'} max={newYorkToday()} required disabled={busy} /></div>
            </div>
            <p className="gf-help">Both dates are included. Up to {options?.max_calendar_days ?? 31} calendar days.</p>
            <div className="gf-fixed-fields"><div className="gf-field"><label htmlFor="custom-pair">Currency pair</label><input id="custom-pair" value="EUR/USD" readOnly /></div><div className="gf-field"><label htmlFor="custom-timeframe">Candle timeframe</label><input id="custom-timeframe" value="4 hours" readOnly /></div></div>
            <div className="gf-window"><span className="gf-window-label">FULL NEW YORK SESSIONS</span>
              <p>Each trading date covers 5 PM the previous day through 5 PM on that date. Weekends are skipped.</p>
              <p>The selected end date’s 5 PM cutoff must have passed. Missing weekday candles stop generation.</p></div>
          </section>
          <section className="gf-card cr-coverage" aria-live="polite"><h3>Your analysis window</h3>
            {details.error ? <p>{details.error}</p> : <><strong>{details.dates.length} trading sessions · {details.candleCount} candles</strong>
              <p>{formatDay(details.firstOpenDate)} at 5 PM<br />through {formatDay(details.lastCloseDate)} at 5 PM</p><p>America/New_York · Daylight saving time is handled automatically.</p></>}
          </section>
        </div>
        <div className="gf-main-column">
          <section className="gf-card"><header className="gf-card-header"><span className="gf-step">02</span><h3>Strategy analysis</h3></header>
            <div className="cr-strategy-label"><strong>Four-factor strategy v4</strong><span>Average across the entire range</span></div>
            <p className="gf-help">Every completed H4 candle has equal weight, out of 5 possible points. EMA20 vs SMA190 earns 1 point when its gap is 60 pips or less, and 2 when larger; equal values earn zero. The other factors earn up to 1 each. Momentum slowdown can reduce its point to 0.5.</p>
            <ul className="cr-factor-list"><li>Two closes vs EMA20</li><li>EMA20 vs SMA190</li><li>RSI14 · 40 / 60 thresholds</li><li>Momentum direction and pace</li></ul>
            {optionsError ? <p className="gf-error" role="alert">{optionsError} <button type="button" onClick={onRetry} disabled={busy}>Retry</button></p>
              : options ? <details className="cr-rules"><summary>View complete strategy rules</summary><p>{options.rule_set.rules}</p></details> : <p role="status">Loading strategy rules…</p>}
          </section>
          <section className="gf-card gf-notes"><header className="gf-card-header"><span className="gf-step">03</span><h3><label htmlFor="custom-notes">Your observations <span className="gf-optional">(optional)</span></label></h3></header>
            <p className="gf-help gf-intro">Add context or questions about the selected period.</p>
            <textarea id="custom-notes" rows={4} value={notes} onChange={e => onNotes(e.target.value)} maxLength={10000} disabled={busy} placeholder="What would you like to review across this date range?" />
            <div className="gf-field-footer"><span>Personal notes</span><span>{notes.length.toLocaleString()} / 10,000 characters</span></div>
          </section>
          <div className="gf-submit-area">{error && <div className="gf-error" role="alert"><strong>Could not generate custom journal</strong><p>{error}</p></div>}
            <div className="gf-submit-row"><p>Review your draft, then save it to<br />Saved custom journals.</p><button className="gf-primary" type="submit" disabled={busy || !options}>{loading ? 'Analyzing date range…' : 'Generate custom journal'}</button></div>
            {loading && <p className="gf-progress" role="status">Reviewing the full range. Longer ranges may take more time.</p>}
          </div>
        </div>
      </div>
    </form>
  </section>
}
