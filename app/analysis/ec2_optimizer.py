from __future__ import annotations

from dataclasses import dataclass

from app.analysis.capacity_analysis import (
    CapacityAnalysis,
    calculate_capacity,
)
from app.analysis.metric_statistics import (
    MetricStatistics,
    calculate_metric_statistics,
)
from app.analysis.workload_analysis import (
    WorkloadAnalysis,
    analyze_workload,
)
from app.ec2.metrics import MetricSummary
from app.tracking.models import EvidenceStatus


ALLOWED_RECOMMENDATIONS = frozenset(
    {
        "KEEP_CURRENT",
        "DOWNSIZE_CANDIDATE",
        "UPSCALE_CANDIDATE",
        "INSUFFICIENT_DATA",
        "INVESTIGATE",
    }
)


@dataclass(frozen=True)
class Ec2OptimizationResult:
    """
    Deterministic EC2 optimization result.

    This object is the authoritative output of the Python
    optimization engine.

    AI is not involved in creating this result.
    """

    recommendation: str

    # Evidence completeness, NOT probability or confidence.
    evidence_score: int

    reason: str
    concerns: tuple[str, ...]
    missing_evidence: tuple[str, ...]

    cpu_statistics: MetricStatistics | None = None
    memory_statistics: MetricStatistics | None = None

    cpu_workload: WorkloadAnalysis | None = None
    memory_workload: WorkloadAnalysis | None = None

    capacity: CapacityAnalysis | None = None


def _validate_recommendation(
    recommendation: str,
) -> str:
    """Validate the deterministic recommendation state."""

    if recommendation not in ALLOWED_RECOMMENDATIONS:
        raise ValueError(
            f"Invalid EC2 recommendation: {recommendation}"
        )

    return recommendation


def _build_concerns(
    *,
    cpu_workload: WorkloadAnalysis,
    memory_workload: WorkloadAnalysis,
) -> list[str]:
    """
    Build deterministic workload concerns.

    These are observations from the measured workload.
    They are not AI-generated.
    """

    concerns: list[str] = []

    if cpu_workload.trend == "GROWING":
        concerns.append(
            "CPU workload shows a growing trend."
        )

    if memory_workload.trend == "GROWING":
        concerns.append(
            "Memory workload shows a growing trend."
        )

    if cpu_workload.spike_risk == "HIGH":
        concerns.append(
            "CPU workload has significant spikes relative to its average."
        )

    if memory_workload.spike_risk == "HIGH":
        concerns.append(
            "Memory workload has significant spikes relative to its average."
        )

    if cpu_workload.stability == "HIGHLY_VARIABLE":
        concerns.append(
            "CPU workload is highly variable."
        )

    if memory_workload.stability == "HIGHLY_VARIABLE":
        concerns.append(
            "Memory workload is highly variable."
        )

    return concerns


def _insufficient_data_result(
    *,
    evidence_status: EvidenceStatus,
    reason: str | None = None,
    additional_missing_evidence: tuple[str, ...] = (),
) -> Ec2OptimizationResult:
    """
    Build a consistent INSUFFICIENT_DATA result.

    No capacity analysis or rightsizing decision is produced
    when evidence is insufficient.
    """

    missing_evidence = tuple(
        dict.fromkeys(
            (
                *evidence_status.missing_evidence,
                *additional_missing_evidence,
            )
        )
    )

    return Ec2OptimizationResult(
        recommendation=_validate_recommendation(
            "INSUFFICIENT_DATA"
        ),
        evidence_score=evidence_status.evidence_score,
        reason=(
            reason
            or "There is not enough verified evidence to make a safe "
            "optimization recommendation."
        ),
        concerns=(),
        missing_evidence=missing_evidence,
        cpu_statistics=None,
        memory_statistics=None,
        cpu_workload=None,
        memory_workload=None,
        capacity=None,
    )


