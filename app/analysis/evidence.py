from __future__ import annotations

from datetime import datetime, timezone

from app.tracking.metric_repository import MetricRepository
from app.tracking.models import EvidenceStatus
from app.tracking.repository import SnapshotRepository


# Do not lower these thresholds.
MIN_METRIC_COVERAGE = 1


def _configuration_age_hours(
    session,
    instance_id: str,
    region: str,
    configuration_version: str,
    now: datetime,
) -> float:
    """Return observed history for the current configuration version."""
    if not configuration_version.strip():
        raise ValueError("configuration_version cannot be empty.")

    repository = SnapshotRepository(session)

    history = repository.get_history(
        instance_id=instance_id,
        region=region,
    )

    matching_snapshots = [
        snapshot
        for snapshot in history
        if snapshot.configuration_version == configuration_version
    ]

    if not matching_snapshots:
        return 0.0

    oldest = min(
        snapshot.observed_at
        for snapshot in matching_snapshots
    )

    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    else:
        oldest = oldest.astimezone(timezone.utc)

    return max(
        (now - oldest).total_seconds() / 3600.0,
        0.0,
    )


def _metric_sufficient(
    *,
    coverage_hours: float,
    required_evidence_hours: float,
) -> bool:
    """Require at least 90% metric coverage."""
    if required_evidence_hours <= 0:
        return False

    return (
        coverage_hours / required_evidence_hours
        >= MIN_METRIC_COVERAGE
    )


def _calculate_evidence_score(
    *,
    configuration_sufficient: bool,
    cpu_sufficient: bool,
    memory_sufficient: bool,
) -> int:
    """Calculate evidence completeness, not confidence or probability."""
    checks = (
        configuration_sufficient,
        cpu_sufficient,
        memory_sufficient,
    )

    passed = sum(1 for check in checks if check)

    return int(round(passed / len(checks) * 100))


def evaluate_evidence(
    session,
    instance_id: str,
    region: str,
    current_instance_type: str,
    instance_state: str,
    required_evidence_hours: float,
    configuration_version: str,
) -> EvidenceStatus:
    """
    Proceed only when configuration history and required metric coverage
    are sufficient for the requested analysis period.

    Metrics from previous configuration versions are never combined with
    evidence for the current configuration.
    """
    if not configuration_version.strip():
        raise ValueError("configuration_version cannot be empty.")

    if required_evidence_hours <= 0:
        raise ValueError(
            "required_evidence_hours must be greater than zero."
        )

    now = datetime.now(timezone.utc)

    configuration_age_hours = _configuration_age_hours(
        session=session,
        instance_id=instance_id,
        region=region,
        configuration_version=configuration_version,
        now=now,
    )

    configuration_age_days = configuration_age_hours / 24.0
    required_days = required_evidence_hours / 24.0

    # The configuration must cover the FULL requested period.
    configuration_sufficient = (
        configuration_age_hours >= required_evidence_hours
    )

    is_stopped = instance_state.lower() == "stopped"

    cpu_coverage = 0.0
    memory_coverage = 0.0

    if is_stopped:
        # Utilization metrics are not required for stopped instances.
        cpu_sufficient = True
        memory_sufficient = True
    else:
        metric_repository = MetricRepository(session)

        cpu_history = metric_repository.get_history(
            instance_id=instance_id,
            region=region,
            metric_name="CPUUtilization",
            configuration_version=configuration_version,
        )

        memory_history = metric_repository.get_history(
            instance_id=instance_id,
            region=region,
            metric_name="mem_used_percent",
            configuration_version=configuration_version,
        )

        cpu_coverage = max(
            (record.coverage_hours for record in cpu_history),
            default=0.0,
        )

        memory_coverage = max(
            (record.coverage_hours for record in memory_history),
            default=0.0,
        )

        cpu_sufficient = _metric_sufficient(
            coverage_hours=cpu_coverage,
            required_evidence_hours=required_evidence_hours,
        )

        memory_sufficient = _metric_sufficient(
            coverage_hours=memory_coverage,
            required_evidence_hours=required_evidence_hours,
        )

    minimum_metric_hours = (
        required_evidence_hours * MIN_METRIC_COVERAGE
    )

    missing_evidence: list[str] = []

    if not configuration_sufficient:
        missing_evidence.append(
            "Current configuration version has only "
            f"{configuration_age_hours:.1f} hours of observed history; "
            f"{required_evidence_hours:.1f} hours "
            f"({required_days:.2f} days) are required."
        )

    if not is_stopped:
        if not cpu_sufficient:
            missing_evidence.append(
                "CPU evidence coverage for the current configuration "
                f"is {cpu_coverage:.1f} hours; at least "
                f"{minimum_metric_hours:.1f} hours "
                f"({MIN_METRIC_COVERAGE:.0%} coverage) are required."
            )

        if not memory_sufficient:
            missing_evidence.append(
                "Memory evidence coverage for the current configuration "
                f"is {memory_coverage:.1f} hours; at least "
                f"{minimum_metric_hours:.1f} hours "
                f"({MIN_METRIC_COVERAGE:.0%} coverage) are required."
            )

    evidence_score = _calculate_evidence_score(
        configuration_sufficient=configuration_sufficient,
        cpu_sufficient=cpu_sufficient,
        memory_sufficient=memory_sufficient,
    )

    sufficient = (
        configuration_sufficient
        and cpu_sufficient
        and memory_sufficient
    )

    return EvidenceStatus(
        sufficient=sufficient,
        evidence_score=evidence_score,
        configuration_age_days=configuration_age_days,
        required_days=required_days,
        cpu_data_sufficient=cpu_sufficient,
        memory_data_sufficient=memory_sufficient,
        missing_evidence=tuple(missing_evidence),
    )
