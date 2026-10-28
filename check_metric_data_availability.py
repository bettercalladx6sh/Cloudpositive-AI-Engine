
#!/usr/bin/env python3
"""
Check CloudWatch metric data availability stored in MySQL.

Reports:
- First and latest datapoint timestamps
- Calendar days covered (inclusive)
- Distinct days containing datapoints
- Total datapoints
- Missing dates inside the available range
- Recorded analysis coverage from metric_observations

Uses DATABASE_URL from .env.
Read-only: does not insert, update, or delete any records.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import unquote, urlparse

try:
    import pymysql
    from dotenv import load_dotenv
except ImportError as exc:
    print(
        "Missing dependencies. Install them using:\n"
        "pip install pymysql python-dotenv"
    )
    raise SystemExit(1) from exc


DEFAULT_DATAPOINT_TABLE = "metric_datapoints"
DEFAULT_OBSERVATION_TABLE = "metric_observations"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Inspect stored CloudWatch metric data availability."
    )

    parser.add_argument(
        "--instance-id",
        help="Filter by EC2 instance ID, e.g. i-0123456789abcdef0",
    )
    parser.add_argument(
        "--region",
        help="Filter by AWS region, e.g. us-east-1",
    )
    parser.add_argument(
        "--metric",
        help="Filter by metric name, e.g. CPUUtilization",
    )
    parser.add_argument(
        "--namespace",
        help="Filter by namespace, e.g. AWS/EC2",
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_DATAPOINT_TABLE,
        help=f"Datapoint table (default: {DEFAULT_DATAPOINT_TABLE})",
    )
    parser.add_argument(
        "--observation-table",
        default=DEFAULT_OBSERVATION_TABLE,
        help=f"Observation table (default: {DEFAULT_OBSERVATION_TABLE})",
    )
    parser.add_argument(
        "--show-missing-days",
        action="store_true",
        help="Print every missing calendar date for each metric.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Show aggregate totals without per-metric details.",
    )

    return parser.parse_args()


def validate_table_name(name: str) -> str:
    """Prevent SQL injection through configurable table names."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Invalid table name: {name!r}")
    return name


def get_connection():
    """Connect using the existing DATABASE_URL in .env."""
    load_dotenv()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL was not found. Put it in your project's .env file."
        )

    parsed = urlparse(database_url)

    if parsed.scheme not in ("mysql", "mysql+pymysql"):
        raise RuntimeError(
            "DATABASE_URL must use mysql:// or mysql+pymysql://."
        )

    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise RuntimeError("DATABASE_URL does not specify a database name.")

    return pymysql.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 3306,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=60,
        write_timeout=10,
        autocommit=True,
    )


def build_filters(args, alias=""):
    """Return safe parameterized SQL filters."""
    prefix = f"{alias}." if alias else ""
    clauses = []
    values = []

    for column, value in (
        ("instance_id", args.instance_id),
        ("region", args.region),
        ("metric_name", args.metric),
        ("namespace", args.namespace),
    ):
        if value:
            clauses.append(f"{prefix}{column} = %s")
            values.append(value)

    sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return sql, values


def fetch_daily_counts(connection, table, args):
    """
    Retrieve one row per metric identity per calendar day.
    SQL aggregation avoids loading every individual datapoint.
    """
    where_sql, params = build_filters(args)

    sql = f"""
        SELECT
            instance_id,
            region,
            namespace,
            metric_name,
            DATE(timestamp) AS metric_date,
            COUNT(*) AS datapoints,
            MIN(timestamp) AS first_timestamp,
            MAX(timestamp) AS last_timestamp
        FROM `{table}`
        {where_sql}
        GROUP BY
            instance_id,
            region,
            namespace,
            metric_name,
            DATE(timestamp)
        ORDER BY
            instance_id,
            region,
            namespace,
            metric_name,
            metric_date
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def fetch_observation_summary(connection, table, args):
    """Read previously recorded analysis-window information."""
    where_sql, params = build_filters(args)

    sql = f"""
        SELECT
            instance_id,
            region,
            namespace,
            metric_name,
            COUNT(*) AS observation_count,
            MIN(first_datapoint) AS earliest_recorded_datapoint,
            MAX(last_datapoint) AS latest_recorded_datapoint,
            MIN(analysis_start) AS earliest_analysis_start,
            MAX(analysis_end) AS latest_analysis_end,
            SUM(datapoint_count) AS sum_recorded_datapoints
        FROM `{table}`
        {where_sql}
        GROUP BY instance_id, region, namespace, metric_name
        ORDER BY instance_id, region, namespace, metric_name
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def metric_key(row):
    return (
        row["instance_id"],
        row["region"],
        row["namespace"],
        row["metric_name"],
    )


