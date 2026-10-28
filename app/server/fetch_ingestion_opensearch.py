"""Run the complete ingestion and OpenSearch JSON workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from app.server.active_tenant import (
    get_active_tenants,
    OUTPUT_FILE as ACTIVE_TENANTS_FILE,
)
from app.server.superindex_module_id import (
    get_superindex_module,
    OUTPUT_FILE as SUPERINDEX_MODULE_FILE,
)
from app.server.data_ingestion_audit import (
    get_completed_ingestion_audits,
    OUTPUT_FILE as AUDIT_OUTPUT_FILE,
)
from app.server.opensearch_index import (
    fetch_opensearch_index_data,
    OUTPUT_FILE as OPENSEARCH_OUTPUT_FILE,
)
from app.server.reorder_opensearch_index import (
    reorder_opensearch_records,
    REORDERED_FILE,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "tenants"

console = Console()
error_console = Console(stderr=True)


def progress(message: str) -> None:
    console.print(f"  [cyan]→[/cyan] {message}")


def success(message: str) -> None:
    console.print(f"  [green]✓[/green] {message}")


def validate_json_file(path: Path) -> Any:
    """Verify that a JSON file exists and contains valid JSON."""

    if not path.is_file():
        raise RuntimeError(
            f"Expected JSON file was not generated: {path}"
        )

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(
            f"Could not read valid JSON from {path}: {exc}"
        ) from exc


def run_workflow() -> bool:
    """Run all ingestion and OpenSearch modules in order."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Active tenants
    progress("Fetching active tenants...")

    tenants = get_active_tenants(save_json=True)

    if not isinstance(tenants, list):
        raise RuntimeError(
            "get_active_tenants() did not return a list."
        )

    if not tenants:
        raise RuntimeError("No active tenants were found.")

    tenant_ids = list(
        dict.fromkeys(
            str(tenant["id"])
            for tenant in tenants
            if tenant.get("id") is not None
        )
    )

    if not tenant_ids:
        raise RuntimeError(
            "No valid active tenant IDs were found."
        )

    saved_tenants = validate_json_file(ACTIVE_TENANTS_FILE)

    if not isinstance(saved_tenants, list):
        raise RuntimeError(
            "active_tenants.json must contain a JSON list."
        )

    success(
        f"Active tenants fetched: {len(tenant_ids)}."
    )

    # 2. Super-index module
    progress("Fetching super_index module...")

    module = get_superindex_module(save_json=True)

    if not isinstance(module, dict) or module.get("id") is None:
        raise RuntimeError(
            "Could not retrieve the super_index module."
        )

    saved_module = validate_json_file(SUPERINDEX_MODULE_FILE)

    if not isinstance(saved_module, dict):
        raise RuntimeError(
            "superindex_module_id.json must contain a JSON object."
        )

    success(
        f"Super_index module fetched: {module['id']}."
    )

    # 3. Completed ingestion audits
    progress("Fetching completed ingestion audits...")

    if AUDIT_OUTPUT_FILE.exists():
        AUDIT_OUTPUT_FILE.unlink()

    audits = get_completed_ingestion_audits(save_json=True)

    if not isinstance(audits, list):
        raise RuntimeError(
            "get_completed_ingestion_audits() "
            "did not return a list."
        )

    saved_audits = validate_json_file(AUDIT_OUTPUT_FILE)

    if not isinstance(saved_audits, list):
        raise RuntimeError(
            "data_ingestion_audit.json must contain a JSON list."
        )

    success(
        f"Completed ingestion audits fetched: "
        f"{len(saved_audits)}."
    )

    # 4. OpenSearch records
    progress("Fetching OpenSearch index records...")

    if OPENSEARCH_OUTPUT_FILE.exists():
        OPENSEARCH_OUTPUT_FILE.unlink()

    opensearch_records = fetch_opensearch_index_data(
        save_json=True
    )

    if not isinstance(opensearch_records, list):
        raise RuntimeError(
            "fetch_opensearch_index_data() "
            "did not return a list."
        )

    saved_opensearch_records = validate_json_file(
        OPENSEARCH_OUTPUT_FILE
    )

    if not isinstance(saved_opensearch_records, list):
        raise RuntimeError(
            "opensearch_index.json must contain a JSON list."
        )

    success(
        f"OpenSearch records fetched: "
        f"{len(saved_opensearch_records)}."
    )

    # 5. Reorder OpenSearch records
    progress("Reordering OpenSearch records using audit order...")

    if REORDERED_FILE.exists():
        REORDERED_FILE.unlink()

    reordered_records = reorder_opensearch_records()

    if not isinstance(reordered_records, list):
        raise RuntimeError(
            "reorder_opensearch_records() "
            "did not return a list."
        )

    saved_reordered_records = validate_json_file(REORDERED_FILE)

    if not isinstance(saved_reordered_records, list):
        raise RuntimeError(
            "reordered_opensearch_index.json "
            "must contain a JSON list."
        )

    success(
        f"OpenSearch records reordered: "
        f"{len(saved_reordered_records)}."
    )

    # Final output
    success("Ingestion and OpenSearch workflow completed.")

    for output_file in (
        ACTIVE_TENANTS_FILE,
        SUPERINDEX_MODULE_FILE,
        AUDIT_OUTPUT_FILE,
        OPENSEARCH_OUTPUT_FILE,
        REORDERED_FILE,
    ):
        console.print(f"    [dim]↳ {output_file}[/dim]")

    return True


def main() -> int:
    """Entry point for command-line execution."""

    try:
        run_workflow()
        return 0
    except Exception as exc:
        error_console.print(
            f"  [red]✗ Workflow failed: "
            f"{type(exc).__name__}: {exc}[/red]"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
