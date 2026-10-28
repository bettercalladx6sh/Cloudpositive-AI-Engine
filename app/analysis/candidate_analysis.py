from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstanceCandidate:
    """Deterministic evaluation of one EC2 candidate."""

    instance_type: str

    vcpu: int
    memory_mib: int

    architecture: str

    cpu_capacity_ratio: float
    memory_capacity_ratio: float

    compatible: bool
    reason: str


def evaluate_candidate(
    *,
    candidate_type: str,
    candidate_vcpu: int,
    candidate_memory_mib: int,
    candidate_architecture: str,
    current_architecture: str,
    current_vcpu: int,
    current_memory_mib: int,
    required_memory_mib: float,
) -> InstanceCandidate:
    """
    Evaluate whether a real AWS EC2 candidate is structurally
    compatible with the current workload requirements.

    This function:

    - does not call AWS
    - does not retrieve pricing
    - does not select the final candidate
    - does not make the final optimization recommendation

    Candidate specifications must come from real AWS data.
    """

    if not candidate_type.strip():
        raise ValueError(
            "candidate_type cannot be empty."
        )

    if candidate_vcpu <= 0:
        raise ValueError(
            "candidate_vcpu must be greater than zero."
        )

    if candidate_memory_mib <= 0:
        raise ValueError(
            "candidate_memory_mib must be greater than zero."
        )

    if current_vcpu <= 0:
        raise ValueError(
            "current_vcpu must be greater than zero."
        )

    if current_memory_mib <= 0:
        raise ValueError(
            "current_memory_mib must be greater than zero."
        )

    if required_memory_mib < 0:
        raise ValueError(
            "required_memory_mib cannot be negative."
        )

    cpu_capacity_ratio = (
        candidate_vcpu
        / current_vcpu
    )

    memory_capacity_ratio = (
        candidate_memory_mib
        / current_memory_mib
    )

    # ---------------------------------------------------------
    # Architecture
    # ---------------------------------------------------------

    if (
        candidate_architecture
        != current_architecture
    ):
        return InstanceCandidate(
            instance_type=candidate_type,
            vcpu=candidate_vcpu,
            memory_mib=candidate_memory_mib,
            architecture=candidate_architecture,
            cpu_capacity_ratio=(
                cpu_capacity_ratio
            ),
            memory_capacity_ratio=(
                memory_capacity_ratio
            ),
            compatible=False,
            reason=(
                "Architecture does not match the current "
                "instance architecture."
            ),
        )

    # ---------------------------------------------------------
    # Memory
    # ---------------------------------------------------------

    if candidate_memory_mib < required_memory_mib:
        return InstanceCandidate(
            instance_type=candidate_type,
            vcpu=candidate_vcpu,
            memory_mib=candidate_memory_mib,
            architecture=candidate_architecture,
            cpu_capacity_ratio=(
                cpu_capacity_ratio
            ),
            memory_capacity_ratio=(
                memory_capacity_ratio
            ),
            compatible=False,
            reason=(
                "Candidate does not provide enough memory "
                "for the calculated requirement."
            ),
        )

    # ---------------------------------------------------------
    # CPU
    # ---------------------------------------------------------

    # A candidate with fewer vCPUs can still be valid if the
    # calculated CPU requirement allows it. The caller that has
    # the full CapacityAnalysis performs the authoritative
    # workload-aware CPU validation.
    #
    # Therefore we do not incorrectly reject every smaller
    # vCPU candidate here.
    return InstanceCandidate(
        instance_type=candidate_type,
        vcpu=candidate_vcpu,
        memory_mib=candidate_memory_mib,
        architecture=candidate_architecture,
        cpu_capacity_ratio=(
            cpu_capacity_ratio
        ),
        memory_capacity_ratio=(
            memory_capacity_ratio
        ),
        compatible=True,
        reason=(
            "Candidate matches the required architecture and "
            "provides sufficient calculated memory capacity. "
            "CPU capacity requires workload-aware validation."
        ),
    )