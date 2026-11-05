"""Versioned, deterministic strategy evaluation. No provider or AI calls."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from math import isclose, isfinite
from typing import Literal

from journal_grounding import InvalidJournalEvidence, NY, _utc, build_evidence_catalog


RULE_SET_ID = "four_factor_v7"
RSI_MA_RULE_SET_ID = "four_factor_v6"
RSI_MA_RULE_SET_IDS = (RULE_SET_ID, RSI_MA_RULE_SET_ID)
TREND_RULE_SET_ID = "four_factor_v5"
SESSION_RULE_SET_ID = "four_factor_v4"
SESSION_RULE_SET_IDS = (*RSI_MA_RULE_SET_IDS, TREND_RULE_SET_ID, SESSION_RULE_SET_ID)
MOMENTUM_RULE_SET_ID = "four_factor_v3"
WEIGHTED_RULE_SET_ID = "four_factor_v2"
LEGACY_RULE_SET_ID = "four_factor_v1"
SUPPORTED_RULE_SET_IDS = (*SESSION_RULE_SET_IDS, MOMENTUM_RULE_SET_ID, WEIGHTED_RULE_SET_ID, LEGACY_RULE_SET_ID)
ACTIVE_RULE_SET_IDS = (RULE_SET_ID,)
RuleSetId = Literal["four_factor_v1", "four_factor_v2", "four_factor_v3", "four_factor_v4", "four_factor_v5", "four_factor_v6", "four_factor_v7"]
DELTA_REL_TOL = 1e-9
DELTA_ABS_TOL = 1e-12
LEGACY_FACTORS = (
    {"id": "two_closes_ema", "name": "Two closes vs EMA20", "points": 1,
     "bullish": "The current and previous completed trading candles each close above their own EMA20.",
     "bearish": "The current and previous completed trading candles each close below their own EMA20."},
    {"id": "ema_sma", "name": "EMA20 vs SMA190", "points": 1,
     "bullish": "EMA20 is strictly above SMA190.", "bearish": "EMA20 is strictly below SMA190."},
    {"id": "rsi_extreme", "name": "RSI14 extremes", "points": 1,
     "bullish": "RSI14 is at or below 30.", "bearish": "RSI14 is at or above 70."},
    {"id": "momentum", "name": "Momentum sign and change", "points": 1,
     "bullish": "Squeeze Momentum is strictly positive and higher than on the previous completed trading candle.",
     "bearish": "Squeeze Momentum is strictly negative and lower than on the previous completed trading candle."},
)
LEGACY_RULES_TEXT = "\n\n".join(
    f"{f['name']} — 1 point. Bullish: {f['bullish']} Bearish: {f['bearish']}" for f in LEGACY_FACTORS
) + (
    "\n\nEvaluate each completed H4 candle. Each factor earns at most one directional point per candle. "
    "Equal values and unmet conditions earn neither side a point. Missing inputs are unavailable. "
    "Use the final candle for session-end bias. Alignment percentages use four possible points; "
    "they are not probabilities of future price movement. The momentum near-zero rule is excluded."
)


WEIGHTED_FACTORS = deepcopy(LEGACY_FACTORS)
WEIGHTED_FACTORS[1]["points"] = 2
WEIGHTED_FACTORS[2].update(
    bullish="RSI14 is at or below 40 (the strategy's oversold threshold).",
    bearish="RSI14 is at or above 60 (the strategy's overbought threshold).",
)
WEIGHTED_RULES_TEXT = "\n\n".join(
    f"{f['name']} — {f['points']} {'point' if f['points'] == 1 else 'points'}. "
    f"Bullish: {f['bullish']} Bearish: {f['bearish']}" for f in WEIGHTED_FACTORS
) + (
    "\n\nEvaluate each completed H4 candle. Each factor awards its full weight to at most one side per candle. "
    "EMA20 vs SMA190 is worth two points; the other three factors are worth one point each. "
    "Equal values and unmet conditions earn neither side a point. Missing inputs are unavailable. "
    "Use the final candle for session-end bias. Alignment percentages use five possible points; "
    "they are not probabilities of future price movement. The momentum near-zero rule is excluded."
)


FACTORS = deepcopy(WEIGHTED_FACTORS)
FACTORS[3].update(
    name="Momentum direction and pace",
    bullish="Positive and rising momentum earns 1 bullish point; reduce to 0.5 when all three consecutive momentum values are positive and the latest positive delta is smaller than the preceding positive delta.",
    bearish="Negative and falling momentum earns 1 bearish point; reduce to 0.5 when all three consecutive momentum values are negative and the latest negative delta is smaller in magnitude than the preceding negative delta.",
    slowdown={"lookback_candles": 3, "reduced_points": 0.5, "reset_at_zero": True,
              "delta_relative_tolerance": DELTA_REL_TOL, "delta_absolute_tolerance": DELTA_ABS_TOL},
)
MOMENTUM_RULES_TEXT = "\n\n".join(
    f"{f['name']} — up to {f['points']} {'point' if f['points'] == 1 else 'points'}. "
    f"Bullish: {f['bullish']} Bearish: {f['bearish']}" for f in FACTORS
) + (
    "\n\nEvaluate each completed H4 candle using only current and earlier data. "
    "EMA20 vs SMA190 is worth two points; each other factor is worth at most one. "
    "Momentum delta is current minus previous momentum. Compare the two deltas from three consecutive trading candles. "
    "Missing three-candle history makes the momentum factor unavailable. A zero touch or crossing resets the pace comparison; "
    "the base positive/rising or negative/falling condition can still earn one point. "
    "Equal delta magnitudes mean steady pace, not slowing. Delta magnitudes within relative tolerance 1e-9 or absolute "
    "tolerance 1e-12 are treated as equal to avoid floating-point artifacts. There is no additional market-noise filter. "
    "Unmet directional conditions earn neither side a point. Slowing never awards an opposite-side point. "
    "Use the final candle for session-end bias. Alignment percentages use five possible points and are not probabilities "
    "of future price movement. The momentum near-zero rule is excluded."
)

RULES_TEXT = MOMENTUM_RULES_TEXT.replace(
    "Use the final candle for session-end bias.",
    "For the session summary, average bullish and bearish points separately across all six completed H4 candles, "
    "giving every candle equal weight. The maximum average is five points. Net score is average bullish minus "
    "average bearish points. The larger average sets the session bias; equal nonzero averages are mixed and "
    "zero averages are neutral. Keep the final candle's bias separately as session-end context. "
    "All twenty-four factor checks must be available; otherwise withhold the session averages, alignment "
    "percentages, net score and directional bias. Never treat missing inputs as zero or average fewer candles. "
    "Store unrounded results and display session averages to two decimal places."
)

# Keep v3 definitions unchanged. Revision 2 is saved with every new v4 result;
# historical v4 evaluations without a revision retain their stored scores.
V4_FACTORS = deepcopy(FACTORS)
V4_FACTORS[1].update(
    bullish="EMA20 is strictly above SMA190. Award 1 bullish point when their absolute gap is at most 60 pips, including exactly 60; otherwise award 2.",
    bearish="EMA20 is strictly below SMA190. Award 1 bearish point when their absolute gap is at most 60 pips, including exactly 60; otherwise award 2.",
    distance_weighting={"pip_size": 0.0001, "threshold_pips": 60, "threshold_inclusive": True,
                        "within_points": 1, "beyond_points": 2},
)
RULES_TEXT = RULES_TEXT.replace(
    f"Bullish: {FACTORS[1]['bullish']} Bearish: {FACTORS[1]['bearish']}",
    f"Bullish: {V4_FACTORS[1]['bullish']} Bearish: {V4_FACTORS[1]['bearish']}",
).replace("EMA20 vs SMA190 is worth two points; each other factor is worth at most one.",
    "EMA20 vs SMA190 is worth up to two points: one for an absolute gap of at most sixty pips, two for a larger gap. "
    "For EUR/USD, one pip is 0.0001, so sixty pips is a price gap of 0.0060. Equal EMA/SMA values earn zero. "
    "Each other factor is worth at most one. The maximum stays five points even when EMA/SMA earns only one; do not shrink the alignment denominator.")


# Version 5 keeps v4's stored definition and evaluation behavior intact.
V4_RULES_TEXT = RULES_TEXT
V5_FACTORS = deepcopy(V4_FACTORS)
V5_FACTORS[2].update(
    name="RSI14 thresholds and trend",
    bullish="Current RSI14 at or below 40 earns 1 bullish point, regardless of its trend. Otherwise, only when current RSI14 is strictly between 40 and 60, three consecutive strictly rising RSI14 readings earn 1 bullish point.",
    bearish="Current RSI14 at or above 60 earns 1 bearish point, regardless of its trend. Otherwise, only when current RSI14 is strictly between 40 and 60, three consecutive strictly falling RSI14 readings earn 1 bearish point.",
    trend={"lookback_candles": 3, "thresholds_take_priority": True,
           "lower_threshold": 40, "upper_threshold": 60, "strict_comparison": True},
)
V5_FACTORS[3].update(
    bullish="Rising momentum earns 1 bullish point, including negative momentum rising toward zero. Reduce to 0.5 when all three consecutive values stay strictly on the same side of zero and the latest positive delta is smaller than the preceding positive delta.",
    bearish="Falling momentum earns 1 bearish point, including positive momentum falling toward zero. Reduce to 0.5 when all three consecutive values stay strictly on the same side of zero and the latest negative delta is smaller in magnitude than the preceding negative delta.",
    direction_basis="change",
)
for old, new in zip(V4_FACTORS, V5_FACTORS):
    RULES_TEXT = RULES_TEXT.replace(
        f"{old['name']} — up to {old['points']} {'point' if old['points'] == 1 else 'points'}. Bullish: {old['bullish']} Bearish: {old['bearish']}",
        f"{new['name']} — up to {new['points']} {'point' if new['points'] == 1 else 'points'}. Bullish: {new['bullish']} Bearish: {new['bearish']}",
    )
RULES_TEXT = RULES_TEXT.replace(
    "the base positive/rising or negative/falling condition can still earn one point.",
    "the base rising/bullish or falling/bearish condition can still earn one point, even when the current value is exactly zero. Unchanged momentum earns zero."
) + (
    " RSI threshold decisions need only the current valid reading. Between the thresholds, compare older < previous < current "
    "for bullish or older > previous > current for bearish. Earlier readings can be outside the threshold band. "
    "Equal or mixed readings earn zero; missing, invalid or nonconsecutive history makes the RSI trend unavailable. "
    "This is a three-reading trend, not a confirmed swing-high/low pattern or price divergence. "
    "Each RSI factor awards at most one point, never threshold and trend points together."
)


# v6 changes only the RSI source; keep all earlier definitions reproducible.
V5_RULES_TEXT = RULES_TEXT
V6_FACTORS = deepcopy(V5_FACTORS)
V6_FACTORS[2].update(
    name="RSI-based MA thresholds and trend",
    source="rsi14_sma14",
    smoothing={"source": "rsi14", "type": "sma", "period": 14},
    bullish=V5_FACTORS[2]["bullish"].replace("RSI14", "RSI14 SMA14"),
    bearish=V5_FACTORS[2]["bearish"].replace("RSI14", "RSI14 SMA14"),
)
RULES_TEXT = V5_RULES_TEXT.replace("RSI14", "RSI14 SMA14") + (
    " The RSI factor uses the simple average of the latest fourteen valid consecutive RSI14 readings, "
    "including the current completed candle, for both thresholds and trend. Raw RSI14 is retained only "
    "as separate context and never substitutes for an unavailable RSI-based MA."
)
RULES_TEXT = RULES_TEXT.replace("RSI14 SMA14 thresholds and trend", "RSI-based MA thresholds and trend")


# Preserve v6's full-point RSI trend decisions for existing journals and clients.
V6_RULES_TEXT = RULES_TEXT
V7_FACTORS = deepcopy(V6_FACTORS)
V7_FACTORS[2].update(
    bullish="Current RSI14 SMA14 at or below 40 earns 1 bullish point, regardless of its trend. Otherwise, only when current RSI14 SMA14 is strictly between 40 and 60, three consecutive strictly rising MA readings earn 1 bullish point, reduced to 0.5 when the current MA is at least 56 and still below 60.",
    bearish="Current RSI14 SMA14 at or above 60 earns 1 bearish point, regardless of its trend. Otherwise, only when current RSI14 SMA14 is strictly between 40 and 60, three consecutive strictly falling MA readings earn 1 bearish point, reduced to 0.5 when the current MA is at most 44 and still above 40.",
    trend_reduction={"bullish_min": 56, "bearish_max": 44, "reduced_points": 0.5},
)
RULES_TEXT = V6_RULES_TEXT.replace(V6_FACTORS[2]["bullish"], V7_FACTORS[2]["bullish"]).replace(
    V6_FACTORS[2]["bearish"], V7_FACTORS[2]["bearish"]
) + (
    " Near-threshold reductions apply only to a confirmed three-reading MA trend inside the open forty-to-sixty band. "
    "At or below forty and at or above sixty, the original full-point threshold rules take priority. "
    "Mixed or equal readings remain neutral. A reduced RSI trend point keeps its direction, "
    "does not award an opposite point, and does not change the five-point maximum or averaging denominator. "
    "Approaching a threshold does not establish a reversal, slower momentum, or consolidation."
)


def rule_set_definition(rule_set_id=RULE_SET_ID):
    if rule_set_id not in SUPPORTED_RULE_SET_IDS:
        raise InvalidJournalEvidence("Unknown strategy rule set.")
    legacy = rule_set_id == LEGACY_RULE_SET_ID
    rules, factors, version = {
        LEGACY_RULE_SET_ID: (LEGACY_RULES_TEXT, LEGACY_FACTORS, 1),
        WEIGHTED_RULE_SET_ID: (WEIGHTED_RULES_TEXT, WEIGHTED_FACTORS, 2),
        MOMENTUM_RULE_SET_ID: (MOMENTUM_RULES_TEXT, FACTORS, 3),
        SESSION_RULE_SET_ID: (V4_RULES_TEXT, V4_FACTORS, 4),
        TREND_RULE_SET_ID: (V5_RULES_TEXT, V5_FACTORS, 5),
        RSI_MA_RULE_SET_ID: (V6_RULES_TEXT, V6_FACTORS, 6),
        RULE_SET_ID: (RULES_TEXT, V7_FACTORS, 7),
    }[rule_set_id]
    return {"id": rule_set_id, "version": version, "name": "Four-factor strategy",
            **({"revision": 2 if rule_set_id == SESSION_RULE_SET_ID else 1} if rule_set_id in SESSION_RULE_SET_IDS else {}),
            "instrument": "EUR_USD", "timeframe": "H4", "rules": rules,
            "factors": deepcopy(list(factors)), "max_points": 4 if legacy else 5,
            "summary_method": "session_average" if rule_set_id in SESSION_RULE_SET_IDS else "final_candle",
            "alignment_denominator": "all_four_factors" if legacy else "all_factor_weights"}


def _number(value):
    return value if type(value) in (int, float) and isfinite(value) else None


def _values(candle):
    indicators = candle.get("indicators") or {}
    return {"close": _number(candle.get("close")), "ema20": _number(indicators.get("ema20")),
            "sma190": _number(indicators.get("sma190")), "rsi14": _number(indicators.get("rsi14")),
            "rsi14_sma14": _number(indicators.get("rsi14_sma14")),
            "momentum": _number((indicators.get("squeeze") or {}).get("momentum"))}


def _consecutive(previous, current):
    """Permit adjacent H4 candles and the regular Friday-to-Sunday market break."""
    if not isinstance(previous, dict):
        return False
    try:
        previous_open, previous_end = _utc(previous["open_time"]), _utc(previous["close_time"])
        current_open = _utc(current["open_time"])
        if previous_end - previous_open != timedelta(hours=4):
            return False
        if previous_end == current_open:
            return True
        end_local, start_local = previous_end.astimezone(NY), current_open.astimezone(NY)
        return (end_local.weekday() == 4 and start_local.weekday() == 6
                and end_local.hour == start_local.hour == 17
                and end_local.minute == start_local.minute == 0
                and end_local.second == start_local.second == 0
                and end_local.microsecond == start_local.microsecond == 0
                and start_local.date() - end_local.date() == timedelta(days=2))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _evidence(candle, candle_id, fields):
    values = _values(candle)
    return {"candle_id": candle_id, "open_time": candle["open_time"], "close_time": candle["close_time"],
            "values": {field: values[field] for field in fields}}


def _result(factor, outcome, reason, evidence):
    return {"factor_id": factor["id"], "name": factor["name"], "outcome": outcome,
            "bullish_points": factor["points"] if outcome == "bullish" else 0,
            "bearish_points": factor["points"] if outcome == "bearish" else 0,
            "reason": reason, "evidence": evidence}


def _ema_sma(factor, candle, candle_id):
    values = _values(candle)
    a, b = values["ema20"], values["sma190"]
    settings = factor.get("distance_weighting")
    gap, reduced = None, False
    if a is None or b is None:
        outcome, reason = "unavailable", "EMA20 or SMA190 is unavailable."
    elif a == b:
        outcome, reason, gap = "neutral", "EMA20 equals SMA190.", 0.0
    else:
        outcome = "bullish" if a > b else "bearish"
        reason = "EMA20 is above SMA190." if a > b else "EMA20 is below SMA190."
        if settings:
            # Decimal conversion of the unrounded stored values avoids an
            # artificial >60 result from binary subtraction at exactly 60.
            distance = abs(Decimal(str(a)) - Decimal(str(b))) / Decimal(str(settings["pip_size"]))
            gap = float(distance)
            if not isfinite(gap):
                outcome, reason, gap = "unavailable", "EMA/SMA distance is unavailable.", None
            else:
                reduced = distance <= Decimal(str(settings["threshold_pips"]))
                reason += (" Gap is at most 60 pips; directional support is reduced to 1 point."
                           if reduced else " Gap exceeds 60 pips; directional support earns 2 points.")
    result = _result(factor, outcome, reason, [_evidence(candle, candle_id, ("ema20", "sma190"))])
    if settings:
        if reduced:
            result["bullish_points"] = settings["within_points"] if outcome == "bullish" else 0
            result["bearish_points"] = settings["within_points"] if outcome == "bearish" else 0
        result["ema_sma_distance"] = {"gap_pips": gap, "threshold_pips": settings["threshold_pips"], "reduced": reduced}
    return result


def _momentum_with_pace(factor, older, previous, current, older_id, previous_id, current_id):
    previous_ok = _consecutive(previous, current)
    older_ok = previous_ok and _consecutive(older, previous)
    values = [_values(older)["momentum"] if older_ok else None,
              _values(previous)["momentum"] if previous_ok else None, _values(current)["momentum"]]
    evidence = [_evidence(current, current_id, ("momentum",))]
    if previous_ok:
        evidence.insert(0, _evidence(previous, previous_id, ("momentum",)))
    if older_ok:
        evidence.insert(0, _evidence(older, older_id, ("momentum",)))
    previous_delta = values[1] - values[0] if all(v is not None for v in values[:2]) else None
    current_delta = values[2] - values[1] if all(v is not None for v in values[1:]) else None
    pace = "unavailable"
    if any(v is None for v in values) or not all(isfinite(d) for d in (previous_delta, current_delta)):
        outcome, reason = "unavailable", "Three consecutive completed candles with finite momentum values are required to assess direction and slowing."
    else:
        momentum = values[2]
        if factor.get("direction_basis") == "change":
            sign = "positive" if momentum > 0 else "negative" if momentum < 0 else "at zero"
            if current_delta > 0:
                outcome, reason = "bullish", f"Momentum is {sign} and rising."
            elif current_delta < 0:
                outcome, reason = "bearish", f"Momentum is {sign} and falling."
            else:
                outcome, reason = "neutral", "Momentum is unchanged."
        elif momentum > 0 and current_delta > 0:
            outcome, reason = "bullish", "Momentum is positive and increasing."
        elif momentum < 0 and current_delta < 0:
            outcome, reason = "bearish", "Momentum is negative and decreasing."
        else:
            outcome, reason = "neutral", "Momentum does not meet the required combination of sign and change."
        same_side = all(v > 0 for v in values) or all(v < 0 for v in values)
        same_direction = (previous_delta > 0 and current_delta > 0) or (previous_delta < 0 and current_delta < 0)
        if not same_side:
            pace = "transition"
            reason += " A zero touch or crossing resets the three-candle pace comparison."
        elif outcome == "neutral":
            pace = "not_directional"
        elif not same_direction:
            pace = "new_move"
            reason += " The preceding delta did not move in this direction, so no slowdown is established."
        elif isclose(abs(current_delta), abs(previous_delta), rel_tol=DELTA_REL_TOL, abs_tol=DELTA_ABS_TOL):
            pace = "steady"
            reason += " Successive delta magnitudes are equal within numerical tolerance; the full point is retained."
        elif abs(current_delta) < abs(previous_delta):
            pace = "slowing"
            reason += " The latest change is smaller in magnitude than the preceding same-direction change; the directional point is reduced to 0.5."
        else:
            pace = "accelerating"
            reason += " The latest change is larger in magnitude than the preceding same-direction change; the full point is retained."
    result = _result(factor, outcome, reason, evidence)
    if pace == "slowing":
        result[f"{outcome}_points"] = 0.5
    result["momentum_change"] = {"pace": pace,
                                 "previous_delta": previous_delta if previous_delta is not None and isfinite(previous_delta) else None,
                                 "current_delta": current_delta if current_delta is not None and isfinite(current_delta) else None}
    if factor.get("direction_basis") == "change":
        result["momentum_change"]["movement"] = (
            "unavailable" if outcome == "unavailable" else
            "rising" if current_delta > 0 else "falling" if current_delta < 0 else "unchanged"
        )
    return result


def _rsi_with_trend(factor, older, previous, current, older_id, previous_id, current_id):
    source = factor.get("source", "rsi14")
    label = "RSI14 SMA14" if source == "rsi14_sma14" else "RSI14"
    rsi = _values(current)[source]
    evidence = [_evidence(current, current_id, (source,))]
    basis = "unavailable"
    if rsi is None or not 0 <= rsi <= 100:
        outcome, reason = "unavailable", f"{label} is undefined or outside its valid range."
    elif rsi <= 40:
        outcome, basis = "bullish", "oversold"
        reason = f"{label} is at or below 40. The bullish threshold takes priority over the trend."
    elif rsi >= 60:
        outcome, basis = "bearish", "overbought"
        reason = f"{label} is at or above 60. The bearish threshold takes priority over the trend."
    else:
        previous_ok = _consecutive(previous, current)
        older_ok = previous_ok and _consecutive(older, previous)
        before = _values(previous)[source] if previous_ok else None
        earliest = _values(older)[source] if older_ok else None
        if previous_ok:
            evidence.insert(0, _evidence(previous, previous_id, (source,)))
        if older_ok:
            evidence.insert(0, _evidence(older, older_id, (source,)))
        if any(v is None or not 0 <= v <= 100 for v in (earliest, before)):
            outcome, reason = "unavailable", f"Between 40 and 60, three consecutive completed candles with valid {label} readings are required."
        elif earliest < before < rsi:
            outcome, basis = "bullish", "rising"
            reason = f"Current {label} is between 40 and 60, and three consecutive readings are strictly rising."
        elif earliest > before > rsi:
            outcome, basis = "bearish", "falling"
            reason = f"Current {label} is between 40 and 60, and three consecutive readings are strictly falling."
        else:
            outcome, basis = "neutral", "mixed_or_flat"
            reason = f"Current {label} is between 40 and 60, but the three readings are mixed or include an equal pair."
    result = _result(factor, outcome, reason, evidence)
    result["rsi_signal"] = {"basis": basis}
    if "source" in factor:
        result["rsi_signal"]["source"] = source
    reduction = factor.get("trend_reduction")
    if reduction:
        proximity = None
        if basis == "rising" and rsi >= reduction["bullish_min"]:
            proximity = "overbought"
        elif basis == "falling" and rsi <= reduction["bearish_max"]:
            proximity = "oversold"
        result["rsi_signal"].update(reduced=proximity is not None, proximity=proximity)
        if proximity:
            result[f"{outcome}_points"] = reduction["reduced_points"]
            result["reason"] += (
                f" The MA is nearing the {proximity} threshold; directional support is reduced to "
                f"{reduction['reduced_points']} points. This does not confirm a reversal."
            )
    return result


def _score(factors, max_points):
    bullish = sum(f["bullish_points"] for f in factors)
    bearish = sum(f["bearish_points"] for f in factors)
    available = sum(f["outcome"] != "unavailable" for f in factors)
    neutral = sum(f["outcome"] == "neutral" for f in factors)
    if available < len(factors):
        direction = "insufficient_data"
    elif bullish == bearish:
        direction = "neutral" if bullish == 0 else "mixed"
    else:
        direction = "bullish" if bullish > bearish else "bearish"
    extra = {}
    if any("momentum_change" in f or "ema_sma_distance" in f for f in factors):
        extra["reduced_factors"] = sum(f.get("momentum_change", {}).get("pace") == "slowing"
                                      or f.get("ema_sma_distance", {}).get("reduced") is True
                                      or f.get("rsi_signal", {}).get("reduced") is True for f in factors)
    return {"bullish_points": bullish, "bearish_points": bearish, "neutral_factors": neutral,
            "unavailable_factors": len(factors) - available, "evaluated_factors": available,
            "max_points": max_points, "net_score": bullish - bearish, "direction": direction,
            "bullish_alignment_percent": bullish * 100 / max_points,
            "bearish_alignment_percent": bearish * 100 / max_points, **extra}


def _session_average(rows, max_points):
    """Equal-weight means for a full session; unavailable inputs never become zeros."""
    count = len(rows)
    factors = [factor for row in rows for factor in row["factors"]]
    summary = _score(factors, max_points * count)
    complete = summary["unavailable_factors"] == 0
    summary.update(method="session_average", max_points=max_points, candle_count=count,
                   candle_ids=[row["candle_id"] for row in rows], complete=complete,
                   complete_candles=sum(row["unavailable_factors"] == 0 for row in rows),
                   expected_factors=len(factors))
    if complete:
        # Decide direction from exact half-point totals before division/formatting.
        for key in ("bullish_points", "bearish_points", "net_score"):
            summary[key] /= count
    else:
        for key in ("bullish_points", "bearish_points", "net_score",
                    "bullish_alignment_percent", "bearish_alignment_percent"):
            summary[key] = None
    return summary


def evaluate_strategy(snapshot, rule_set_id=RULE_SET_ID, *, allow_partial=False):
    """Only current/past candles influence a score; missing history is explicit."""
    catalog = build_evidence_catalog(snapshot, allow_partial=allow_partial)
    definition = rule_set_definition(rule_set_id)
    definitions = definition["factors"]
    max_points = definition["max_points"]
    rsi_low, rsi_high = (30, 70) if rule_set_id == LEGACY_RULE_SET_ID else (40, 60)
    settings = snapshot.get("indicator_settings", {})
    if (snapshot.get("instrument") != "EUR_USD" or snapshot.get("timeframe") != "H4"
            or settings.get("ema", {}).get("period") != 20
            or settings.get("sma", {}).get("period") != 190
            or settings.get("rsi", {}).get("period") != 14):
        raise InvalidJournalEvidence("The scored strategy requires EUR/USD H4 with EMA20, SMA190 and RSI14.")
    if rule_set_id in RSI_MA_RULE_SET_IDS and any(
            settings.get("rsi_ma", {}).get(key) != expected
            for key, expected in (("source", "rsi14"), ("type", "sma"), ("period", 14))):
        raise InvalidJournalEvidence("The RSI-based MA strategy requires SMA14 smoothing of RSI14.")
    rows = []
    previous = snapshot.get("previous_candle")
    history = snapshot.get("previous_candles")
    older = history[0] if isinstance(history, list) and len(history) == 2 and history[1] == previous else None
    for index, candle in enumerate(snapshot["candles"]):
        candle_id = f"C{index + 1}"
        previous_id = "P0" if index == 0 else f"C{index}"
        older_id = "P-1" if index == 0 else "P0" if index == 1 else f"C{index - 1}"
        current = _values(candle)
        prior = _values(previous) if _consecutive(previous, candle) else {}
        factors = []

        evidence = [_evidence(candle, candle_id, ("close", "ema20"))]
        if prior:
            evidence.insert(0, _evidence(previous, previous_id, ("close", "ema20")))
        if any(v is None for v in (prior.get("close"), prior.get("ema20"), current["close"], current["ema20"])):
            outcome, reason = "unavailable", "A consecutive previous candle with close and EMA20 is required."
        elif current["close"] > current["ema20"] and prior["close"] > prior["ema20"]:
            outcome, reason = "bullish", "Both closes are above their own EMA20 values."
        elif current["close"] < current["ema20"] and prior["close"] < prior["ema20"]:
            outcome, reason = "bearish", "Both closes are below their own EMA20 values."
        else:
            outcome, reason = "neutral", "The closes are mixed or at least one equals its own EMA20."
        factors.append(_result(definitions[0], outcome, reason, evidence))

        factors.append(_ema_sma(definitions[1], candle, candle_id))

        rsi = current["rsi14"]
        if rsi is None or not 0 <= rsi <= 100:
            outcome, reason = "unavailable", "RSI14 is undefined or outside its valid range."
        elif rsi <= rsi_low:
            outcome, reason = "bullish", f"RSI14 is at or below {rsi_low}, meeting the bullish rule."
        elif rsi >= rsi_high:
            outcome, reason = "bearish", f"RSI14 is at or above {rsi_high}, meeting the bearish rule."
        else:
            outcome, reason = "neutral", f"RSI14 is between {rsi_low} and {rsi_high}; neither threshold is met."
        if rule_set_id in (*RSI_MA_RULE_SET_IDS, TREND_RULE_SET_ID):
            factors.append(_rsi_with_trend(definitions[2], older, previous, candle, older_id, previous_id, candle_id))
        else:
            factors.append(_result(definitions[2], outcome, reason, [_evidence(candle, candle_id, ("rsi14",))]))

        momentum, old_momentum = current["momentum"], prior.get("momentum")
        evidence = [_evidence(candle, candle_id, ("momentum",))]
        if prior:
            evidence.insert(0, _evidence(previous, previous_id, ("momentum",)))
        if momentum is None or old_momentum is None:
            outcome, reason = "unavailable", "Current and consecutive previous momentum values are required."
        elif momentum > 0 and momentum > old_momentum:
            outcome, reason = "bullish", "Momentum is positive and increasing."
        elif momentum < 0 and momentum < old_momentum:
            outcome, reason = "bearish", "Momentum is negative and decreasing."
        else:
            outcome, reason = "neutral", "Momentum does not meet the required combination of sign and change."
        if rule_set_id in (*SESSION_RULE_SET_IDS, MOMENTUM_RULE_SET_ID):
            factors.append(_momentum_with_pace(definitions[3], older, previous, candle, older_id, previous_id, candle_id))
        else:
            factors.append(_result(definitions[3], outcome, reason, evidence))
        rows.append({"candle_id": candle_id, "open_time": candle["open_time"], "close_time": candle["close_time"],
                     "open_time_local": catalog[candle_id]["open_time_local"],
                     "close_time_local": catalog[candle_id]["close_time_local"],
                     "factors": factors, **_score(factors, max_points)})
        older, previous = previous, candle
    session_end = {"method": "final_candle", "candle_id": rows[-1]["candle_id"], **_score(rows[-1]["factors"], max_points)}
    result = {"schema_version": 1, "rule_set": definition, "candles": rows, "summary": session_end}
    if rule_set_id in SESSION_RULE_SET_IDS:
        result.update(summary=_session_average(rows, max_points), session_end=session_end)
    return result
