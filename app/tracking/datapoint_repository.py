from __future__ import annotations

from datetime import datetime, timezone

from app.ec2.metrics import MetricDatapoint


class DatapointRepository:
    """Repository for raw CloudWatch metric datapoints in MySQL."""
    def __init__(self, session) -> None: self._connection = session

    def save_many(self, *, instance_id: str, region: str, namespace: str,
                  metric_name: str, configuration_version: str,
                  datapoints: tuple[MetricDatapoint, ...], observed_at: datetime) -> None:
        if not configuration_version.strip(): raise ValueError("configuration_version cannot be empty.")
        if not datapoints: return
        observed_at = self._normalise_datetime(observed_at)
        sql = """
            INSERT IGNORE INTO metric_datapoints
            (instance_id, region, namespace, metric_name, configuration_version,
             timestamp, average, minimum, maximum, observed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        rows = [(instance_id, region, namespace, metric_name, configuration_version,
                 self._normalise_datetime(dp.timestamp), dp.average, dp.minimum,
                 dp.maximum, observed_at) for dp in datapoints]
        with self._connection.cursor() as cursor: cursor.executemany(sql, rows)

    def get_range(self, *, instance_id: str, region: str, namespace: str,
                  metric_name: str, configuration_version: str,
                  start_time: datetime, end_time: datetime) -> tuple[MetricDatapoint, ...]:
        if not configuration_version.strip(): raise ValueError("configuration_version cannot be empty.")
        start_time, end_time = self._normalise_datetime(start_time), self._normalise_datetime(end_time)
        if end_time <= start_time: raise ValueError("end_time must be after start_time.")
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT timestamp, average, minimum, maximum FROM metric_datapoints
                WHERE instance_id=%s AND region=%s AND namespace=%s AND metric_name=%s
                  AND configuration_version=%s AND timestamp >= %s AND timestamp < %s
                ORDER BY timestamp
            """, (instance_id, region, namespace, metric_name, configuration_version, start_time, end_time))
            rows = cursor.fetchall()
        return tuple(self._record_to_datapoint(row) for row in rows)

    def get_all(self, *, instance_id: str, region: str, namespace: str,
                metric_name: str, configuration_version: str) -> tuple[MetricDatapoint, ...]:
        if not configuration_version.strip(): raise ValueError("configuration_version cannot be empty.")
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT timestamp, average, minimum, maximum FROM metric_datapoints
                WHERE instance_id=%s AND region=%s AND namespace=%s AND metric_name=%s
                  AND configuration_version=%s ORDER BY timestamp
            """, (instance_id, region, namespace, metric_name, configuration_version))
            rows = cursor.fetchall()
        return tuple(self._record_to_datapoint(row) for row in rows)

    @staticmethod
    def _normalise_datetime(value: datetime) -> datetime:
        if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _record_to_datapoint(cls, record: dict) -> MetricDatapoint:
        return MetricDatapoint(timestamp=cls._normalise_datetime(record["timestamp"]),
                               average=record["average"], minimum=record["minimum"], maximum=record["maximum"])
