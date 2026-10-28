from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.aws.client import AwsClient


@dataclass(frozen=True)
class Ec2Price:
    instance_type: str
    region: str
    hourly_usd: float
    monthly_usd: float


@dataclass(frozen=True)
class Ec2Candidate:
    instance_type: str
    vcpus: int
    memory_mib: int
    architecture: str


def _extract_hourly_price(
    product: dict[str, Any],
) -> float | None:
    terms = product.get(
        "terms",
        {},
    ).get(
        "OnDemand",
        {},
    )

    prices: list[float] = []

    for term in terms.values():
        dimensions = term.get(
            "priceDimensions",
            {},
        )

        for dimension in dimensions.values():
            unit = dimension.get("unit")
            price = dimension.get(
                "pricePerUnit",
                {},
            ).get("USD")

            if unit != "Hrs" or price is None:
                continue

            try:
                value = float(price)
            except (TypeError, ValueError):
                continue

            if value >= 0:
                prices.append(value)

    if not prices:
        return None

    return min(prices)


def _pricing_client(
    aws: AwsClient,
) -> Any:
    return aws.client("pricing")


@lru_cache(maxsize=256)
def get_ec2_on_demand_price(
    region: str,
    instance_type: str,
    architecture: str,
) -> Ec2Price | None:
    """
    Query real AWS EC2 On-Demand pricing.

    No prices are hard-coded.
    """

    pricing_aws = AwsClient(region)
    client = _pricing_client(pricing_aws)

    filters = [
        {
            "Type": "TERM_MATCH",
            "Field": "ServiceCode",
            "Value": "AmazonEC2",
        },
        {
            "Type": "TERM_MATCH",
            "Field": "instanceType",
            "Value": instance_type,
        },
        {
            "Type": "TERM_MATCH",
            "Field": "regionCode",
            "Value": region,
        },
        {
            "Type": "TERM_MATCH",
            "Field": "operatingSystem",
            "Value": "Linux",
        },
        {
            "Type": "TERM_MATCH",
            "Field": "tenancy",
            "Value": "Shared",
        },
        {
            "Type": "TERM_MATCH",
            "Field": "preInstalledSw",
            "Value": "NA",
        },
        {
            "Type": "TERM_MATCH",
            "Field": "capacitystatus",
            "Value": "Used",
        },
    ]

    response = client.get_products(
        ServiceCode="AmazonEC2",
        Filters=filters,
        FormatVersion="aws_v1",
        MaxResults=10,
    )

    for raw_product in response.get(
        "PriceList",
        [],
    ):
        try:
            product = json.loads(raw_product)
        except (
            TypeError,
            json.JSONDecodeError,
        ):
            continue

        hourly = _extract_hourly_price(product)

        if hourly is None:
            continue

        return Ec2Price(
            instance_type=instance_type,
            region=region,
            hourly_usd=hourly,
            monthly_usd=hourly * 730,
        )

    return None


def discover_compatible_candidates(
    aws: AwsClient,
    instance_type: str,
    architecture: str,
) -> tuple[Ec2Candidate, ...]:
    """
    Discover real AWS instance types in the same family and
    architecture.

    Both smaller and larger candidates are returned.

    Direction filtering is intentionally performed later so the
    caller can show the complete comparison and explain why
    candidates were rejected.
    """

    family = instance_type.split(
        ".",
        1,
    )[0]

    ec2 = aws.client("ec2")

    paginator = ec2.get_paginator(
        "describe_instance_types"
    )

    candidates: list[Ec2Candidate] = []

    for page in paginator.paginate(
        Filters=[
            {
                "Name": "instance-type",
                "Values": [f"{family}.*"],
            },
            {
                "Name": (
                    "processor-info."
                    "supported-architecture"
                ),
                "Values": [architecture],
            },
            {
                "Name": "supported-usage-class",
                "Values": ["on-demand"],
            },
        ]
    ):
        for item in page.get(
            "InstanceTypes",
            [],
        ):
            candidate_type = item.get(
                "InstanceType"
            )

            processor = item.get(
                "ProcessorInfo",
                {},
            )

            architectures = processor.get(
                "SupportedArchitectures",
                [],
            )

            vcpu_info = item.get(
                "VCpuInfo",
                {},
            )

            vcpus = vcpu_info.get(
                "DefaultVCpus"
            )

            memory_info = item.get(
                "MemoryInfo",
                {},
            )

            memory_mib = memory_info.get(
                "SizeInMiB"
            )

            if not candidate_type:
                continue

            if architecture not in architectures:
                continue

            if vcpus is None:
                continue

            if memory_mib is None:
                continue

            candidates.append(
                Ec2Candidate(
                    instance_type=candidate_type,
                    vcpus=int(vcpus),
                    memory_mib=int(memory_mib),
                    architecture=architecture,
                )
            )

    candidates.sort(
        key=lambda candidate: (
            candidate.vcpus,
            candidate.memory_mib,
            candidate.instance_type,
        )
    )

    return tuple(candidates)