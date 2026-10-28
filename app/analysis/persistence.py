from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.tracking.analysis_repository import AnalysisRepository
from app.tracking.recommendation_repository import (
    RecommendationRepository,
)
from app.tracking.recommendation_snapshot_repository import (
    RecommendationSnapshotRepository,
)


@dataclass(frozen=True)
class AnalysisPersistenceResult:
    """
    Database records created for one completed deterministic analysis.
    """

    analysis_id: int
    recommendation_id: int | None
    snapshot_id: int


class AnalysisPersistenceService:
    """
    Persist one completed deterministic EC2 analysis.

    This service does not make AWS calls and does not make
    optimization decisions.

    Python deterministic analysis remains authoritative.
    """

    def __init__(
        self,
        session,
    ) -> None:
        self.session = session

        self.analysis_repository = (
            AnalysisRepository(session)
        )

        self.recommendation_repository = (
            RecommendationRepository(session)
        )

        self.snapshot_repository = (
            RecommendationSnapshotRepository(session)
        )

    def create_analysis(
        self,
        *,
        instance_id: str,
        region: str,
        execution_run_id: int,
        started_at: datetime,
        analysis_version: str,
    ):
        """
        Create a RUNNING analysis record.

        The caller owns the transaction.
        """

        return self.analysis_repository.create(
            instance_id=instance_id,
            region=region,
            execution_run_id=execution_run_id,
            started_at=started_at,
            analysis_version=analysis_version,
        )

    def complete_analysis(
        self,
        *,
        analysis_id: int,
        status: str,
        recommendation: str,
        evidence_start: datetime | None,
        evidence_end: datetime | None,
        next_eligible_analysis_at: datetime | None,
    ):
        """
        Complete an existing analysis run.

        The caller owns the transaction.
        """

        return self.analysis_repository.complete(
            analysis_id=analysis_id,
            status=status,
            recommendation=recommendation,
            evidence_start=evidence_start,
            evidence_end=evidence_end,
            next_eligible_analysis_at=(
                next_eligible_analysis_at
            ),
        )

    def create_recommendation(
        self,
        *,
        instance_id: str,
        region: str,
        analysis_id: int,
        recommendation: str,
        recommended_instance: str | None,
        created_at: datetime,
        cooldown_days: int,
    ):
        """
        Persist a deterministic recommendation.

        The caller must decide whether the recommendation is
        eligible to enter the recommendation lifecycle.
        """

        return self.recommendation_repository.create(
            instance_id=instance_id,
            region=region,
            analysis_id=analysis_id,
            recommendation=recommendation,
            recommended_instance=recommended_instance,
            created_at=created_at,
            cooldown_days=cooldown_days,
        )

    def create_snapshot(
        self,
        *,
        instance_id: str,
        region: str,
        analysis_id: int,
        configuration_version: str,
        instance_type: str,
        instance_state: str,
        recommendation: str,
        recommended_instance: str | None,
        cpu_average: float | None,
        cpu_minimum: float | None,
        cpu_maximum: float | None,
        memory_average: float | None,
        memory_minimum: float | None,
        memory_maximum: float | None,
        cpu_datapoint_count: int,
        memory_datapoint_count: int,
        evidence_start: datetime | None,
        evidence_end: datetime | None,
        reason: str,
        concerns: str | None,
        missing_evidence: str | None,
        created_at: datetime | None = None,
    ):
        """
        Persist an immutable deterministic recommendation snapshot.

        AI reasoning is deliberately excluded.
        """

        return self.snapshot_repository.create(
            instance_id=instance_id,
            region=region,
            analysis_id=analysis_id,
            configuration_version=configuration_version,
            instance_type=instance_type,
            instance_state=instance_state,
            recommendation=recommendation,
            recommended_instance=recommended_instance,
            cpu_average=cpu_average,
            cpu_minimum=cpu_minimum,
            cpu_maximum=cpu_maximum,
            memory_average=memory_average,
            memory_minimum=memory_minimum,
            memory_maximum=memory_maximum,
            cpu_datapoint_count=cpu_datapoint_count,
            memory_datapoint_count=memory_datapoint_count,
            evidence_start=evidence_start,
            evidence_end=evidence_end,
            reason=reason,
            concerns=concerns,
            missing_evidence=missing_evidence,
            created_at=(
                created_at
                or datetime.now(timezone.utc)
            ),
        )