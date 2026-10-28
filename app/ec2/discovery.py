from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.aws.client import AwsClient, get_aws_client
from app.aws.regions import AwsRegion


@dataclass(frozen=True)
class Ec2Instance:
    """Facts about an EC2 instance discovered from AWS."""

    instance_id: str
    region: str
    availability_zone: str
    instance_type: str
    state: str
    architecture: str | None
    platform: str | None
    launch_time: datetime | None
    private_ip: str | None
    public_ip: str | None
    name: str | None
    tags: tuple[tuple[str, str], ...]


def _extract_tags(instance: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Convert AWS instance tags into an immutable tuple."""
    tags: list[tuple[str, str]] = []

    for tag in instance.get("Tags", []):
        key = tag.get("Key")
        value = tag.get("Value")

        if key is not None and value is not None:
            tags.append((key, value))

    tags.sort(key=lambda item: item[0])

    return tuple(tags)


def _extract_name(
    tags: tuple[tuple[str, str], ...],
) -> str | None:
    """Return the EC2 Name tag if one exists."""
    for key, value in tags:
        if key == "Name":
            return value

    return None


def _parse_instance(
    instance: dict[str, Any],
    region: str,
) -> Ec2Instance | None:
    """Convert an AWS EC2 instance response into our domain model."""
    instance_id = instance.get("InstanceId")
    instance_type = instance.get("InstanceType")
    state = instance.get("State", {}).get("Name")
    availability_zone = (
        instance.get("Placement", {}).get("AvailabilityZone")
    )

    if not all(
        (
            instance_id,
            instance_type,
            state,
            availability_zone,
        )
    ):
        return None

    tags = _extract_tags(instance)

    return Ec2Instance(
        instance_id=instance_id,
        region=region,
        availability_zone=availability_zone,
        instance_type=instance_type,
        state=state,
        architecture=instance.get("Architecture"),
        platform=instance.get("Platform"),
        launch_time=instance.get("LaunchTime"),
        private_ip=instance.get("PrivateIpAddress"),
        public_ip=instance.get("PublicIpAddress"),
        name=_extract_name(tags),
        tags=tags,
    )


def discover_instances(
    aws: AwsClient,
    regions: tuple[AwsRegion, ...],
) -> tuple[Ec2Instance, ...]:
    """
    Discover EC2 instances across usable AWS regions.

    Only regions that are already enabled for the account are queried.
    This function makes real EC2 DescribeInstances API calls.
    """
    instances: list[Ec2Instance] = []

    for region in regions:
        if region.opt_in_status == "not-opted-in":
            continue

        regional_aws = get_aws_client(region.name)
        ec2 = regional_aws.client("ec2")

        paginator = ec2.get_paginator("describe_instances")

        for page in paginator.paginate():
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    parsed = _parse_instance(
                        instance,
                        region.name,
                    )

                    if parsed is not None:
                        instances.append(parsed)

    instances.sort(
        key=lambda instance: (
            instance.region,
            instance.instance_id,
        )
    )

    return tuple(instances)