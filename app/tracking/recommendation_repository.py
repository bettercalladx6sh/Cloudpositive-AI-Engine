from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database.models import RecommendationRecord
from app.analysis.recommendation_lifecycle import RecommendationLifecycleResult, RecommendationStatus


class RecommendationRepository:
    """Persistence operations for deterministic recommendations."""
    def __init__(self, session) -> None: self.connection = session

    def create(self, *, instance_id: str, region: str, analysis_id: int,
               recommendation: str, recommended_instance: str | None,
               created_at: datetime, cooldown_days: int) -> RecommendationRecord:
        if cooldown_days < 0: raise ValueError("cooldown_days cannot be negative.")
        created_at = self._utc(created_at)
        next_eligible = created_at + timedelta(days=cooldown_days)
        with self.connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO recommendations
                (instance_id, region, analysis_id, recommendation, recommended_instance,
                 created_at, status, actioned_at, expired_at, next_eligible_analysis_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,NULL,%s)
            """, (instance_id, region, analysis_id, recommendation, recommended_instance,
                  created_at, RecommendationStatus.PENDING.value, next_eligible))
            record_id = cursor.lastrowid
        return self.get_by_id(int(record_id))

    def get_by_id(self, recommendation_id: int) -> RecommendationRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM recommendations WHERE id=%s", (recommendation_id,))
            row = cursor.fetchone()
        return RecommendationRecord(**row) if row else None

    def get_latest_active(self, *, instance_id: str, region: str) -> RecommendationRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM recommendations
                WHERE instance_id=%s AND region=%s AND status IN ('PENDING','ACTIONED')
                ORDER BY created_at DESC LIMIT 1
            """, (instance_id, region))
            row = cursor.fetchone()
        return RecommendationRecord(**row) if row else None

    def mark_actioned(self, *, recommendation_id: int, actioned_at: datetime | None = None,
                      cooldown_days: int) -> RecommendationRecord:
        if cooldown_days < 0: raise ValueError("cooldown_days cannot be negative.")
        record = self.get_by_id(recommendation_id)
        if record is None: raise LookupError(f"Recommendation {recommendation_id} was not found.")
        if record.status != RecommendationStatus.PENDING.value: raise ValueError("Only PENDING recommendations can be marked ACTIONED.")
        actioned_at = self._utc(actioned_at or datetime.now(timezone.utc))
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE recommendations SET status='ACTIONED', actioned_at=%s, next_eligible_analysis_at=%s WHERE id=%s",
                           (actioned_at, actioned_at + timedelta(days=cooldown_days), recommendation_id))
        return self.get_by_id(recommendation_id)

    def expire(self, *, recommendation_id: int, expired_at: datetime | None = None) -> RecommendationRecord:
        record = self.get_by_id(recommendation_id)
        if record is None: raise LookupError(f"Recommendation {recommendation_id} was not found.")
        if record.status == RecommendationStatus.EXPIRED.value: return record
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE recommendations SET status='EXPIRED', expired_at=%s WHERE id=%s",
                           (self._utc(expired_at or datetime.now(timezone.utc)), recommendation_id))
        return self.get_by_id(recommendation_id)

    def apply_lifecycle_result(self, *, recommendation_id: int,
                               lifecycle_result: RecommendationLifecycleResult) -> RecommendationRecord:
        record = self.get_by_id(recommendation_id)
        if record is None: raise LookupError(f"Recommendation {recommendation_id} was not found.")
        expired_at = record.expired_at
        if lifecycle_result.status == RecommendationStatus.EXPIRED and expired_at is None:
            expired_at = datetime.now(timezone.utc)
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE recommendations SET status=%s, next_eligible_analysis_at=%s, expired_at=%s WHERE id=%s",
                           (lifecycle_result.status.value, self._utc(lifecycle_result.next_eligible_analysis_at), expired_at, recommendation_id))
        return self.get_by_id(recommendation_id)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
