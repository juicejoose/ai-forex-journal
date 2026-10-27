import { useEffect, useState } from 'react'

const PAGE_SIZE = 20

export default function JournalHistory({ onOpen, onDelete, deletingId, busy }) {
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [page, setPage] = useState(null)
  const [error, setError] = useState('')
  const loading = page === null && !error

  useEffect(() => {
    const controller = new AbortController()

    async function loadHistory() {
      try {
        const response = await fetch(
          `http://127.0.0.1:8000/journals?limit=${PAGE_SIZE}&offset=${offset}`,
          { signal: controller.signal }
        )
        const data = await response.json().catch(() => null)

        if (!response.ok) {
          throw new Error('Could not load journal history. Please try again.')
        }

        if (
          !Array.isArray(data?.items) ||
          !Number.isInteger(data.total) ||
          !data.items.every((item) =>
            Number.isInteger(item?.id) &&
            ['pair', 'journal_date', 'timeframe'].every(
              (field) => typeof item[field] === 'string'
            )
          )
        ) {
          throw new Error('The server returned an invalid journal list.')
        }

        if (!controller.signal.aborted) setPage(data)
      } catch (err) {
        if (!controller.signal.aborted) setError(err.message)
      }
    }

    loadHistory()
    return () => controller.abort()
  }, [offset, reload])

  function loadPage(nextOffset) {
    setPage(null)
    setError('')
    setOffset(nextOffset)
    setReload((value) => value + 1)
  }

  return (
    <section aria-labelledby="history-heading">
      <h2 id="history-heading">Saved journals</h2>

      <button
        type="button"
        onClick={() => loadPage(0)}
        disabled={busy || loading}
      >
        Refresh history
      </button>

      {loading && <p role="status">Loading history...</p>}
      {error && <p role="alert">{error}</p>}

      {page && (
        <>
          <p>{page.total} saved journals</p>

          {page.items.length === 0 ? (
            <p>{page.total === 0 ? 'No saved journals yet.' : 'No journals on this page.'}</p>
          ) : (
            <ul>
              {page.items.map((journal) => (
                <li key={journal.id}>
                  <button
                    type="button"
                    onClick={() => onOpen(journal.id)}
                    disabled={busy}
                  >
                    {journal.journal_date} — {journal.pair} ({journal.timeframe})
                    {' '}· #{journal.id}
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(journal)}
                    disabled={busy}
                    aria-label={`Delete journal #${journal.id} from ${journal.journal_date}`}
                    style={{ marginLeft: '0.5rem' }}
                  >
                    {deletingId === journal.id ? 'Deleting...' : 'Delete'}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            onClick={() => loadPage(Math.max(0, offset - PAGE_SIZE))}
            disabled={busy || offset === 0}
          >
            Previous
          </button>

          <button
            type="button"
            onClick={() => loadPage(offset + PAGE_SIZE)}
            disabled={busy || offset + PAGE_SIZE >= page.total}
          >
            Next
          </button>
        </>
      )}
    </section>
  )
}
