export function validTodayView(view) {
  const count = view?.session?.candle_count
  if (view?.schema_version !== 1 || !Number.isInteger(count) || count < 0 || count > 6 ||
      !Number.isFinite(Date.parse(view.as_of)) || !Array.isArray(view.slots) || view.slots.length !== 6 ||
      view.session.complete !== (count === 6) || view.session.expected_candle_count !== 6) return false
  if (count === 0) return view.market_data === null && view.rule_evaluation === null && view.snapshot_id === null
  return typeof view.snapshot_id === 'string' && validTodayEvidence(view.market_data, view.rule_evaluation) &&
    view.market_data.candles.length === count && view.market_data.journal_date === view.journal_date
}

export function validTodayEvidence(snapshot, evaluation) {
  const count = snapshot?.candles?.length
  return snapshot?.analysis_kind === 'intraday' && Number.isInteger(count) && count >= 1 && count <= 6 &&
    snapshot.session?.complete === (count === 6) && snapshot.session?.candle_count === count &&
    typeof snapshot.data_key === 'string' && Number.isFinite(Date.parse(snapshot.data_through)) &&
    evaluation?.analysis_kind === 'intraday' && evaluation.candles?.length === count &&
    evaluation.rule_set?.id === 'four_factor_v4' && evaluation.summary?.method === (count === 6 ? 'session_average' : 'session_to_date')
}

export function summaryIsBehind(preview, view) {
  return Boolean(preview && view && preview.market_data?.data_key !== view.market_data?.data_key)
}

export function freshTodayView(view, now = Date.now()) {
  const age = now - Date.parse(view?.as_of)
  return Number.isFinite(age) && age >= -5000 && age < 120000
}
