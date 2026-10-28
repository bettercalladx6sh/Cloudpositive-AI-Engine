from __future__ import annotations


ACTIONABLE_RECOMMENDATIONS = frozenset(
    {
        "DOWNSIZE_CANDIDATE",
        "UPSCALE_CANDIDATE",
    }
)


def should_create_recommendation(
    recommendation: str,
) -> bool:
    """
    Return True only when a deterministic recommendation
    should enter the active recommendation lifecycle.

    KEEP_CURRENT, INVESTIGATE, and INSUFFICIENT_DATA are
    historical analysis outcomes and must not create an
    active recommendation that blocks future analysis.
    """

    return recommendation in ACTIONABLE_RECOMMENDATIONS


def validate_recommendation_instance(
    *,
    recommendation: str,
    recommended_instance: str | None,
) -> None:
    """
    Enforce the invariant between recommendation type and
    validated replacement instance.
    """

    if recommendation in ACTIONABLE_RECOMMENDATIONS:
        if not recommended_instance:
            raise ValueError(
                "Actionable recommendation requires "
                "a validated recommended_instance."
            )

        return

    if recommended_instance is not None:
        raise ValueError(
            "Non-actionable recommendation cannot contain "
            "a recommended_instance."
        )