def format_datetime(value):
    if value is None:
        return "N/A"
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def print_report(daily_rows, observations, args):
    grouped = defaultdict(list)

    for row in daily_rows:
        grouped[metric_key(row)].append(row)

    observation_map = {
        metric_key(row): row for row in observations
    }

    print("\n" + "=" * 88)
    print("             CLOUDWATCH METRIC DATA AVAILABILITY REPORT")
    print("=" * 88)

    if args.instance_id:
        print(f"Instance filter : {args.instance_id}")
    if args.region:
        print(f"Region filter   : {args.region}")
    if args.namespace:
        print(f"Namespace filter: {args.namespace}")
    if args.metric:
        print(f"Metric filter   : {args.metric}")

    print(f"Metric groups found: {len(grouped)}")

    if not grouped:
        print("\nNo metric datapoints matched your filters.")
        print("=" * 88)
        return

    overall_datapoints = 0
    overall_days_with_data = 0
    overall_calendar_days = 0

    for key, rows in grouped.items():
        instance_id, region, namespace, metric_name = key

        first_timestamp = rows[0]["first_timestamp"]
        last_timestamp = rows[-1]["last_timestamp"]

        first_day = first_timestamp.date()
        last_day = last_timestamp.date()

        calendar_days = (last_day - first_day).days + 1
        days_with_data = len(rows)
        total_datapoints = sum(row["datapoints"] for row in rows)
        missing_days_count = calendar_days - days_with_data

        overall_datapoints += total_datapoints
        overall_days_with_data += days_with_data
        overall_calendar_days += calendar_days

        observation = observation_map.get(key)

        if not args.summary_only:
            print("\n" + "-" * 88)
            print(f"Instance ID       : {instance_id}")
            print(f"Region            : {region}")
            print(f"Namespace         : {namespace}")
            print(f"Metric            : {metric_name}")
            print("-" * 88)
            print(f"First datapoint   : {format_datetime(first_timestamp)}")
            print(f"Latest datapoint  : {format_datetime(last_timestamp)}")
            print(f"Calendar days     : {calendar_days}")
            print(f"Days with data    : {days_with_data}")
            print(f"Days without data : {missing_days_count}")
            print(f"Total datapoints  : {total_datapoints}")

            coverage_pct = (
                days_with_data / calendar_days * 100
                if calendar_days
                else 0
            )
            print(f"Daily coverage    : {coverage_pct:.2f}%")

            if observation:
                print("\nRecorded analysis observations:")
                print(
                    "  Observation count       : "
                    f"{observation['observation_count']}"
                )
                print(
                    "  Earliest analysis start : "
                    f"{format_datetime(observation['earliest_analysis_start'])}"
                )
                print(
                    "  Latest analysis end     : "
                    f"{format_datetime(observation['latest_analysis_end'])}"
                )
                print(
                    "  Recorded first datapoint: "
                    f"{format_datetime(observation['earliest_recorded_datapoint'])}"
                )
                print(
                    "  Recorded last datapoint : "
                    f"{format_datetime(observation['latest_recorded_datapoint'])}"
                )
                print(
                    "  Sum of observation counts: "
                    f"{observation['sum_recorded_datapoints']}"
                )
                print(
                    "  Note: observation counts may overlap; "
                    "they are not necessarily unique datapoints."
                )
            else:
                print("\nNo matching metric_observations records found.")

            if args.show_missing_days:
                present_dates = {row["metric_date"] for row in rows}
                missing_dates = []
                current_day = first_day

                while current_day <= last_day:
                    if current_day not in present_dates:
                        missing_dates.append(current_day)
                    current_day += timedelta(days=1)

                print("\nMissing calendar dates:")
                if missing_dates:
                    for missing_date in missing_dates:
                        print(f"  - {missing_date.isoformat()}")
                else:
                    print("  None")

    print("\n" + "=" * 88)
    print("SUMMARY")
    print("=" * 88)
    print(f"Metric groups                  : {len(grouped)}")
    print(f"Total datapoint records        : {overall_datapoints}")
    print(f"Sum of days with data*         : {overall_days_with_data}")
    print(f"Sum of calendar days per metric*: {overall_calendar_days}")
    print("*Day totals are per metric group; the same date can count multiple times.")
    print("=" * 88)


def main():
    args = parse_args()

    try:
        datapoint_table = validate_table_name(args.table)
        observation_table = validate_table_name(args.observation_table)

        connection = get_connection()
        try:
            daily_rows = fetch_daily_counts(
                connection, datapoint_table, args
            )

            # The observation table is supplementary. If it is unavailable
            # or has a different schema, datapoint reporting still works.
            try:
                observations = fetch_observation_summary(
                    connection, observation_table, args
                )
            except Exception as exc:
                print(
                    f"\nWarning: Could not read observation table "
                    f"'{observation_table}': {exc}",
                    file=sys.stderr,
                )
                observations = []

            print_report(daily_rows, observations, args)
        finally:
            connection.close()

    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
