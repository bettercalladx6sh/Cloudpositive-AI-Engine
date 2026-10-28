from __future__ import annotations

from dataclasses import dataclass

from app.aws.client import AwsClient
from app.tracking.change_detector import detect_configuration_change
from app.tracking.change_repository import ConfigurationChangeRepository
from app.tracking.models import TrackingResult
from app.tracking.repository import SnapshotRepository, record_to_snapshot
from app.tracking.snapshot import get_current_snapshot


@dataclass(frozen=True)
class TrackingRunResult:
    """Result of tracking one EC2 instance."""

    tracking: TrackingResult
    previous_snapshot_found: bool
    configuration_change_saved: bool


def track_instance(
    aws: AwsClient,
    instance_id: str,
    session,
) -> TrackingRunResult:
    """Track the current EC2 configuration without duplicate snapshots."""

    current_snapshot = get_current_snapshot(
        aws=aws,
        instance_id=instance_id,
    )

    snapshot_repository = SnapshotRepository(session)
    change_repository = ConfigurationChangeRepository(session)

    previous_record = snapshot_repository.get_latest(
        instance_id=current_snapshot.instance_id,
        region=current_snapshot.region,
    )

    previous_snapshot = (
        record_to_snapshot(previous_record)
        if previous_record is not None
        else None
    )

    tracking_result = detect_configuration_change(
        previous=previous_snapshot,
        current=current_snapshot,
)

    configuration_change_saved = False

    # First time we have ever seen this instance.
    if previous_snapshot is None:
        snapshot_repository.save(current_snapshot)

    # Configuration changed.
    elif tracking_result.configuration_change is not None:
        change_repository.save(
            tracking_result.configuration_change
        )

        snapshot_repository.save(current_snapshot)

        configuration_change_saved = True

    # No configuration change:
    # DO NOT save another duplicate snapshot.

    session.commit()

    return TrackingRunResult(
        tracking=tracking_result,
        previous_snapshot_found=previous_snapshot is not None,
        configuration_change_saved=configuration_change_saved,
    )