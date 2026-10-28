from datetime import datetime, timedelta, timezone

from app.analysis.eligibility import (
    EligibilityAction,
    EligibilityInput,
    EligibilityReason,
    determine_eligibility,
)


NOW = datetime(
    2026,
    1,
    31,
    12,
    0,
    tzinfo=timezone.utc,
)


def _base(
    **overrides,
) -> EligibilityInput:
    values = {
        "now": NOW,
        "has_prior_analysis": True,
        "next_eligible_analysis_at": None,
        "recommendation_status": None,
        "recommendation_created_at": None,
        "recommendation_actioned_at": None,
        "recommendation_expired_at": None,
        "evidence_sufficient": True,
        "configuration_changed_at": None,
        "stabilization_hours": 1.0,
    }

    values.update(overrides)

    return EligibilityInput(**values)


def test_no_prior_analysis_with_sufficient_evidence():
    result = determine_eligibility(
        _base(
            has_prior_analysis=False,
        )
    )

    assert result.action == EligibilityAction.ANALYZE
    assert (
        result.reason
        == EligibilityReason.NO_PRIOR_ANALYSIS
    )


def test_insufficient_evidence_requires_collection():
    result = determine_eligibility(
        _base(
            evidence_sufficient=False,
        )
    )

    assert result.action == EligibilityAction.COLLECT_DATA
    assert (
        result.reason
        == EligibilityReason.EVIDENCE_INSUFFICIENT
    )


def test_analysis_cooldown_skips():
    result = determine_eligibility(
        _base(
            next_eligible_analysis_at=(
                NOW + timedelta(days=2)
            ),
        )
    )

    assert result.action == EligibilityAction.SKIP
    assert (
        result.reason
        == EligibilityReason.ANALYSIS_COOLDOWN_ACTIVE
    )


def test_pending_recommendation_skips():
    result = determine_eligibility(
        _base(
            recommendation_status="PENDING",
            recommendation_created_at=NOW,
        )
    )

    assert result.action == EligibilityAction.SKIP
    assert (
        result.reason
        == EligibilityReason.RECOMMENDATION_COOLDOWN_ACTIVE
    )


def test_actioned_recommendation_skips():
    result = determine_eligibility(
        _base(
            recommendation_status="ACTIONED",
            recommendation_actioned_at=NOW,
        )
    )

    assert result.action == EligibilityAction.SKIP
    assert (
        result.reason
        == EligibilityReason.RECOMMENDATION_COOLDOWN_ACTIVE
    )


def test_configuration_stabilization_skips():
    result = determine_eligibility(
        _base(
            configuration_changed_at=NOW,
            stabilization_hours=24.0,
        )
    )

    assert result.action == EligibilityAction.SKIP
    assert (
        result.reason
        == EligibilityReason.CONFIGURATION_STABILIZING
    )


def test_stabilization_expires():
    result = determine_eligibility(
        _base(
            now=NOW + timedelta(hours=2),
            configuration_changed_at=NOW,
            stabilization_hours=1.0,
        )
    )

    assert result.action == EligibilityAction.ANALYZE