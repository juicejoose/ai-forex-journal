const sectionTitles = new Set([
  '1. Market summary',
  '2. Bullish factors',
  '3. Bearish factors',
  '4. Signal agreement and conflict',
  '5. Trade concerns',
  '6. Overall directional bias',
  'Candle evidence — New York time; indicators at candle close',
])

// Presentation only: the original text remains the editor/save source of truth.
// Unknown formats stay readable as plain text; no HTML or links are executed.
export function journalSections(text) {
  const sections = []
  let current = { title: '', lines: [] }
  function finish() {
    const body = current.lines.join('\n')
    if (current.title || body.trim()) sections.push({ title: current.title, body })
  }
  for (const line of text.replace(/\r\n?/g, '\n').split('\n')) {
    const trimmed = line.trim()
    const markdown = /^#{1,6}\s+(.+)$/.exec(trimmed)
    if (sectionTitles.has(trimmed) || markdown) {
      finish()
      current = { title: markdown ? markdown[1] : trimmed, lines: [] }
    } else {
      current.lines.push(line)
    }
  }
  finish()
  return sections
}
