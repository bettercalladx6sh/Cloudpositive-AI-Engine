from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class EligibilityAction(str, Enum):
    """
    Action the application should take for a resource.
    """

    ANALYZE = "ANALYZE"
    COLLECT_DATA = "COLLECT_DATA"
    SKIP = "SKIP"


class EligibilityReason(str, Enum):
    """
    Machine-readable reason for an eligibility decision.
    """

    NO_PRIOR_ANALYSIS = "NO_PRIOR_ANALYSIS"
    ANALYSIS_COOLDOWN_ACTIVE = "ANALYSIS_COOLDOWN_ACTIVE"
    RECOMMENDATION_COOLDOWN_ACTIVE = (
        "RECOMMENDATION_COOLDOWN_ACTIVE"
    )
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
    CONFIGURATION_STABILIZING = "CONFIGURATION_STABILIZING"


@dataclass(frozen=True)
class EligibilityInput:
    """
    Persisted state required to determine whether a resource
    can be analyzed.

    This class deliberately contains no AWS objects.
    """

    now: datetime

    has_prior_analysis: bool

    next_eligible_analysis_at: datetime | None

    recommendation_status: str | None

    recommendation_created_at: datetime | None

    recommendation_actioned_at: datetime | None

    recommendation_expired_at: datetime | None

    evidence_sufficient: bool

    configuration_changed_at: datetime | None

    stabilization_hours: float


@dataclass(frozen=True)
class EligibilityResult:
    """
    Deterministic eligibility decision.
    """

    action: EligibilityAction
    reason: EligibilityReason
    eligible_at: datetime | None
    message: str


ACTIVE_RECOMMENDATION_STATUSES = frozenset(
    {
        "PENDING",
        "ACTIONED",
    }
)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _configuration_is_stabilizing(
    *,
    now: datetime,
    configuration_changed_at: datetime | None,
    stabilization_hours: float,
) -> bool:
    if configuration_changed_at is None:
        return False

    if stabilization_hours <= 0:
        return False

    changed_at = _ensure_utc(configuration_changed_at)
    elapsed_seconds = (
        _ensure_utc(now) - changed_at
    ).total_seconds()

    required_seconds = stabilization_hours * 3600.0

    return elapsed_seconds < required_seconds


def determine_eligibility(
    eligibility: EligibilityInput,
) -> EligibilityResult:
    """
    Determine whether a resource should be analyzed.

    This function is deterministic and performs no I/O.

    Ordering is intentional:

    1. Configuration stabilization
    2. Analysis cooldown
    3. Recommendation lifecycle cooldown
    4. Evidence sufficiency
    5. Analysis
    """

    now = _ensure_utc(eligibility.now)

    if _configuration_is_stabilizing(
        now=now,
        configuration_changed_at=(
            eligibility.configuration_changed_at
        ),
        stabilization_hours=(
            eligibility.stabilization_hours
        ),
    ):
        changed_at = _ensure_utc(
            eligibility.configuration_changed_at  # type: ignore[arg-type]
        )

        eligible_at = changed_at.replace(
            microsecond=0
        )

        from datetime import timedelta

        eligible_at += timedelta(
            hours=eligibility.stabilization_hours
        )

        return EligibilityResult(
            action=EligibilityAction.SKIP,
            reason=EligibilityReason.CONFIGURATION_STABILIZING,
            eligible_at=eligible_at,
            message=(
                "Resource configuration changed recently "
                "and is still within the stabilization period."
            ),
        )

    if (
        eligibility.next_eligible_analysis_at is not None
        and now
        < _ensure_utc(
            eligibility.next_eligible_analysis_at
        )
    ):
        next_eligible = _ensure_utc(
            eligibility.next_eligible_analysis_at
        )

        return EligibilityResult(
            action=EligibilityAction.SKIP,
            reason=EligibilityReason.ANALYSIS_COOLDOWN_ACTIVE,
            eligible_at=next_eligible,
            message=(
                "Analysis cooldown is still active."
            ),
        )

    recommendation_status = (
        eligibility.recommendation_status
    )

    if (
        recommendation_status
        in ACTIVE_RECOMMENDATION_STATUSES
    ):
        if (
            recommendation_status == "PENDING"
            and eligibility.recommendation_created_at
            is not None
        ):
            return EligibilityResult(
                action=EligibilityAction.SKIP,
                reason=(
                    EligibilityReason.RECOMMENDATION_COOLDOWN_ACTIVE
                ),
                eligible_at=None,
                message=(
                    "A pending recommendation already exists."
                ),
            )

        if (
            recommendation_status == "ACTIONED"
            and eligibility.recommendation_actioned_at
            is not None
        ):
            return EligibilityResult(
                action=EligibilityAction.SKIP,
                reason=(
                    EligibilityReason.RECOMMENDATION_COOLDOWN_ACTIVE
                ),
                eligible_at=None,
                message=(
                    "The previous recommendation was actioned "
                    "and its cooldown is still active."
                ),
            )

    if not eligibility.evidence_sufficient:
        return EligibilityResult(
            action=EligibilityAction.COLLECT_DATA,
            reason=EligibilityReason.EVIDENCE_INSUFFICIENT,
            eligible_at=now,
            message=(
                "Required evidence is not available yet. "
                "Collect missing metric data before analysis."
            ),
        )

    if not eligibility.has_prior_analysis:
        return EligibilityResult(
            action=EligibilityAction.ANALYZE,
            reason=EligibilityReason.NO_PRIOR_ANALYSIS,
            eligible_at=now,
            message=(
                "No prior analysis exists and sufficient "
                "evidence is available."
            ),
        )

    return EligibilityResult(
        action=EligibilityAction.ANALYZE,
        reason=EligibilityReason.EVIDENCE_SUFFICIENT,
        eligible_at=now,
        message=(
            "The resource has sufficient evidence and "
            "is eligible for analysis."
        ),
    )