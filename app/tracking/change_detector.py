from __future__ import annotations

from app.tracking.models import (
    ConfigurationChange,
    InstanceSnapshot,
    TrackingResult,
)


def detect_configuration_change(
    previous: InstanceSnapshot | None,
    current: InstanceSnapshot,
) -> TrackingResult:
    """
    Compare the previous and current EC2 snapshots.

    A configuration change is detected when the deterministic
    configuration version changes.

    The first observation is not considered a change because there is
    no previous state to compare against.
    """

    if previous is None:
        return TrackingResult(
            snapshot=current,
            configuration_changed=False,
            configuration_change=None,
        )

    if previous.instance_id != current.instance_id:
        raise ValueError(
            "Previous and current snapshots must belong to "
            "the same EC2 instance."
        )

    if previous.region != current.region:
        raise ValueError(
            "Previous and current snapshots must belong to "
            "the same AWS region."
        )

    if (
        previous.configuration_version
        == current.configuration_version
    ):
        return TrackingResult(
            snapshot=current,
            configuration_changed=False,
            configuration_change=None,
        )

    change = ConfigurationChange(
        instance_id=current.instance_id,
        region=current.region,
        detected_at=current.observed_at,
        previous_instance_type=previous.instance_type,
        current_instance_type=current.instance_type,
        previous_configuration_version=(
            previous.configuration_version
        ),
        current_configuration_version=(
            current.configuration_version
        ),
    )

    return TrackingResult(
        snapshot=current,
        configuration_changed=True,
        configuration_change=change,
    )