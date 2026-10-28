from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.analysis.ai_reasoning import AiReasoning
from app.analysis.schema_validator import (
    SchemaValidationError,
    validate_ai_reasoning_payload,
    validate_ec2_analysis_input,
    validate_ec2_optimization_result,
)


def valid_ai_payload():
    return {
        "recommendation": "KEEP_CURRENT",
        "confidence": 0.8,
        "reason": "The supplied evidence supports keeping the current size.",
        "concerns": [],
        "missing_evidence": [],
    }


def test_valid_ai_payload_is_accepted():
    assert validate_ai_reasoning_payload(valid_ai_payload())["recommendation"] == "KEEP_CURRENT"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(confidence="high"),
        lambda data: data.update(reason=""),
        lambda data: data.update(concerns=["valid", 42]),
        lambda data: data.update(extra_field=True),
        lambda data: data.update(recommendation="DOWNSIZE_NOW"),
    ],
)
def test_invalid_ai_payload_is_rejected(mutate):
    payload = valid_ai_payload()
    mutate(payload)
    with pytest.raises(SchemaValidationError):
        validate_ai_reasoning_payload(payload)


def test_ec2_analysis_input_accepts_expected_structure():
    evidence = SimpleNamespace(
        sufficient=True,
        evidence_score=100,
        missing_evidence=(),
    )
    cpu = SimpleNamespace(datapoints=[0.0, 1.5])
    memory = SimpleNamespace(datapoints=[10.0, 12.0])

    validate_ec2_analysis_input(
        evidence_status=evidence,
        cpu=cpu,
        memory=memory,
        instance_state="running",
        current_vcpu=2,
        current_memory_mib=4096,
    )


def test_ec2_analysis_input_rejects_invalid_capacity():
    evidence = SimpleNamespace(
        sufficient=True,
        evidence_score=100,
        missing_evidence=(),
    )
    metrics = SimpleNamespace(datapoints=[])

    with pytest.raises(SchemaValidationError):
        validate_ec2_analysis_input(
            evidence_status=evidence,
            cpu=metrics,
            memory=metrics,
            instance_state="running",
            current_vcpu=float("nan"),
            current_memory_mib=4096,
        )


@dataclass(frozen=True)
class Ec2OptimizationResult:
    recommendation: str
    evidence_score: int
    reason: str
    concerns: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    cpu_statistics: object | None = None
    memory_statistics: object | None = None
    cpu_workload: object | None = None
    memory_workload: object | None = None
    capacity: object | None = None


def test_deterministic_result_schema_is_accepted():
    result = Ec2OptimizationResult(
        recommendation="KEEP_CURRENT",
        evidence_score=100,
        reason="No deterministic reason to resize.",
        concerns=(),
        missing_evidence=(),
    )
    validate_ec2_optimization_result(result)


def test_deterministic_result_with_invalid_recommendation_is_rejected():
    result = Ec2OptimizationResult(
        recommendation="DELETE_INSTANCE",
        evidence_score=100,
        reason="No deterministic reason to resize.",
        concerns=(),
        missing_evidence=(),
    )
    with pytest.raises(SchemaValidationError):
        validate_ec2_optimization_result(result)


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(output_text=next(self.outputs))


class FakeClient:
    def __init__(self, outputs):
        self.responses = FakeResponses(outputs)


def test_ai_retries_invalid_schema_then_accepts_valid_response():
    import json

    valid = json.dumps(valid_ai_payload())
    client = FakeClient(['{"recommendation": 42}', valid])
    result = AiReasoning(client=client, model="unit-test").reason({"evidence": "provided"})
    assert result.recommendation == "KEEP_CURRENT"
    assert client.responses.calls == 2


def test_ai_stops_after_three_invalid_responses():
    client = FakeClient(['{}', '{}', '{}'])
    with pytest.raises(SchemaValidationError, match="after 3 attempts"):
        AiReasoning(client=client, model="unit-test").reason({"evidence": "provided"})
    assert client.responses.calls == 3
