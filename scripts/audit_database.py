
#!/usr/bin/env python3
"""Read-only database audit with actionable JSON troubleshooting report.

Run from the project root:
  python scripts/audit_database.py
  python scripts/audit_database.py --hours 72
  python scripts/audit_database.py --date 2026-10-07
  python scripts/audit_database.py --all-history

Reads MySQL through PyMySQL. It never writes to the database and never calls AWS APIs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    import pymysql
except ImportError:
    print("ERROR: PyMySQL is required. Install with: python -m pip install pymysql")
    raise SystemExit(2)


REQUIRED_TABLES = {
    "instance_snapshots",
    "configuration_changes",
    "metric_observations",
    "metric_datapoints",
    "metric_collection_checkpoints",
    "analysis_runs",
    "recommendations",
    "recommendation_snapshots",
    "execution_runs",
    "metric_cumulative_summaries",
}

EXPECTED_METRICS = (
    ("AWS/EC2", "CPUUtilization"),
    ("EC2/Custom", "mem_used_percent"),
)

COUNTS = {"PASS": 0, "FAIL": 0, "WARN": 0}
CHECKS: list[dict[str, Any]] = []
REPORT_PATH = Path("output/database-audit-report.json")
STARTED: datetime | None = None


# ---------------------------------------------------------------------------
# Minimal PyMySQL adapter. No SQLAlchemy dependency.
# ---------------------------------------------------------------------------

class QueryResult:
    def __init__(self, cursor):
        self.rows = cursor.fetchall() if cursor.description else []

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def fetchall(self):
        return self.rows

    def one(self):
        if len(self.rows) != 1:
            raise RuntimeError(
                f"Expected one row, got {len(self.rows)}"
            )
        return self.rows[0]

    def scalar_one(self):
        return next(iter(self.one().values()))


class Connection:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def execute(self, query, params=None):
        sql = re.sub(
            r":([A-Za-z_][A-Za-z0-9_]*)",
            r"%(\1)s",
            str(query),
        )

        with self.conn.cursor() as cur:
            cur.execute(sql, params or {})
            return QueryResult(cur)


class Engine:
    def __init__(self, url):
        parsed = urlparse(url)

        if parsed.scheme not in {"mysql+pymysql", "mysql"}:
            raise ValueError(
                "DATABASE_URL must use mysql+pymysql:// or mysql://"
            )

        self.cfg = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": unquote(parsed.path.lstrip("/")),
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
            "connect_timeout": 10,
            "read_timeout": 60,
            "write_timeout": 60,
        }

        if not self.cfg["database"]:
            raise ValueError(
                "DATABASE_URL must include a database name"
            )

        self.open = []

    def connect(self):
        return Connection(pymysql.connect(**self.cfg))

    def tables_connection(self):
        conn = pymysql.connect(**self.cfg)
        self.open.append(conn)
        return conn

    def dispose(self):
        for conn in self.open:
            try:
                conn.close()
            except Exception:
                pass

        self.open.clear()


class Inspector:
    def __init__(self, conn):
        self.conn = conn

    def get_table_names(self):
        with self.conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            return [
                next(iter(row.values()))
                for row in cur.fetchall()
            ]

    def get_columns(self, table):
        if not table.replace("_", "").isalnum():
            raise ValueError("Invalid table name")

        with self.conn.cursor() as cur:
            cur.execute(f"SHOW COLUMNS FROM `{table}`")
            return {row["Field"] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Configuration and utility functions
# ---------------------------------------------------------------------------

def load_env():
    try:
        from dotenv import load_dotenv

        candidates = (
            Path.cwd() / ".env",
            Path(__file__).resolve().parent / ".env",
            Path(__file__).resolve().parent.parent / ".env",
        )

        for candidate in candidates:
            if candidate.is_file():
                load_dotenv(candidate, override=False)
                break

    except ImportError:
        pass


def get_engine():
    load_env()
    url = os.getenv("DATABASE_URL")

    if not url:
        print(
            "ERROR: DATABASE_URL is not set. "
            "Run from the project root with your .env file."
        )
        raise SystemExit(2)

    return Engine(url)


def fmt(value):
    if value is None:
        return "NULL"

    if isinstance(value, datetime):
        return value.isoformat(sep=" ")

    if isinstance(value, float):
        return (
            f"{value:.6f}"
            if math.isfinite(value)
            else str(value)
        )

    return str(value)


def heading(title):
    print("\n" + "=" * 96)
    print(title)
    print("=" * 96)


def cols(inspector, table):
    return inspector.get_columns(table)


def count_rows(conn, table):
    try:
        result = conn.execute(
            f"SELECT COUNT(*) AS n FROM `{table}`"
        ).one()
        return int(result["n"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Diagnostic guidance. Possible causes are hypotheses, not confirmed facts.
# ---------------------------------------------------------------------------

def guidance(label: str, detail: str, state: str):
    text = (label + " " + detail).lower()

    rules = [
        (
            ("required tables", "table is missing", "table missing"),
            [
                "A migration or database initialization did not create a required table.",
                "The audit may be connected to a different database.",
            ],
            [
                "Confirm the database name in DATABASE_URL without sharing its password.",
                "Compare SHOW TABLES with the project's database initialization/migration code.",
                "Review startup logs for migration errors.",
            ],
            [
                "Run the project's intended migration/initialization procedure after reviewing it.",
                "Do not invent columns or manually create tables based on guesses.",
            ],
            [
                "Rerun the audit and confirm required tables exist."
            ],
            "Missing tables can block persistence of metrics, evidence, or recommendations.",
        ),
        (
            (
                "datapoint",
                "hourly bucket",
                "metric series",
                "raw history",
                "cpu",
                "memory",
            ),
            [
                "The collector may not have run for this interval.",
                "The metric may not have been published or may have been queried with the wrong namespace, name, dimensions, or time range.",
                "Collection may have succeeded but database persistence may have failed.",
            ],
            [
                "Check collection logs for the instance and affected timestamps.",
                "Check the matching checkpoint and configuration version.",
                "Verify CPU AWS/EC2:CPUUtilization and memory EC2/Custom:mem_used_percent settings.",
                "If necessary, separately verify CloudWatch publication; this audit makes no AWS calls.",
            ],
            [
                "Fix the confirmed query, collection, or persistence defect.",
                "Fetch only confirmed missing intervals; do not redownload all history.",
                "Do not convert missing metrics to zero.",
            ],
            [
                "Rerun the same date/window audit and verify stored intervals and checkpoint state."
            ],
            "Incomplete metric evidence can make utilization summaries and recommendations unreliable.",
        ),
        (
            ("null", "missing aggregate", "evidence completeness", "column missing"),
            [
                "A write path may have persisted an incomplete row.",
                "Application and database schema versions may differ.",
                "A required value may be omitted in one code path.",
            ],
            [
                "Inspect the affected table/column and corresponding INSERT/model code.",
                "Review collection/aggregation logs near the record timestamp.",
                "Compare live schema with the code version writing these rows.",
            ],
            [
                "Fix the writer or migration so required fields are consistently persisted.",
                "Backfill only from verified source data; never fabricate metrics.",
            ],
            [
                "Rerun the same NULL/schema check and inspect newly written records."
            ],
            "Missing fields can invalidate evidence and downstream analysis.",
        ),
        (
            ("duplicate",),
            [
                "A retry may have inserted the same logical datapoint twice.",
                "The database uniqueness key may not match the metric-series identity.",
            ],
            [
                "Inspect instance, region, namespace, metric, configuration version and timestamp.",
                "Review retry/upsert behavior and unique indexes.",
            ],
            [
                "Make persistence idempotent and align uniqueness rules with the intended key.",
                "Do not delete duplicates before checking their provenance and summary effects.",
            ],
            [
                "Rerun duplicate checks and reconcile affected summaries."
            ],
            "Duplicates can distort counts, averages and recommendations.",
        ),
        (
            ("checkpoint", "stale", "future"),
            [
                "Checkpoint and datapoint persistence may not be coordinated.",
                "A checkpoint may advance despite incomplete writes.",
                "The collector may not have run recently or timestamps may use inconsistent timezones.",
            ],
            [
                "Compare checkpoint_at, updated_at and newest stored datapoint for the same series/version.",
                "Verify checkpoints advance only after successful persistence.",
                "Check whether a stopped instance or unavailable metric explains staleness.",
            ],
            [
                "Correct checkpoint advancement to represent successfully processed intervals.",
                "Reprocess only verified missing intervals.",
                "Document expected staleness for stopped instances.",
            ],
            [
                "Rerun checkpoint checks and verify ordering and timezone handling."
            ],
            "Incorrect checkpoints can skip missing intervals or cause repeated API calls.",
        ),
        (
            ("cumulative", "summary/raw", "summary row", "value_sum"),
            [
                "The summary may not have refreshed after raw data changed.",
                "Summary and raw calculations may use different NULL/zero filters.",
                "The compared records may cover different versions or windows.",
            ],
            [
                "Compare count, sum, average, minimum and maximum for the exact series key.",
                "Confirm intended zero/NULL filtering and time-window semantics in application code.",
                "Check summary updates and configuration-version scoping.",
            ],
            [
                "Fix the aggregation/update path first.",
                "Rebuild only affected summaries using verified raw data and exact application rules.",
            ],
            [
                "Rerun summary reconciliation and verify compared fields agree."
            ],
            "Incorrect summaries can mislead utilization analysis.",
        ),
        (
            ("observation", "window", "boundary", "overlap", "gap"),
            [
                "Evidence windows may have gaps or overlap intentionally as rolling windows.",
                "Writer and audit may use different inclusive/exclusive boundaries.",
            ],
            [
                "Inspect adjacent start/end timestamps for the same instance/metric/version.",
                "Confirm whether windows should be contiguous or rolling.",
                "Review timestamp boundary logic in the writer and raw-data queries.",
            ],
            [
                "Fix boundary calculations if continuity is required.",
                "Document intentional rolling overlap and prevent double counting.",
            ],
            [
                "Rerun window checks and document any expected overlap."
            ],
            "Bad windows can omit or double-count evidence.",
        ),
        (
            ("analysis run", "recommendation", "execution_runs", "snapshot"),
            [
                "An analysis may have failed before final status was stored.",
                "Recommendation/evidence persistence may be missing or incomplete.",
            ],
            [
                "Inspect run ID, status, timestamps and error fields.",
                "Review application logs/traceback at the run time.",
                "Check transaction commit/rollback and finalization paths.",
            ],
            [
                "Fix the underlying exception or transaction/finalization logic.",
                "Ensure failed runs are marked failed with useful error details.",
            ],
            [
                "Run a controlled analysis and confirm terminal status and expected records."
            ],
            "Incomplete history weakens troubleshooting and recommendation auditability.",
        ),
    ]

    if state == "PASS":
        return {
            "possible_issues": [],
            "diagnostic_checks": [],
            "recommended_solution": [],
            "verification_steps": [
                "No action needed unless related evidence changes."
            ],
            "impact": "No issue detected by this specific check.",
        }

    for keys, possible, checks, fixes, verify, impact in rules:
        if any(key in text for key in keys):
            return {
                "possible_issues": possible,
                "diagnostic_checks": checks,
                "recommended_solution": fixes,
                "verification_steps": verify,
                "impact": impact,
            }

    return {
        "possible_issues": [
            "The condition may be a defect or an expected state; the current evidence does not prove its root cause."
        ],
        "diagnostic_checks": [
            "Inspect the referenced table, rows, timestamps, instance and metric series.",
            "Compare with application logs and persistence/aggregation code.",
            "Confirm whether this condition is expected under the configured collection policy.",
        ],
        "recommended_solution": [
            "Fix only after confirming the root cause from evidence.",
            "Do not fabricate metrics or modify AWS resources as part of this audit.",
        ],
        "verification_steps": [
            "Rerun the same audit scope and confirm the finding is resolved or documented."
        ],
        "impact": "May affect data integrity, evidence sufficiency, or confidence in recommendations.",
    }


# ---------------------------------------------------------------------------
# Every call to status() becomes an individual JSON check.
# ---------------------------------------------------------------------------

def status(label, good, detail, *, affected_records=None):
    state = (
        "PASS" if good is True
        else "FAIL" if good is False
        else "WARN"
    )

    COUNTS[state] += 1
    advice = guidance(label, str(detail), state)

    check = {
        "check_id": (
            f"CHK-{len(CHECKS) + 1:04d}-"
            f"{re.sub(r'[^A-Z0-9]+', '_', label.upper()).strip('_')[:55]}"
        ),
        "status": state,
        "component": label.split(":", 1)[0],
        "what_was_checked": label,
        "expected_result": "The stated invariant or expected condition is satisfied.",
        "actual_result": str(detail),
        "possible_issues": advice["possible_issues"],
        "diagnostic_checks": advice["diagnostic_checks"],
        "recommended_solution": advice["recommended_solution"],
        "verification_steps": advice["verification_steps"],
        "impact": advice["impact"],
        "affected_records": (
            affected_records
            if affected_records is not None
            else {"details": str(detail)}
        ),
        "automatic_correction_performed": False,
        "aws_api_calls_made": False,
    }

    CHECKS.append(check)
    print(f"[{state:<4}] {label}: {detail}")


# ---------------------------------------------------------------------------
# Database audit sections
# ---------------------------------------------------------------------------

def audit_inventory(conn, inspector):
    heading("1. DATABASE TABLE INVENTORY")

    tables = set(inspector.get_table_names())
    missing = sorted(REQUIRED_TABLES - tables)

    status(
        "Required tables",
        not missing,
        (
            "missing: " + ", ".join(missing)
            if missing
            else f"all {len(REQUIRED_TABLES)} expected tables exist"
        ),
    )

    counts = {}

    for table in sorted(tables):
        count = count_rows(conn, table)
        counts[table] = count

        print(
            f"{table:38} rows="
            f"{count if count is not None else 'ERROR'}"
        )

        if table in REQUIRED_TABLES and count == 0:
            status(
                f"Table {table}",
                None,
                "table exists but is empty; confirm whether records are expected yet",
            )

    return tables, counts


def audit_metrics(conn, inspector, args, tables):
    heading("2. RAW METRIC DATAPOINTS AND HOURLY COVERAGE")

    if "metric_datapoints" not in tables:
        status(
            "Raw datapoints table",
            False,
            "metric_datapoints is missing",
        )
        return

    columns = cols(inspector, "metric_datapoints")

    required = {
        "instance_id", "region", "namespace", "metric_name",
        "timestamp", "average", "minimum", "maximum",
        "configuration_version", "observed_at",
    }

    missing = sorted(required - columns)

    if missing:
        status(
            "Raw datapoint schema",
            False,
            "missing columns: " + ", ".join(missing),
        )
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if args.date:
        start = datetime.combine(args.date, time.min)
        end = start + timedelta(days=1)
    elif args.all_history:
        start = end = None
    else:
        end = now
        start = end - timedelta(hours=args.hours)

    where = ""
    params = {}

    if start is not None:
        where = "WHERE timestamp >= :start AND timestamp < :end"
        params = {"start": start, "end": end}

    query = f"""
        SELECT instance_id, region, namespace, metric_name,
               configuration_version, timestamp, average, minimum,
               maximum, observed_at
        FROM metric_datapoints
        {where}
        ORDER BY instance_id, region, namespace, metric_name,
                 configuration_version, timestamp
    """

    rows = conn.execute(query, params).all()

    scope = (
        args.date.isoformat()
        if args.date
        else "all history"
        if args.all_history
        else f"last {args.hours:g} hours"
    )

    status(
        "Datapoint rows in scope",
        bool(rows),
        f"{len(rows)} stored rows for {scope}",
    )

    nulls = defaultdict(int)
    duplicates = []
    seen = set()
    series = defaultdict(list)
    zeros = []

    for row in rows:
        key = (
            row["instance_id"],
            row["region"],
            row["namespace"],
            row["metric_name"],
            row["configuration_version"],
        )

        series[key].append(row)

        for field in (
            "instance_id", "region", "namespace", "metric_name",
            "configuration_version", "timestamp", "observed_at",
            "average", "minimum", "maximum",
        ):
            if row.get(field) is None:
                nulls[field] += 1

        logical_key = key + (row["timestamp"],)

        if logical_key in seen:
            duplicates.append({
                "instance_id": row["instance_id"],
                "namespace": row["namespace"],
                "metric_name": row["metric_name"],
                "timestamp": fmt(row["timestamp"]),
            })

        seen.add(logical_key)

        if any(
            row.get(field) == 0
            for field in ("average", "minimum", "maximum")
        ):
            zeros.append({
                "instance_id": row["instance_id"],
                "metric": (
                    row["namespace"] + "/" + row["metric_name"]
                ),
                "timestamp": fmt(row["timestamp"]),
            })

    status(
        "Required datapoint fields not NULL",
        not nulls,
        f"NULL counts: {dict(nulls)}" if nulls else "no NULL values in required fields",
        affected_records=dict(nulls),
    )

    status(
        "Duplicate metric timestamps",
        not duplicates,
        f"{len(duplicates)} duplicate logical rows" if duplicates else "none detected",
        affected_records=duplicates[:100],
    )

    status(
        "Zero-valued metric rows",
        None if zeros else True,
        (
            f"{len(zeros)} row(s) contain zero in average/minimum/maximum; "
            "verify whether expected and whether app filtering is consistent"
        ),
        affected_records=zeros[:100],
    )

    # Build known instance inventory from stored records.
    instances = set()

    for table in (
        "instance_snapshots",
        "metric_datapoints",
        "metric_collection_checkpoints",
        "metric_observations",
        "metric_cumulative_summaries",
    ):
        if table not in tables:
            continue

        table_columns = cols(inspector, table)

        if {"instance_id", "region"}.issubset(table_columns):
            found = conn.execute(
                f"SELECT DISTINCT instance_id, region FROM `{table}`"
            ).all()

            instances.update(
                (row["instance_id"], row["region"])
                for row in found
            )

    expected = set(series)

    for instance_id, region in instances:
        for namespace, metric in EXPECTED_METRICS:
            versions = set()

            for table in (
                "metric_datapoints",
                "metric_collection_checkpoints",
                "metric_observations",
                "metric_cumulative_summaries",
            ):
                if table not in tables:
                    continue

                table_columns = cols(inspector, table)

                if not {
                    "instance_id", "region", "namespace", "metric_name"
                }.issubset(table_columns):
                    continue

                if "configuration_version" in table_columns:
                    version_select = (
                        "DISTINCT configuration_version AS version"
                    )
                else:
                    version_select = "DISTINCT 'legacy' AS version"

                found = conn.execute(
                    f"""
                    SELECT {version_select}
                    FROM `{table}`
                    WHERE instance_id=:i
                      AND region=:r
                      AND namespace=:n
                      AND metric_name=:m
                    """,
                    {
                        "i": instance_id,
                        "r": region,
                        "n": namespace,
                        "m": metric,
                    },
                ).all()

                versions.update(str(row["version"]) for row in found)

            for version in versions or {"legacy"}:
                expected.add((
                    instance_id, region, namespace, metric, version
                ))

    gaps = []

    if args.all_history:
        for key in sorted(expected):
            stored = series.get(key, [])

            if not stored:
                gaps.append({
                    "series": list(key),
                    "missing": "no stored raw datapoints; historical range unknown",
                })
                continue

            start = min(
                row["timestamp"] for row in stored
            ).replace(minute=0, second=0, microsecond=0)

            end = max(
                row["timestamp"] for row in stored
            ).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

            present = {
                row["timestamp"].replace(
                    minute=0, second=0, microsecond=0
                )
                for row in stored
                if row["timestamp"]
            }

            hours = max(
                0, int((end - start).total_seconds() // 3600)
            )

            for hour in range(hours):
                bucket = start + timedelta(hours=hour)

                if bucket not in present:
                    gaps.append({
                        "series": list(key),
                        "missing_hour_utc": fmt(bucket),
                    })

    elif start is not None:
        for key in sorted(expected):
            present = {
                row["timestamp"].replace(
                    minute=0, second=0, microsecond=0
                )
                for row in series.get(key, [])
                if row["timestamp"] and start <= row["timestamp"] < end
            }

            first_bucket = start.replace(
                minute=0, second=0, microsecond=0
            )

            hours = max(
                0, int((end - start).total_seconds() // 3600)
            )

            for hour in range(hours):
                bucket = first_bucket + timedelta(hours=hour)

                if bucket not in present:
                    gaps.append({
                        "series": list(key),
                        "missing_hour_utc": fmt(bucket),
                    })

    status(
        "Hourly metric coverage",
        not gaps,
        f"{len(gaps)} missing/unknown hourly buckets or series",
        affected_records=gaps[:300],
    )

    print(
        "NOTE: missing database rows do not prove CloudWatch did not publish data; "
        "this audit never queries AWS."
    )


def audit_checkpoints(conn, inspector, tables):
    heading("3. COLLECTION CHECKPOINTS")

    table = "metric_collection_checkpoints"

    if table not in tables:
        status("Checkpoint table", False, f"{table} is missing")
        return

    columns = cols(inspector, table)

    required = {
        "instance_id", "region", "namespace", "metric_name",
        "configuration_version", "checkpoint_at", "updated_at",
    }

    if not required.issubset(columns):
        status(
            "Checkpoint schema",
            False,
            "missing columns: " + ", ".join(sorted(required - columns)),
        )
        return

    checkpoints = conn.execute(
        f"SELECT * FROM `{table}`"
    ).all()

    status(
        "Checkpoint records",
        bool(checkpoints),
        f"{len(checkpoints)} rows",
    )

    problems = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for checkpoint_row in checkpoints:
        key = {
            field: checkpoint_row[field]
            for field in (
                "instance_id", "region", "namespace",
                "metric_name", "configuration_version",
            )
        }

        if "metric_datapoints" not in tables:
            continue

        raw = conn.execute(
            """
            SELECT MAX(timestamp) AS newest, COUNT(*) AS n
            FROM metric_datapoints
            WHERE instance_id=:instance_id
              AND region=:region
              AND namespace=:namespace
              AND metric_name=:metric_name
              AND configuration_version=:configuration_version
            """,
            key,
        ).one()

        checkpoint_at = checkpoint_row.get("checkpoint_at")
        newest = raw.get("newest")

        if (
            newest is None
            or (
                checkpoint_at is not None
                and checkpoint_at < newest
            )
            or (
                checkpoint_at is not None
                and checkpoint_at > now + timedelta(hours=1)
            )
        ):
            problems.append({
                "series": key,
                "checkpoint_at": fmt(checkpoint_at),
                "newest_datapoint": fmt(newest),
                "rows": raw.get("n"),
            })

        elif (
            checkpoint_at
            and now - checkpoint_at > timedelta(hours=48)
        ):
            print(
                f"[WARN detail] checkpoint older than 48h: "
                f"{key} checkpoint={fmt(checkpoint_at)} "
                "(may be expected for stopped instances)"
            )

    status(
        "Checkpoint ordering vs raw data",
        not problems,
        f"{len(problems)} missing-raw, behind-raw or future checkpoint conflict(s)",
        affected_records=problems[:200],
    )

    if (
        "metric_datapoints" in tables
        and "id" in columns
    ):
        orphaned = conn.execute(
            """
            SELECT DISTINCT d.instance_id, d.region, d.namespace,
                   d.metric_name, d.configuration_version
            FROM metric_datapoints d
            LEFT JOIN metric_collection_checkpoints c
              ON c.instance_id=d.instance_id
             AND c.region=d.region
             AND c.namespace=d.namespace
             AND c.metric_name=d.metric_name
             AND c.configuration_version=d.configuration_version
            WHERE c.id IS NULL
            """
        ).all()

        status(
            "Raw series with no checkpoint",
            not orphaned,
            f"{len(orphaned)} series have raw rows but no checkpoint",
            affected_records=orphaned[:200],
        )


def audit_summaries(conn, inspector, tables):
    heading("4. CUMULATIVE SUMMARY RECONCILIATION")

    if "metric_cumulative_summaries" not in tables:
        status(
            "Cumulative summary table",
            False,
            "metric_cumulative_summaries is missing",
        )
        return

    if "metric_datapoints" not in tables:
        status(
            "Cumulative summary source",
            False,
            "metric_datapoints is missing",
        )
        return

    columns = cols(inspector, "metric_cumulative_summaries")

    summaries = conn.execute(
        "SELECT * FROM metric_cumulative_summaries"
    ).all()

    status(
        "Cumulative summary rows",
        bool(summaries),
        f"{len(summaries)} rows",
    )

    required = {
        "instance_id", "region", "namespace", "metric_name",
        "configuration_version", "datapoint_count", "average",
        "minimum", "maximum", "value_sum",
    }

    if not required.issubset(columns):
        status(
            "Cumulative summary schema",
            False,
            "missing columns: " + ", ".join(sorted(required - columns)),
        )
        return

    mismatches = []

    for summary in summaries:
        key = {
            field: summary[field]
            for field in (
                "instance_id", "region", "namespace",
                "metric_name", "configuration_version",
            )
        }

        raw = conn.execute(
            """
            SELECT COUNT(average) AS n,
                   SUM(average) AS value_sum,
                   AVG(average) AS average,
                   MIN(average) AS minimum,
                   MAX(average) AS maximum
            FROM metric_datapoints
            WHERE instance_id=:instance_id
              AND region=:region
              AND namespace=:namespace
              AND metric_name=:metric_name
              AND configuration_version=:configuration_version
            """,
            key,
        ).one()

        errors = []

        if int(summary.get("datapoint_count") or 0) != int(raw.get("n") or 0):
            errors.append(
                f"count summary={summary.get('datapoint_count')} "
                f"raw={raw.get('n')}"
            )

        for field in ("average", "minimum", "maximum", "value_sum"):
            stored = summary.get(field)
            actual = raw.get(field)

            if stored is None and actual is None:
                continue

            if (
                stored is None
                or actual is None
                or not math.isclose(
                    float(stored),
                    float(actual),
                    rel_tol=1e-4,
                    abs_tol=1e-4,
                )
            ):
                errors.append(
                    f"{field} summary={fmt(stored)} raw={fmt(actual)}"
                )

        if errors:
            mismatches.append({
                "series": key,
                "mismatches": errors,
            })

    status(
        "Cumulative summaries vs raw datapoints",
        not mismatches,
        f"{len(mismatches)} summary rows differ from raw calculation",
        affected_records=mismatches[:200],
    )

    print(
        "Aggregation mismatches must be checked against the application's "
        "zero/NULL filtering and window rules before treating them as defects."
    )


def audit_observations(conn, inspector, tables):
    heading("5. METRIC OBSERVATIONS AND ANALYSIS WINDOWS")

    table = "metric_observations"

    if table not in tables:
        status(
            "Metric observations table",
            False,
            "metric_observations is missing",
        )
        return

    columns = cols(inspector, table)
    rows = conn.execute(f"SELECT * FROM `{table}`").all()

    status("Observation records", bool(rows), f"{len(rows)} rows")

    required_values = [
        field
        for field in (
            "average", "minimum", "maximum", "datapoint_count",
            "coverage_hours", "analysis_start", "analysis_end",
            "observed_at",
        )
        if field in columns
    ]

    nulls = []
    invalid_windows = []
    windows = defaultdict(list)

    for row in rows:
        for field in required_values:
            if row.get(field) is None:
                nulls.append({
                    "instance_id": row.get("instance_id"),
                    "metric": (
                        f"{row.get('namespace')}/{row.get('metric_name')}"
                    ),
                    "field": field,
                })

        start = row.get("analysis_start")
        end = row.get("analysis_end")

        if start and end:
            if end <= start:
                invalid_windows.append({
                    "instance_id": row.get("instance_id"),
                    "start": fmt(start),
                    "end": fmt(end),
                })

            key = tuple(
                row.get(field)
                for field in (
                    "instance_id", "region", "namespace",
                    "metric_name", "configuration_version",
                )
            )
            windows[key].append(row)

    status(
        "Observation required fields",
        not nulls,
        f"{len(nulls)} NULL required-field occurrence(s)",
        affected_records=nulls[:300],
    )

    status(
        "Observation window validity",
        not invalid_windows,
        f"{len(invalid_windows)} invalid windows (end must be after start)",
        affected_records=invalid_windows[:200],
    )

    gaps = []
    overlaps = []

    for key, series in windows.items():
        series.sort(
            key=lambda row: (
                row.get("analysis_start") or datetime.min,
                row.get("analysis_end") or datetime.min,
            )
        )

        for previous, following in zip(series, series[1:]):
            previous_end = previous.get("analysis_end")
            next_start = following.get("analysis_start")

            if not previous_end or not next_start:
                continue

            if previous_end < next_start:
                gaps.append({
                    "series": list(key),
                    "previous_end": fmt(previous_end),
                    "next_start": fmt(next_start),
                })

            elif previous_end > next_start:
                overlaps.append({
                    "series": list(key),
                    "previous_end": fmt(previous_end),
                    "next_start": fmt(next_start),
                })

    status(
        "Observation window gaps",
        not gaps,
        f"{len(gaps)} gap(s) between adjacent windows",
        affected_records=gaps[:200],
    )

    status(
        "Observation window overlaps",
        None if overlaps else True,
        f"{len(overlaps)} overlap(s); confirm if rolling windows are intentional",
        affected_records=overlaps[:200],
    )


def audit_runs(conn, inspector, tables):
    heading("6. ANALYSIS RUNS, RECOMMENDATIONS, SNAPSHOTS")

    if "analysis_runs" not in tables:
        status("Analysis runs table", False, "analysis_runs is missing")
    else:
        columns = cols(inspector, "analysis_runs")
        rows = conn.execute("SELECT * FROM analysis_runs").all()

        status("Analysis run records", bool(rows), f"{len(rows)} rows")

        incomplete = [
            {
                "id": row.get("id"),
                "instance_id": row.get("instance_id"),
                "status": row.get("status"),
                "started_at": fmt(row.get("started_at")),
                "completed_at": fmt(row.get("completed_at")),
                "error_message": row.get("error_message"),
            }
            for row in rows
            if (
                "completed_at" in columns
                and row.get("completed_at") is None
            )
            or str(row.get("status", "")).lower()
            in {"running", "started", "in_progress"}
        ]

        failed = [
            {
                "id": row.get("id"),
                "instance_id": row.get("instance_id"),
                "status": row.get("status"),
                "error_message": row.get("error_message"),
            }
            for row in rows
            if str(row.get("status", "")).lower()
            in {"failed", "error"}
        ]

        status(
            "Incomplete analysis runs",
            not incomplete,
            f"{len(incomplete)} incomplete run(s)",
            affected_records=incomplete[:200],
        )

        status(
            "Failed analysis runs",
            not failed,
            f"{len(failed)} failed/error run(s)",
            affected_records=failed[:200],
        )

    for table in (
        "recommendations",
        "recommendation_snapshots",
        "execution_runs",
    ):
        if table not in tables:
            status(f"{table} table", False, "table is missing")
            continue

        count = count_rows(conn, table)

        status(
            f"{table} records",
            count is not None,
            f"{count} rows" if count is not None else "could not count rows",
        )

        if table == "recommendation_snapshots":
            columns = cols(inspector, table)

            required = {
                "cpu_average", "memory_average",
                "cpu_datapoint_count", "memory_datapoint_count",
                "evidence_start", "evidence_end",
            }

            if required.issubset(columns):
                result = conn.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM recommendation_snapshots
                    WHERE cpu_average IS NULL
                       OR memory_average IS NULL
                       OR cpu_datapoint_count IS NULL
                       OR memory_datapoint_count IS NULL
                       OR evidence_start IS NULL
                       OR evidence_end IS NULL
                    """
                ).one()

                status(
                    "Recommendation snapshot evidence completeness",
                    int(result["n"]) == 0,
                    f"{result['n']} snapshot(s) missing CPU/memory values, "
                    "counts or evidence bounds",
                )


