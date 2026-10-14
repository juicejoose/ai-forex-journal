import { useState } from 'react'

function App() {
  const [pair, setPair] = useState('EURUSD')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const [preview, setPreview] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setPreview(null)
    const trimmedPair = pair.trim()
    const trimmedNotes = notes.trim()

    if (!trimmedPair) {
      setError('Please enter a currency pair.')
      return
    }

    if (!trimmedNotes) {
      setError('Please enter your market observations.')
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
          <p>Observations: {preview.notes}</p>
        </section>
      )}
    </main>
  )
}

export default App