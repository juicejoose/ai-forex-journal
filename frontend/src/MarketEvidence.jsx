const newYorkTime = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric', month: 'short', day: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
})

const newYorkClock = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: 'numeric', minute: '2-digit', hour12: true,
})

const newYorkDate = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric', month: 'short', day: 'numeric',
})

function timestamp(value, formatter = newYorkTime) {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Unavailable' : formatter.format(parsed)
}

function dateRange(openTime, closeTime) {
  const start = timestamp(openTime, newYorkDate)
  const end = timestamp(closeTime, newYorkDate)
  return start === end ? start : `${start} - ${end}`
}

function number(value, digits = 5) {
  return Number.isFinite(value) ? value.toFixed(digits) : 'Unavailable'
}

function candleChange(open, close) {
  if (!Number.isFinite(open) || !Number.isFinite(close) || open <= 0) {
    return 'Unavailable'
  }
  const change = ((close - open) / open) * 100
  if (!Number.isFinite(change)) return 'Unavailable'
  const rounded = Number(change.toFixed(2))
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(2)}%`
}

const cellStyle = { padding: '0.5rem', textAlign: 'left', whiteSpace: 'nowrap' }

export default function MarketEvidence({ snapshot }) {
  if (!snapshot) {
    return <p>No market snapshot was stored with this older journal.</p>
  }

  const { session, summary, candles, indicator_settings: settings } = snapshot

  return (
    <section aria-labelledby="evidence-heading" style={{ margin: '1rem 0' }}>
      <h3 id="evidence-heading">Market evidence</h3>
      <p>
        {snapshot.source} {snapshot.environment} · EUR/USD · 4-hour candles · Midpoint prices
      </p>
      <p>{timestamp(session.start)} → {timestamp(session.end)}</p>
      <p>
        {session.candle_count} completed candles · Price change:{' '}
        {summary.change_pips > 0 ? '+' : ''}{number(summary.change_pips, 1)} pips
        {' '}({number(summary.change_percent, 2)}%)
      </p>
      <p>
        Open {number(summary.open)} · High {number(summary.high)} · Low{' '}
        {number(summary.low)} · Close {number(summary.close)}
      </p>
      <details style={{ marginTop: '0.75rem' }}>
        <summary>View all six candles and indicators</summary>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <caption>
              Candle times in New York; indicators at candle close.
              Price change compares each candle’s open and close.
            </caption>
            <thead>
              <tr>
                {['Time range', 'Open', 'Close', 'Change (%)', 'EMA20', 'SMA190', 'RSI14', 'Squeeze', 'Momentum', 'Histogram', 'Released'].map((label) => (
                  <th key={label} scope="col" style={cellStyle}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {candles.map((candle) => (
                <tr key={candle.open_time}>
                  <th scope="row" style={cellStyle}>
                    <div>
                      {timestamp(candle.open_time, newYorkClock)} - {timestamp(candle.close_time, newYorkClock)}
                    </div>
                    <small style={{ fontWeight: 'normal' }}>
                      {dateRange(candle.open_time, candle.close_time)}
                    </small>
                  </th>
                  <td style={cellStyle}>{number(candle.open)}</td>
                  <td style={cellStyle}>{number(candle.close)}</td>
                  <td style={cellStyle}>{candleChange(candle.open, candle.close)}</td>
                  <td style={cellStyle}>{number(candle.indicators.ema20)}</td>
                  <td style={cellStyle}>{number(candle.indicators.sma190)}</td>
                  <td style={cellStyle}>{number(candle.indicators.rsi14, 2)}</td>
                  <td style={cellStyle}>{candle.indicators.squeeze.state}</td>
                  <td style={cellStyle}>{number(candle.indicators.squeeze.momentum, 5)}</td>
                  <td style={cellStyle}>{candle.indicators.squeeze.histogram_color}</td>
                  <td style={cellStyle}>
                    {candle.indicators.squeeze.released === null
                      ? 'Unavailable' : candle.indicators.squeeze.released ? 'Yes' : 'No'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Calculated from closing prices: EMA {settings.ema.period},{' '}
          SMA {settings.sma.period}, Wilder RSI {settings.rsi.period}.
          {' '}LazyBear Squeeze: BB {settings.squeeze.bb_period} × {settings.squeeze.bb_multiplier},
          {' '}KC {settings.squeeze.kc_period} × {settings.squeeze.kc_multiplier}.
          {' '}True range: {settings.squeeze.use_true_range ? 'on' : 'off'}.
        </p>
        <p>
          Squeeze ON means compression. A green histogram has positive momentum
          that is not increasing; it does not by itself indicate a release.
        </p>
        <p>
          Retrieved {timestamp(snapshot.retrieved_at)}. Saving keeps these exact values
          with the journal; reopening it does not fetch new market data.
        </p>
      </details>
    </section>
  )
}
