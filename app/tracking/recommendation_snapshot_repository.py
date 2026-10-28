from __future__ import annotations

from datetime import datetime, timezone

from app.database.models import RecommendationSnapshotRecord


class RecommendationSnapshotRepository:
    """Persistence operations for immutable recommendation snapshots."""
    def __init__(self, session) -> None: self.connection = session

    def create(self, *, instance_id: str, region: str, analysis_id: int,
               configuration_version: str, instance_type: str, instance_state: str,
               recommendation: str, recommended_instance: str | None,
               cpu_average: float | None, cpu_minimum: float | None, cpu_maximum: float | None,
               memory_average: float | None, memory_minimum: float | None, memory_maximum: float | None,
               cpu_datapoint_count: int, memory_datapoint_count: int,
               evidence_start: datetime | None, evidence_end: datetime | None,
               reason: str, concerns: str | None, missing_evidence: str | None,
               created_at: datetime) -> RecommendationSnapshotRecord:
        with self.connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO recommendation_snapshots
                (instance_id, region, analysis_id, configuration_version, instance_type,
                 instance_state, recommendation, recommended_instance, cpu_average, cpu_minimum,
                 cpu_maximum, memory_average, memory_minimum, memory_maximum,
                 cpu_datapoint_count, memory_datapoint_count, evidence_start, evidence_end,
                 reason, concerns, missing_evidence, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (instance_id, region, analysis_id, configuration_version, instance_type, instance_state,
                  recommendation, recommended_instance, cpu_average, cpu_minimum, cpu_maximum,
                  memory_average, memory_minimum, memory_maximum, cpu_datapoint_count,
                  memory_datapoint_count, self._utc(evidence_start), self._utc(evidence_end),
                  reason, concerns, missing_evidence, self._utc(created_at)))
            record_id = cursor.lastrowid
        return self.get_by_id(int(record_id))

    def get_by_id(self, snapshot_id: int) -> RecommendationSnapshotRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM recommendation_snapshots WHERE id=%s", (snapshot_id,))
            row = cursor.fetchone()
        return RecommendationSnapshotRecord(**row) if row else None

    def get_latest(self, *, instance_id: str, region: str) -> RecommendationSnapshotRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM recommendation_snapshots WHERE instance_id=%s AND region=%s
                ORDER BY created_at DESC, id DESC LIMIT 1
            """, (instance_id, region))
            row = cursor.fetchone()
        return RecommendationSnapshotRecord(**row) if row else None

    def list_for_instance(self, *, instance_id: str, region: str) -> list[RecommendationSnapshotRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM recommendation_snapshots WHERE instance_id=%s AND region=%s
                ORDER BY created_at DESC, id DESC
            """, (instance_id, region))
            rows = cursor.fetchall()
        return [RecommendationSnapshotRecord(**row) for row in rows]

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None: return None
        if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
