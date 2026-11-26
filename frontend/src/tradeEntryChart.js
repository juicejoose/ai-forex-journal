import { validChartContext } from './chartContext.js'
import { chartTime } from './marketChartData.js'

export const entryChartFields = {
  stopLoss: 'Initial stop', takeProfit: 'Initial target',
}

export function entryChartWindow(context, at) {
  const boundary = context?.before_at
  if (!validChartContext(context,boundary,boundary)) throw new Error('The entry chart data could not be validated.')
  const candles = [...context.preceding, ...context.following.map(row=>({...row,timeline_phase:'entry_chart'}))]
  if (!candles.length) throw new Error('No chart candles were available for that time.')
  const requested = chartTime(at || context.retrieved_at)
  const selected = candles.findLast(candle=>chartTime(candle.open_time) <= requested) ?? candles[0]
  return {snapshot:{analysis_kind:'trade_entry_chart', candles, as_of:context.retrieved_at}, selected:chartTime(selected.open_time)}
}

export function pickTradeField(field, price) {
  if (!Object.hasOwn(entryChartFields,field) || !Number.isFinite(price) || price <= 0 || price > 100 || Number(price.toFixed(5)) === 0) {
    throw new Error('Select a valid price in the price pane.')
  }
  return {[field]:price.toFixed(5)}
}
