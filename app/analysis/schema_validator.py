
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SchemaValidationError(ValueError):
    """Raised when data does not match its expected schema."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        message = "Schema validation failed:\n- " + "\n- ".join(errors)
        super().__init__(message)


@dataclass(frozen=True)
class FieldRule:
    """Validation rules for one field."""

    types: tuple[type, ...]
    required: bool = True
    nullable: bool = False
    allowed_values: tuple[Any, ...] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None


def validate_schema(
    payload: Any,
    schema: Mapping[str, FieldRule],
    *,
    allow_extra_fields: bool = False,
) -> None:
    """
    Validate a mapping against an explicitly defined schema.

    Raises SchemaValidationError if validation fails.
    Does not modify or fill in missing data.
    """
    if not isinstance(payload, Mapping):
        raise SchemaValidationError(
            ["Expected an object/mapping at the root."]
        )

    errors: list[str] = []

    # Check required fields and validate supplied values.
    for field_name, rule in schema.items():
        if field_name not in payload:
            if rule.required:
                errors.append(
                    f"'{field_name}' is required but missing."
                )
            continue

        value = payload[field_name]

        if value is None:
            if rule.nullable:
                continue

            errors.append(f"'{field_name}' cannot be None.")
            continue

        # bool is a subclass of int in Python, but should not
        # be accepted as a numeric metric.
        if isinstance(value, bool) and bool not in rule.types:
            errors.append(
                f"'{field_name}' must not be a boolean."
            )
            continue

        if not isinstance(value, rule.types):
            expected = ", ".join(
                item.__name__ for item in rule.types
            )
            errors.append(
                f"'{field_name}' must be {expected}; "
                f"received {type(value).__name__}."
            )
            continue

        if rule.allowed_values is not None:
            if value not in rule.allowed_values:
                errors.append(
                    f"'{field_name}' has invalid value {value!r}. "
                    f"Allowed values: {rule.allowed_values!r}."
                )

        if isinstance(value, (int, float)) and not isinstance(
            value, bool
        ):
            if rule.minimum is not None and value < rule.minimum:
                errors.append(
                    f"'{field_name}' must be >= {rule.minimum}."
                )

            if rule.maximum is not None and value > rule.maximum:
                errors.append(
                    f"'{field_name}' must be <= {rule.maximum}."
                )

    # Reject unexpected fields when strict validation is enabled.
    if not allow_extra_fields:
        unexpected = set(payload.keys()) - set(schema.keys())

        for field_name in sorted(unexpected):
            errors.append(
                f"Unexpected field '{field_name}'."
            )

    if errors:
        raise SchemaValidationError(errors)


def run_with_validation_retry(
    operation: Callable[[], T],
    validator: Callable[[T], None],
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> T:
    """
    Run an operation and validate its result.

    Retries when the result fails schema validation.
    Raises the final validation error after max_attempts.

    The operation must be capable of producing a corrected result;
    otherwise, retrying the same invalid result will not help.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    if retry_delay_seconds < 0:
        raise ValueError(
            "retry_delay_seconds cannot be negative."
        )

    last_error: SchemaValidationError | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = operation()
            validator(result)

            logger.info(
                "Schema validation passed on attempt %d/%d.",
                attempt,
                max_attempts,
            )
            return result

        except SchemaValidationError as exc:
            last_error = exc

            logger.warning(
                "Schema validation failed on attempt %d/%d: %s",
                attempt,
                max_attempts,
                exc.errors,
            )

            if attempt < max_attempts:
                delay = retry_delay_seconds * (2 ** (attempt - 1))
                if delay:
                    time.sleep(delay)

    assert last_error is not None
    raise last_error


def validate_ai_reasoning_payload(payload):
    """
    Validate the structure and types of an AI reasoning response.

    Raises SchemaValidationError if the payload is invalid.
    """
    import math

    if not isinstance(payload, dict):
        raise SchemaValidationError(
            "AI response must be a JSON object."
        )

    required_fields = {
        "recommendation",
        "confidence",
        "reason",
        "concerns",
        "missing_evidence",
    }

    missing = required_fields - payload.keys()
    unexpected = payload.keys() - required_fields

    errors = []

    if missing:
        errors.append(
            f"Missing required fields: {sorted(missing)}"
        )

    if unexpected:
        errors.append(
            f"Unexpected fields: {sorted(unexpected)}"
        )

    if errors:
        raise SchemaValidationError("; ".join(errors))

    allowed_recommendations = {
        "KEEP_CURRENT",
        "DOWNSIZE_CANDIDATE",
        "UPSCALE_CANDIDATE",
        "STOP_INSTANCE",
        "INVESTIGATE",
        "INSUFFICIENT_DATA",
    }

    recommendation = payload["recommendation"]

    if (
        not isinstance(recommendation, str)
        or recommendation not in allowed_recommendations
    ):
        errors.append(
            "recommendation must be one of: "
            + ", ".join(sorted(allowed_recommendations))
        )

    confidence = payload["confidence"]

    if confidence is not None:
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
        ):
            errors.append(
                "confidence must be a number or null."
            )
        elif (
            not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0
        ):
            errors.append(
                "confidence must be finite and between 0 and 1."
            )

    if not isinstance(payload["reason"], str):
        errors.append("reason must be a string.")

    for field in ("concerns", "missing_evidence"):
        value = payload[field]

        if not isinstance(value, list):
            errors.append(f"{field} must be a list.")
        elif not all(isinstance(item, str) for item in value):
            errors.append(
                f"Every item in {field} must be a string."
            )

    if errors:
        raise SchemaValidationError("; ".join(errors))

    return payload


