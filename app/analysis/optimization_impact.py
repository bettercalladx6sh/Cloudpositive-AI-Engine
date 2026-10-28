from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OptimizationImpact:
    decision: str

    current_instance: str
    recommended_instance: str | None

    current_vcpu: int
    recommended_vcpu: int | None

    current_memory_mib: int
    recommended_memory_mib: int | None

    current_monthly_cost: float | None
    recommended_monthly_cost: float | None

    monthly_cost_change_usd: float | None
    annual_cost_change_usd: float | None
    savings_percent: float | None

    current_cpu_headroom_percent: float | None
    recommended_cpu_headroom_percent: float | None

    current_memory_headroom_percent: float | None
    recommended_memory_headroom_percent: float | None

    summary: str
    why_effective: str

    benefits: tuple[str, ...]
    risks: tuple[str, ...]
    evidence: tuple[str, ...]


def _capacity_headroom(
    *,
    capacity: Any,
    memory_mib: int,
) -> tuple[float | None, float | None]:
    """
    Calculate CPU and memory headroom from deterministic capacity data.

    Missing capacity values remain None. They are never converted into
    fabricated zero values.
    """

    if capacity is None:
        return None, None

    cpu_required = getattr(
        capacity,
        "estimated_cpu_required_percent",
        None,
    )

    memory_required = getattr(
        capacity,
        "estimated_memory_required_mib",
        None,
    )

    if cpu_required is None:
        cpu_headroom = None
    else:
        cpu_headroom = 100.0 - float(cpu_required)

    if memory_required is None:
        memory_headroom = None
    else:
        memory_headroom = (
            float(memory_mib)
            - float(memory_required)
        )

    return cpu_headroom, memory_headroom


