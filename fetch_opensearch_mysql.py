
#!/usr/bin/env python3
"""Fetch MySQL ingestion details and OpenSearch records on demand."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.server.active_tenant import (
    get_active_tenants,
    get_mysql_connection,
)
from app.server.data_ingestion_audit import (
    get_completed_ingestion_audits,
)
load_dotenv(PROJECT_ROOT / ".env")

OUTPUT_DIR = PROJECT_ROOT / "output" / "tenants"

ACTIVE_TENANTS_FILE = OUTPUT_DIR / "active_tenants.json"
MODULE_FILE = OUTPUT_DIR / "superindex_module.json"
AUDIT_FILE = OUTPUT_DIR / "data_ingestion_audit.json"
OPENSEARCH_FILE = OUTPUT_DIR / "opensearch_index.json"

MODULE_NAME = "super_index"
INDEX_PREFIX = "super_index_"

YEAR_START = "2026-01-01T00:00:00"
YEAR_END = "2027-01-01T00:00:00"

PAGE_SIZE = 1000
SCROLL_TIME = "2m"


def json_serializer(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable"
    )


def save_json(file_path: Path, data: Any) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with file_path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False,
            default=json_serializer,
        )
        file.write("\n")

    print(f"Saved: {file_path}")


def normalize_id(value: Any) -> str:
    return str(value).strip() if value is not None else ""


# =========================================================
# 1. ACTIVE TENANTS
# =========================================================

def fetch_active_tenants() -> list[dict[str, Any]]:
    tenants = get_active_tenants(save_json=False)

    # Normalize returned records to dictionaries.
    tenant_records = [
        dict(tenant) for tenant in tenants
    ]

    save_json(ACTIVE_TENANTS_FILE, tenant_records)

    print(f"Active tenants fetched: {len(tenant_records)}")

    for tenant in tenant_records:
        print(
            f"Tenant ID: {tenant.get('id')} | "
            f"Status: {tenant.get('tenant_status', 'N/A')}"
        )

    return tenant_records


# =========================================================
# 2. SUPER INDEX MODULE ID
# =========================================================

def fetch_superindex_module_id() -> dict[str, Any]:
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM ingestion_modules
            WHERE LOWER(module_name) = %s
            LIMIT 1
            """,
            (MODULE_NAME,),
        )

        module = cursor.fetchone()

        if not module:
            raise RuntimeError(
                f"Module '{MODULE_NAME}' was not found "
                "in ingestion_modules."
            )

        module = dict(module)
        save_json(MODULE_FILE, module)

        print(f"Module name: {module.get('module_name')}")
        print(f"Super Index module ID: {module.get('id')}")

        return module

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# =========================================================
# 3. COMPLETED DATA INGESTION AUDITS
# =========================================================

def fetch_data_ingestion_audit() -> list[dict[str, Any]]:
    # Reuse your existing audit implementation.
    audits = get_completed_ingestion_audits(save_json=False)

    # Your existing SQL orders by end_time DESC.
    # Sort again to guarantee newest-first output.
    audits = [dict(audit) for audit in audits]

    def audit_sort_key(audit):
        value = audit.get("end_time")

        if value is None:
            return datetime.min

        if isinstance(value, datetime):
            return value.replace(tzinfo=None)

        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())

        try:
            return datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except (ValueError, TypeError):
            return datetime.min

    audits.sort(key=audit_sort_key, reverse=True)

    save_json(AUDIT_FILE, audits)

    print(f"Completed ingestion audits fetched: {len(audits)}")

    if audits:
        print(f"Newest audit end_time: {audits[0].get('end_time')}")
        print(f"Newest audit tenant_id: {audits[0].get('tenant_id')}")
        print(f"Newest audit job_id: {audits[0].get('job_id')}")

    return audits


# =========================================================
# 4. OPENSEARCH CONNECTION
# =========================================================

def get_opensearch_connection():
    url = os.getenv("OPENSEARCH_URL")
    username = os.getenv("OPENSEARCH_USER")
    password = os.getenv("OPENSEARCH_PASSWORD")

    if not url:
        raise RuntimeError("Missing OPENSEARCH_URL in .env")

    if not username or not password:
        raise RuntimeError(
            "Missing OPENSEARCH_USER or OPENSEARCH_PASSWORD in .env"
        )

    client = OpenSearch(
        hosts=[url],
        http_auth=(username, password),
        use_ssl=url.lower().startswith("https://"),
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False,
        timeout=30,
        max_retries=2,
        retry_on_timeout=True,
    )

    try:
        client.info()
        print("OpenSearch connection successful.")
        return client
    except Exception:
        client.close()
        raise


