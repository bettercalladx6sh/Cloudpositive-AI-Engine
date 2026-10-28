from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapacityAnalysis:
    """Deterministic estimate of workload capacity requirements."""

    current_vcpu: float
    current_memory_mib: float

    cpu_p95: float
    memory_p95: float

    cpu_safety_factor: float
    memory_safety_factor: float

    estimated_cpu_required_percent: float
    estimated_memory_required_mib: float

    cpu_headroom_percent: float
    memory_headroom_percent: float

    cpu_pressure: str
    memory_pressure: str


def _pressure(
    p95: float,
) -> str:
    """Classify resource pressure using P95 utilization."""

    if p95 >= 90.0:
        return "CRITICAL"

    if p95 >= 80.0:
        return "HIGH"

    if p95 >= 60.0:
        return "MEDIUM"

    if p95 >= 40.0:
        return "LOW"

    return "VERY_LOW"


def calculate_capacity(
    *,
    current_vcpu: float,
    current_memory_mib: float,
    cpu_p95: float,
    memory_p95: float,
    cpu_safety_factor: float = 1.25,
    memory_safety_factor: float = 1.25,
) -> CapacityAnalysis:
    """
    Estimate the capacity required by the observed workload.

    CPU:
        CPU P95 is multiplied by the safety factor.

    Memory:
        Current memory capacity is multiplied by memory P95
        utilization and the memory safety factor.

    This function does not call AWS and does not make a final
    optimization recommendation.
    """

    if current_vcpu <= 0:
        raise ValueError(
            "current_vcpu must be greater than zero."
        )

    if current_memory_mib <= 0:
        raise ValueError(
            "current_memory_mib must be greater than zero."
        )

    if not 0.0 <= cpu_p95 <= 100.0:
        raise ValueError(
            "cpu_p95 must be between 0 and 100."
        )

    if not 0.0 <= memory_p95 <= 100.0:
        raise ValueError(
            "memory_p95 must be between 0 and 100."
        )

    if cpu_safety_factor < 1.0:
        raise ValueError(
            "cpu_safety_factor must be at least 1.0."
        )

    if memory_safety_factor < 1.0:
        raise ValueError(
            "memory_safety_factor must be at least 1.0."
        )

    estimated_cpu_required_percent = min(
        cpu_p95 * cpu_safety_factor,
        100.0,
    )

    estimated_memory_required_mib = (
        current_memory_mib
        * (memory_p95 / 100.0)
        * memory_safety_factor
    )

    cpu_headroom_percent = max(
        0.0,
        100.0
        - estimated_cpu_required_percent,
    )

    memory_headroom_percent = max(
        0.0,
        current_memory_mib
        - estimated_memory_required_mib,
    )

    return CapacityAnalysis(
        current_vcpu=current_vcpu,
        current_memory_mib=current_memory_mib,

        cpu_p95=cpu_p95,
        memory_p95=memory_p95,

        cpu_safety_factor=cpu_safety_factor,
        memory_safety_factor=memory_safety_factor,

        estimated_cpu_required_percent=(
            estimated_cpu_required_percent
        ),

        estimated_memory_required_mib=(
            estimated_memory_required_mib
        ),

        cpu_headroom_percent=(
            cpu_headroom_percent
        ),

        memory_headroom_percent=(
            memory_headroom_percent
        ),

        cpu_pressure=_pressure(
            cpu_p95
        ),

        memory_pressure=_pressure(
            memory_p95
        ),
    )