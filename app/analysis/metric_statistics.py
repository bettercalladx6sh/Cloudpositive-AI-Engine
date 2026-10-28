from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Sequence

from app.ec2.metrics import MetricDatapoint


@dataclass(frozen=True)
class MetricStatistics:
    """Deterministic statistical summary of a CloudWatch metric."""

    datapoint_count: int

    average: float
    minimum: float
    maximum: float

    p50: float
    p90: float
    p95: float
    p99: float

    standard_deviation: float

    above_70_percent: float
    above_80_percent: float
    above_90_percent: float


def _percentile(
    values: Sequence[float],
    percentile: float,
) -> float:
    """Calculate a linearly interpolated percentile."""

    if not values:
        raise ValueError(
            "Cannot calculate a percentile from no values."
        )

    if not 0.0 <= percentile <= 100.0:
        raise ValueError(
            "Percentile must be between 0 and 100."
        )

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        (len(ordered) - 1)
        * (percentile / 100.0)
    )

    lower_index = int(position)

    upper_index = min(
        lower_index + 1,
        len(ordered) - 1,
    )

    fraction = position - lower_index

    lower = ordered[lower_index]
    upper = ordered[upper_index]

    return lower + (
        (upper - lower)
        * fraction
    )


def _percentage_above(
    values: Sequence[float],
    threshold: float,
) -> float:
    """Return the percentage of datapoints above a threshold."""

    if not values:
        return 0.0

    count = sum(
        1
        for value in values
        if value > threshold
    )

    return (
        count
        / len(values)
        * 100.0
    )


def _standard_deviation(
    values: Sequence[float],
) -> float:
    """
    Calculate population standard deviation.

    The complete collected evidence is treated as the population
    being analyzed, rather than as a sample of a larger dataset.
    """

    if not values:
        return 0.0

    if len(values) == 1:
        return 0.0

    average = mean(values)

    variance = mean(
        (
            value - average
        ) ** 2
        for value in values
    )

    return sqrt(variance)


def _extract_average_values(
    datapoints: Sequence[MetricDatapoint],
) -> list[float]:
    """
    Extract valid Average values.

    Missing Average values are ignored rather than interpreted
    as zero utilization.
    """

    return [
        float(datapoint.average)
        for datapoint in datapoints
        if datapoint.average is not None
    ]


def calculate_metric_statistics(
    datapoints: tuple[MetricDatapoint, ...],
) -> MetricStatistics | None:
    """
    Calculate deterministic statistics from CloudWatch datapoints.

    Missing metric values are never treated as zero.

    Returns None when no usable Average datapoints exist.
    """

    if not datapoints:
        return None

    values = _extract_average_values(
        datapoints
    )

    if not values:
        return None

    return MetricStatistics(
        datapoint_count=len(values),

        average=mean(values),

        minimum=min(values),

        maximum=max(values),

        p50=_percentile(
            values,
            50.0,
        ),

        p90=_percentile(
            values,
            90.0,
        ),

        p95=_percentile(
            values,
            95.0,
        ),

        p99=_percentile(
            values,
            99.0,
        ),

        standard_deviation=_standard_deviation(
            values
        ),

        above_70_percent=_percentage_above(
            values,
            70.0,
        ),

        above_80_percent=_percentage_above(
            values,
            80.0,
        ),

        above_90_percent=_percentage_above(
            values,
            90.0,
        ),
    )