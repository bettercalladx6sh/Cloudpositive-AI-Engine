from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse, unquote

import pymysql
from pymysql.connections import Connection

from app.config import load_config


class DatabaseConfigurationError(ValueError):
    """Raised when database configuration is missing or invalid."""


def _database_parameters() -> dict[str, Any]:
    config = load_config()
    url = config.database.url
    if not url.startswith("mysql+pymysql://"):
        raise DatabaseConfigurationError(
            "DATABASE_URL must use mysql+pymysql://."
        )

    parsed = urlparse(url)
    if not parsed.hostname or not parsed.path.strip("/"):
        raise DatabaseConfigurationError(
            "DATABASE_URL must include a MySQL host and database name."
        )

    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/"),
        "charset": "utf8mb4",
        "autocommit": False,
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 10,
        "read_timeout": 60,
        "write_timeout": 60,
    }


def create_database_connection() -> Connection:
    """Open a direct PyMySQL connection to the configured MySQL database."""
    try:
        return pymysql.connect(**_database_parameters())
    except pymysql.MySQLError as exc:
        raise DatabaseConfigurationError(
            f"Unable to connect to MySQL: {exc}"
        ) from exc


def create_connection_factory():
    """Return a factory that opens a fresh direct PyMySQL connection."""
    def factory() -> Connection:
        return create_database_connection()

    return factory


@contextmanager
def get_connection() -> Generator[Connection, None, None]:
    connection = create_database_connection()
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_connection_from_factory(connection_factory) -> Generator[Connection, None, None]:
    """Yield a direct MySQL connection from a connection factory."""
    connection = connection_factory()
    try:
        yield connection
    finally:
        connection.close()
