"""Indicators over chronological, completed candle closes.

Outputs retain the input length and index alignment. None means there are not
enough observations, or RSI is undefined because both smoothed gains and losses
are zero. Values are not rounded internally.
"""

from collections.abc import Sequence
from math import fsum, isfinite, sqrt
from typing import TypedDict


def _validate_period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("The indicator period must be a positive integer.")


def _validated_prices(values: Sequence[float], period: int) -> list[float]:
    _validate_period(period)
    prices = [float(value) for value in values]
    if any(not isfinite(price) for price in prices):
        raise ValueError("Indicator inputs must contain only finite numbers.")
    return prices


def sma(values: Sequence[float], period: int) -> list[float | None]:
    """Average the latest `period` closes, including the current close."""
    prices = _validated_prices(values, period)
    result: list[float | None] = [None] * len(prices)

    for index in range(period - 1, len(prices)):
        result[index] = fsum(prices[index - period + 1:index + 1]) / period
    return result


def sma_nullable(values: Sequence[float | None], period: int) -> list[float | None]:
    """SMA of complete, consecutive indicator windows; never fill missing RSI.

    Keep source alignment and full precision. A missing observation requires a
    fresh complete window, so unavailable history cannot silently become a score.
    """
    _validate_period(period)
    result: list[float | None] = [None] * len(values)
    for value in values:
        if value is not None and (type(value) not in (int, float) or not isfinite(value)):
            raise ValueError("Smoothing inputs must be finite numbers or None.")
    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        if all(value is not None for value in window):
            result[index] = fsum(window) / period
    return result


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """Use alpha=2/(period+1), seeded with the first `period` closes' SMA."""
    prices = _validated_prices(values, period)
    result: list[float | None] = [None] * len(prices)
    if len(prices) < period:
        return result

    previous = fsum(prices[:period]) / period
    result[period - 1] = previous
    alpha = 2.0 / (period + 1)

    for index in range(period, len(prices)):
        previous += alpha * (prices[index] - previous)
        result[index] = previous
    return result


def _rsi_from_averages(average_gain: float, average_loss: float) -> float | None:
    if average_loss == 0.0:
        return 100.0 if average_gain > 0.0 else None
    if average_gain == 0.0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


def rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    """Wilder RSI, seeded with the mean of the first `period` price changes.

    The first possible value needs period+1 closes and appears at index `period`.
    After seeding, gains and losses use Wilder's alpha=1/period smoothing.
    An entirely flat seed has undefined RSI (None), not an invented neutral value.
    """
    prices = _validated_prices(values, period)
    result: list[float | None] = [None] * len(prices)
    if len(prices) <= period:
        return result

    changes = [current - previous for previous, current in zip(prices, prices[1:])]
    average_gain = fsum(max(change, 0.0) for change in changes[:period]) / period
    average_loss = fsum(max(-change, 0.0) for change in changes[:period]) / period
    result[period] = _rsi_from_averages(average_gain, average_loss)

    for index in range(period + 1, len(prices)):
        change = changes[index - 1]
        average_gain = (average_gain * (period - 1) + max(change, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-change, 0.0)) / period
        result[index] = _rsi_from_averages(average_gain, average_loss)
    return result


class SqueezeMomentumResult(TypedDict):
    momentum: list[float | None]
    state: list[str | None]
    histogram_color: list[str | None]
    squeeze_color: list[str | None]
    released: list[bool | None]
    upper_bb: list[float | None]
    lower_bb: list[float | None]
    upper_kc: list[float | None]
    lower_kc: list[float | None]


def _regression_endpoint(values: Sequence[float]) -> float:
    """Least-squares fitted value at the newest point (Pine linreg offset 0)."""
    count = len(values)
    x_mean = (count - 1) / 2.0
    y_mean = fsum(values) / count
    numerator = fsum((index - x_mean) * (value - y_mean)
                     for index, value in enumerate(values))
    denominator = fsum((index - x_mean) ** 2 for index in range(count))
    return y_mean + (numerator / denominator) * x_mean


