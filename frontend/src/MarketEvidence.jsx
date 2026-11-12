import { changeTone, formatChange } from './journalCalendar.js'

const newYorkTime = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', year: 'numeric', month: 'short', day: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
})
const newYorkClock = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', hour12: true,
})
const newYorkDate = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', year: 'numeric', month: 'short', day: 'numeric',
})
function timestamp(value, formatter = newYorkTime) {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Unavailable' : formatter.format(parsed)
}
function dateRange(openTime, closeTime) {
  const start = timestamp(openTime, newYorkDate)
  const end = timestamp(closeTime, newYorkDate)
  return start === end ? start : `${start} – ${end}`
}
function number(value, digits = 5) {
  return Number.isFinite(value) ? value.toFixed(digits) : 'Unavailable'
}
function change(open, close) {
  if (!Number.isFinite(open) || !Number.isFinite(close) || open <= 0) return null
  const result = (close - open) / open * 100
  return Number.isFinite(result) ? result : null
}

export default function MarketEvidence({ snapshot }) {
  if (!snapshot) return <div className="jv-legacy"><h3>Market evidence</h3><p>No market snapshot was stored with this older journal. Its text is available below.</p></div>

  const { session = {}, summary = {}, indicator_settings: settings = {} } = snapshot
  const candles = Array.isArray(snapshot.candles) ? snapshot.candles : []
  const hasRsiMa = Boolean(settings.rsi_ma) || candles.some((candle) => Object.hasOwn(candle.indicators ?? {}, 'rsi14_sma14'))
  const customRange = snapshot.analysis_kind === 'custom_range'
  const partial = snapshot.analysis_kind === 'intraday' && !session.complete
  const sessionChange = change(summary.open, summary.close)
  const pips = Number.isFinite(sessionChange) ? (summary.close - summary.open) * 10000 : null

  return <section className={`jv-market${customRange ? ' jv-market-range' : ''}`} aria-label="Market evidence">
    <div className="jv-price-strip">
      <div className={`jv-return jv-tone-${changeTone(sessionChange)}`}>
        <span>{partial ? 'Session so far' : customRange ? 'Range change' : 'Session change'}</span><strong>{formatChange(sessionChange)}</strong>
        <span>{pips > 0 ? '+' : ''}{number(pips, 1)} pips</span>
      </div>
      <dl className="jv-ohlc">
        {['open', 'high', 'low', 'close'].map((key) => <div key={key}><dt>{key}</dt><dd>{number(summary[key])}</dd></div>)}
      </dl>
    </div>
    <details className="jv-candles">
      <summary><span>Market details & candles</span><span className="jv-summary-hint">{session.candle_count ?? candles.length} completed</span></summary>
      <header className="jv-market-header">
        <h3>Market evidence</h3>
        <p>{snapshot.source} · {snapshot.environment} · Midpoint prices</p>
      </header>
      <p className="jv-session-window">{timestamp(session.start)} <span aria-hidden="true">→</span><span className="jv-sr-only"> through </span> {timestamp(session.end)}</p>
      {customRange && <p className="jv-range-coverage">{snapshot.range.trading_day_count} trading sessions · {candles.length} completed H4 candles · Weekend sessions excluded</p>}
      {partial && <p className="jv-range-coverage">Session in progress · {candles.length} of 6 completed · Data through {timestamp(snapshot.data_through)}. Prices and indicators exclude the forming candle.</p>}
      <div className="jv-table-scroll" role="region" aria-label="Candle prices and indicators" tabIndex={0}>
        <table>
          <caption>New York time · Indicators at candle close · Change compares each candle’s open and close.</caption>
          <thead><tr>{['Time range', 'Open', 'Close', 'Change (%)', 'EMA20', 'SMA190', 'RSI14', ...(hasRsiMa ? ['RSI-based MA (SMA14)'] : []), 'Squeeze', 'Momentum', 'Histogram', 'Released'].map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{candles.map((candle) => {
            const indicators = candle.indicators ?? {}
            const squeeze = indicators.squeeze ?? {}
            const candleChange = change(candle.open, candle.close)
            return <tr key={candle.open_time}>
              <th scope="row"><span>{timestamp(candle.open_time, newYorkClock)} – {timestamp(candle.close_time, newYorkClock)}</span><small>{dateRange(candle.open_time, candle.close_time)}</small></th>
              <td>{number(candle.open)}</td><td>{number(candle.close)}</td>
              <td className={`jv-tone-${changeTone(candleChange)}`}>{formatChange(candleChange)}</td>
              <td>{number(indicators.ema20)}</td><td>{number(indicators.sma190)}</td><td>{number(indicators.rsi14, 2)}</td>
              {hasRsiMa && <td>{number(indicators.rsi14_sma14, 2)}</td>}
              <td><span className="jv-table-badge">{squeeze.state ?? 'Unavailable'}</span></td>
              <td>{number(squeeze.momentum, 5)}</td><td>{squeeze.histogram_color ?? 'Unavailable'}</td>
              <td>{typeof squeeze.released === 'boolean' ? squeeze.released ? 'Yes' : 'No' : 'Unavailable'}</td>
            </tr>
          })}</tbody>
        </table>
      </div>
      <div className="jv-evidence-notes">
        <p>Closing-price indicators: EMA {settings.ema?.period ?? '—'} · SMA {settings.sma?.period ?? '—'} · Wilder RSI {settings.rsi?.period ?? '—'}. LazyBear Squeeze: BB {settings.squeeze?.bb_period ?? '—'} × {settings.squeeze?.bb_multiplier ?? '—'}, KC {settings.squeeze?.kc_period ?? '—'} × {settings.squeeze?.kc_multiplier ?? '—'}. True range: {typeof settings.squeeze?.use_true_range === 'boolean' ? settings.squeeze.use_true_range ? 'on' : 'off' : 'unavailable'}.</p>
        {hasRsiMa && <p>RSI-based MA is the SMA of the latest 14 RSI14 readings. Strategies v6 and later use this smoothed value for thresholds and trend; raw RSI14 remains separate context.</p>}
        <p>Squeeze ON means compression. A green histogram has positive momentum that is not increasing; it does not by itself indicate a release.</p>
        <p>Retrieved {timestamp(snapshot.retrieved_at)}. Saving keeps these exact values with the journal; reopening it does not fetch new market data.</p>
      </div>
    </details>
  </section>
}
