export const relationLabels = { supporting: 'Supporting', conflicting: 'Conflicting', neutral: 'Neutral', unavailable: 'Unavailable', mixed: 'Mixed' }
export const pointText = value => Number.isFinite(value) ? value.toFixed(2) : 'Unavailable'
export const preferredAnalysis = record => record.strategy_analyses?.some(item => item.source === 'entry_time')
  ? 'entry_time' : record.context?.setup ? 'saved_setup' : 'entry_time'

export function evidenceAge(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return 'Unknown'
  if (seconds < 60) return 'Less than 1 minute'
  const minutes = Math.floor(seconds / 60), hours = Math.floor(minutes / 60), days = Math.floor(hours / 24)
  return days ? `${days}d ${hours % 24}h` : hours ? `${hours}h ${minutes % 60}m` : `${minutes}m`
}

export function scopeLabel(analysis) {
  if (analysis.summary.method === 'final_candle') return 'Saved final-candle summary'
  if (analysis.coverage.earlier_session) return 'Earlier-session average'
  return analysis.coverage.session_complete ? 'Session average' : 'Session-to-cutoff average'
}