def squeeze_momentum(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    bb_period: int = 20,
    bb_multiplier: float = 2.0,
    kc_period: int = 20,
    kc_multiplier: float = 1.5,
    use_true_range: bool = True,
) -> SqueezeMomentumResult:
    """Python implementation of LazyBear's corrected September 2014 formula.

    Formula sources:
    https://www.tradingview.com/script/nqQ1DT5a-Squeeze-Momentum-Indicator-LazyBear/
    https://pastebin.com/UCpcX8d7

    BB uses population standard deviation. KC uses SMA of closes and SMA of
    ranges (not Wilder ATR). Momentum fits a regression to rolling deviations
    from a center made from the high/low midpoint and SMA of closes.

    ON: both BB boundaries are strictly inside KC; OFF: both strictly outside.
    NEUTRAL: neither condition. Missing history remains None. `released` is an
    extra event flag: True only for an immediately preceding ON followed by OFF.
    With defaults, state first exists at index 20 and momentum at index 38.
    """
    close_values = _validated_prices(closes, bb_period)
    high_values = _validated_prices(highs, kc_period)
    low_values = _validated_prices(lows, kc_period)
    if kc_period < 2:
        raise ValueError("KC period must be at least 2 for linear regression.")
    if not isinstance(use_true_range, bool):
        raise ValueError("use_true_range must be True or False.")
    for multiplier in (bb_multiplier, kc_multiplier):
        if isinstance(multiplier, bool) or not isfinite(multiplier) or multiplier <= 0:
            raise ValueError("Band multipliers must be finite positive numbers.")
    count = len(close_values)
    if len(high_values) != count or len(low_values) != count:
        raise ValueError("High, low, and close series must have equal lengths.")
    if any(not low <= close <= high
           for high, low, close in zip(high_values, low_values, close_values)):
        raise ValueError("Each candle must satisfy low <= close <= high.")

    output: SqueezeMomentumResult = {
        "momentum": [None] * count,
        "state": [None] * count,
        "histogram_color": [None] * count,
        "squeeze_color": [None] * count,
        "released": [None] * count,
        "upper_bb": [None] * count,
        "lower_bb": [None] * count,
        "upper_kc": [None] * count,
        "lower_kc": [None] * count,
    }
    bb_means = sma(close_values, bb_period)
    kc_means = sma(close_values, kc_period)
    if use_true_range:
        # The author's `tr` has no value on the first bar without a prior close.
        ranges = [
            max(high_values[index] - low_values[index],
                abs(high_values[index] - close_values[index - 1]),
                abs(low_values[index] - close_values[index - 1]))
            for index in range(1, count)
        ]
        range_means = [None] + sma(ranges, kc_period) if count else []
    else:
        ranges = [high - low for high, low in zip(high_values, low_values)]
        range_means = sma(ranges, kc_period)

    deviations: list[float] = []
    for index in range(count):
        bb_mean = bb_means[index]
        kc_mean = kc_means[index]
        range_mean = range_means[index]

        if bb_mean is not None:
            window = close_values[index - bb_period + 1:index + 1]
            variance = fsum((value - bb_mean) ** 2 for value in window) / bb_period
            width = bb_multiplier * sqrt(variance)
            output["upper_bb"][index] = bb_mean + width
            output["lower_bb"][index] = bb_mean - width

        if kc_mean is not None and range_mean is not None:
            output["upper_kc"][index] = kc_mean + kc_multiplier * range_mean
            output["lower_kc"][index] = kc_mean - kc_multiplier * range_mean

        upper_bb, lower_bb = output["upper_bb"][index], output["lower_bb"][index]
        upper_kc, lower_kc = output["upper_kc"][index], output["lower_kc"][index]
        if (upper_bb is not None and lower_bb is not None
                and upper_kc is not None and lower_kc is not None):
            if lower_bb > lower_kc and upper_bb < upper_kc:
                state = "ON"
            elif lower_bb < lower_kc and upper_bb > upper_kc:
                state = "OFF"
            else:
                state = "NEUTRAL"
            output["state"][index] = state
            output["squeeze_color"][index] = {"ON": "black", "OFF": "gray", "NEUTRAL": "blue"}[state]
            prior_state = output["state"][index - 1] if index else None
            if prior_state is not None:
                output["released"][index] = prior_state == "ON" and state == "OFF"

        if kc_mean is not None:
            window_start = index - kc_period + 1
            highest = max(high_values[window_start:index + 1])
            lowest = min(low_values[window_start:index + 1])
            center = ((highest + lowest) / 2.0 + kc_mean) / 2.0
            deviations.append(close_values[index] - center)
            if len(deviations) >= kc_period:
                momentum = _regression_endpoint(deviations[-kc_period:])
                output["momentum"][index] = momentum
                previous = output["momentum"][index - 1] if index else None
                previous = 0.0 if previous is None else previous
                if momentum > 0:
                    color = "lime" if momentum > previous else "green"
                else:
                    color = "red" if momentum < previous else "maroon"
                output["histogram_color"][index] = color

    return output