def audit_schema_nulls(conn, inspector, tables):
    heading("7. REQUIRED COLUMN AND NULL CHECKS")

    expected = {
        "metric_datapoints": [
            "instance_id", "region", "namespace", "metric_name",
            "configuration_version", "timestamp", "observed_at",
        ],
        "metric_collection_checkpoints": [
            "instance_id", "region", "namespace", "metric_name",
            "configuration_version", "checkpoint_at", "updated_at",
        ],
        "metric_observations": [
            "instance_id", "region", "namespace", "metric_name",
            "configuration_version", "datapoint_count", "coverage_hours",
            "analysis_start", "analysis_end", "observed_at",
        ],
        "metric_cumulative_summaries": [
            "instance_id", "region", "namespace", "metric_name",
            "configuration_version", "datapoint_count", "value_sum",
            "coverage_percent", "gap_count", "last_updated_at",
        ],
        "analysis_runs": [
            "instance_id", "region", "execution_run_id", "started_at",
            "status", "recommendation", "analysis_version", "created_at",
        ],
    }

    for table, fields in expected.items():
        if table not in tables:
            continue

        actual = cols(inspector, table)

        for field in fields:
            if field not in actual:
                status(
                    f"Schema column {table}.{field}",
                    False,
                    "column is missing",
                )
                continue

            result = conn.execute(
                f"SELECT COUNT(*) AS n FROM `{table}` WHERE `{field}` IS NULL"
            ).one()

            status(
                f"NULL check {table}.{field}",
                int(result["n"]) == 0,
                f"{result['n']} NULL row(s)",
            )