# =========================================================
# 5. FETCH OPENSEARCH DOCUMENTS FOR ONE TENANT
# =========================================================

def fetch_tenant_opensearch_records(
    client,
    tenant_id: str,
) -> list[dict[str, Any]]:
    index_name = f"{INDEX_PREFIX}{tenant_id}"

    query = {
        "size": PAGE_SIZE,
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"cloud_type.keyword": "AWS"}},
                    {"term": {"product_code.keyword": "AmazonEC2"}},
                    {
                        "range": {
                            "timestamp": {
                                "gte": YEAR_START,
                                "lt": YEAR_END,
                            }
                        }
                    },
                ]
            }
        },
        "sort": [
            {
                "timestamp": {
                    "order": "desc",
                    "unmapped_type": "date",
                }
            }
        ],
    }

    records: list[dict[str, Any]] = []
    scroll_id = None
    expected_total = 0

    try:
        response = client.search(
            index=index_name,
            body=query,
            scroll=SCROLL_TIME,
        )

        scroll_id = response.get("_scroll_id")
        total = response.get("hits", {}).get("total", 0)

        expected_total = (
            total.get("value", 0)
            if isinstance(total, dict)
            else total
        )

        hits = response.get("hits", {}).get("hits", [])

        while hits:
            for hit in hits:
                source = dict(hit.get("_source") or {})

                # Preserve the source structure expected by your
                # reorder script: tenant_id, job_id, timestamp, etc.
                source.setdefault("tenant_id", tenant_id)

                records.append(source)

            if not scroll_id:
                break

            response = client.scroll(
                scroll_id=scroll_id,
                scroll=SCROLL_TIME,
            )

            scroll_id = response.get("_scroll_id")
            hits = response.get("hits", {}).get("hits", [])

        print(
            f"Tenant {tenant_id}: fetched {len(records)} "
            f"of {expected_total} documents from {index_name}"
        )

        if len(records) != expected_total:
            raise RuntimeError(
                f"Incomplete retrieval from {index_name}: "
                f"expected {expected_total}, received {len(records)}"
            )

        return records

    except NotFoundError:
        # A missing tenant index is not silently treated as an empty one.
        raise RuntimeError(
            f"OpenSearch index '{index_name}' does not exist."
        )

    except Exception as error:
        raise RuntimeError(
            f"Failed to fetch index '{index_name}': {error}"
        ) from error

    finally:
        if scroll_id:
            try:
                client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass


# =========================================================
# 6. FETCH OPENSEARCH DATA FOR ALL ACTIVE TENANTS
# =========================================================

def fetch_opensearch() -> list[dict[str, Any]]:
    tenants = get_active_tenants(save_json=False)

    tenant_ids = list(
        dict.fromkeys(
            normalize_id(tenant.get("id"))
            for tenant in tenants
            if normalize_id(tenant.get("id"))
        )
    )

    print(f"Active tenant IDs: {len(tenant_ids)}")

    if not tenant_ids:
        save_json(OPENSEARCH_FILE, [])
        print("No active tenants found.")
        return []

    client = None
    all_records: list[dict[str, Any]] = []

    try:
        client = get_opensearch_connection()

        for number, tenant_id in enumerate(tenant_ids, start=1):
            print(
                f"\nProcessing tenant {number}/{len(tenant_ids)}: "
                f"{tenant_id}"
            )

            records = fetch_tenant_opensearch_records(
                client,
                tenant_id,
            )
            all_records.extend(records)

        all_records.sort(
            key=lambda record: str(record.get("timestamp") or ""),
            reverse=True,
        )

        save_json(OPENSEARCH_FILE, all_records)

        print(f"Total OpenSearch records fetched: {len(all_records)}")

        return all_records

    finally:
        if client is not None:
            client.close()
            print("OpenSearch connection closed.")


# =========================================================
# CLI
# =========================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fetch MySQL ingestion and OpenSearch data."
    )

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument(
        "--active-tenants",
        action="store_true",
        help="Fetch active tenants.",
    )
    group.add_argument(
        "--superindex-module-id",
        action="store_true",
        help="Fetch the super_index module details and ID.",
    )
    group.add_argument(
        "--data-ingestion-audit",
        action="store_true",
        help="Fetch completed ingestion audits, newest first.",
    )
    group.add_argument(
        "--opensearch",
        action="store_true",
        help="Fetch OpenSearch documents for active tenants.",
    )

    args = parser.parse_args()

    try:
        if args.active_tenants:
            fetch_active_tenants()

        elif args.superindex_module_id:
            fetch_superindex_module_id()

        elif args.data_ingestion_audit:
            fetch_data_ingestion_audit()

        elif args.opensearch:
            fetch_opensearch()

    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
