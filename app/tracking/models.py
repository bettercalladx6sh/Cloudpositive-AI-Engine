from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InstanceSnapshot:
    """Point-in-time snapshot of an EC2 instance configuration."""

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
    configuration_version: str
    observed_at: datetime


@dataclass(frozen=True)
class ConfigurationChange:
    """Detected material EC2 configuration change."""

    instance_id: str
    region: str
    detected_at: datetime
    previous_instance_type: str
    current_instance_type: str
    previous_configuration_version: str
    current_configuration_version: str


@dataclass(frozen=True)
class TrackingResult:
    """Result of synchronizing the current instance snapshot."""

    snapshot: InstanceSnapshot
    configuration_changed: bool
    configuration_change: ConfigurationChange | None


@dataclass(frozen=True)
class EvidenceStatus:
    """
    Deterministic assessment of whether sufficient evidence exists.

    The evidence score is a completeness measure. It is NOT a probability
    and must never be interpreted as prediction or recommendation confidence.
    """

    sufficient: bool
    evidence_score: int
    configuration_age_days: float
    required_days: float
    cpu_data_sufficient: bool
    memory_data_sufficient: bool
    missing_evidence: tuple[str, ...]


@dataclass(frozen=True)
class RecommendationResult:
    """
    Deterministic optimization result.

    This object intentionally contains no AI confidence/probability.
    """

    recommendation: str
    evidence_score: int
    reason: str
    concerns: tuple[str, ...]
    missing_evidence: tuple[str, ...]