from __future__ import annotations

from datetime import datetime, timezone

from app.database.models import MetricCollectionCheckpointRecord


class MetricCheckpointRepository:
    """Persist and retrieve per-metric collection checkpoints."""
    def __init__(self, session) -> None: self._connection = session

    def get_checkpoint(self, *, instance_id: str, region: str, namespace: str,
                       metric_name: str, configuration_version: str) -> datetime | None:
        self._validate_identity(instance_id=instance_id, region=region, namespace=namespace,
                                metric_name=metric_name, configuration_version=configuration_version)
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT checkpoint_at FROM metric_collection_checkpoints
                WHERE instance_id=%s AND region=%s AND namespace=%s AND metric_name=%s
                  AND configuration_version=%s
            """, (instance_id, region, namespace, metric_name, configuration_version))
            row = cursor.fetchone()
        return self._normalise_datetime(row["checkpoint_at"]) if row else None

    def save_checkpoint(self, *, instance_id: str, region: str, namespace: str,
                        metric_name: str, configuration_version: str,
                        checkpoint_at: datetime) -> None:
        self._validate_identity(instance_id=instance_id, region=region, namespace=namespace,
                                metric_name=metric_name, configuration_version=configuration_version)
        checkpoint_at = self._normalise_datetime(checkpoint_at)
        updated_at = datetime.now(timezone.utc)
        with self._connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO metric_collection_checkpoints
                (instance_id, region, namespace, metric_name, configuration_version, checkpoint_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE checkpoint_at=VALUES(checkpoint_at), updated_at=VALUES(updated_at)
            """, (instance_id, region, namespace, metric_name, configuration_version, checkpoint_at, updated_at))

    def replace_checkpoint(self, *, instance_id: str, region: str, namespace: str,
                           metric_name: str, configuration_version: str,
                           checkpoint_at: datetime) -> None:
        self._validate_identity(instance_id=instance_id, region=region, namespace=namespace,
                                metric_name=metric_name, configuration_version=configuration_version)
        checkpoint_at = self._normalise_datetime(checkpoint_at)
        updated_at = datetime.now(timezone.utc)
        with self._connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO metric_collection_checkpoints
                (instance_id, region, namespace, metric_name, configuration_version, checkpoint_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE checkpoint_at=VALUES(checkpoint_at), updated_at=VALUES(updated_at)
            """, (instance_id, region, namespace, metric_name, configuration_version, checkpoint_at, updated_at))

    @staticmethod
    def _normalise_datetime(value: datetime) -> datetime:
        if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _validate_identity(*, instance_id: str, region: str, namespace: str,
                           metric_name: str, configuration_version: str) -> None:
        for value, label in ((instance_id, "EC2 instance ID"), (region, "AWS region"),
                             (namespace, "Metric namespace"), (metric_name, "Metric name"),
                             (configuration_version, "configuration_version")):
            if not value.strip(): raise ValueError(f"{label} cannot be empty.")