def validate_ec2_analysis_input(
    *,
    evidence_status,
    cpu,
    memory,
    instance_state,
    current_vcpu,
    current_memory_mib,
):
    """
    Validate inputs before deterministic EC2 analysis.

    This validates data structure and basic numeric safety.
    It does not claim that AWS evidence is complete or accurate.
    """
    import math

    errors = []

    if not hasattr(evidence_status, "sufficient"):
        errors.append(
            "evidence_status must have a 'sufficient' attribute."
        )

    if not hasattr(evidence_status, "evidence_score"):
        errors.append(
            "evidence_status must have an 'evidence_score' attribute."
        )

    if not hasattr(evidence_status, "missing_evidence"):
        errors.append(
            "evidence_status must have a 'missing_evidence' attribute."
        )

    for name, metric in (("cpu", cpu), ("memory", memory)):
        if not hasattr(metric, "datapoints"):
            errors.append(
                f"{name} must have a 'datapoints' attribute."
            )
            continue

        datapoints = metric.datapoints

        if datapoints is None:
            continue

        try:
            iter(datapoints)
        except TypeError:
            errors.append(f"{name}.datapoints must be iterable.")

    if not isinstance(instance_state, str) or not instance_state.strip():
        errors.append(
            "instance_state must be a non-empty string."
        )

    for name, value in (
        ("current_vcpu", current_vcpu),
        ("current_memory_mib", current_memory_mib),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            errors.append(f"{name} must be numeric.")
        elif not math.isfinite(value) or value <= 0:
            errors.append(
                f"{name} must be finite and greater than zero."
            )

    if errors:
        raise SchemaValidationError(
            "Invalid EC2 analysis input: " + "; ".join(errors)
        )

    return True


def validate_ec2_optimization_result(result):
    """
    Validate the deterministic EC2 analysis result before it is
    persisted or included in the final report.

    Raises SchemaValidationError if the result is invalid.
    """
    import math

    from app.analysis.ec2_optimizer import (
        ALLOWED_RECOMMENDATIONS,
        Ec2OptimizationResult,
    )

    errors = []

    if not isinstance(result, Ec2OptimizationResult):
        raise SchemaValidationError([
            "Deterministic analysis must return an Ec2OptimizationResult."
        ])

    if result.recommendation not in ALLOWED_RECOMMENDATIONS:
        errors.append(
            f"Invalid recommendation: {result.recommendation!r}"
        )

    if (
        isinstance(result.evidence_score, bool)
        or not isinstance(result.evidence_score, int)
        or result.evidence_score < 0
    ):
        errors.append(
            "evidence_score must be a non-negative integer."
        )

    if not isinstance(result.reason, str) or not result.reason.strip():
        errors.append("reason must be a non-empty string.")

    for field_name in ("concerns", "missing_evidence"):
        value = getattr(result, field_name)

        if not isinstance(value, (tuple, list)):
            errors.append(f"{field_name} must be a list or tuple.")
        elif not all(isinstance(item, str) for item in value):
            errors.append(
                f"Every item in {field_name} must be a string."
            )

    for field_name in ("cpu_statistics", "memory_statistics"):
        statistics = getattr(result, field_name)

        if statistics is None:
            continue

        for metric_name in (
            "average",
            "minimum",
            "maximum",
            "p95",
        ):
            if not hasattr(statistics, metric_name):
                continue

            value = getattr(statistics, metric_name)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                errors.append(
                    f"{field_name}.{metric_name} must be a finite number."
                )

    for field_name in ("cpu_workload", "memory_workload", "capacity"):
        value = getattr(result, field_name)

        if value is not None and not hasattr(value, "__dataclass_fields__"):
            errors.append(
                f"{field_name} must be a valid analysis dataclass or None."
            )

    if errors:
        raise SchemaValidationError(errors)

    return result