# ---------------------------------------------------------------------------
# JSON report and final summary
# ---------------------------------------------------------------------------

def write_report(started, finished, scope, database_name):
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    issues = sorted(
        (check for check in CHECKS if check["status"] != "PASS"),
        key=lambda check: (
            0 if check["status"] == "FAIL" else 1,
            check["check_id"],
        ),
    )

    report = {
        "report_type": "aws_cost_optimizer_database_audit",
        "report_version": 1,
        "audit_id": str(uuid.uuid4()),
        "overall_status": (
            "FAIL" if COUNTS["FAIL"]
            else "WARN" if COUNTS["WARN"]
            else "PASS"
        ),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "duration_seconds": round(
            (finished - started).total_seconds(), 3
        ),
        "database": {
            "name": database_name,
            "driver": "PyMySQL",
            "read_only_audit": True,
        },
        "audit_scope": scope,
        "safety": {
            "database_changes_made": False,
            "aws_api_calls_made": False,
            "aws_resources_modified": False,
            "automatic_corrections_performed": False,
        },
        "summary": {
            "checks_executed": len(CHECKS),
            "passed": COUNTS["PASS"],
            "failed": COUNTS["FAIL"],
            "warnings": COUNTS["WARN"],
            "issues_requiring_review": len(issues),
            "priority_order": ["FAIL", "WARN"],
        },
        "checks": CHECKS,
        "issues_to_fix": issues,
        "recommended_fix_order": [
            {
                "priority": index + 1,
                "check_id": issue["check_id"],
                "status": issue["status"],
                "issue": issue["what_was_checked"],
                "next_step": (
                    issue["diagnostic_checks"][0]
                    if issue["diagnostic_checks"]
                    else "Review finding details."
                ),
            }
            for index, issue in enumerate(issues)
        ],
        "limitations": [
            "Database-only audit; it does not call AWS APIs.",
            "Missing stored metrics do not prove AWS did not publish them.",
            "Possible issues are hypotheses, not confirmed causes unless evidence supports them.",
            "The audit does not automatically fix database records or AWS resources.",
            "Validate application-specific filtering/window rules before rebuilding summaries.",
        ],
    }

    temp_path = REPORT_PATH.with_suffix(
        REPORT_PATH.suffix + ".tmp"
    )

    temp_path.write_text(
        json.dumps(report, indent=2, default=str, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    temp_path.replace(REPORT_PATH)
    return REPORT_PATH


def scope_args(args):
    if args.date:
        return {
            "type": "specific_date",
            "date": args.date.isoformat(),
            "timezone": "UTC",
        }

    if args.all_history:
        return {"type": "all_history"}

    return {
        "type": "last_hours",
        "hours": args.hours,
        "timezone": "UTC",
    }


def main():
    global STARTED, REPORT_PATH

    parser = argparse.ArgumentParser(
        description="Read-only database audit with JSON troubleshooting report"
    )

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "--date",
        type=date.fromisoformat,
        help="UTC date, e.g. 2026-10-07",
    )

    group.add_argument(
        "--all-history",
        action="store_true",
        help="audit all stored metric history",
    )

    parser.add_argument(
        "--hours",
        type=float,
        default=24,
        help="lookback hours; default 24",
    )

    parser.add_argument(
        "--report",
        default="output/database-audit-report.json",
        help="JSON report output path",
    )

    args = parser.parse_args()

    if args.hours <= 0:
        parser.error("--hours must be greater than zero")

    REPORT_PATH = Path(args.report).expanduser().resolve()
    STARTED = datetime.now(timezone.utc)

    database_name = None
    engine = None

    print("AWS COST & INFRASTRUCTURE OPTIMIZER — DATABASE AUDIT")
    print(
        "READ-ONLY: no database writes, no AWS API calls, "
        "no AWS resource changes"
    )

    try:
        engine = get_engine()

        with engine.connect() as conn:
            database_name = conn.execute(
                "SELECT DATABASE() AS db"
            ).one()["db"]

            inspector = Inspector(engine.tables_connection())

            tables, counts = audit_inventory(conn, inspector)

            audit_metrics(conn, inspector, args, tables)
            audit_checkpoints(conn, inspector, tables)
            audit_summaries(conn, inspector, tables)
            audit_observations(conn, inspector, tables)
            audit_runs(conn, inspector, tables)
            audit_schema_nulls(conn, inspector, tables)

            heading("8. FINAL INVENTORY SUMMARY")

            for table in sorted(REQUIRED_TABLES):
                print(
                    f"{table:38} "
                    f"rows={counts.get(table, 'TABLE MISSING')}"
                )

    except Exception as exc:
        status(
            "Fatal audit/database query",
            False,
            f"{type(exc).__name__}: {exc}",
        )

        print(
            f"\n[FATAL] Audit stopped: {type(exc).__name__}: {exc}"
        )
        print(
            "Check DATABASE_URL, schema compatibility and application logs."
        )

        finished = datetime.now(timezone.utc)

        try:
            path = write_report(
                STARTED,
                finished,
                scope_args(args),
                database_name,
            )
            print(f"JSON troubleshooting report: {path}")
        except Exception as report_exc:
            print(f"Could not write JSON report: {report_exc}")

        return 2

    finally:
        if engine:
            engine.dispose()

    finished = datetime.now(timezone.utc)

    path = write_report(
        STARTED,
        finished,
        scope_args(args),
        database_name,
    )

    heading("AUDIT RESULT")

    print(
        f"PASS={COUNTS['PASS']} "
        f"FAIL={COUNTS['FAIL']} "
        f"WARN={COUNTS['WARN']}"
    )

    print(f"JSON troubleshooting report: {path}")

    issues = sorted(
        (check for check in CHECKS if check["status"] != "PASS"),
        key=lambda check: (
            0 if check["status"] == "FAIL" else 1,
            check["check_id"],
        ),
    )

    if not issues:
        print("No FAIL/WARN findings were recorded.")
    else:
        heading("ISSUES TO REVIEW / FIX — FAILURES FIRST")

        for index, issue in enumerate(issues, 1):
            print(
                f"{index}. [{issue['status']}] "
                f"{issue['what_was_checked']}"
            )

            print(f"   Actual: {issue['actual_result']}")

            if issue["diagnostic_checks"]:
                print(
                    "   First diagnostic step: "
                    + issue["diagnostic_checks"][0]
                )

            if issue["recommended_solution"]:
                print(
                    "   Suggested solution: "
                    + issue["recommended_solution"][0]
                )

    print("\nSafety: no database changes or AWS API calls were made.")

    return 1 if COUNTS["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())