def _pricing_current(
    pricing: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Return current pricing only when real pricing evidence exists.

    A None value is valid and means pricing was not required or was
    unavailable. We never replace it with fabricated pricing data.
    """

    current = pricing.get("current")

    if current is None:
        return None

    if not isinstance(current, dict):
        return None

    return current


def build_optimization_impact(
    *,
    deterministic: Any,
    pricing: dict[str, Any],
    current_vcpu: int,
    current_memory_mib: int,
) -> OptimizationImpact:
    """
    Build the user-facing optimization impact.

    Deterministic analysis remains authoritative.

    Pricing is optional because KEEP_CURRENT, INVESTIGATE and
    INSUFFICIENT_DATA decisions do not require candidate pricing.

    This function never invents pricing, capacity or recommendations.
    """

    decision = deterministic.recommendation

    # ---------------------------------------------------------
    # CURRENT INSTANCE / PRICING
    # ---------------------------------------------------------

    current_pricing = _pricing_current(pricing)

    current_instance = ""

    current_monthly_cost: float | None = None

    if current_pricing is not None:
        current_instance = str(
            current_pricing.get("instance_type") or ""
        )

        monthly_value = current_pricing.get("monthly_usd")

        if monthly_value is not None:
            current_monthly_cost = float(monthly_value)

    # ---------------------------------------------------------
    # CURRENT CAPACITY HEADROOM
    # ---------------------------------------------------------

    capacity = deterministic.capacity

    (
        current_cpu_headroom,
        current_memory_headroom,
    ) = _capacity_headroom(
        capacity=capacity,
        memory_mib=current_memory_mib,
    )

    # ---------------------------------------------------------
    # NO RESIZE RECOMMENDATION
    # ---------------------------------------------------------

    if decision in {
        "KEEP_CURRENT",
        "INVESTIGATE",
        "INSUFFICIENT_DATA",
    }:
        if decision == "KEEP_CURRENT":
            if current_instance:
                summary = (
                    f"The current instance type "
                    f"{current_instance} should remain in place "
                    f"because the deterministic analysis did not "
                    f"validate a safe capacity change."
                )
            else:
                summary = (
                    "The current instance should remain in place "
                    "because the deterministic analysis did not "
                    "validate a safe capacity change."
                )

            why_effective = (
                "Keeping the current capacity avoids introducing "
                "unverified resource or compatibility risk."
            )

        elif decision == "INVESTIGATE":
            if current_instance:
                summary = (
                    f"The current instance type "
                    f"{current_instance} requires further "
                    f"investigation before a resize decision "
                    f"can be made."
                )
            else:
                summary = (
                    "The current instance requires further "
                    "investigation before a resize decision "
                    "can be made."
                )

            why_effective = (
                "Additional operational evidence is required "
                "before changing the instance capacity."
            )

        else:
            if current_instance:
                summary = (
                    f"The current instance type "
                    f"{current_instance} cannot be safely evaluated "
                    f"for resizing yet."
                )
            else:
                summary = (
                    "The current instance cannot be safely "
                    "evaluated for resizing yet."
                )

            why_effective = (
                "Waiting for sufficient verified evidence "
                "prevents a capacity decision based on incomplete "
                "information."
            )

        return OptimizationImpact(
            decision=decision,
            current_instance=current_instance,
            recommended_instance=None,
            current_vcpu=current_vcpu,
            recommended_vcpu=None,
            current_memory_mib=current_memory_mib,
            recommended_memory_mib=None,
            current_monthly_cost=current_monthly_cost,
            recommended_monthly_cost=None,
            monthly_cost_change_usd=None,
            annual_cost_change_usd=None,
            savings_percent=None,
            current_cpu_headroom_percent=current_cpu_headroom,
            recommended_cpu_headroom_percent=None,
            current_memory_headroom_percent=current_memory_headroom,
            recommended_memory_headroom_percent=None,
            summary=summary,
            why_effective=why_effective,
            benefits=(),
            risks=(
                "No specific instance change has been validated.",
            ),
            evidence=tuple(
                deterministic.missing_evidence
            ),
        )

    # ---------------------------------------------------------
    # RESIZE CANDIDATE
    # ---------------------------------------------------------

    candidate = pricing.get(
        "recommended_candidate"
    )

    if candidate is None:
        return OptimizationImpact(
            decision=decision,
            current_instance=current_instance,
            recommended_instance=None,
            current_vcpu=current_vcpu,
            recommended_vcpu=None,
            current_memory_mib=current_memory_mib,
            recommended_memory_mib=None,
            current_monthly_cost=current_monthly_cost,
            recommended_monthly_cost=None,
            monthly_cost_change_usd=None,
            annual_cost_change_usd=None,
            savings_percent=None,
            current_cpu_headroom_percent=current_cpu_headroom,
            recommended_cpu_headroom_percent=None,
            current_memory_headroom_percent=current_memory_headroom,
            recommended_memory_headroom_percent=None,
            summary=(
                f"Deterministic analysis identified "
                f"{decision.lower().replace('_', ' ')}, "
                f"but no compatible AWS instance passed "
                f"capacity validation."
            ),
            why_effective=(
                "Keeping the current instance is safer than "
                "selecting a smaller or larger instance that "
                "has not been proven sufficient."
            ),
            benefits=(),
            risks=(
                "No compatible validated instance was found.",
            ),
            evidence=(
                "Candidate capacity validation did not produce "
                "a safe instance.",
            ),
        )

    # ---------------------------------------------------------
    # VALIDATED CANDIDATE
    # ---------------------------------------------------------

    recommended_instance = str(
        candidate["instance_type"]
    )

    recommended_vcpu = int(
        candidate["vcpus"]
    )

    recommended_memory_mib = int(
        candidate["memory_mib"]
    )

    recommended_monthly_cost = float(
        candidate["monthly_usd"]
    )

    monthly_cost_change: float | None = None

    if current_monthly_cost is not None:
        monthly_cost_change = (
            recommended_monthly_cost
            - current_monthly_cost
        )

    annual_cost_change: float | None = None

    if monthly_cost_change is not None:
        annual_cost_change = (
            monthly_cost_change * 12
        )

    savings_percent = None

    if candidate.get("savings_percent") is not None:
        savings_percent = float(
            candidate["savings_percent"]
        )

    # ---------------------------------------------------------
    # RECOMMENDED CAPACITY HEADROOM
    # ---------------------------------------------------------

    recommended_cpu_headroom = None
    recommended_memory_headroom = None

    if capacity is not None:
        cpu_required = getattr(
            capacity,
            "estimated_cpu_required_percent",
            None,
        )

        memory_required = getattr(
            capacity,
            "estimated_memory_required_mib",
            None,
        )

        if cpu_required is not None:
            recommended_cpu_headroom = (
                100.0
                - float(cpu_required)
            )

        if memory_required is not None:
            recommended_memory_headroom = (
                float(recommended_memory_mib)
                - float(memory_required)
            )

    # ---------------------------------------------------------
    # USER-FACING EXPLANATION
    # ---------------------------------------------------------

    if decision == "DOWNSIZE_CANDIDATE":
        if (
            current_monthly_cost is not None
            and recommended_monthly_cost is not None
        ):
            why_effective = (
                f"The candidate passed deterministic capacity "
                f"validation while reducing the monthly EC2 cost "
                f"from ${current_monthly_cost:.2f} to "
                f"${recommended_monthly_cost:.2f}."
            )
        else:
            why_effective = (
                "The candidate passed deterministic capacity "
                "validation, but complete pricing evidence is "
                "not available for a cost comparison."
            )

        summary = (
            f"The current instance type "
            f"{current_instance} can be downsized to "
            f"{recommended_instance} because the observed "
            f"workload requires less CPU and memory capacity "
            f"than the current instance provides."
        )

        benefits = (
            "Lower EC2 monthly cost.",
            "Reduced provisioned CPU capacity is supported by observed utilization.",
            "Reduced provisioned memory capacity is supported by observed utilization.",
        )

        risks = (
            "Observed workload can change after resizing.",
            "Future CPU or memory growth could reduce available headroom.",
        )

    else:
        summary = (
            f"The current instance type "
            f"{current_instance} can be increased to "
            f"{recommended_instance} because the observed "
            f"workload indicates additional capacity is required."
        )

        why_effective = (
            "The candidate passed deterministic capacity "
            "validation and provides additional CPU or memory "
            "capacity for the observed workload."
        )

        benefits = (
            "Additional verified capacity.",
            "More headroom for the observed workload.",
        )

        risks = (
            "Higher EC2 monthly cost.",
            "Additional capacity may remain underutilized if workload pressure decreases.",
        )

    return OptimizationImpact(
        decision=decision,
        current_instance=current_instance,
        recommended_instance=recommended_instance,
        current_vcpu=current_vcpu,
        recommended_vcpu=recommended_vcpu,
        current_memory_mib=current_memory_mib,
        recommended_memory_mib=recommended_memory_mib,
        current_monthly_cost=current_monthly_cost,
        recommended_monthly_cost=recommended_monthly_cost,
        monthly_cost_change_usd=monthly_cost_change,
        annual_cost_change_usd=annual_cost_change,
        savings_percent=savings_percent,
        current_cpu_headroom_percent=current_cpu_headroom,
        recommended_cpu_headroom_percent=recommended_cpu_headroom,
        current_memory_headroom_percent=current_memory_headroom,
        recommended_memory_headroom_percent=recommended_memory_headroom,
        summary=summary,
        why_effective=why_effective,
        benefits=benefits,
        risks=risks,
        evidence=(
            "Candidate passed deterministic CPU capacity validation.",
            "Candidate passed deterministic memory capacity validation.",
            "Candidate pricing was retrieved from AWS.",
        ),
    )