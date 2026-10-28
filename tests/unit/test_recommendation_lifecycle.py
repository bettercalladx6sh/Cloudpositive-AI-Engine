from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.recommendation_lifecycle import (
    RecommendationLifecycleInput,
    RecommendationLifecycleResult,
    RecommendationStatus,
    evaluate_recommendation_lifecycle,
)


NOW = datetime(
    2026,
    1,
    31,
    12,
    0,
    tzinfo=timezone.utc,
)


def test_pending_recommendation_remains_pending():
    result = evaluate_recommendation_lifecycle(
        RecommendationLifecycleInput(
            status=RecommendationStatus.PENDING,
            created_at=NOW,
            actioned_at=None,
            now=NOW + timedelta(days=10),
            cooldown_days=30,
        )
    )

    assert result.status == RecommendationStatus.PENDING
    assert result.changed is False


def test_pending_recommendation_expires():
    result = evaluate_recommendation_lifecycle(
        RecommendationLifecycleInput(
            status=RecommendationStatus.PENDING,
            created_at=NOW,
            actioned_at=None,
            now=NOW + timedelta(days=31),
            cooldown_days=30,
        )
    )

    assert result.status == RecommendationStatus.EXPIRED
    assert result.changed is True


def test_actioned_recommendation_remains_actioned():
    actioned_at = NOW

    result = evaluate_recommendation_lifecycle(
        RecommendationLifecycleInput(
            status=RecommendationStatus.ACTIONED,
            created_at=NOW - timedelta(days=10),
            actioned_at=actioned_at,
            now=NOW + timedelta(days=10),
            cooldown_days=30,
        )
    )

    assert result.status == RecommendationStatus.ACTIONED
    assert result.changed is False


def test_actioned_recommendation_expires():
    actioned_at = NOW

    result = evaluate_recommendation_lifecycle(
        RecommendationLifecycleInput(
            status=RecommendationStatus.ACTIONED,
            created_at=NOW - timedelta(days=60),
            actioned_at=actioned_at,
            now=NOW + timedelta(days=31),
            cooldown_days=30,
        )
    )

    assert result.status == RecommendationStatus.EXPIRED
    assert result.changed is True


def test_expired_recommendation_stays_expired():
    result = evaluate_recommendation_lifecycle(
        RecommendationLifecycleInput(
            status=RecommendationStatus.EXPIRED,
            created_at=NOW - timedelta(days=90),
            actioned_at=None,
            now=NOW,
            cooldown_days=30,
        )
    )

    assert result.status == RecommendationStatus.EXPIRED
    assert result.changed is False


def test_actioned_requires_actioned_at():
    with pytest.raises(ValueError):
        evaluate_recommendation_lifecycle(
            RecommendationLifecycleInput(
                status=RecommendationStatus.ACTIONED,
                created_at=NOW,
                actioned_at=None,
                now=NOW,
                cooldown_days=30,
            )
        )


def test_negative_cooldown_rejected():
    with pytest.raises(ValueError):
        evaluate_recommendation_lifecycle(
            RecommendationLifecycleInput(
                status=RecommendationStatus.PENDING,
                created_at=NOW,
                actioned_at=None,
                now=NOW,
                cooldown_days=-1,
            )
        )