from __future__ import annotations

from dataclasses import dataclass

from app.analysis.capacity_analysis import CapacityAnalysis
from app.pricing.ec2_pricing import Ec2Candidate


@dataclass(frozen=True)
class CandidateValidationResult:
    """Deterministic validation result for one EC2 candidate."""

    instance_type: str
    safe: bool

    cpu_sufficient: bool
    memory_sufficient: bool

    reasons: tuple[str, ...]


def validate_candidate(
    *,
    candidate: Ec2Candidate,
    capacity: CapacityAnalysis,
) -> CandidateValidationResult:
    """
    Validate whether an EC2 candidate can support the observed workload.

    The validation is intentionally conservative.

    CPU:
        The workload requirement is expressed against the current
        instance's vCPU capacity. Candidate CPU capacity is compared
        proportionally by vCPU count.

    Memory:
        The candidate must provide at least the calculated
        safety-adjusted memory requirement.

    This function does not:
        - call AWS
        - retrieve pricing
        - select a candidate
        - make a final optimization recommendation
    """

    reasons: list[str] = []

    if candidate.vcpus <= 0:
        return CandidateValidationResult(
            instance_type=candidate.instance_type,
            safe=False,
            cpu_sufficient=False,
            memory_sufficient=False,
            reasons=("Candidate reports invalid vCPU capacity.",),
        )

    if candidate.memory_mib <= 0:
        return CandidateValidationResult(
            instance_type=candidate.instance_type,
            safe=False,
            cpu_sufficient=False,
            memory_sufficient=False,
            reasons=("Candidate reports invalid memory capacity.",),
        )

    required_cpu_vcpus = (
        capacity.current_vcpu
        * capacity.estimated_cpu_required_percent
        / 100.0
    )

    cpu_sufficient = (
        candidate.vcpus >= required_cpu_vcpus
    )

    memory_sufficient = (
        candidate.memory_mib
        >= capacity.estimated_memory_required_mib
    )

    if not cpu_sufficient:
        reasons.append(
            f"Candidate provides {candidate.vcpus} vCPUs, "
            f"but approximately {required_cpu_vcpus:.2f} vCPUs "
            f"are required by the observed CPU workload."
        )

    if not memory_sufficient:
        reasons.append(
            f"Candidate provides {candidate.memory_mib} MiB memory, "
            f"but approximately "
            f"{capacity.estimated_memory_required_mib:.0f} MiB "
            f"are required by the observed memory workload."
        )

    if cpu_sufficient:
        reasons.append(
            "Candidate provides sufficient calculated CPU capacity."
        )

    if memory_sufficient:
        reasons.append(
            "Candidate provides sufficient calculated memory capacity."
        )

    return CandidateValidationResult(
        instance_type=candidate.instance_type,
        safe=(
            cpu_sufficient
            and memory_sufficient
        ),
        cpu_sufficient=cpu_sufficient,
        memory_sufficient=memory_sufficient,
        reasons=tuple(reasons),
    )
