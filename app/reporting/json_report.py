from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()

    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _serialize(getattr(value, key))
            for key in value.__dataclass_fields__
        }

    if isinstance(value, tuple):
        return [_serialize(item) for item in value]

    if isinstance(value, list):
        return [_serialize(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _serialize(item)
            for key, item in value.items()
        }

    return value


def write_report(
    output_path: str,
    account_id: str,
    identity_arn: str,
    analysis_hours: float,
    instances: list[dict[str, Any]],
) -> Path:
    """Write the complete optimizer result as JSON."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "account_id": account_id,
        "identity_arn": identity_arn,
        "analysis_hours": analysis_hours,
        "instance_count": len(instances),
        "instances": _serialize(instances),
    }

    path.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return path