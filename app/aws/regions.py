from __future__ import annotations

from dataclasses import dataclass

from app.aws.client import AwsClient


@dataclass(frozen=True)
class AwsRegion:
    """An AWS region available to the account."""

    name: str
    endpoint: str
    opt_in_status: str


def discover_regions(aws: AwsClient) -> tuple[AwsRegion, ...]:
    """
    Discover regions available to the AWS account.

    This makes a real EC2 DescribeRegions API call.
    """
    ec2 = aws.client("ec2")

    response = ec2.describe_regions(
        AllRegions=True,
    )

    regions: list[AwsRegion] = []

    for region in response.get("Regions", []):
        region_name = region.get("RegionName")
        endpoint = region.get("Endpoint")
        opt_in_status = region.get("OptInStatus", "unknown")

        if not region_name or not endpoint:
            continue

        regions.append(
            AwsRegion(
                name=region_name,
                endpoint=endpoint,
                opt_in_status=opt_in_status,
            )
        )

    regions.sort(key=lambda region: region.name)

    return tuple(regions)