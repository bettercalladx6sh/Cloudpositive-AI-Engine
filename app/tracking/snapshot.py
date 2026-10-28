from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.aws.client import AwsClient
from app.ec2.discovery import Ec2Instance
from app.tracking.models import InstanceSnapshot


def calculate_configuration_version(
    instance: Ec2Instance,
) -> str:
    """
    Generate a deterministic version for the current EC2 configuration.

    Only configuration attributes currently represented by the domain
    model are included.

    Runtime state, IP addresses, names, tags and timestamps are excluded
    because they do not represent an EC2 capacity configuration change.
    """

    configuration = {
        "instance_type": instance.instance_type,
        "architecture": instance.architecture,
        "platform": instance.platform,
    }

    serialized = json.dumps(
        configuration,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


def create_snapshot(
    instance: Ec2Instance,
) -> InstanceSnapshot:
    """
    Create a point-in-time snapshot from a discovered EC2 instance.

    The instance data comes directly from AWS discovery. No values are
    invented or inferred.
    """

    return InstanceSnapshot(
        instance_id=instance.instance_id,
        region=instance.region,
        availability_zone=instance.availability_zone,
        instance_type=instance.instance_type,
        state=instance.state,
        architecture=instance.architecture,
        platform=instance.platform,
        launch_time=instance.launch_time,
        private_ip=instance.private_ip,
        public_ip=instance.public_ip,
        name=instance.name,
        tags=instance.tags,
        configuration_version=calculate_configuration_version(
            instance
        ),
        observed_at=datetime.now(timezone.utc),
    )


def get_current_snapshot(
    aws: AwsClient,
    instance_id: str,
) -> InstanceSnapshot:
    """
    Retrieve one EC2 instance from AWS and create its current snapshot.

    This makes a real EC2 DescribeInstances API call.
    """

    if not instance_id.strip():
        raise ValueError("EC2 instance ID cannot be empty.")

    ec2 = aws.client("ec2")

    response = ec2.describe_instances(
        InstanceIds=[instance_id],
    )

    for reservation in response.get("Reservations", []):
        for instance_data in reservation.get("Instances", []):
            if instance_data.get("InstanceId") != instance_id:
                continue

            parsed = _parse_instance(
                instance_data=instance_data,
                region=aws.region,
            )

            return create_snapshot(parsed)

    raise LookupError(
        f"EC2 instance {instance_id} was not found "
        f"in region {aws.region}."
    )


def _parse_instance(
    instance_data: dict,
    region: str,
) -> Ec2Instance:
    """Convert an AWS EC2 response into the existing EC2 domain model."""

    from app.ec2.discovery import _extract_name, _extract_tags

    instance_id = instance_data.get("InstanceId")
    instance_type = instance_data.get("InstanceType")
    state = instance_data.get("State", {}).get("Name")
    availability_zone = (
        instance_data.get("Placement", {}).get("AvailabilityZone")
    )

    if not instance_id:
        raise LookupError(
            "AWS EC2 response did not contain an instance ID."
        )

    if not instance_type:
        raise LookupError(
            f"AWS EC2 response for {instance_id} "
            "did not contain an instance type."
        )

    if not state:
        raise LookupError(
            f"AWS EC2 response for {instance_id} "
            "did not contain an instance state."
        )

    if not availability_zone:
        raise LookupError(
            f"AWS EC2 response for {instance_id} "
            "did not contain an availability zone."
        )

    tags = _extract_tags(instance_data)

    return Ec2Instance(
        instance_id=instance_id,
        region=region,
        availability_zone=availability_zone,
        instance_type=instance_type,
        state=state,
        architecture=instance_data.get("Architecture"),
        platform=instance_data.get("Platform"),
        launch_time=instance_data.get("LaunchTime"),
        private_ip=instance_data.get("PrivateIpAddress"),
        public_ip=instance_data.get("PublicIpAddress"),
        name=_extract_name(tags),
        tags=tags,
    )