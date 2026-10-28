
"""Fetch completed ingestion audits for active tenants during 2026."""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.server.active_tenant import (
    get_active_tenants,
    get_mysql_connection,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

OUTPUT_DIR = PROJECT_ROOT / "output" / "tenants"
OUTPUT_FILE = OUTPUT_DIR / "data_ingestion_audit.json"


def json_serializer(value: Any):
    """Convert database values into JSON-compatible values."""

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


def get_completed_ingestion_audits(
    save_json: bool = True,
) -> list[dict[str, Any]]:
    """
    Fetch completed ingestion audits for active tenants during 2026.

    Conditions:
        1. status must be COMPLETED.
        2. tenant_id must match an active tenant's id.
        3. audit_date must fall within calendar year 2026.
        4. job_id must not be NULL.
        5. Results are ordered by end_time, newest first.
        6. Results are saved to the JSON file when save_json=True.

    Returns:
        A list of matching audit records.
    """

    connection = None
    cursor = None

    try:
        # Fetch active tenants using the existing function.
        active_tenants = get_active_tenants(save_json=False)

        # The tenant records use "id" as their identifier.
        active_tenant_ids = [
            str(tenant["id"])
            for tenant in active_tenants
            if tenant.get("id") is not None
        ]

        # Remove duplicate IDs while preserving order.
        active_tenant_ids = list(dict.fromkeys(active_tenant_ids))

        print(f"Active tenant IDs found: {len(active_tenant_ids)}")

        audits = []

        if active_tenant_ids:
            connection = get_mysql_connection()
            cursor = connection.cursor(dictionary=True)

            placeholders = ", ".join(
                ["%s"] * len(active_tenant_ids)
            )

            query = f"""
                SELECT *
                FROM data_ingestion_audit
                WHERE status = %s
                  AND tenant_id IN ({placeholders})
                  AND audit_date >= %s
                  AND audit_date < %s
                  AND job_id IS NOT NULL
                ORDER BY end_time DESC
            """

            parameters = [
                "COMPLETED",
                *active_tenant_ids,
                date(2026, 1, 1),
                date(2027, 1, 1),
            ]

            cursor.execute(query, parameters)
            audits = cursor.fetchall()

        print(
            "Completed audit records matching all conditions: "
            f"{len(audits)}"
        )

        # Save results, including an empty list if nothing matches.
        if save_json:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            with OUTPUT_FILE.open("w", encoding="utf-8") as file:
                json.dump(
                    audits,
                    file,
                    indent=4,
                    ensure_ascii=False,
                    default=json_serializer,
                )
                file.write("\n")

            print(f"JSON saved successfully: {OUTPUT_FILE}")
            print(f"File size: {OUTPUT_FILE.stat().st_size} bytes")

        return audits

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    try:
        audit_records = get_completed_ingestion_audits()

        print(
            "Finished successfully. "
            f"Total audit records: {len(audit_records)}"
        )

    except Exception as error:
        print(f"Failed to fetch ingestion audits: {error}")
        raise SystemExit(1)
