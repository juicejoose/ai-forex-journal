"""Price-distance calculations for validated manual EUR/USD plans, never orders."""
from decimal import Decimal, localcontext, ROUND_HALF_UP

VERSION = "trade_plan_v1"
PIP = Decimal("0.0001")
ASSUMPTIONS = (
    "Planned price distances only. No position size or monetary risk is calculated. "
    "Spread, commission, financing and slippage are not included. "
    "These levels are not executed prices or guaranteed fills. "
    "No minimum reward-to-risk rule is configured; the ratio adds no strategy points."
)


def calculate_trade_plan(plan, direction, zones):
    if plan is None:
        return None
    with localcontext() as context:
        context.prec = 28
        risk = abs(plan.entry_price-plan.stop_loss) / PIP
        reward = abs(plan.take_profit-plan.entry_price) / PIP
        ratio = reward/risk
        ratio_display = "<0.01" if ratio < Decimal("0.01") else str(ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def position(value, zone):
        return "below" if value < Decimal(zone["lower"]) else "above" if value > Decimal(zone["upper"]) else "inside"

    return {"version": VERSION, "instrument": "EUR_USD", "direction": direction,
        "source": "user_entered_planned_levels", "pip_size": str(PIP),
        "entry_price": f"{plan.entry_price:.5f}", "stop_loss": f"{plan.stop_loss:.5f}",
        "take_profit": f"{plan.take_profit:.5f}", "risk_pips": f"{risk:.1f}",
        "reward_pips": f"{reward:.1f}", "reward_to_risk": str(ratio),
        "reward_to_risk_display": ratio_display, "assumptions": ASSUMPTIONS,
        "minimum_reward_to_risk": None,
        "zone_positions": [{"zone_id": zone["id"], "label": zone["label"], "kind": zone["kind"],
            "entry_position": position(plan.entry_price, zone),
            "stop_position": position(plan.stop_loss, zone),
            "target_position": position(plan.take_profit, zone)} for zone in zones]}


def trade_plan_description(plan):
    text = (f"User's planned {plan['direction']} trade: entry {plan['entry_price']}, stop loss {plan['stop_loss']}, "
            f"take profit {plan['take_profit']}. Planned risk distance {plan['risk_pips']} pips; potential reward distance "
            f"{plan['reward_pips']} pips; reward-to-risk {plan['reward_to_risk_display']}:1 before costs. "
            "The ratio is descriptive context, not a pass/fail rule or win probability.")
    for zone in plan["zone_positions"]:
        text += (f" Relative to {zone['label']}: planned entry {zone['entry_position']}, "
                 f"stop {zone['stop_position']}, target {zone['target_position']} the supplied {zone['kind']} zone.")
    return text
