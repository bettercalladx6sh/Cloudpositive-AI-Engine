#!/usr/bin/env python3
"""Fetch the super_index ingestion module and save it as JSON."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.server.active_tenant import get_mysql_connection


# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Output directory and JSON file
OUTPUT_DIR = PROJECT_ROOT / "output" / "tenants"
OUTPUT_FILE = OUTPUT_DIR / "superindex_module_id.json"


def _json_serializer(value: Any):
    """Convert MySQL-specific values into JSON-compatible values."""

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


def get_superindex_module(save_json: bool = True) -> dict[str, Any] | None:
    """
    Fetch the super_index module row from ingestion_modules.

    Args:
        save_json: Save the retrieved row to JSON when True.

    Returns:
        A dictionary containing all columns from the matching row,
        or None if no matching row exists.
    """

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM ingestion_modules
            WHERE module_name = %s
            LIMIT 1
            """,
            ("super_index",),
        )

        module = cursor.fetchone()

        if module is None:
            print("No ingestion_modules row found for module_name='super_index'.")

            if save_json:
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

                with OUTPUT_FILE.open("w", encoding="utf-8") as file:
                    json.dump(None, file, indent=4)

            return None

        if save_json:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            with OUTPUT_FILE.open("w", encoding="utf-8") as file:
                json.dump(
                    module,
                    file,
                    indent=4,
                    ensure_ascii=False,
                    default=_json_serializer,
                )
                file.write("\n")

            print(f"JSON saved to: {OUTPUT_FILE}")

        print("super_index module fetched successfully.")

        return module

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    try:
        superindex_module = get_superindex_module()
        print(json.dumps(
            superindex_module,
            indent=4,
            ensure_ascii=False,
            default=_json_serializer,
        ))

    except Exception as error:
        print(f"Failed to fetch super_index module: {error}")
        raise SystemExit(1)