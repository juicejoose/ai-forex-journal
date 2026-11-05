export const paceLabels = { slowing: 'Slowing', accelerating: 'Accelerating', steady: 'Steady pace', transition: 'Zero-crossing reset', new_move: 'New directional move', not_directional: 'No directional point', unavailable: 'Insufficient history' }

export function factorDescription(factor) {
  if (factor.outcome === 'unavailable') return 'Insufficient data'
  if (factor.factor_id === 'rsi_extreme' && factor.rsi_signal) {
    if (factor.rsi_signal.source === 'rsi14_sma14') {
      if (factor.rsi_signal.reduced && factor.rsi_signal.basis === 'rising') return 'RSI MA rising · near overbought'
      if (factor.rsi_signal.reduced && factor.rsi_signal.basis === 'falling') return 'RSI MA falling · near oversold'
      return ({ oversold: 'Oversold MA · threshold', overbought: 'Overbought MA · threshold',
        rising: 'RSI MA rising', falling: 'RSI MA falling', mixed_or_flat: 'Mixed or flat RSI MA' })[factor.rsi_signal.basis] || 'Review evidence'
    }
    return ({ oversold: 'Oversold · threshold', overbought: 'Overbought · threshold',
      rising: 'RSI rising', falling: 'RSI falling', mixed_or_flat: 'Mixed or flat RSI' })[factor.rsi_signal.basis] || 'Review evidence'
  }
  if (factor.factor_id === 'momentum' && factor.momentum_change) {
    const pace = paceLabels[factor.momentum_change.pace] || 'Review evidence'
    const movement = ({ rising: 'Rising', falling: 'Falling', unchanged: 'Unchanged' })[factor.momentum_change.movement]
    if (movement === 'Unchanged') return movement
    return movement ? `${movement} · ${pace.toLowerCase()}` : pace
  }
  if (factor.factor_id === 'ema_sma' && factor.ema_sma_distance && ['bullish', 'bearish'].includes(factor.outcome)) {
    return `${factor.outcome === 'bullish' ? 'Above' : 'Below'} SMA190 · ${factor.ema_sma_distance.reduced ? 'within 60 pips' : 'gap > 60 pips'}`
  }
  const descriptions = {
    two_closes_ema: { bullish: 'Both above EMA20', bearish: 'Both below EMA20', neutral: 'Mixed or at EMA20' },
    ema_sma: { bullish: 'EMA20 above SMA190', bearish: 'EMA20 below SMA190', neutral: 'EMA20 equals SMA190' },
    rsi_extreme: { bullish: 'Oversold', bearish: 'Overbought', neutral: 'Between thresholds' },
    momentum: { bullish: 'Positive and rising', bearish: 'Negative and falling', neutral: 'Sign / change not met' },
  }
  return descriptions[factor.factor_id]?.[factor.outcome] || 'Review evidence'
}
