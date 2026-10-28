
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pymysql
from rich.console import Console
from rich.table import Table


CPU_NAMESPACE = "AWS/EC2"
CPU_METRIC = "CPUUtilization"

MEMORY_NAMESPACE = "EC2/Custom"
MEMORY_METRIC = "mem_used_percent"

DEFAULT_GAP_LIMIT_HOURS = 1.5


def _database_settings() -> dict[str, Any]:
    """Read the existing DATABASE_URL without printing credentials."""

    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured in the environment."
        )

    parsed = urlparse(database_url)

    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise RuntimeError(
            "Readiness reporting expects a MySQL DATABASE_URL."
        )

    if not parsed.hostname or not parsed.path.strip("/"):
        raise RuntimeError(
            "DATABASE_URL must contain a MySQL host and database name."
        )

    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.lstrip("/")),
        "charset": "utf8mb4",
        "connect_timeout": 5,
        "read_timeout": 10,
        "write_timeout": 10,
        "cursorclass": pymysql.cursors.DictCursor,
    }


def _hours_until(
    first: datetime | None,
    last: datetime | None,
) -> float:
    if first is None or last is None:
        return 0.0

    return max(
        0.0,
        (last - first).total_seconds() / 3600,
    )


def _as_utc(value: Any) -> datetime | None:
    """Normalize MySQL datetime values to UTC-aware datetimes."""

    if value is None:
        return None

    if isinstance(value, str):
        value = datetime.fromisoformat(value)

    if value.tzinfo is None:
        # MySQL DATETIME values are assumed to be stored in UTC.
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _hours(value: float | None) -> float | None:
    if value is None:
        return None

    return round(value, 2)


def _find_metric_table(
    connection: Any,
) -> str:
    """Find the expected cached metrics table without guessing its columns."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'metric_datapoints'
            LIMIT 1
            """
        )

        row = cursor.fetchone()

    if not row:
        raise RuntimeError(
            "Table metric_datapoints was not found in the configured database."
        )

    return str(row["TABLE_NAME"])


