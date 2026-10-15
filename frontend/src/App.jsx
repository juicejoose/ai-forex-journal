import { useState } from 'react'

function App() {
  const [pair, setPair] = useState('EURUSD')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [journalDate, setJournalDate] = useState('')
  const [timeframe, setTimeframe] = useState('1h')
  const [strategy, setStrategy] = useState('')

  const [preview, setPreview] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setPreview(null)
    const trimmedPair = pair.trim()
    const trimmedNotes = notes.trim()
    const trimmedStrategy = strategy.trim()

    if (!trimmedPair) {
      setError('Please enter a currency pair.')
      return
    }

    if (!trimmedNotes) {
      setError('Please enter your market observations.')
      return
    }

    if (!journalDate) {
      setError('Please choose a journal date.')
      return
    }

    if (!trimmedStrategy) {
      setError('Please enter your strategy rules.')
      return
    }

    setLoading(true)

    try {
      const response = await fetch(
        'http://127.0.0.1:8000/journal/preview',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            pair: trimmedPair,
            journal_date: journalDate,
            timeframe,
            strategy: trimmedStrategy,
            notes: trimmedNotes,
          }),
        }
      )

      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`)
      }

      const data = await response.json()
      setPreview(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main>
      <h1>Forex AI Journal</h1>
      <p>Turn your market observations into journal entries.</p>

      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="pair">Currency pair</label>
          <input
            id="pair"
            type="text"
            value={pair}
            onChange={(event) => setPair(event.target.value)}
          />
        </div>

        <div>
          <label htmlFor="journal-date">Journal date</label>
          <input
            id="journal-date"
            type="date"
            value={journalDate}
            onChange={(event) => setJournalDate(event.target.value)}
          />
        </div>

        <div>
          <label htmlFor="timeframe">Candle timeframe</label>
          <select
            id="timeframe"
            value={timeframe}
            onChange={(event) => setTimeframe(event.target.value)}
          >
            <option value="15m">15 minutes</option>
            <option value="1h">1 hour</option>
            <option value="4h">4 hours</option>
            <option value="1d">1 day</option>
          </select>
        </div>

        <div>
          <label htmlFor="strategy">Strategy rules</label>
          <textarea
            id="strategy"
            rows={5}
            value={strategy}
            onChange={(event) => setStrategy(event.target.value)}
          />
        </div>

        <div>
          <label htmlFor="notes">Market observations</label>
          <textarea
            id="notes"
            rows={5}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
        </div>

        <button type="submit" disabled={loading}>
          {loading ? 'Loading...' : 'Preview entry'}
        </button>

      </form>

      {error && <p role="alert">{error}</p>}

      {preview && (
        <section>
          <h2>Entry preview</h2>
          <p>Currency pair: {preview.pair}</p>
          <p>Journal date: {preview.journal_date}</p>
          <p>Candle timeframe: {preview.timeframe}</p>
          <p>Strategy rules: {preview.strategy}</p>
          <p>Observations: {preview.notes}</p>
        </section>
      )}
    </main>
  )
}

export default App