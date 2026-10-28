
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.aws.client import AwsClient


# Split large CloudWatch requests into smaller intervals.
MAX_REQUEST_DAYS = 30

CPU_NAMESPACE = "AWS/EC2"
CPU_METRIC_NAME = "CPUUtilization"

MEMORY_NAMESPACE = "EC2/Custom"
MEMORY_METRIC_NAME = "mem_used_percent"

METRIC_PERIOD_SECONDS = 3600


@dataclass(frozen=True)
class MetricDatapoint:
    """One real CloudWatch metric datapoint."""

    timestamp: datetime
    average: float | None
    minimum: float | None
    maximum: float | None


@dataclass(frozen=True)
class MetricSummary:
    """Deterministic summary of collected metric data."""

    namespace: str
    metric_name: str
    average: float | None
    minimum: float | None
    maximum: float | None
    datapoint_count: int
    first_datapoint: datetime | None
    last_datapoint: datetime | None
    coverage_hours: float
    expected_datapoints: int
    missing_datapoints: int
    coverage_percent: float
    datapoints: tuple[MetricDatapoint, ...]


@dataclass(frozen=True)
class Ec2Metrics:
    """CPU and memory metrics for one EC2 instance."""

    instance_id: str
    region: str
    analysis_start: datetime
    analysis_end: datetime
    cpu: MetricSummary
    memory: MetricSummary


def _ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""

    if not isinstance(value, datetime):
        raise TypeError("Timestamp must be a datetime object.")

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _is_valid_number(value: float | None) -> bool:
    """Return whether a metric value is present and finite."""

    return (
        value is not None
        and math.isfinite(value)
    )


def is_zero_metric_datapoint(
    datapoint: MetricDatapoint,
) -> bool:
    """
    Return True when the datapoint's Average is exactly zero.

    This helper identifies zero-average datapoints for average
    calculations. It does not mean the datapoint should be deleted.

    A zero Minimum or Maximum alone does not make a datapoint
    a zero-average datapoint.
    """

    return (
        datapoint.average is not None
        and datapoint.average == 0
    )


def _calculate_coverage_hours(
    first_datapoint: datetime | None,
    last_datapoint: datetime | None,
) -> float:
    """Return the elapsed time between the first and last datapoints.

    This measures the observed timestamp span, not the number of
    hourly datapoints. A single datapoint therefore has zero elapsed
    span, and 107 hourly datapoints may span only 106 hours.
    """
    if first_datapoint is None or last_datapoint is None:
        return 0.0

    first = first_datapoint
    last = last_datapoint

    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    else:
        first = first.astimezone(timezone.utc)

    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    else:
        last = last.astimezone(timezone.utc)

    if last < first:
        return 0.0

    return (last - first).total_seconds() / 3600.0



