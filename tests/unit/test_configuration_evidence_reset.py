from datetime import datetime, timedelta, timezone

from app.tracking.models import InstanceSnapshot


def test_configuration_versions_are_distinct() -> None:
    first = InstanceSnapshot(
        instance_id="i-test",
        region="us-east-1",
        availability_zone="us-east-1a",
        instance_type="t3a.large",
        state="running",
        architecture="x86_64",
        platform=None,
        launch_time=None,
        private_ip=None,
        public_ip=None,
        name="test",
        tags=(),
        configuration_version="version-large",
        observed_at=datetime.now(timezone.utc),
    )

    second = InstanceSnapshot(
        instance_id="i-test",
        region="us-east-1",
        availability_zone="us-east-1a",
        instance_type="t3a.medium",
        state="running",
        architecture="x86_64",
        platform=None,
        launch_time=None,
        private_ip=None,
        public_ip=None,
        name="test",
        tags=(),
        configuration_version="version-medium",
        observed_at=(
            datetime.now(timezone.utc)
            + timedelta(hours=1)
        ),
    )

    assert (
        first.configuration_version
        != second.configuration_version
    )

    assert first.instance_type == "t3a.large"
    assert second.instance_type == "t3a.medium"