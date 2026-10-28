from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class RecommendationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIONED = "ACTIONED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class RecommendationLifecycleInput:
    """
    Current persisted recommendation state.
    """

    status: RecommendationStatus
    created_at: datetime
    actioned_at: datetime | None
    now: datetime

    cooldown_days: int


@dataclass(frozen=True)
class RecommendationLifecycleResult:
    """
    Result of evaluating recommendation lifecycle.
    """

    status: RecommendationStatus
    next_eligible_analysis_at: datetime
    changed: bool
    reason: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _cooldown_end(
    *,
    start: datetime,
    cooldown_days: int,
) -> datetime:
    return _utc(start) + timedelta(
        days=cooldown_days
    )


def evaluate_recommendation_lifecycle(
    lifecycle: RecommendationLifecycleInput,
) -> RecommendationLifecycleResult:
    """
    Evaluate whether a recommendation remains active.

    Rules:

    PENDING
        Before cooldown -> PENDING
        After cooldown  -> EXPIRED

    ACTIONED
        Before cooldown -> ACTIONED
        After cooldown  -> EXPIRED

    EXPIRED
        Remains EXPIRED

    No AWS calls occur here.
    """

    now = _utc(lifecycle.now)

    if lifecycle.cooldown_days < 0:
        raise ValueError(
            "cooldown_days cannot be negative."
        )

    if lifecycle.status == RecommendationStatus.EXPIRED:
        return RecommendationLifecycleResult(
            status=RecommendationStatus.EXPIRED,
            next_eligible_analysis_at=now,
            changed=False,
            reason=(
                "Recommendation is already expired."
            ),
        )

    if lifecycle.status == RecommendationStatus.PENDING:
        eligible_at = _cooldown_end(
            start=lifecycle.created_at,
            cooldown_days=lifecycle.cooldown_days,
        )

        if now < eligible_at:
            return RecommendationLifecycleResult(
                status=RecommendationStatus.PENDING,
                next_eligible_analysis_at=eligible_at,
                changed=False,
                reason=(
                    "Pending recommendation cooldown "
                    "is still active."
                ),
            )

        return RecommendationLifecycleResult(
            status=RecommendationStatus.EXPIRED,
            next_eligible_analysis_at=now,
            changed=True,
            reason=(
                "Pending recommendation cooldown "
                "has expired."
            ),
        )

    if lifecycle.status == RecommendationStatus.ACTIONED:
        if lifecycle.actioned_at is None:
            raise ValueError(
                "ACTIONED recommendation must have actioned_at."
            )

        eligible_at = _cooldown_end(
            start=lifecycle.actioned_at,
            cooldown_days=lifecycle.cooldown_days,
        )

        if now < eligible_at:
            return RecommendationLifecycleResult(
                status=RecommendationStatus.ACTIONED,
                next_eligible_analysis_at=eligible_at,
                changed=False,
                reason=(
                    "Actioned recommendation cooldown "
                    "is still active."
                ),
            )

        return RecommendationLifecycleResult(
            status=RecommendationStatus.EXPIRED,
            next_eligible_analysis_at=now,
            changed=True,
            reason=(
                "Actioned recommendation cooldown "
                "has expired."
            ),
        )

    raise ValueError(
        f"Unsupported recommendation status: "
        f"{lifecycle.status}"
    )