def _get_columns(
    connection: Any,
    table_name: str,
) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
            """,
            (table_name,),
        )

        return {
            str(row["COLUMN_NAME"])
            for row in cursor.fetchall()
        }


def _choose_column(
    columns: set[str],
    options: tuple[str, ...],
    purpose: str,
) -> str:
    for option in options:
        if option in columns:
            return option

    raise RuntimeError(
        f"Cannot identify the {purpose} column in metric_datapoints. "
        f"Available columns: {', '.join(sorted(columns))}"
    )


def _load_metric_rows(
    connection: Any,
    *,
    start: datetime,
    now: datetime,
) -> list[dict[str, Any]]:
    """
    Read cached metric timestamps only.

    This does not call AWS or fetch metric payloads.
    Column names are inspected first to accommodate common schema variants.
    """

    table = _find_metric_table(connection)
    columns = _get_columns(connection, table)

    instance_col = _choose_column(
        columns,
        ("instance_id",),
        "instance ID",
    )
    region_col = _choose_column(
        columns,
        ("region",),
        "region",
    )
    namespace_col = _choose_column(
        columns,
        ("namespace",),
        "namespace",
    )
    metric_col = _choose_column(
        columns,
        ("metric_name",),
        "metric name",
    )
    timestamp_col = _choose_column(
        columns,
        ("timestamp", "datapoint_timestamp", "collected_at"),
        "datapoint timestamp",
    )

    query = f"""
        SELECT
            `{instance_col}` AS instance_id,
            `{region_col}` AS region,
            `{namespace_col}` AS namespace,
            `{metric_col}` AS metric_name,
            `{timestamp_col}` AS datapoint_time
        FROM `{table}`
        WHERE `{timestamp_col}` >= %s
          AND `{timestamp_col}` <= %s
          AND (
              (`{namespace_col}` = %s AND `{metric_col}` = %s)
              OR
              (`{namespace_col}` = %s AND `{metric_col}` = %s)
          )
        ORDER BY
            `{instance_col}`,
            `{region_col}`,
            `{namespace_col}`,
            `{metric_col}`,
            `{timestamp_col}`
    """

    with connection.cursor() as cursor:
        cursor.execute(
            query,
            (
                start.replace(tzinfo=None),
                now.replace(tzinfo=None),
                CPU_NAMESPACE,
                CPU_METRIC,
                MEMORY_NAMESPACE,
                MEMORY_METRIC,
            ),
        )

        return list(cursor.fetchall())


def _analyze_metric(
    *,
    rows: list[dict[str, Any]],
    instance_id: str,
    region: str,
    namespace: str,
    metric_name: str,
    start: datetime,
    now: datetime,
    required_hours: float,
    gap_limit_hours: float,
) -> dict[str, Any]:
    matching = [
        row
        for row in rows
        if str(row["instance_id"]) == instance_id
        and str(row["region"]) == region
        and str(row["namespace"]) == namespace
        and str(row["metric_name"]) == metric_name
    ]

    timestamps = sorted(
        {
            timestamp
            for row in matching
            if (timestamp := _as_utc(row["datapoint_time"]))
            is not None
            and start <= timestamp <= now
        }
    )

    first = timestamps[0] if timestamps else None
    last = timestamps[-1] if timestamps else None

    span_hours = _hours_until(first, last)

    # The window is the requested duration, not just the first-to-last span.
    elapsed_hours = max(
        0.0,
        (now - start).total_seconds() / 3600,
    )

    coverage_percent = (
        min(100.0, span_hours / required_hours * 100)
        if required_hours > 0
        else 100.0
    )

    gaps: list[dict[str, Any]] = []

    for previous, current in zip(
        timestamps,
        timestamps[1:],
    ):
        gap_hours = (
            current - previous
        ).total_seconds() / 3600

        if gap_hours > gap_limit_hours:
            gaps.append(
                {
                    "from": previous.isoformat(),
                    "to": current.isoformat(),
                    "gap_hours": round(gap_hours, 2),
                }
            )

    latest_age_hours = (
        (now - last).total_seconds() / 3600
        if last is not None
        else None
    )

    if not timestamps:
        status = "NO_DATA"
        remaining_hours = required_hours

    elif span_hours < required_hours:
        status = "COLLECTING"
        remaining_hours = max(
            0.0,
            required_hours - span_hours,
        )

    elif latest_age_hours is not None and latest_age_hours > gap_limit_hours:
        status = "STALE"
        remaining_hours = None

    elif gaps:
        status = "HAS_GAPS"
        remaining_hours = None

    else:
        status = "READY"
        remaining_hours = 0.0

    return {
        "namespace": namespace,
        "metric_name": metric_name,
        "datapoint_count": len(timestamps),
        "first_datapoint": first.isoformat() if first else None,
        "last_datapoint": last.isoformat() if last else None,
        "latest_datapoint_age_hours": _hours(latest_age_hours),
        "observed_span_hours": _hours(span_hours),
        "required_hours": round(required_hours, 2),
        "coverage_percent": round(coverage_percent, 2),
        "gap_count": len(gaps),
        "gaps": gaps,
        "status": status,
        "estimated_remaining_hours": _hours(remaining_hours),
        "note": (
            "Estimated from existing timestamps. Future collection "
            "assumes metrics continue arriving at a sufficient rate."
        ),
    }


def build_readiness_report(
    *,
    analysis_hours: float,
    required_evidence_hours: float,
    gap_limit_hours: float = DEFAULT_GAP_LIMIT_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a readiness report from cached MySQL metric timestamps."""

    if analysis_hours <= 0:
        raise ValueError("analysis_hours must be greater than zero.")

    if required_evidence_hours <= 0:
        raise ValueError(
            "required_evidence_hours must be greater than zero."
        )

    if gap_limit_hours <= 0:
        raise ValueError("gap_limit_hours must be greater than zero.")

    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now = now.astimezone(timezone.utc)
    start = now - timedelta(hours=analysis_hours)

    report: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "analysis_window": {
            "start": start.isoformat(),
            "end": now.isoformat(),
            "requested_hours": analysis_hours,
            "required_evidence_hours": required_evidence_hours,
            "maximum_allowed_gap_hours": gap_limit_hours,
        },
        "data_source": "Existing MySQL metric_datapoints cache",
        "additional_cloudwatch_api_calls": 0,
        "instances": [],
        "summary": {},
        "limitations": [
            "Only cached datapoints inside the configured analysis window are counted.",
            "An instance with no cached datapoints cannot be discovered from this table alone.",
            "Metric readiness does not replace evaluate_evidence() or its configuration-change cooldown rules.",
            "Estimated remaining time assumes future datapoints arrive consistently.",
        ],
    }

    connection = pymysql.connect(**_database_settings())

    try:
        rows = _load_metric_rows(
            connection,
            start=start,
            now=now,
        )
    finally:
        connection.close()

    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        key = (
            str(row["instance_id"]),
            str(row["region"]),
        )

        grouped.setdefault(
            key,
            {
                "instance_id": key[0],
                "region": key[1],
                "metrics": {},
            },
        )

    for (instance_id, region), item in grouped.items():
        item["metrics"]["cpu"] = _analyze_metric(
            rows=rows,
            instance_id=instance_id,
            region=region,
            namespace=CPU_NAMESPACE,
            metric_name=CPU_METRIC,
            start=start,
            now=now,
            required_hours=required_evidence_hours,
            gap_limit_hours=gap_limit_hours,
        )

        item["metrics"]["memory"] = _analyze_metric(
            rows=rows,
            instance_id=instance_id,
            region=region,
            namespace=MEMORY_NAMESPACE,
            metric_name=MEMORY_METRIC,
            start=start,
            now=now,
            required_hours=required_evidence_hours,
            gap_limit_hours=gap_limit_hours,
        )

        statuses = [
            metric["status"]
            for metric in item["metrics"].values()
        ]

        if all(status == "READY" for status in statuses):
            item["status"] = "READY"
            item["estimated_remaining_hours"] = 0.0

        elif any(status == "STALE" for status in statuses):
            item["status"] = "STALE"
            item["estimated_remaining_hours"] = None

        elif any(status == "HAS_GAPS" for status in statuses):
            item["status"] = "HAS_GAPS"
            item["estimated_remaining_hours"] = None

        else:
            item["status"] = "COLLECTING"
            remaining = [
                metric["estimated_remaining_hours"]
                for metric in item["metrics"].values()
                if metric["estimated_remaining_hours"] is not None
            ]
            item["estimated_remaining_hours"] = (
                max(remaining) if remaining else None
            )

        report["instances"].append(item)

    statuses = [
        item["status"]
        for item in report["instances"]
    ]

    report["summary"] = {
        "instances_with_cached_metrics": len(report["instances"]),
        "ready_instances": statuses.count("READY"),
        "collecting_instances": statuses.count("COLLECTING"),
        "stale_instances": statuses.count("STALE"),
        "instances_with_gaps": statuses.count("HAS_GAPS"),
        "total_cpu_datapoints": sum(
            item["metrics"]["cpu"]["datapoint_count"]
            for item in report["instances"]
        ),
        "total_memory_datapoints": sum(
            item["metrics"]["memory"]["datapoint_count"]
            for item in report["instances"]
        ),
    }

    return report


def write_readiness_report(
    *,
    analysis_hours: float,
    required_evidence_hours: float,
    output_path: str = "output/analysis-readiness.json",
    console: Console | None = None,
) -> dict[str, Any] | None:
    """Write a readiness report without interrupting the main analysis."""

    console = console or Console()

    try:
        report = build_readiness_report(
            analysis_hours=analysis_hours,
            required_evidence_hours=required_evidence_hours,
        )

        path = Path(output_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        console.print(
        f"Metric readiness report stored in: {output_path}"
)
        
        return report

    except Exception as exc:
        console.print(
            f"  [yellow]! Readiness report could not be generated: "
            f"{exc}[/yellow]"
        )
        return None