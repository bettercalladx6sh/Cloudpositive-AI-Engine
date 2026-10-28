from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from app.aws.client import AwsClient
from app.ec2.metrics import (
    CPU_METRIC_NAME,
    CPU_NAMESPACE,
    MEMORY_METRIC_NAME,
    MEMORY_NAMESPACE,
    METRIC_PERIOD_SECONDS,
    MetricDatapoint,
    MetricSummary,
    collect_metric_interval,
    summarize_metric_datapoints,
)
from app.tracking.analysis_repository import AnalysisRepository
from app.tracking.cumulative_metrics import calculate_cumulative_summary
from app.tracking.cumulative_repository import MetricCumulativeRepository
from app.tracking.datapoint_repository import DatapointRepository
from app.tracking.metric_checkpoint_repository import MetricCheckpointRepository
from app.tracking.metric_repository import MetricRepository


# A missing CloudWatch interval is not queried again on every program run.
# If the latest observation for the same fixed window is younger than this,
# retry is deferred. This uses existing tables and does not alter the schema.
MISSING_INTERVAL_RETRY_COOLDOWN_HOURS = 6


@dataclass(frozen=True)
class Ec2Metrics:
    cpu: MetricSummary
    memory: MetricSummary


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _floor_hour(value: datetime) -> datetime:
    value = _normalise_datetime(value)
    return value.replace(minute=0, second=0, microsecond=0)


def _get_history(
    *,
    datapoint_repository: DatapointRepository,
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    configuration_version: str,
) -> tuple[MetricDatapoint, ...]:
    return datapoint_repository.get_all(
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
    )


def _get_persisted_window_start(
    *,
    session,
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    configuration_version: str,
) -> datetime | None:
    """Read the original window start from existing metric observations."""
    with session.cursor() as cursor:
        cursor.execute(
            """
            SELECT analysis_start
            FROM metric_observations
            WHERE instance_id = %s
              AND region = %s
              AND namespace = %s
              AND metric_name = %s
              AND configuration_version = %s
              AND analysis_start IS NOT NULL
            ORDER BY observed_at ASC, id ASC
            LIMIT 1
            """,
            (instance_id, region, namespace, metric_name, configuration_version),
        )
        row = cursor.fetchone()
    if not row:
        return None
    value = row["analysis_start"] if isinstance(row, dict) else row[0]
    return _normalise_datetime(value)


def _get_recent_observation_time(
    *,
    session,
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    configuration_version: str,
    analysis_start: datetime,
    analysis_end: datetime,
) -> datetime | None:
    """Return the latest attempt time for this exact evidence window."""
    with session.cursor() as cursor:
        cursor.execute(
            """
            SELECT MAX(observed_at) AS latest_observed_at
            FROM metric_observations
            WHERE instance_id = %s
              AND region = %s
              AND namespace = %s
              AND metric_name = %s
              AND configuration_version = %s
              AND analysis_start = %s
              AND analysis_end = %s
            """,
            (
                instance_id,
                region,
                namespace,
                metric_name,
                configuration_version,
                analysis_start.replace(tzinfo=None),
                analysis_end.replace(tzinfo=None),
            ),
        )
        row = cursor.fetchone()
    if not row:
        return None
    value = row.get("latest_observed_at") if isinstance(row, dict) else row[0]
    return _normalise_datetime(value) if value is not None else None

def _choose_window(
    *,
    session,
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    configuration_version: str,
    analysis_hours: float,
    now: datetime,
) -> tuple[datetime, datetime]:
    """
    Always use the latest requested analysis window.

    Example:
        analysis_hours = 120
        start = current time minus 120 hours, rounded down to the hour
        end = current completed UTC hour

    Previously saved observations must not override the requested start.
    """
    analysis_end = _floor_hour(now)
    analysis_start = _floor_hour(
        now - timedelta(hours=analysis_hours)
    )

    return analysis_start, analysis_end