def _calculate_expected_datapoints(
    start_time: datetime,
    end_time: datetime,
) -> int:
    """
    Calculate expected hourly datapoints for [start_time, end_time).

    Only complete one-hour periods are counted.
    """

    duration_seconds = (
        _ensure_utc(end_time) - _ensure_utc(start_time)
    ).total_seconds()

    if duration_seconds <= 0:
        return 0

    return int(duration_seconds // METRIC_PERIOD_SECONDS)


def _calculate_missing_datapoints(
    expected_datapoints: int,
    datapoint_count: int,
) -> int:
    """Calculate expected datapoints not represented in the result."""

    return max(expected_datapoints - datapoint_count, 0)


def _calculate_coverage_percent(
    expected_datapoints: int,
    datapoint_count: int,
) -> float:
    """Calculate observed datapoint coverage against the expected count."""

    if expected_datapoints <= 0:
        return 0.0

    return min(
        datapoint_count / expected_datapoints * 100.0,
        100.0,
    )


def summarize_metric_datapoints(
    namespace: str,
    metric_name: str,
    datapoints: list[MetricDatapoint]
    | tuple[MetricDatapoint, ...],
    *,
    expected_start: datetime | None = None,
    expected_end: datetime | None = None,
) -> MetricSummary:
    """
    Summarize metric datapoints without making AWS API calls.

    Important rules:
    - Zero-average datapoints are retained as evidence.
    - Zero-average datapoints are excluded from the average calculation.
    - Minimum and maximum calculations retain genuine zero values.
    - Coverage counts all unique observed datapoints, including zeros.
    - Duplicate timestamps are represented by one datapoint.
    - Missing data is not fabricated or replaced with zero.
    """

    if (expected_start is None) != (expected_end is None):
        raise ValueError(
            "expected_start and expected_end must either both be "
            "provided or both be omitted."
        )

    if expected_start is not None:
        expected_start = _ensure_utc(expected_start)

    if expected_end is not None:
        expected_end = _ensure_utc(expected_end)

    if (
        expected_start is not None
        and expected_end is not None
        and expected_end <= expected_start
    ):
        raise ValueError(
            "expected_end must be after expected_start."
        )

    normalized_by_timestamp: dict[
        datetime,
        MetricDatapoint,
    ] = {}

    for datapoint in datapoints:
        timestamp = _ensure_utc(datapoint.timestamp)

        # Keep only datapoints within the requested half-open interval.
        if expected_start is not None and timestamp < expected_start:
            continue

        if expected_end is not None and timestamp >= expected_end:
            continue

        normalized_datapoint = MetricDatapoint(
            timestamp=timestamp,
            average=datapoint.average,
            minimum=datapoint.minimum,
            maximum=datapoint.maximum,
        )

        # Keep zero values. They are real observations, not missing data.
        # Deduplicate using normalized UTC timestamps.
        normalized_by_timestamp[timestamp] = normalized_datapoint

    normalized = sorted(
        normalized_by_timestamp.values(),
        key=lambda item: item.timestamp,
    )

    expected_datapoints = (
        _calculate_expected_datapoints(
            expected_start,
            expected_end,
        )
        if expected_start is not None and expected_end is not None
        else 0
    )

    datapoint_count = len(normalized)

    missing_datapoints = (
        _calculate_missing_datapoints(
            expected_datapoints,
            datapoint_count,
        )
        if expected_start is not None and expected_end is not None
        else 0
    )

    coverage_percent = (
        _calculate_coverage_percent(
            expected_datapoints,
            datapoint_count,
        )
        if expected_start is not None and expected_end is not None
        else (100.0 if datapoint_count else 0.0)
    )

    if not normalized:
        return MetricSummary(
            namespace=namespace,
            metric_name=metric_name,
            average=None,
            minimum=None,
            maximum=None,
            datapoint_count=0,
            first_datapoint=None,
            last_datapoint=None,
            coverage_hours=0.0,
            expected_datapoints=expected_datapoints,
            missing_datapoints=(
                expected_datapoints
                if expected_start is not None
                and expected_end is not None
                else 0
            ),
            coverage_percent=0.0,
            datapoints=(),
        )

    # Only positive/non-zero valid Average values contribute to the
    # utilization average. Zero observations remain in the evidence.
    averages = [
        datapoint.average
        for datapoint in normalized
        if _is_valid_number(datapoint.average)
        and not is_zero_metric_datapoint(datapoint)
    ]

    # Minimum and maximum describe the actual observed datapoints.
    # Zero is valid for these statistics and is not discarded.
    minimums = [
        datapoint.minimum
        for datapoint in normalized
        if _is_valid_number(datapoint.minimum)
    ]

    maximums = [
        datapoint.maximum
        for datapoint in normalized
        if _is_valid_number(datapoint.maximum)
    ]

    first_datapoint = normalized[0].timestamp
    last_datapoint = normalized[-1].timestamp

    return MetricSummary(
        namespace=namespace,
        metric_name=metric_name,
        average=(
            sum(averages) / len(averages)
            if averages
            else None
        ),
        minimum=min(minimums) if minimums else None,
        maximum=max(maximums) if maximums else None,
        datapoint_count=datapoint_count,
        first_datapoint=first_datapoint,
        last_datapoint=last_datapoint,
        coverage_hours=_calculate_coverage_hours(
            first_datapoint,
            last_datapoint,
        ),
        expected_datapoints=expected_datapoints,
        missing_datapoints=missing_datapoints,
        coverage_percent=coverage_percent,
        datapoints=tuple(normalized),
    )


def _get_metric_datapoints(
    cloudwatch: Any,
    namespace: str,
    metric_name: str,
    instance_id: str,
    start_time: datetime,
    end_time: datetime,
) -> list[MetricDatapoint]:
    """
    Retrieve one metric interval from CloudWatch.

    Makes exactly one GetMetricStatistics request per invocation.

    Zero-valued datapoints are deliberately retained so that valid
    observations are not incorrectly counted as missing.
    """

    start_time = _ensure_utc(start_time)
    end_time = _ensure_utc(end_time)

    if end_time <= start_time:
        raise ValueError(
            "end_time must be after start_time."
        )

    response = cloudwatch.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=[
            {
                "Name": "InstanceId",
                "Value": instance_id,
            },
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=METRIC_PERIOD_SECONDS,
        Statistics=[
            "Average",
            "Minimum",
            "Maximum",
        ],
    )

    result: list[MetricDatapoint] = []

    for item in response.get("Datapoints", []):
        timestamp = item.get("Timestamp")

        if timestamp is None:
            continue

        normalized_timestamp = _ensure_utc(timestamp)

        # Enforce [start_time, end_time).
        if normalized_timestamp < start_time:
            continue

        if normalized_timestamp >= end_time:
            continue

        average = item.get("Average")
        minimum = item.get("Minimum")
        maximum = item.get("Maximum")

        datapoint = MetricDatapoint(
            timestamp=normalized_timestamp,
            average=(
                float(average)
                if average is not None
                else None
            ),
            minimum=(
                float(minimum)
                if minimum is not None
                else None
            ),
            maximum=(
                float(maximum)
                if maximum is not None
                else None
            ),
        )

        # Do not discard zero datapoints here. They represent observed
        # data and must remain available for coverage and auditing.
        result.append(datapoint)

    return result


def collect_metric_interval(
    aws: AwsClient,
    instance_id: str,
    namespace: str,
    metric_name: str,
    start_time: datetime,
    end_time: datetime,
) -> MetricSummary:
    """Collect and summarize one metric over an explicit interval."""

    if not instance_id.strip():
        raise ValueError(
            "EC2 instance ID cannot be empty."
        )

    if not namespace.strip():
        raise ValueError(
            "CloudWatch namespace cannot be empty."
        )

    if not metric_name.strip():
        raise ValueError(
            "CloudWatch metric name cannot be empty."
        )

    start_time = _ensure_utc(start_time)
    end_time = _ensure_utc(end_time)

    if end_time <= start_time:
        raise ValueError(
            "end_time must be after start_time."
        )

    cloudwatch = aws.client("cloudwatch")

    all_datapoints: dict[
        datetime,
        MetricDatapoint,
    ] = {}

    current_start = start_time

    while current_start < end_time:
        current_end = min(
            current_start + timedelta(days=MAX_REQUEST_DAYS),
            end_time,
        )

        interval_datapoints = _get_metric_datapoints(
            cloudwatch=cloudwatch,
            namespace=namespace,
            metric_name=metric_name,
            instance_id=instance_id,
            start_time=current_start,
            end_time=current_end,
        )

        for datapoint in interval_datapoints:
            timestamp = _ensure_utc(datapoint.timestamp)
            all_datapoints[timestamp] = datapoint

        current_start = current_end

    return summarize_metric_datapoints(
        namespace=namespace,
        metric_name=metric_name,
        datapoints=tuple(all_datapoints.values()),
        expected_start=start_time,
        expected_end=end_time,
    )


def collect_ec2_metrics_interval(
    aws: AwsClient,
    instance_id: str,
    start_time: datetime,
    end_time: datetime,
) -> Ec2Metrics:
    """Collect CPU and memory for one explicit evidence interval."""

    if not instance_id.strip():
        raise ValueError(
            "EC2 instance ID cannot be empty."
        )

    start_time = _ensure_utc(start_time)
    end_time = _ensure_utc(end_time)

    if end_time <= start_time:
        raise ValueError(
            "end_time must be after start_time."
        )

    cpu = collect_metric_interval(
        aws=aws,
        instance_id=instance_id,
        namespace=CPU_NAMESPACE,
        metric_name=CPU_METRIC_NAME,
        start_time=start_time,
        end_time=end_time,
    )

    memory = collect_metric_interval(
        aws=aws,
        instance_id=instance_id,
        namespace=MEMORY_NAMESPACE,
        metric_name=MEMORY_METRIC_NAME,
        start_time=start_time,
        end_time=end_time,
    )

    return Ec2Metrics(
        instance_id=instance_id,
        region=aws.region,
        analysis_start=start_time,
        analysis_end=end_time,
        cpu=cpu,
        memory=memory,
    )

def collect_ec2_metrics(
    aws: AwsClient,
    instance_id: str,
    analysis_hours: float,
) -> Ec2Metrics:
    """
    Collect CloudWatch metrics for an EC2 instance.

    On the first day of the month, collect the configured rolling
    analysis_hours window.

    On any subsequent day, collect metrics from the first day of the
    current UTC month until now.
    """

    if not math.isfinite(analysis_hours) or analysis_hours <= 0:
        raise ValueError(
            "analysis_hours must be a finite number greater than zero."
        )

    end_time = datetime.now(timezone.utc)

    if end_time.day > 1:
        # Start at midnight UTC on the first day of this month.
        start_time = end_time.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    else:
        # Preserve the existing rolling window on day one.
        start_time = end_time - timedelta(hours=analysis_hours)

    return collect_ec2_metrics_interval(
        aws=aws,
        instance_id=instance_id,
        start_time=start_time,
        end_time=end_time,
    )