from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MetricCumulativeSummaryRecord:
    id: int
    instance_id: str
    region: str
    namespace: str
    metric_name: str
    configuration_version: str
    evidence_start: datetime | None
    evidence_end: datetime | None
    datapoint_count: int
    value_sum: float
    average: float | None
    minimum: float | None
    maximum: float | None
    p50: float | None
    p95: float | None
    p99: float | None
    standard_deviation: float | None
    trend: str | None
    volatility: str | None
    coverage_percent: float
    gap_count: int
    last_updated_at: datetime
