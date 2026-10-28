from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Sequence


@dataclass(frozen=True)
class CumulativeMetricSummary:
    evidence_start: datetime | None
    evidence_end: datetime | None

    datapoint_count: int
    value_sum: float

    average: float | None
    minimum: float | None
    maximum: float | None

    p50: float | None
    p95: float | None
    p99: float | None

    standard_deviation: float | None

    trend: str | None
    volatility: str | None

    coverage_percent: float
    gap_count: int


def _percentile(
    values: Sequence[float],
    percentile: float,
) -> float | None:
    if not values:
        return None

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        (len(ordered) - 1)
        * percentile
        / 100.0
    )

    lower = int(position)
    upper = min(
        lower + 1,
        len(ordered) - 1,
    )

    fraction = position - lower

    return (
        ordered[lower]
        + (
            ordered[upper]
            - ordered[lower]
        )
        * fraction
    )


def _calculate_trend(
    values: Sequence[float],
) -> str | None:
    if len(values) < 2:
        return None

    midpoint = len(values) // 2

    if midpoint == 0:
        return None

    first_half = values[:midpoint]
    second_half = values[midpoint:]

    first_average = mean(first_half)
    second_average = mean(second_half)

    if first_average == 0:
        if second_average == 0:
            return "STABLE"

        return "GROWING"

    change_percent = (
        (second_average - first_average)
        / abs(first_average)
        * 100.0
    )

    if change_percent >= 10.0:
        return "GROWING"

    if change_percent <= -10.0:
        return "DECLINING"

    return "STABLE"


def _calculate_volatility(
    values: Sequence[float],
) -> str | None:
    if len(values) < 2:
        return None

    average = mean(values)

    if average == 0:
        return "STABLE"

    deviation = pstdev(values)

    coefficient = deviation / abs(average)

    if coefficient >= 0.50:
        return "HIGH"

    if coefficient >= 0.20:
        return "MODERATE"

    return "LOW"


def _calculate_gap_count(
    timestamps: Sequence[datetime],
    period_seconds: int,
) -> int:
    if len(timestamps) < 2:
        return 0

    ordered = sorted(timestamps)

    gaps = 0

    for previous, current in zip(
        ordered,
        ordered[1:],
    ):
        previous = _normalise_datetime(previous)
        current = _normalise_datetime(current)

        elapsed = (
            current - previous
        ).total_seconds()

        if elapsed > period_seconds:
            missing_intervals = (
                int(elapsed // period_seconds) - 1
            )

            if missing_intervals > 0:
                gaps += missing_intervals

    return gaps


def _normalise_datetime(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(timezone.utc)


def _extract_value(
    datapoint: object,
) -> float | None:
    """
    Extract the authoritative metric value.

    The current MetricDatapoint model uses `average`.
    """

    value = getattr(
        datapoint,
        "average",
        None,
    )

    if value is None:
        return None

    return float(value)


def calculate_cumulative_summary(
    *,
    datapoints: Sequence[object],
    period_seconds: int,
) -> CumulativeMetricSummary:
    """
    Calculate cumulative statistics from raw metric datapoints.

    Raw datapoints are authoritative.

    The current datapoint model exposes:
        timestamp
        average
        minimum
        maximum

    The average value is used as the primary observation for
    cumulative statistics.
    """

    if period_seconds <= 0:
        raise ValueError(
            "period_seconds must be greater than zero."
        )

    if not datapoints:
        return CumulativeMetricSummary(
            evidence_start=None,
            evidence_end=None,
            datapoint_count=0,
            value_sum=0.0,
            average=None,
            minimum=None,
            maximum=None,
            p50=None,
            p95=None,
            p99=None,
            standard_deviation=None,
            trend=None,
            volatility=None,
            coverage_percent=0.0,
            gap_count=0,
        )

    ordered = sorted(
        datapoints,
        key=lambda item: _normalise_datetime(
            item.timestamp
        ),
    )

    valued_datapoints = [
        item
        for item in ordered
        if _extract_value(item) is not None
    ]

    if not valued_datapoints:
        return CumulativeMetricSummary(
            evidence_start=_normalise_datetime(
                ordered[0].timestamp
            ),
            evidence_end=_normalise_datetime(
                ordered[-1].timestamp
            ),
            datapoint_count=0,
            value_sum=0.0,
            average=None,
            minimum=None,
            maximum=None,
            p50=None,
            p95=None,
            p99=None,
            standard_deviation=None,
            trend=None,
            volatility=None,
            coverage_percent=0.0,
            gap_count=_calculate_gap_count(
                [
                    item.timestamp
                    for item in ordered
                ],
                period_seconds,
            ),
        )

    values = [
        _extract_value(item)
        for item in valued_datapoints
    ]

    numeric_values = [
        value
        for value in values
        if value is not None
    ]

    timestamps = [
        _normalise_datetime(
            item.timestamp
        )
        for item in valued_datapoints
    ]

    evidence_start = timestamps[0]
    evidence_end = timestamps[-1]

    datapoint_count = len(numeric_values)

    value_sum = sum(numeric_values)

    average = (
        value_sum / datapoint_count
        if datapoint_count
        else None
    )

    minimum = min(numeric_values)
    maximum = max(numeric_values)

    p50 = _percentile(
        numeric_values,
        50.0,
    )

    p95 = _percentile(
        numeric_values,
        95.0,
    )

    p99 = _percentile(
        numeric_values,
        99.0,
    )

    standard_deviation = (
        pstdev(numeric_values)
        if len(numeric_values) >= 2
        else 0.0
    )

    gap_count = _calculate_gap_count(
        timestamps,
        period_seconds,
    )

    expected_datapoints = (
        int(
            (
                evidence_end
                - evidence_start
            ).total_seconds()
            // period_seconds
        )
        + 1
    )

    coverage_percent = (
        min(
            datapoint_count
            / expected_datapoints
            * 100.0,
            100.0,
        )
        if expected_datapoints > 0
        else 0.0
    )

    return CumulativeMetricSummary(
        evidence_start=evidence_start,
        evidence_end=evidence_end,
        datapoint_count=datapoint_count,
        value_sum=value_sum,
        average=average,
        minimum=minimum,
        maximum=maximum,
        p50=p50,
        p95=p95,
        p99=p99,
        standard_deviation=standard_deviation,
        trend=_calculate_trend(
            numeric_values
        ),
        volatility=_calculate_volatility(
            numeric_values
        ),
        coverage_percent=coverage_percent,
        gap_count=gap_count,
    )