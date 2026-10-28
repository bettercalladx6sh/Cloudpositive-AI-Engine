from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class InstanceSnapshotRecord:
    id: int
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
    tags: str | None
    configuration_version: str
    observed_at: datetime


@dataclass
class ConfigurationChangeRecord:
    id: int
    instance_id: str
    region: str
    detected_at: datetime
    previous_instance_type: str
    current_instance_type: str


@dataclass
class MetricObservationRecord:
    id: int
    instance_id: str
    region: str
    namespace: str
    metric_name: str
    configuration_version: str
    average: float | None
    minimum: float | None
    maximum: float | None
    datapoint_count: int
    first_datapoint: datetime | None
    last_datapoint: datetime | None
    coverage_hours: float
    analysis_start: datetime
    analysis_end: datetime
    observed_at: datetime


@dataclass
class MetricDatapointRecord:
    id: int
    instance_id: str
    region: str
    namespace: str
    metric_name: str
    configuration_version: str
    timestamp: datetime
    average: float | None
    minimum: float | None
    maximum: float | None
    observed_at: datetime


@dataclass
class MetricCollectionCheckpointRecord:
    id: int
    instance_id: str
    region: str
    namespace: str
    metric_name: str
    configuration_version: str
    checkpoint_at: datetime
    updated_at: datetime


@dataclass
class AnalysisRunRecord:
    id: int
    instance_id: str
    region: str
    execution_run_id: int
    started_at: datetime
    completed_at: datetime | None
    status: str
    recommendation: str
    evidence_start: datetime | None
    evidence_end: datetime | None
    next_eligible_analysis_at: datetime | None
    analysis_version: str
    error_message: str | None
    created_at: datetime


@dataclass
class RecommendationRecord:
    id: int
    instance_id: str
    region: str
    analysis_id: int
    recommendation: str
    recommended_instance: str | None
    created_at: datetime
    status: str
    actioned_at: datetime | None
    expired_at: datetime | None
    next_eligible_analysis_at: datetime | None


@dataclass
class RecommendationSnapshotRecord:
    id: int
    instance_id: str
    region: str
    analysis_id: int
    configuration_version: str
    instance_type: str
    instance_state: str
    recommendation: str
    recommended_instance: str | None
    cpu_average: float | None
    cpu_minimum: float | None
    cpu_maximum: float | None
    memory_average: float | None
    memory_minimum: float | None
    memory_maximum: float | None
    cpu_datapoint_count: int
    memory_datapoint_count: int
    evidence_start: datetime | None
    evidence_end: datetime | None
    reason: str
    concerns: str | None
    missing_evidence: str | None
    created_at: datetime


@dataclass
class ExecutionRunRecord:
    id: int
    execution_id: str
    username: str
    client_ip: str | None
    command: str
    source: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    aws_account_id: str | None
    aws_identity: str | None
    aws_region: str | None
    resources_discovered: int
    resources_analyzed: int
    resources_skipped: int
    resources_collecting_data: int
    recommendations_created: int
    error_message: str | None
    created_at: datetime


def row_to_record(cls, row: dict[str, Any] | None):
    if row is None:
        return None
    return cls(**row)
