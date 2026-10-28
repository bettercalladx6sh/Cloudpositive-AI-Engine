"""Analyze one EC2 instance and print one JSON result."""

# Example:
# python analyze_instance.py --resource-id i-0022548e58310083f --days 5

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from rich.console import Console

MAX_ANALYSIS_HOURS = 90 * 24


def positive_number(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "value must be a number"
        ) from exc

    if number <= 0:
        raise argparse.ArgumentTypeError(
            "value must be greater than zero"
        )

    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a read-only analysis for one EC2 instance "
            "over a selected number of days or hours. "
            "Prints one JSON object to stdout."
        )
    )

    parser.add_argument(
        "--resource-id",
        required=True,
        help="EC2 instance ID, e.g. i-0123456789abcdef0",
    )

    period = parser.add_mutually_exclusive_group(required=True)

    period.add_argument(
        "--days",
        type=positive_number,
        help="Analysis window in days, e.g. --days 1 or --days 5",
    )

    period.add_argument(
        "--hours",
        type=positive_number,
        help="Analysis window in hours, e.g. --hours 1 or --hours 24",
    )

    parser.add_argument(
        "--region",
        default=None,
        help="Optional AWS region, e.g. us-east-1",
    )

    return parser


def _print_json(payload: dict) -> None:
    print(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not re.fullmatch(
        r"i-[0-9a-fA-F]{8}(?:[0-9a-fA-F]{9})?",
        args.resource_id,
    ):
        _print_json({
            "status": "ERROR",
            "resource_id": args.resource_id,
            "message": "Invalid EC2 instance ID format.",
        })
        return 2

    analysis_hours = (
        args.days * 24
        if args.days is not None
        else args.hours
    )

    if analysis_hours < 1 or analysis_hours > MAX_ANALYSIS_HOURS:
        parser.error(
            "analysis window must be between 1 hour and 90 days"
        )

    # Keep application progress on stderr so stdout contains JSON only.
    import app.main as optimizer_main

    optimizer_main.console = Console(stderr=True)

    with tempfile.TemporaryDirectory(
        prefix="ec2-analysis-"
    ) as temp_dir:
        report_path = Path(temp_dir) / "analysis-result.json"

        # Run EC2 analysis and report generation only.
        # Explicitly disable ingestion, audits, and OpenSearch.
        exit_code = optimizer_main.main(
            resource_id=args.resource_id,
            analysis_hours=analysis_hours,
            report_path=str(report_path),
            region=args.region,
            run_ingestion=False,
        )

        if exit_code != 0:
            _print_json({
                "status": "ERROR",
                "resource_id": args.resource_id,
                "analysis_hours": analysis_hours,
                "message": (
                    "EC2 analysis did not complete. "
                    "See stderr for details."
                ),
            })
            return exit_code

        try:
            report = json.loads(
                report_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            _print_json({
                "status": "ERROR",
                "resource_id": args.resource_id,
                "analysis_hours": analysis_hours,
                "message": (
                    "Could not read the generated analysis report: "
                    f"{exc}"
                ),
            })
            return 1

        instances = report.get("instances", [])

        matching = next(
            (
                item
                for item in instances
                if item.get("instance", {}).get("instance_id")
                == args.resource_id
            ),
            None,
        )

        if matching is None:
            _print_json({
                "status": "ERROR",
                "resource_id": args.resource_id,
                "analysis_hours": analysis_hours,
                "message": (
                    "No analysis result was produced for this instance."
                ),
            })
            return 1

        result = {
            "status": "OK",
            "generated_at": report.get("generated_at"),
            "account_id": report.get("account_id"),
            "resource_id": args.resource_id,
            "analysis_period": {
                "days": args.days,
                "hours": analysis_hours,
            },
            "instance": matching,
        }

        _print_json(result)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
