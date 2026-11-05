import './GenerateJournalForm.css'
import RuleSetSelect from './RuleSetSelect.jsx'

function Arrow() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

export default function GenerateJournalForm({ pair, journalDate, timeframe, strategy, notes,
  loadedProfile, busy, loading, error, onDateChange, onStrategyChange, onNotesChange,
  onChooseProfile, onSubmit, ruleSetId, ruleDefinition, ruleDefinitions, ruleError, onRetryRules, onRuleSetChange }) {
  const customized = !ruleSetId && loadedProfile && strategy.trim() !== loadedProfile.rules.trim()

  return <section className="generate-form" aria-labelledby="generate-heading">
    <header className="gf-heading">
      <p className="gf-eyebrow">NEW ENTRY</p>
      <h2 id="generate-heading">Generate journal</h2>
      <p>Choose a session and the strategy you want to review.</p>
    </header>
    <form onSubmit={onSubmit} noValidate aria-busy={loading}>
      <div className="gf-layout">
        <div className="gf-session-column">
          <section className="gf-card gf-session" aria-labelledby="session-heading">
            <header className="gf-card-header"><span className="gf-step" aria-hidden="true">01</span><h3 id="session-heading">Session details</h3></header>
            <div className="gf-field">
              <label htmlFor="journal-date">Journal date <span className="gf-required" aria-hidden="true">Required</span></label>
              <input id="journal-date" type="date" value={journalDate} onChange={(event) => onDateChange(event.target.value)} disabled={busy} aria-required="true" aria-describedby="session-help" />
              <p id="session-help" className="gf-help">Choose a completed weekday session.</p>
            </div>
            <div className="gf-fixed-fields">
              <div className="gf-field"><label htmlFor="pair">Currency pair</label><input id="pair" type="text" value={pair} readOnly /></div>
              <div className="gf-field"><label htmlFor="timeframe">Candle timeframe</label><select id="timeframe" value={timeframe} disabled><option value="4h">4 hours</option></select></div>
            </div>
            <div className="gf-window">
              <span className="gf-window-label"><svg width="15" height="15" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.4" /><path d="M10 6v4l3 2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>New York session</span>
              <div className="gf-window-times"><div><strong>5:00 PM</strong><span>Previous day</span></div><Arrow /><div><strong>5:00 PM</strong><span>Selected date</span></div></div>
              <p>America/New_York · Daylight saving time is handled automatically.</p>
            </div>
          </section>
          <aside className="gf-included" aria-labelledby="included-heading">
            <h3 id="included-heading">Included in the review</h3>
            <p>Six completed 4-hour candles, with:</p>
            <ul><li>RSI 14 + SMA 14 smoothing</li><li>EMA 20</li><li>SMA 190</li><li>Squeeze Momentum</li></ul>
          </aside>
        </div>
        <div className="gf-main-column">
          <section className="gf-card" aria-labelledby="strategy-heading">
            <header className="gf-card-header gf-strategy-header">
              <span className="gf-step" aria-hidden="true">02</span><h3 id="strategy-heading"><label htmlFor="strategy">Strategy rules</label></h3>
              <button className="gf-secondary" type="button" onClick={onChooseProfile} disabled={busy}>Saved strategies <Arrow /></button>
            </header>
            <RuleSetSelect id="generation-rule-set" value={ruleSetId} onChange={onRuleSetChange} definitions={ruleDefinitions} error={ruleError} onRetry={onRetryRules} disabled={busy} />
            <p id="strategy-help" className="gf-help gf-intro">{ruleSetId ? 'The saved rule definitions below are fixed for this version. Add session-specific context in Your observations.' : 'Describe your bullish and bearish conditions, including any thresholds or timing that matter.'}</p>
            {loadedProfile && <div className="gf-profile" role="status" id="loaded-profile-help">
              <p><span>Loaded profile</span><strong>{loadedProfile.name}</strong>{customized && <span className="gf-customized">Customized for this journal</span>}</p>
              <p>{ruleSetId ? 'This profile uses the fixed four-factor scoring rules.' : 'Changes here apply to this journal. Save profile edits in the Strategy profiles tab.'}</p>
            </div>}
            <textarea id="strategy" rows={8} value={strategy} onChange={(event) => onStrategyChange(event.target.value)} readOnly={Boolean(ruleSetId)} disabled={busy} maxLength={10000} aria-required="true" aria-describedby={loadedProfile ? 'strategy-help loaded-profile-help strategy-count' : 'strategy-help strategy-count'} placeholder={'Bullish factors:\nDescribe the conditions you want checked.\n\nBearish factors:\nDescribe the conditions you want checked.'} />
            <div className="gf-field-footer"><span>{ruleSetId ? `Fixed rules · Version ${ruleDefinition?.version ?? '…'}` : 'Required'}</span><span id="strategy-count">{strategy.length.toLocaleString()} / 10,000 characters</span></div>
          </section>
          <section className="gf-card gf-notes" aria-labelledby="notes-heading">
            <header className="gf-card-header"><span className="gf-step" aria-hidden="true">03</span><h3 id="notes-heading"><label htmlFor="notes">Your observations <span className="gf-optional">(optional)</span></label></h3></header>
            <p id="notes-help" className="gf-help gf-intro">Add your own context or questions for this session.</p>
            <textarea id="notes" rows={4} value={notes} onChange={(event) => onNotesChange(event.target.value)} disabled={busy} maxLength={10000} aria-describedby="notes-help notes-count" placeholder="What stood out to you? What would you like to review?" />
            <div className="gf-field-footer"><span>Personal notes</span><span id="notes-count">{notes.length.toLocaleString()} / 10,000 characters</span></div>
          </section>
          <div className="gf-submit-area">
            {error && <div className="gf-error" role="alert"><strong>Could not generate journal</strong><p>{error}</p></div>}
            <div className="gf-submit-row">
              <p>Review and edit your draft<br />before saving it to your journal.</p>
              <button className="gf-primary" type="submit" disabled={busy || Boolean(ruleSetId && !ruleDefinition)}>{loading ? <><span className="gf-spinner" aria-hidden="true" />Generating journal…</> : <>Generate journal <Arrow /></>}</button>
            </div>
            {loading && <p className="gf-progress" role="status">Preparing your journal. This may take a moment.</p>}
          </div>
        </div>
      </div>
    </form>
  </section>
}
