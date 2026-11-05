export const CURRENT_RULE_SET_ID = 'four_factor_v7'
export const STRATEGY_CHOICES = [
  { value: CURRENT_RULE_SET_ID, label: 'Four-factor strategy v7 · Session average' },
  { value: '', label: 'Written strategy · AI review' },
]

export function isRetiredRuleSet(value) {
  return Boolean(value) && value !== CURRENT_RULE_SET_ID
}
