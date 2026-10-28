
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to UTC for database operations."""
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _to_record(row: dict[str, Any] | None):
    """Convert a database row to an AnalysisRunRecord."""
    if row is None:
        return None

    # Import here instead of at module initialization time.
    # This helps prevent circular imports.
    from app.database.models import AnalysisRunRecord

    return AnalysisRunRecord(**row)


class AnalysisRepository:
    """Persistence operations for deterministic analysis runs."""

    def __init__(self, session) -> None:
        self.connection = session

    def create(
        self,
        *,
        instance_id: str,
        region: str,
        execution_run_id: int,
        started_at: datetime,
        analysis_version: str,
    ):
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO analysis_runs (
                    instance_id,
                    region,
                    execution_run_id,
                    started_at,
                    completed_at,
                    status,
                    recommendation,
                    evidence_start,
                    evidence_end,
                    next_eligible_analysis_at,
                    analysis_version,
                    error_message,
                    created_at
                )
                VALUES (
                    %s, %s, %s, %s, NULL, 'RUNNING', 'RUNNING',
                    NULL, NULL, NULL, %s, NULL, %s
                )
                """,
                (
                    instance_id,
                    region,
                    execution_run_id,
                    _utc(started_at),
                    analysis_version,
                    datetime.now(timezone.utc),
                ),
            )
            record_id = cursor.lastrowid

        return self.get_by_id(int(record_id))

    def get_by_id(self, analysis_id: int):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM analysis_runs WHERE id = %s",
                (analysis_id,),
            )
            row = cursor.fetchone()

        return _to_record(row)

    def complete(
        self,
        *,
        analysis_id: int,
        status: str,
        recommendation: str,
        evidence_start: datetime | None,
        evidence_end: datetime | None,
        next_eligible_analysis_at: datetime | None,
        completed_at: datetime | None = None,
    ):
        if self.get_by_id(analysis_id) is None:
            raise LookupError(
                f"Analysis run {analysis_id} was not found."
            )

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE analysis_runs
                SET status = %s,
                    recommendation = %s,
                    evidence_start = %s,
                    evidence_end = %s,
                    next_eligible_analysis_at = %s,
                    completed_at = %s
                WHERE id = %s
                """,
                (
                    status,
                    recommendation,
                    _utc(evidence_start),
                    _utc(evidence_end),
                    _utc(next_eligible_analysis_at),
                    _utc(completed_at) or datetime.now(timezone.utc),
                    analysis_id,
                ),
            )

        return self.get_by_id(analysis_id)

    def fail(
        self,
        *,
        analysis_id: int,
        error_message: str,
        completed_at: datetime | None = None,
    ):
        if self.get_by_id(analysis_id) is None:
            raise LookupError(
                f"Analysis run {analysis_id} was not found."
            )

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE analysis_runs
                SET status = 'FAILED',
                    recommendation = 'INSUFFICIENT_DATA',
                    completed_at = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    _utc(completed_at) or datetime.now(timezone.utc),
                    error_message,
                    analysis_id,
                ),
            )

        return self.get_by_id(analysis_id)

    def get_latest(
        self,
        *,
        instance_id: str,
        region: str,
    ):
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM analysis_runs
                WHERE instance_id = %s AND region = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (instance_id, region),
            )
            row = cursor.fetchone()

        return _to_record(row)

    def get_earliest(
        self,
        *,
        instance_id: str,
        region: str,
    ):
        """Return the earliest recorded analysis for this instance."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM analysis_runs
                WHERE instance_id = %s AND region = %s
                ORDER BY started_at ASC, id ASC
                LIMIT 1
                """,
                (instance_id, region),
            )
            row = cursor.fetchone()

        return _to_record(row)
