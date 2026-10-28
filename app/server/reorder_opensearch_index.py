"""Reorder OpenSearch records using audit order and newest timestamps."""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "tenants"

AUDIT_FILE = OUTPUT_DIR / "data_ingestion_audit.json"
OPENSEARCH_FILE = OUTPUT_DIR / "opensearch_index.json"
REORDERED_FILE = OUTPUT_DIR / "reordered_opensearch_index.json"


def load_json_file(file_path: Path) -> list[dict[str, Any]]:
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in {file_path.name}")

    return data


def normalize_id(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def parse_timestamp(value: Any) -> datetime:
    """Parse timestamps into comparable UTC datetime values."""
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        timestamp = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        )

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        return timestamp.astimezone(timezone.utc)

    except (ValueError, TypeError, OverflowError):
        return datetime.min.replace(tzinfo=timezone.utc)


def reorder_opensearch_records() -> list[dict[str, Any]]:
    audit_records = load_json_file(AUDIT_FILE)
    opensearch_records = load_json_file(OPENSEARCH_FILE)

    # Group OpenSearch records by tenant_id + job_id.
    records_by_job: dict[
        tuple[str, str], list[dict[str, Any]]
    ] = defaultdict(list)

    for record in opensearch_records:
        tenant_id = normalize_id(record.get("tenant_id"))
        job_id = normalize_id(record.get("job_id"))

        if tenant_id and job_id:
            records_by_job[(tenant_id, job_id)].append(record)

    reordered_records: list[dict[str, Any]] = []
    processed_jobs: set[tuple[str, str]] = set()

    matched_jobs = 0
    unmatched_jobs = 0

    # Audit records are already ordered newest to oldest.
    # Keep that order; do not sort the audit file again.
    for audit in audit_records:
        tenant_id = normalize_id(audit.get("tenant_id"))
        job_id = normalize_id(audit.get("job_id"))

        if not tenant_id or not job_id:
            continue

        key = (tenant_id, job_id)

        # A job can appear multiple times in the audit file,
        # for example with different module_id values.
        # Process each tenant/job pair once, at its first appearance.
        if key in processed_jobs:
            continue

        processed_jobs.add(key)

        matching_records = records_by_job.get(key, [])

        if not matching_records:
            unmatched_jobs += 1
            continue

        # Newest OpenSearch timestamp first within each job.
        # Stable sorting preserves original order for equal timestamps.
        matching_records_sorted = sorted(
            matching_records,
            key=lambda record: parse_timestamp(record.get("timestamp")),
            reverse=True,
        )

        reordered_records.extend(matching_records_sorted)
        matched_jobs += 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with REORDERED_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            reordered_records,
            file,
            indent=4,
            ensure_ascii=False,
        )
        file.write("\n")

    print(f"Audit records loaded: {len(audit_records)}")
    print(f"OpenSearch records loaded: {len(opensearch_records)}")
    print(f"Jobs with matching records: {matched_jobs}")
    print(f"Jobs without matching records: {unmatched_jobs}")
    print(f"Reordered records written: {len(reordered_records)}")
    print(f"Output file: {REORDERED_FILE}")

    return reordered_records


if __name__ == "__main__":
    try:
        reorder_opensearch_records()
    except Exception as error:
        print(f"Failed to reorder OpenSearch records: {error}", file=sys.stderr)
        raise SystemExit(1)