def _get_analysis_datapoints(
    *,
    history: tuple[MetricDatapoint, ...],
    analysis_start: datetime,
    analysis_end: datetime,
) -> tuple[MetricDatapoint, ...]:
    start = _normalise_datetime(analysis_start)
    end = _normalise_datetime(analysis_end)
    by_timestamp: dict[datetime, MetricDatapoint] = {}
    for datapoint in history:
        timestamp = _normalise_datetime(datapoint.timestamp)
        if start <= timestamp < end:
            by_timestamp[timestamp] = MetricDatapoint(
                timestamp=timestamp,
                average=datapoint.average,
                minimum=datapoint.minimum,
                maximum=datapoint.maximum,
            )
    return tuple(by_timestamp[key] for key in sorted(by_timestamp))


def _find_missing_intervals(
    *,
    history: tuple[MetricDatapoint, ...],
    analysis_start: datetime,
    analysis_end: datetime,
) -> tuple[tuple[datetime, datetime], ...]:
    """Return contiguous ranges of absent hourly datapoint timestamps only."""
    start = _floor_hour(analysis_start)
    end = _floor_hour(analysis_end)
    if end <= start:
        return ()

    expected = int((end - start).total_seconds() // METRIC_PERIOD_SECONDS)
    existing_hours = {
        _floor_hour(_normalise_datetime(point.timestamp))
        for point in history
        if start <= _normalise_datetime(point.timestamp) < end
    }
    missing = [
        start + timedelta(seconds=METRIC_PERIOD_SECONDS * index)
        for index in range(expected)
        if start + timedelta(seconds=METRIC_PERIOD_SECONDS * index) not in existing_hours
    ]
    if not missing:
        return ()

    intervals: list[tuple[datetime, datetime]] = []
    interval_start = previous = missing[0]
    one_hour = timedelta(seconds=METRIC_PERIOD_SECONDS)
    for hour in missing[1:]:
        if hour != previous + one_hour:
            intervals.append((interval_start, previous + one_hour))
            interval_start = hour
        previous = hour
    intervals.append((interval_start, previous + one_hour))
    return tuple(intervals)


def _collect_missing_intervals(
    *,
    aws: AwsClient,
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    configuration_version: str,
    analysis_start: datetime,
    analysis_end: datetime,
    history: tuple[MetricDatapoint, ...],
    session,
) -> None:
    """
    Fetch missing hourly CloudWatch datapoints in the requested window.

    Missing intervals are checked on every run. Existing datapoints are
    preserved, and no synthetic zero-valued datapoints are created.
    """
    intervals = _find_missing_intervals(
        history=history,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
    )

    if not intervals:
        return

    repository = DatapointRepository(session)

    for start, end in intervals:
        summary = collect_metric_interval(
            aws=aws,
            instance_id=instance_id,
            namespace=namespace,
            metric_name=metric_name,
            start_time=start,
            end_time=end,
        )

        if not summary.datapoints:
            continue

        repository.save_many(
            instance_id=instance_id,
            region=region,
            namespace=namespace,
            metric_name=metric_name,
            configuration_version=configuration_version,
            datapoints=summary.datapoints,
            observed_at=_utc_now(),
        )
def _update_checkpoint(
    *,
    checkpoint_repository: MetricCheckpointRepository,
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    configuration_version: str,
    history: tuple[MetricDatapoint, ...],
    analysis_start: datetime,
    analysis_end: datetime,
) -> None:
    points = _get_analysis_datapoints(
        history=history,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
    )
    if not points:
        return
    latest = max(_normalise_datetime(point.timestamp) for point in points)
    current = checkpoint_repository.get_checkpoint(
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
    )
    if current is None or latest > _normalise_datetime(current):
        checkpoint_repository.save_checkpoint(
            instance_id=instance_id,
            region=region,
            namespace=namespace,
            metric_name=metric_name,
            configuration_version=configuration_version,
            checkpoint_at=latest,
        )
    elif latest < _normalise_datetime(current):
        checkpoint_repository.replace_checkpoint(
            instance_id=instance_id,
            region=region,
            namespace=namespace,
            metric_name=metric_name,
            configuration_version=configuration_version,
            checkpoint_at=latest,
        )


def _update_metric_observation(
    *,
    session,
    instance_id: str,
    region: str,
    metric: MetricSummary,
    configuration_version: str,
    analysis_start: datetime,
    analysis_end: datetime,
) -> None:
    MetricRepository(session).save(
        instance_id=instance_id,
        region=region,
        metric=metric,
        configuration_version=configuration_version,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
        observed_at=_utc_now(),
    )


def _update_cumulative_summary(
    *,
    session,
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    configuration_version: str,
) -> None:
    points = DatapointRepository(session).get_all(
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
    )
    summary = calculate_cumulative_summary(
        datapoints=points,
        period_seconds=METRIC_PERIOD_SECONDS,
    )
    MetricCumulativeRepository(session).save(
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
        evidence_start=summary.evidence_start,
        evidence_end=summary.evidence_end,
        datapoint_count=summary.datapoint_count,
        value_sum=summary.value_sum,
        average=summary.average,
        minimum=summary.minimum,
        maximum=summary.maximum,
        p50=summary.p50,
        p95=summary.p95,
        p99=summary.p99,
        standard_deviation=summary.standard_deviation,
        trend=summary.trend,
        volatility=summary.volatility,
        coverage_percent=summary.coverage_percent,
        gap_count=summary.gap_count,
        last_updated_at=_utc_now(),
    )


def _track_metric(
    *,
    aws: AwsClient,
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    analysis_hours: float,
    configuration_version: str,
    session,
) -> MetricSummary:
    now = _utc_now()
    datapoint_repository = DatapointRepository(session)
    checkpoint_repository = MetricCheckpointRepository(session)

    # Always inspect persisted evidence before deciding whether to call AWS.
    history = _get_history(
        datapoint_repository=datapoint_repository,
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
    )
    analysis_start, analysis_end = _choose_window(
        session=session,
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
        analysis_hours=analysis_hours,
        now=now,
    )

    _collect_missing_intervals(
        aws=aws,
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
        history=history,
        session=session,
    )

    refreshed_history = _get_history(
        datapoint_repository=datapoint_repository,
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
    )
    window_points = _get_analysis_datapoints(
        history=refreshed_history,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
    )
    summary = summarize_metric_datapoints(
        namespace=namespace,
        metric_name=metric_name,
        datapoints=window_points,
        expected_start=analysis_start,
        expected_end=analysis_end,
    )
    _update_metric_observation(
        session=session,
        instance_id=instance_id,
        region=region,
        metric=summary,
        configuration_version=configuration_version,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
    )
    _update_cumulative_summary(
        session=session,
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
    )
    _update_checkpoint(
        checkpoint_repository=checkpoint_repository,
        instance_id=instance_id,
        region=region,
        namespace=namespace,
        metric_name=metric_name,
        configuration_version=configuration_version,
        history=refreshed_history,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
    )
    session.commit()
    return summary


def track_metrics(
    *,
    aws: AwsClient,
    instance_id: str,
    analysis_hours: float,
    session,
    configuration_version: str,
) -> Ec2Metrics:
    """Collect only missing CPU and memory hours for one EC2 configuration."""
    if not instance_id.strip():
        raise ValueError("EC2 instance ID cannot be empty.")
    if not math.isfinite(analysis_hours) or analysis_hours <= 0:
        raise ValueError("analysis_hours must be finite and greater than zero.")
    if not configuration_version.strip():
        raise ValueError("configuration_version cannot be empty.")

    region = aws.region
    cpu = _track_metric(
        aws=aws,
        instance_id=instance_id,
        region=region,
        namespace=CPU_NAMESPACE,
        metric_name=CPU_METRIC_NAME,
        analysis_hours=analysis_hours,
        configuration_version=configuration_version,
        session=session,
    )
    memory = _track_metric(
        aws=aws,
        instance_id=instance_id,
        region=region,
        namespace=MEMORY_NAMESPACE,
        metric_name=MEMORY_METRIC_NAME,
        analysis_hours=analysis_hours,
        configuration_version=configuration_version,
        session=session,
    )
    return Ec2Metrics(cpu=cpu, memory=memory)