def analyze_ec2(
    evidence_status: EvidenceStatus,
    cpu: MetricSummary,
    memory: MetricSummary,
    instance_state: str,
    current_vcpu: float,
    current_memory_mib: float,
) -> Ec2OptimizationResult:
    """
    Produce a deterministic EC2 optimization recommendation.

    Decision authority:

        AWS/CloudWatch evidence
                 ↓
        deterministic statistics
                 ↓
        workload analysis
                 ↓
        capacity analysis
                 ↓
        deterministic recommendation

    AI is NOT involved.

    AWS resources are NOT modified.

    Evidence must be sufficient before any rightsizing analysis
    can take place.
    """

    # =========================================================
    # 1. EVIDENCE GATE
    # =========================================================

    if not evidence_status.sufficient:
        return _insufficient_data_result(
            evidence_status=evidence_status,
        )

    # =========================================================
    # 2. INSTANCE STATE
    # =========================================================

    if instance_state.lower() != "running":
        return Ec2OptimizationResult(
            recommendation=_validate_recommendation(
                "INVESTIGATE"
            ),
            evidence_score=evidence_status.evidence_score,
            reason=(
                "The instance is not currently running. "
                "Current CPU and memory utilization cannot be used "
                "as a normal running-workload sizing decision."
            ),
            concerns=(
                f"Current instance state is '{instance_state}'.",
                "Running workload evidence should be reviewed before resizing.",
            ),
            missing_evidence=(),
            cpu_statistics=None,
            memory_statistics=None,
            cpu_workload=None,
            memory_workload=None,
            capacity=None,
        )

    # =========================================================
    # 3. METRIC STATISTICS
    # =========================================================

    cpu_statistics = calculate_metric_statistics(
        cpu.datapoints
    )

    memory_statistics = calculate_metric_statistics(
        memory.datapoints
    )

    if cpu_statistics is None:
        return _insufficient_data_result(
            evidence_status=evidence_status,
            reason=(
                "CPU datapoints are unavailable, so the instance "
                "cannot be safely evaluated."
            ),
            additional_missing_evidence=(
                "CPU datapoints are required.",
            ),
        )

    if memory_statistics is None:
        return _insufficient_data_result(
            evidence_status=evidence_status,
            reason=(
                "Memory datapoints are unavailable, so the instance "
                "cannot be safely evaluated."
            ),
            additional_missing_evidence=(
                "Memory datapoints are required.",
            ),
        )

    # =========================================================
    # 4. WORKLOAD ANALYSIS
    # =========================================================

    cpu_workload = analyze_workload(
        datapoints=cpu.datapoints,
        p95=cpu_statistics.p95,
    )

    memory_workload = analyze_workload(
        datapoints=memory.datapoints,
        p95=memory_statistics.p95,
    )

    if cpu_workload is None:
        return _insufficient_data_result(
            evidence_status=evidence_status,
            reason=(
                "CPU workload history could not be calculated."
            ),
            additional_missing_evidence=(
                "CPU workload history is required.",
            ),
        )

    if memory_workload is None:
        return _insufficient_data_result(
            evidence_status=evidence_status,
            reason=(
                "Memory workload history could not be calculated."
            ),
            additional_missing_evidence=(
                "Memory workload history is required.",
            ),
        )

    # =========================================================
    # 5. CAPACITY ANALYSIS
    # =========================================================

    capacity = calculate_capacity(
        current_vcpu=current_vcpu,
        current_memory_mib=current_memory_mib,
        cpu_p95=cpu_statistics.p95,
        memory_p95=memory_statistics.p95,
    )

    concerns = _build_concerns(
        cpu_workload=cpu_workload,
        memory_workload=memory_workload,
    )

    # =========================================================
    # 6. HIGH-RISK WORKLOAD → INVESTIGATE
    # =========================================================

    if (
        cpu_workload.spike_risk == "HIGH"
        and cpu_workload.trend == "GROWING"
    ):
        return Ec2OptimizationResult(
            recommendation=_validate_recommendation(
                "INVESTIGATE"
            ),
            evidence_score=evidence_status.evidence_score,
            reason=(
                "CPU workload is both highly spiky and growing. "
                "A simple instance-size change could be unsafe "
                "without understanding the workload pattern."
            ),
            concerns=tuple(concerns),
            missing_evidence=(),
            cpu_statistics=cpu_statistics,
            memory_statistics=memory_statistics,
            cpu_workload=cpu_workload,
            memory_workload=memory_workload,
            capacity=capacity,
        )

    if (
        memory_workload.spike_risk == "HIGH"
        and memory_workload.trend == "GROWING"
    ):
        return Ec2OptimizationResult(
            recommendation=_validate_recommendation(
                "INVESTIGATE"
            ),
            evidence_score=evidence_status.evidence_score,
            reason=(
                "Memory workload is both highly spiky and growing. "
                "Further workload investigation is required before "
                "changing instance capacity."
            ),
            concerns=tuple(concerns),
            missing_evidence=(),
            cpu_statistics=cpu_statistics,
            memory_statistics=memory_statistics,
            cpu_workload=cpu_workload,
            memory_workload=memory_workload,
            capacity=capacity,
        )

    # =========================================================
    # 7. UPSCALE CANDIDATE
    # =========================================================

    if (
        cpu_statistics.p95 >= 80.0
        or memory_statistics.p95 >= 80.0
    ):
        if cpu_statistics.p95 >= 80.0:
            concerns.append(
                f"CPU P95 is {cpu_statistics.p95:.2f}%."
            )

        if memory_statistics.p95 >= 80.0:
            concerns.append(
                f"Memory P95 is {memory_statistics.p95:.2f}%."
            )

        return Ec2OptimizationResult(
            recommendation=_validate_recommendation(
                "UPSCALE_CANDIDATE"
            ),
            evidence_score=evidence_status.evidence_score,
            reason=(
                "Sustained high resource utilization indicates "
                "that the current instance may not provide enough "
                "capacity."
            ),
            concerns=tuple(concerns),
            missing_evidence=(),
            cpu_statistics=cpu_statistics,
            memory_statistics=memory_statistics,
            cpu_workload=cpu_workload,
            memory_workload=memory_workload,
            capacity=capacity,
        )

    # =========================================================
    # 8. DOWNSIZE CANDIDATE
    # =========================================================

    if (
        cpu_statistics.p95 <= 40.0
        and memory_statistics.p95 <= 60.0
        and cpu_workload.trend != "GROWING"
        and memory_workload.trend != "GROWING"
        and cpu_workload.spike_risk != "HIGH"
        and memory_workload.spike_risk != "HIGH"
    ):
        concerns.append(
            "A smaller compatible AWS instance must be validated "
            "before making any resizing decision."
        )

        return Ec2OptimizationResult(
            recommendation=_validate_recommendation(
                "DOWNSIZE_CANDIDATE"
            ),
            evidence_score=evidence_status.evidence_score,
            reason=(
                "CPU and memory P95 utilization remain comfortably "
                "below the current capacity, with no strong growing "
                "trend or high spike risk."
            ),
            concerns=tuple(concerns),
            missing_evidence=(),
            cpu_statistics=cpu_statistics,
            memory_statistics=memory_statistics,
            cpu_workload=cpu_workload,
            memory_workload=memory_workload,
            capacity=capacity,
        )

    # =========================================================
    # 9. KEEP CURRENT
    # =========================================================

    return Ec2OptimizationResult(
        recommendation=_validate_recommendation(
            "KEEP_CURRENT"
        ),
        evidence_score=evidence_status.evidence_score,
        reason=(
            "Observed workload does not provide strong deterministic "
            "evidence that the instance should be resized."
        ),
        concerns=tuple(concerns),
        missing_evidence=(),
        cpu_statistics=cpu_statistics,
        memory_statistics=memory_statistics,
        cpu_workload=cpu_workload,
        memory_workload=memory_workload,
        capacity=capacity,
    )