from __future__ import annotations

from datetime import datetime, timezone

from app.database.models import MetricObservationRecord
from app.ec2.metrics import MetricSummary


class MetricRepository:
    """Repository for CloudWatch metric collection summaries."""
    def __init__(self, session) -> None: self._connection = session

    def save(self, *, instance_id: str, region: str, metric: MetricSummary,
             configuration_version: str, analysis_start: datetime,
             analysis_end: datetime, observed_at: datetime) -> None:
        if not configuration_version.strip(): raise ValueError("configuration_version cannot be empty.")
        observed_at = self._utc(observed_at)
        with self._connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO metric_observations
                (instance_id, region, namespace, metric_name, configuration_version,
                 average, minimum, maximum, datapoint_count, first_datapoint,
                 last_datapoint, coverage_hours, analysis_start, analysis_end, observed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (instance_id, region, metric.namespace, metric.metric_name,
                  configuration_version, metric.average, metric.minimum, metric.maximum,
                  metric.datapoint_count, metric.first_datapoint, metric.last_datapoint,
                  metric.coverage_hours, analysis_start, analysis_end, observed_at))

    def get_history(self, *, instance_id: str, region: str, metric_name: str,
                    configuration_version: str) -> tuple[MetricObservationRecord, ...]:
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM metric_observations
                WHERE instance_id=%s AND region=%s AND metric_name=%s
                  AND configuration_version=%s
                ORDER BY observed_at DESC, id DESC
            """, (instance_id, region, metric_name, configuration_version))
            rows = cursor.fetchall()
        return tuple(MetricObservationRecord(**row) for row in rows)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
