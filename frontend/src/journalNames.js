export const JOURNAL_NAME_LIMIT = 120

export function journalName(journal, customRange = false) {
  return journal?.title?.trim() || `${customRange ? 'Custom journal' : 'Journal'} #${journal.id}`
}

export function journalEditsSaved(saved, text, title) {
  return saved !== null && text.trim() === saved.edited_draft && title.trim() === (saved.title ?? '')
}
