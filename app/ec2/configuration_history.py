from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from botocore.exceptions import ClientError

from app.aws.client import AwsClient


MIN_CONFIGURATION_EVIDENCE_DAYS = 30


@dataclass(frozen=True)
class ConfigurationChange:
    """A detected EC2 instance configuration state."""

    instance_id: str
    instance_type: str
    observed_at: datetime


@dataclass(frozen=True)
class ConfigurationHistory:
    """Historical evidence about an EC2 instance configuration."""

    instance_id: str
    current_instance_type: str
    current_configuration_since: datetime | None
    evidence_days: float
    history_available: bool
    evidence_sufficient: bool
    changes: tuple[ConfigurationChange, ...]
    explanation: str


def _get_config_client(aws: AwsClient) -> Any:
    """Return an AWS Config client for the configured region."""
    return aws.client("config")


def _get_configuration_items(
    config_client: Any,
    instance_id: str,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """
    Retrieve AWS Config history for an EC2 instance.

    AWS Config limits a single history request to a maximum seven-day
    time range, so the requested period is split into smaller windows.
    """
    items: list[dict[str, Any]] = []

    current_start = start_time

    while current_start < end_time:
        current_end = min(
            current_start + timedelta(days=7),
            end_time,
        )

        response = config_client.get_resource_config_history(
            resourceType="AWS::EC2::Instance",
            resourceId=instance_id,
            laterTime=current_end,
            earlierTime=current_start,
            chronologicalOrder="Forward",
        )

        items.extend(
            response.get("configurationItems", [])
        )

        current_start = current_end

    return items


def _extract_instance_type(
    configuration_item: dict[str, Any],
) -> str | None:
    """Extract the EC2 instance type from an AWS Config item."""
    configuration = configuration_item.get("configuration")

    if not configuration:
        return None

    if isinstance(configuration, str):
        import json

        try:
            configuration = json.loads(configuration)
        except json.JSONDecodeError:
            return None

    if not isinstance(configuration, dict):
        return None

    return configuration.get("instanceType")


def _extract_capture_time(
    configuration_item: dict[str, Any],
) -> datetime | None:
    """Extract the AWS Config capture timestamp."""
    capture_time = configuration_item.get(
        "configurationItemCaptureTime"
    )

    if not isinstance(capture_time, datetime):
        return None

    if capture_time.tzinfo is None:
        return capture_time.replace(tzinfo=timezone.utc)

    return capture_time.astimezone(timezone.utc)


def _build_changes(
    instance_id: str,
    configuration_items: list[dict[str, Any]],
) -> tuple[ConfigurationChange, ...]:
    """Convert AWS Config items into ordered configuration changes."""
    changes: list[ConfigurationChange] = []

    for item in configuration_items:
        instance_type = _extract_instance_type(item)
        observed_at = _extract_capture_time(item)

        if instance_type is None or observed_at is None:
            continue

        changes.append(
            ConfigurationChange(
                instance_id=instance_id,
                instance_type=instance_type,
                observed_at=observed_at,
            )
        )

    changes.sort(key=lambda change: change.observed_at)

    return tuple(changes)


def _find_current_configuration_since(
    changes: tuple[ConfigurationChange, ...],
    current_instance_type: str,
) -> datetime | None:
    """
    Find when the current instance type was first observed.

    If the current type is present from the beginning of the available
    history, we cannot prove when it actually started. In that case,
    return None rather than making an unsafe assumption.
    """
    if not changes:
        return None

    current_indexes = [
        index
        for index, change in enumerate(changes)
        if change.instance_type == current_instance_type
    ]

    if not current_indexes:
        return None

    first_current_index = current_indexes[0]

    if first_current_index == 0:
        return None

    return changes[first_current_index].observed_at


def get_configuration_history(
    aws: AwsClient,
    instance_id: str,
    current_instance_type: str,
    history_days: int = 90,
) -> ConfigurationHistory:
    """
    Retrieve configuration history for an EC2 instance.

    AWS Config is used as the historical source.

    If AWS Config is unavailable, disabled, or the history does not
    establish when the current configuration began, the function
    reports insufficient evidence rather than guessing.
    """
    if not instance_id.strip():
        raise ValueError("EC2 instance ID cannot be empty.")

    if not current_instance_type.strip():
        raise ValueError(
            "Current EC2 instance type cannot be empty."
        )

    if history_days <= 0:
        raise ValueError(
            "history_days must be greater than zero."
        )

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=history_days)

    config_client = _get_config_client(aws)

    try:
        configuration_items = _get_configuration_items(
            config_client=config_client,
            instance_id=instance_id,
            start_time=start_time,
            end_time=end_time,
        )
    except ClientError as exc:
        error_code = exc.response.get(
            "Error",
            {},
        ).get("Code", "Unknown")

        return ConfigurationHistory(
            instance_id=instance_id,
            current_instance_type=current_instance_type,
            current_configuration_since=None,
            evidence_days=0.0,
            history_available=False,
            evidence_sufficient=False,
            changes=(),
            explanation=(
                "AWS Config configuration history is unavailable "
                f"for this instance. AWS returned {error_code}. "
                "The optimizer will not assume the configuration age."
            ),
        )

    changes = _build_changes(
        instance_id=instance_id,
        configuration_items=configuration_items,
    )

    if not changes:
        return ConfigurationHistory(
            instance_id=instance_id,
            current_instance_type=current_instance_type,
            current_configuration_since=None,
            evidence_days=0.0,
            history_available=False,
            evidence_sufficient=False,
            changes=(),
            explanation=(
                "No usable AWS Config configuration history was "
                "found. The optimizer cannot establish how long "
                "the current configuration has been active."
            ),
        )

    current_configuration_since = (
        _find_current_configuration_since(
            changes=changes,
            current_instance_type=current_instance_type,
        )
    )

    if current_configuration_since is None:
        return ConfigurationHistory(
            instance_id=instance_id,
            current_instance_type=current_instance_type,
            current_configuration_since=None,
            evidence_days=0.0,
            history_available=True,
            evidence_sufficient=False,
            changes=changes,
            explanation=(
                "AWS Config contains history, but it cannot establish "
                "when the current instance configuration began. "
                "Configuration age is therefore unknown."
            ),
        )

    evidence_duration = (
        end_time - current_configuration_since
    )

    evidence_days = max(
        evidence_duration.total_seconds() / 86400,
        0.0,
    )

    evidence_sufficient = (
        evidence_days >= MIN_CONFIGURATION_EVIDENCE_DAYS
    )

    if evidence_sufficient:
        explanation = (
            f"The current configuration has been observed for "
            f"{evidence_days:.1f} days. At least "
            f"{MIN_CONFIGURATION_EVIDENCE_DAYS} days of "
            "configuration-specific evidence are available."
        )
    else:
        remaining_days = (
            MIN_CONFIGURATION_EVIDENCE_DAYS - evidence_days
        )

        explanation = (
            f"The current configuration has only "
            f"{evidence_days:.1f} days of evidence. "
            f"Wait approximately {remaining_days:.1f} more days "
            "before making a rightsizing recommendation."
        )

    return ConfigurationHistory(
        instance_id=instance_id,
        current_instance_type=current_instance_type,
        current_configuration_since=current_configuration_since,
        evidence_days=evidence_days,
        history_available=True,
        evidence_sufficient=evidence_sufficient,
        changes=changes,
        explanation=explanation,
    )