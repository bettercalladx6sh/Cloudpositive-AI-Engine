"""Fetch AWS EC2 documents from available active tenants' OpenSearch indices."""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from opensearchpy.exceptions import NotFoundError, RequestError

from app.server.active_tenant import get_active_tenants
from app.auth.opensearch_connection import get_opensearch_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "tenants"
OUTPUT_FILE = OUTPUT_DIR / "opensearch_index.json"

PAGE_SIZE = 1000
SCROLL_TIMEOUT = "2m"


def json_serializer(value: Any):
    """Convert supported Python values into JSON-compatible values."""

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


def build_search_query(sort_by_timestamp: bool = True) -> dict[str, Any]:
    """Build the AWS EC2 search query."""

    query: dict[str, Any] = {
        "_source": [
            "job_id",
            "timestamp",
            "cloud_type",
            "product_code",
            "resource_id",
            "resource_name",
            "region",
            "account_id",
        ],
        "query": {
            "bool": {
                "filter": [
                    {"term": {"cloud_type.keyword": "AWS"}},
                    {"term": {"product_code.keyword": "AmazonEC2"}},
                ]
            }
        },
    }

    if sort_by_timestamp:
        query["sort"] = [
            {
                "timestamp": {
                    "order": "desc",
                    "unmapped_type": "date",
                }
            }
        ]

    return query


def fetch_index_records(
    client,
    index_name: str,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Fetch all matching documents from one available index."""

    records: list[dict[str, Any]] = []
    scroll_id = None

    try:
        if not client.indices.exists(index=index_name):
            return records

        mappings = client.indices.get_mapping(index=index_name)
        if not mappings:
            return records

        query = build_search_query(sort_by_timestamp=True)

        try:
            response = client.search(
                index=index_name,
                body=query,
                size=PAGE_SIZE,
                scroll=SCROLL_TIMEOUT,
                allow_no_indices=True,
                ignore_unavailable=True,
            )
        except RequestError as error:
            # Retry without sorting if timestamp cannot be sorted.
            if "No mapping found for [timestamp]" not in str(error):
                raise

            query = build_search_query(sort_by_timestamp=False)

            response = client.search(
                index=index_name,
                body=query,
                size=PAGE_SIZE,
                scroll=SCROLL_TIMEOUT,
                allow_no_indices=True,
                ignore_unavailable=True,
            )

        scroll_id = response.get("_scroll_id")
        hits = response.get("hits", {}).get("hits", [])

        while hits:
            for hit in hits:
                source = hit.get("_source", {})

                records.append(
                    {
                        "tenant_id": tenant_id,
                        "index_name": index_name,
                        "job_id": source.get("job_id"),
                        "timestamp": source.get("timestamp"),
                        "cloud_type": source.get("cloud_type"),
                        "product_code": source.get("product_code"),

                        # Required resource details
                        "resource_id": source.get("resource_id"),
                        "resource_name": source.get("resource_name"),
                        "region": source.get("region"),
                        "account_id": source.get("account_id"),
                    }
                )

            if not scroll_id:
                break

            response = client.scroll(
                scroll_id=scroll_id,
                scroll=SCROLL_TIMEOUT,
            )

            scroll_id = response.get("_scroll_id", scroll_id)
            hits = response.get("hits", {}).get("hits", [])

    except NotFoundError:
        return records

    finally:
        if scroll_id:
            try:
                client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass

    return records


def fetch_opensearch_index_data(
    save_json: bool = True,
) -> list[dict[str, Any]]:
    """
    Fetch AWS EC2 documents for all active tenants.

    Missing indices and indices without mappings are skipped.
    Results are optionally saved to the output JSON file.
    """

    client = None
    all_records: list[dict[str, Any]] = []

    try:
        active_tenants = get_active_tenants(save_json=False)

        active_tenant_ids = list(
            dict.fromkeys(
                str(tenant["id"])
                for tenant in active_tenants
                if tenant.get("id") is not None
            )
        )

        if active_tenant_ids:
            client = get_opensearch_connection()

            for tenant_id in active_tenant_ids:
                index_name = f"super_index_{tenant_id}"

                try:
                    records = fetch_index_records(
                        client=client,
                        index_name=index_name,
                        tenant_id=tenant_id,
                    )
                    all_records.extend(records)

                except NotFoundError:
                    continue

        if save_json:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            with OUTPUT_FILE.open("w", encoding="utf-8") as file:
                json.dump(
                    all_records,
                    file,
                    indent=4,
                    ensure_ascii=False,
                    default=json_serializer,
                )
                file.write("\n")

        print(f"Total records collected: {len(all_records)}")
        return all_records

    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    try:
        fetch_opensearch_index_data()
    except Exception as error:
        print(f"OpenSearch error: {type(error).__name__}: {error}")
        raise SystemExit(1)
