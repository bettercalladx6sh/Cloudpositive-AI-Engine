from __future__ import annotations

from dataclasses import dataclass

from app.aws.client import AwsClient


@dataclass(frozen=True)
class Ec2InstanceSpec:
    """Hardware and capability information for an EC2 instance type."""

    instance_type: str
    vcpu_count: int
    memory_mib: int
    architecture: tuple[str, ...]
    network_performance: str
    instance_family: str
    instance_size: str


def _split_instance_type(
    instance_type: str,
) -> tuple[str, str]:
    """Split an EC2 instance type into family and size."""
    if "." not in instance_type:
        raise ValueError(
            f"Invalid EC2 instance type: {instance_type}"
        )

    family, size = instance_type.split(".", 1)

    if not family or not size:
        raise ValueError(
            f"Invalid EC2 instance type: {instance_type}"
        )

    return family, size


def get_instance_specs(
    aws: AwsClient,
    instance_type: str,
) -> Ec2InstanceSpec:
    """
    Retrieve specifications for an EC2 instance type.

    Uses the real EC2 DescribeInstanceTypes API.
    """
    ec2 = aws.client("ec2")

    response = ec2.describe_instance_types(
        InstanceTypes=[instance_type],
    )

    instance_types = response.get("InstanceTypes", [])

    if not instance_types:
        raise LookupError(
            f"AWS returned no specification for "
            f"instance type {instance_type}."
        )

    details = instance_types[0]

    vcpu_count = details.get(
        "VCpuInfo",
        {},
    ).get("DefaultVCpus")

    memory_mib = details.get(
        "MemoryInfo",
        {},
    ).get("SizeInMiB")

    architecture = tuple(
        details.get(
            "ProcessorInfo",
            {},
        ).get(
            "SupportedArchitectures",
            [],
        )
    )

    network_performance = details.get(
        "NetworkInfo",
        {},
    ).get(
        "NetworkPerformance",
        "unknown",
    )

    if vcpu_count is None or memory_mib is None:
        raise LookupError(
            f"AWS returned incomplete specifications for "
            f"{instance_type}."
        )

    instance_family, instance_size = _split_instance_type(
        instance_type
    )

    return Ec2InstanceSpec(
        instance_type=instance_type,
        vcpu_count=vcpu_count,
        memory_mib=memory_mib,
        architecture=architecture,
        network_performance=network_performance,
        instance_family=instance_family,
        instance_size=instance_size,
    )


def get_instance_specs_for_types(
    aws: AwsClient,
    instance_types: tuple[str, ...],
) -> dict[str, Ec2InstanceSpec]:
    """
    Retrieve specifications for multiple EC2 instance types.

    Each unique instance type is requested only once from AWS.
    """
    unique_types = tuple(sorted(set(instance_types)))

    if not unique_types:
        return {}

    ec2 = aws.client("ec2")

    response = ec2.describe_instance_types(
        InstanceTypes=list(unique_types),
    )

    specifications: dict[str, Ec2InstanceSpec] = {}

    for details in response.get("InstanceTypes", []):
        instance_type = details.get("InstanceType")

        if not instance_type:
            continue

        vcpu_count = details.get(
            "VCpuInfo",
            {},
        ).get("DefaultVCpus")

        memory_mib = details.get(
            "MemoryInfo",
            {},
        ).get("SizeInMiB")

        architecture = tuple(
            details.get(
                "ProcessorInfo",
                {},
            ).get(
                "SupportedArchitectures",
                [],
            )
        )

        network_performance = details.get(
            "NetworkInfo",
            {},
        ).get(
            "NetworkPerformance",
            "unknown",
        )

        if vcpu_count is None or memory_mib is None:
            continue

        instance_family, instance_size = _split_instance_type(
            instance_type
        )

        specifications[instance_type] = Ec2InstanceSpec(
            instance_type=instance_type,
            vcpu_count=vcpu_count,
            memory_mib=memory_mib,
            architecture=architecture,
            network_performance=network_performance,
            instance_family=instance_family,
            instance_size=instance_size,
        )

    return specifications