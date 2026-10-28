from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Sequence

from app.ec2.metrics import MetricDatapoint


@dataclass(frozen=True)
class WorkloadAnalysis:
    """Deterministic analysis of workload behavior."""

    datapoint_count: int

    first_average: float
    last_average: float

    average: float
    p95: float
    maximum: float

    trend_percent: float

    stability: str
    trend: str
    spike_risk: str


def _calculate_trend(
    *,
    first_average: float,
    last_average: float,
    overall_average: float,
) -> tuple[str, float]:
    """
    Determine workload trend.

    Both relative and absolute movement are considered.

    This prevents tiny utilization values from producing misleading
    large percentage changes.
    """

    if first_average <= 0:
        return "STABLE", 0.0

    trend_percent = (
        (
            last_average
            - first_average
        )
        / first_average
        * 100.0
    )

    absolute_change = abs(
        last_average
        - first_average
    )

    # Very low utilization can produce very large relative
    # percentages without representing meaningful capacity change.
    if (
        overall_average < 20.0
        and absolute_change < 5.0
    ):
        return "STABLE", trend_percent

    if absolute_change <= 5.0:
        return "STABLE", trend_percent

    if trend_percent > 15.0:
        return "GROWING", trend_percent

    if trend_percent < -15.0:
        return "DECLINING", trend_percent

    return "STABLE", trend_percent


def _calculate_stability(
    *,
    average: float,
    p95: float,
) -> str:
    """Classify workload stability using P95 relative to average."""

    if average <= 0:
        return "STABLE"

    ratio = p95 / average

    if ratio <= 1.5:
        return "STABLE"

    if ratio <= 2.5:
        return "VARIABLE"

    return "HIGHLY_VARIABLE"


def _calculate_spike_risk(
    *,
    average: float,
    maximum: float,
) -> str:
    """Classify spike risk using maximum relative to average."""

    if average <= 0:
        return "LOW"

    ratio = maximum / average

    if ratio <= 2.0:
        return "LOW"

    if ratio <= 4.0:
        return "MEDIUM"

    return "HIGH"


def _extract_values(
    datapoints: Sequence[MetricDatapoint],
) -> list[float]:
    """
    Extract valid Average values.

    Missing Average values are ignored and never converted to zero.
    """

    return [
        float(datapoint.average)
        for datapoint in datapoints
        if datapoint.average is not None
    ]


def analyze_workload(
    *,
    datapoints: Sequence[MetricDatapoint],
    p95: float,
) -> WorkloadAnalysis | None:
    """
    Analyze workload behavior from CloudWatch datapoints.

    No AWS calls are made.

    No pricing is calculated.

    No recommendation is produced.

    This module only describes observed workload behavior.
    """

    if not datapoints:
        return None

    values = _extract_values(
        datapoints
    )

    if not values:
        return None

    count = len(values)

    average = mean(values)

    maximum = max(values)

    # Split the observed period into two chronological halves.
    midpoint = max(
        1,
        count // 2,
    )

    first_half = values[:midpoint]

    second_half = values[midpoint:]

    if not second_half:
        second_half = first_half

    first_average = mean(
        first_half
    )

    last_average = mean(
        second_half
    )

    trend, trend_percent = _calculate_trend(
        first_average=first_average,
        last_average=last_average,
        overall_average=average,
    )

    stability = _calculate_stability(
        average=average,
        p95=p95,
    )

    spike_risk = _calculate_spike_risk(
        average=average,
        maximum=maximum,
    )

    return WorkloadAnalysis(
        datapoint_count=count,
        first_average=first_average,
        last_average=last_average,
        average=average,
        p95=p95,
        maximum=maximum,
        trend_percent=trend_percent,
        stability=stability,
        trend=trend,
        spike_risk=spike_risk,
    )