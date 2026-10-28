"""Fetch active tenants from MySQL and save them as JSON."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import mysql.connector
from dotenv import load_dotenv


# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load .env from the project root
load_dotenv(PROJECT_ROOT / ".env")

# Output JSON file
OUTPUT_DIR = PROJECT_ROOT / "output" / "tenants"
OUTPUT_FILE = OUTPUT_DIR / "active_tenants.json"


def get_mysql_connection():
    """Connect to the remote MySQL server using .env configuration."""

    host = os.getenv("DB_HOST")
    port = int(os.getenv("DB_PORT") or "3306")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    database = os.getenv("DB_NAME")

    missing = [
        name
        for name, value in {
            "MYSQL_HOST": host,
            "DB_USER": user,
            "DB_PASSWORD": password,
            "DB_NAME": database,
        }.items()
        if not value
    ]

    if missing:
        raise ValueError(
            "Missing MySQL configuration in .env: "
            + ", ".join(missing)
        )

    return mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connection_timeout=10,
    )


def _json_serializer(value: Any):
    """Convert MySQL values into JSON-compatible values."""

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


def get_active_tenants(
    save_json: bool = True,
) -> list[dict[str, Any]]:
    """
    Fetch active tenants from MySQL.

    Returns:
        A list of tenant dictionaries.

    Args:
        save_json: Save the results to active_tenants.json.
    """

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM tenants
            WHERE tenant_status = %s
              AND is_deleted = %s
            """,
            ("active", 0),
        )

        tenants = cursor.fetchall()

        if save_json:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            with OUTPUT_FILE.open("w", encoding="utf-8") as file:
                json.dump(
                    tenants,
                    file,
                    indent=4,
                    ensure_ascii=False,
                    default=_json_serializer,
                )
                file.write("\n")

            print(f"JSON saved to: {OUTPUT_FILE}")

        print(f"Active tenants fetched: {len(tenants)}")

        return tenants

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    try:
        active_tenants = get_active_tenants()
        print("Active tenant fetch completed successfully.")

    except (ValueError, mysql.connector.Error, OSError) as error:
        print(f"Active tenant fetch failed: {error}")
        raise SystemExit(1)