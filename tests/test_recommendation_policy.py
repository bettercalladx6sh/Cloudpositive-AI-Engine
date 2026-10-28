from app.analysis.recommendation_policy import (
    should_create_recommendation,
    validate_recommendation_instance,
)


def test_actionable_recommendation_creates_lifecycle_record():
    assert should_create_recommendation(
        "DOWNSIZE_CANDIDATE"
    )

    assert should_create_recommendation(
        "UPSCALE_CANDIDATE"
    )


def test_non_actionable_recommendation_does_not_create_lifecycle_record():
    assert not should_create_recommendation(
        "KEEP_CURRENT"
    )

    assert not should_create_recommendation(
        "INVESTIGATE"
    )

    assert not should_create_recommendation(
        "INSUFFICIENT_DATA"
    )


def test_actionable_recommendation_requires_instance():
    validate_recommendation_instance(
        recommendation="DOWNSIZE_CANDIDATE",
        recommended_instance="t3a.small",
    )


def test_actionable_recommendation_without_instance_fails():
    try:
        validate_recommendation_instance(
            recommendation="DOWNSIZE_CANDIDATE",
            recommended_instance=None,
        )
    except ValueError:
        return

    raise AssertionError(
        "Expected ValueError for missing recommended_instance."
    )


def test_non_actionable_recommendation_cannot_have_instance():
    try:
        validate_recommendation_instance(
            recommendation="KEEP_CURRENT",
            recommended_instance="t3a.small",
        )
    except ValueError:
        return

    raise AssertionError(
        "Expected ValueError for non-actionable recommendation."
    )