from __future__ import annotations

import json
import sys
import traceback
from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from app.analysis.ai_reasoning import AiReasoning
from app.analysis.candidate_validation import validate_candidate
from app.analysis.ec2_optimizer import analyze_ec2
from app.analysis.schema_validator import (
    validate_ec2_analysis_input,
    validate_ec2_optimization_result,
)
from app.analysis.evidence import evaluate_evidence
from app.analysis.optimization_impact import build_optimization_impact
from app.analysis.persistence import AnalysisPersistenceService
from app.analysis.recommendation_policy import (
    should_create_recommendation,
    validate_recommendation_instance,
)
from app.analysis.readiness_report import write_readiness_report
from app.aws.client import get_aws_client
from app.aws.regions import discover_regions
from app.config import load_config
from app.database.connection import create_connection_factory
from app.database.init import initialize_database
from app.ec2.discovery import discover_instances
from app.ec2.specs import get_instance_specs
from app.pricing.ec2_pricing import (
    discover_compatible_candidates,
    get_ec2_on_demand_price,
)
from app.reporting.json_report import write_report

# Updated import: use the unified ingestion/OpenSearch runner.
from app.server.fetch_ingestion_opensearch import (
    main as run_ingestion_opensearch,
)

from app.tracking.execution_context import (
    create_cli_execution_context,
)
from app.tracking.execution_repository import ExecutionRepository
from app.tracking.metric_tracker import track_metrics
from app.tracking.tracker import track_instance


console = Console()


# =============================================================
# CLI HELPERS
# =============================================================


def _ok(message: str) -> None:
    console.print(f"  [green]✓[/green] {message}")


def _info(message: str) -> None:
    console.print(f"  [cyan]→[/cyan] {message}")


def _warn(message: str) -> None:
    console.print(f"  [yellow]![/yellow] {message}")


def _error(message: str) -> None:
    console.print(f"  [red]✗[/red] {message}")


def _instance_name(instance: Any) -> str:
    return (
        instance.name.strip()
        if instance.name
        and isinstance(instance.name, str)
        and instance.name.strip()
        else instance.instance_id
    )


def _format_bool(value: bool | None) -> str:
    if value is True:
        return "[green]yes[/green]"

    if value is False:
        return "[red]no[/red]"

    return "[yellow]unknown[/yellow]"


# =============================================================
# SERIALIZATION HELPERS
# =============================================================


def _to_json_safe(value: Any) -> Any:
    """
    Convert application objects into JSON-safe Python values.

    This is used only for reports and AI input.
    It does not change the authoritative deterministic objects.
    """

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value):
        return _to_json_safe(asdict(value))

    if isinstance(value, dict):
        return {
            str(key): _to_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_json_safe(item) for item in value]

    return str(value)


def _safe_metric_summary(
    metric: Any,
) -> dict[str, Any] | None:
    """Convert an optional metric summary into JSON-safe data."""

    if metric is None:
        return None

    return _to_json_safe(
        {
            "namespace": metric.namespace,
            "metric_name": metric.metric_name,
            "average": metric.average,
            "minimum": metric.minimum,
            "maximum": metric.maximum,
            "datapoint_count": metric.datapoint_count,
            "first_datapoint": metric.first_datapoint,
            "last_datapoint": metric.last_datapoint,
            "coverage_hours": metric.coverage_hours,
        }
    )


# =============================================================
# INGESTION / OPENSEARCH INTEGRATION
# =============================================================



def _integrate_ingestion_report(
    report_path: str | Path | None = None,
) -> bool:
    """Run the ingestion, audit, and OpenSearch workflow."""

    console.print()
    console.print("  [cyan]→[/cyan] Running ingestion and audit workflow...")

    try:
        exit_code = run_ingestion_opensearch()

        if exit_code != 0:
            console.print(
                f"  [red]✗[/red] Ingestion workflow failed "
                f"(exit code: {exit_code})"
            )
            if report_path is not None:
                console.print(f"  EC2 report: {report_path}")
            return False

        console.print(
            "  [green]✓[/green] Ingestion and audit workflow completed"
        )
        console.print(
            "  [green]✓[/green] OpenSearch workflow completed"
        )

        if report_path is not None:
            console.print(f"  EC2 report: {report_path}")

        return True

    except Exception as exc:
        console.print(
            f"  [red]✗[/red] Ingestion workflow failed: "
            f"{type(exc).__name__}: {exc}"
        )
        if report_path is not None:
            console.print(f"  EC2 report: {report_path}")
        return False



# =============================================================
# PRICING / CANDIDATE ANALYSIS
# =============================================================


def _pricing_analysis(
    *,
    aws: Any,
    instance: Any,
    deterministic: Any,
    current_vcpu: int,
    current_memory_mib: int,
) -> dict[str, Any]:
    """
    Perform real AWS candidate discovery, deterministic validation,
    and real AWS pricing.

    This function is an orchestration layer only.

    It does not:
    - modify AWS resources
    - invent candidate specifications
    - override deterministic analysis
    - make decisions without sufficient deterministic evidence
    """

    recommendation = deterministic.recommendation

    empty_result: dict[str, Any] = {
        "current": None,
        "candidates": [],
        "validated_candidates": [],
        "recommended_candidate": None,
        "missing_evidence": [],
    }

    if recommendation not in {
        "DOWNSIZE_CANDIDATE",
        "UPSCALE_CANDIDATE",
    }:
        return empty_result

    if deterministic.capacity is None:
        return {
            **empty_result,
            "missing_evidence": [
                "Deterministic capacity analysis is unavailable."
            ],
        }

    architecture = (
        instance.architecture
        if instance.architecture
        else ""
    ).strip()

    if not architecture:
        return {
            **empty_result,
            "missing_evidence": [
                "Instance architecture is unavailable."
            ],
        }

    current_price = get_ec2_on_demand_price(
        region=instance.region,
        instance_type=instance.instance_type,
        architecture=architecture,
    )

    if current_price is None:
        return {
            **empty_result,
            "missing_evidence": [
                "Current EC2 On-Demand price could not be retrieved."
            ],
        }

    current = {
        "instance_type": current_price.instance_type,
        "vcpus": current_vcpu,
        "memory_mib": current_memory_mib,
        "architecture": architecture,
        "hourly_usd": current_price.hourly_usd,
        "monthly_usd": current_price.monthly_usd,
    }

    candidates = list(
        discover_compatible_candidates(
            aws=aws,
            instance_type=instance.instance_type,
            architecture=architecture,
        )
    )

    candidate_results: list[dict[str, Any]] = []
    pricing_missing: list[str] = []

    for candidate in candidates:
        if candidate.instance_type == instance.instance_type:
            continue

        if recommendation == "DOWNSIZE_CANDIDATE":
            direction_valid = (
                candidate.vcpus <= current_vcpu
                and candidate.memory_mib <= current_memory_mib
                and (
                    candidate.vcpus < current_vcpu
                    or candidate.memory_mib < current_memory_mib
                )
            )

            direction = "DOWNSIZE"

        else:
            direction_valid = (
                candidate.vcpus >= current_vcpu
                and candidate.memory_mib >= current_memory_mib
                and (
                    candidate.vcpus > current_vcpu
                    or candidate.memory_mib > current_memory_mib
                )
            )

            direction = "UPSCALE"

        if not direction_valid:
            continue

        validation = validate_candidate(
            candidate=candidate,
            capacity=deterministic.capacity,
        )

        price = get_ec2_on_demand_price(
            region=instance.region,
            instance_type=candidate.instance_type,
            architecture=architecture,
        )

        if price is None:
            pricing_missing.append(
                f"Pricing unavailable for candidate "
                f"{candidate.instance_type}."
            )
            continue

        monthly_cost_change = (
            price.monthly_usd - current_price.monthly_usd
        )

        annual_cost_change = monthly_cost_change * 12

        if current_price.monthly_usd:
            savings_percent = (
                (
                    current_price.monthly_usd
                    - price.monthly_usd
                )
                / current_price.monthly_usd
                * 100
            )
        else:
            savings_percent = 0

        candidate_results.append(
            {
                "instance_type": candidate.instance_type,
                "vcpus": candidate.vcpus,
                "memory_mib": candidate.memory_mib,
                "architecture": candidate.architecture,
                "direction": direction,
                "hourly_usd": price.hourly_usd,
                "monthly_usd": price.monthly_usd,
                "monthly_cost_change_usd": monthly_cost_change,
                "annual_cost_change_usd": annual_cost_change,
                "savings_percent": savings_percent,
                "safe": validation.safe,
                "cpu_sufficient": validation.cpu_sufficient,
                "memory_sufficient": validation.memory_sufficient,
                "validation_reasons": list(validation.reasons),
            }
        )

    safe_candidates = [
        candidate
        for candidate in candidate_results
        if candidate["safe"]
    ]

    if recommendation == "DOWNSIZE_CANDIDATE":
        safe_candidates.sort(
            key=lambda candidate: (
                candidate["monthly_usd"],
                candidate["memory_mib"],
                candidate["vcpus"],
                candidate["instance_type"],
            )
        )
    else:
        safe_candidates.sort(
            key=lambda candidate: (
                candidate["monthly_usd"],
                candidate["vcpus"],
                candidate["memory_mib"],
                candidate["instance_type"],
            )
        )

    recommended_candidate = (
        safe_candidates[0]
        if safe_candidates
        else None
    )

    missing_evidence: list[str] = []

    if not candidates:
        missing_evidence.append(
            "No compatible real AWS instance types were discovered."
        )
    elif not candidate_results:
        missing_evidence.append(
            "Compatible real AWS candidates were discovered, "
            "but no candidate had retrievable pricing."
        )
    elif not safe_candidates:
        missing_evidence.append(
            "Real AWS candidates were discovered, but none passed "
            "deterministic capacity validation."
        )

    if pricing_missing:
        missing_evidence.extend(pricing_missing)

    return {
        "current": current,
        "candidates": candidate_results,
        "validated_candidates": safe_candidates,
        "recommended_candidate": recommended_candidate,
        "missing_evidence": missing_evidence,
    }


# =============================================================
# FINAL RECOMMENDATION RECONCILIATION
# =============================================================


def _reconcile_final_recommendation(
    *,
    deterministic: Any,
    pricing: dict[str, Any],
) -> Any:
    """Reconcile the workload-level recommendation with real AWS
    candidate validation.
    """

    recommendation = deterministic.recommendation

    if recommendation not in {
        "DOWNSIZE_CANDIDATE",
        "UPSCALE_CANDIDATE",
    }:
        return deterministic

    recommended_candidate = pricing.get("recommended_candidate")

    if recommended_candidate is not None:
        return deterministic

    if recommendation == "DOWNSIZE_CANDIDATE":
        reason = (
            "Observed CPU and memory utilization suggest that "
            "the current instance may have excess capacity, but "
            "no smaller compatible real AWS instance passed "
            "deterministic capacity validation. The current "
            "instance is therefore retained."
        )

        concern = (
            "No smaller compatible AWS instance was validated "
            "as sufficient for the observed workload."
        )
    else:
        reason = (
            "Observed CPU or memory utilization suggests that "
            "additional capacity may be required, but no larger "
            "compatible real AWS instance passed deterministic "
            "capacity validation. The current instance is "
            "therefore retained."
        )

        concern = (
            "No larger compatible AWS instance was validated "
            "as sufficient for the observed workload."
        )

    return replace(
        deterministic,
        recommendation="KEEP_CURRENT",
        reason=reason,
        concerns=(
            *deterministic.concerns,
            concern,
        ),
    )


# =============================================================
# CLI DISPLAY
# =============================================================


def _display_stopped_instance(
    *,
    instance: Any,
) -> None:
    """Display explanation for a stopped instance."""

    _warn(
        "Instance is stopped. Active CPU and memory workload "
        "evidence is unavailable."
    )

    _warn(
        "The optimizer will not guess whether this instance "
        "should be downsized or upsized."
    )


def _display_metrics(
    *,
    deterministic: Any,
) -> None:
    """Display CPU and memory evidence without tables."""

    if (
        deterministic.cpu_statistics is None
        or deterministic.memory_statistics is None
    ):
        _warn("CPU or memory statistics are unavailable.")
        return

    if (
        deterministic.cpu_workload is None
        or deterministic.memory_workload is None
    ):
        _warn("CPU or memory workload analysis is unavailable.")
        return

    console.print("  [bold]Observed workload[/bold]")

    console.print(
        "    "
        f"CPU     "
        f"avg {deterministic.cpu_statistics.average:.2f}% | "
        f"p95 {deterministic.cpu_statistics.p95:.2f}% | "
        f"max {deterministic.cpu_statistics.maximum:.2f}% | "
        f"trend {deterministic.cpu_workload.trend} | "
        f"spike risk {deterministic.cpu_workload.spike_risk}"
    )

    console.print(
        "    "
        f"Memory  "
        f"avg {deterministic.memory_statistics.average:.2f}% | "
        f"p95 {deterministic.memory_statistics.p95:.2f}% | "
        f"max {deterministic.memory_statistics.maximum:.2f}% | "
        f"trend {deterministic.memory_workload.trend} | "
        f"spike risk {deterministic.memory_workload.spike_risk}"
    )


def _display_candidate_comparison(
    *,
    pricing: dict[str, Any],
    deterministic: Any,
) -> None:
    """Display real AWS candidate details without tables."""

    candidates = pricing.get("candidates", [])

    if not candidates:
        missing = pricing.get("missing_evidence", [])

        if missing:
            console.print("  [bold]Candidate validation[/bold]")

            for reason in missing:
                _warn(reason)

        return

    console.print(
        "  [bold]Real AWS candidate validation[/bold]"
    )

    for candidate in candidates:
        status = (
            "[green]VALID[/green]"
            if candidate["safe"]
            else "[red]REJECTED[/red]"
        )

        console.print(
            "    "
            f"{candidate['instance_type']} | "
            f"{candidate['vcpus']} vCPU | "
            f"{candidate['memory_mib']} MiB | "
            f"${candidate['monthly_usd']:.2f}/month | "
            f"{status}"
        )

        console.print(
            "      "
            f"CPU sufficient: "
            f"{_format_bool(candidate['cpu_sufficient'])} | "
            f"Memory sufficient: "
            f"{_format_bool(candidate['memory_sufficient'])}"
        )

        if candidate["validation_reasons"]:
            for reason in candidate["validation_reasons"]:
                console.print(
                    f"      [dim]reason:[/dim] {reason}"
                )

    recommended = pricing.get("recommended_candidate")
    current = pricing.get("current")

    if recommended is None or current is None:
        return

    console.print(
        "  [bold green]Validated candidate[/bold green]"
    )

    console.print(
        f"    Instance: {recommended['instance_type']}"
    )

    console.print(
        f"    Capacity: {recommended['vcpus']} vCPU | "
        f"{recommended['memory_mib']} MiB"
    )

    console.print(
        f"    Current cost: ${current['monthly_usd']:.2f}/month"
    )

    console.print(
        f"    Candidate cost: "
        f"${recommended['monthly_usd']:.2f}/month"
    )

    console.print(
        f"    Monthly difference: "
        f"${recommended['monthly_cost_change_usd']:.2f}"
    )

    console.print(
        f"    Annual difference: "
        f"${recommended['annual_cost_change_usd']:.2f}"
    )

    console.print(
        f"    Savings: {recommended['savings_percent']:.2f}%"
    )

    console.print(
        f"    CPU sufficient: "
        f"{_format_bool(recommended['cpu_sufficient'])}"
    )

    console.print(
        f"    Memory sufficient: "
        f"{_format_bool(recommended['memory_sufficient'])}"
    )


def _display_pros_cons(
    *,
    impact: Any,
) -> None:
    """Display benefits and risks."""

    if impact.benefits:
        console.print("  [bold green]Benefits[/bold green]")

        for benefit in impact.benefits:
            console.print(f"    [green]✓[/green] {benefit}")

    if impact.risks:
        console.print("  [bold yellow]Risks / trade-offs[/bold yellow]")

        for risk in impact.risks:
            console.print(f"    [yellow]![/yellow] {risk}")


def _display_optimization(
    *,
    impact: Any,
    pricing: dict[str, Any],
    deterministic: Any,
) -> None:
    """Display the complete deterministic optimization decision."""

    decision = deterministic.recommendation

    console.print(f"  [bold]Decision:[/bold] {decision}")
    console.print(f"  [bold]Current:[/bold] {impact.current_instance}")

    if impact.recommended_instance:
        console.print(
            f"  [bold]Recommended:[/bold] {impact.recommended_instance}"
        )
    else:
        console.print(
            "  [bold]Recommended:[/bold] [dim]none[/dim]"
        )

    console.print(f"  [bold]Why:[/bold] {impact.summary}")

    console.print(
        f"  [bold]Why this matters:[/bold] {impact.why_effective}"
    )

    if (
        impact.current_monthly_cost is not None
        and impact.recommended_monthly_cost is not None
    ):
        console.print("  [bold]Cost impact[/bold]")

        console.print(
            f"    Current: ${impact.current_monthly_cost:.2f}/month"
        )

        console.print(
            f"    Recommended: "
            f"${impact.recommended_monthly_cost:.2f}/month"
        )

        if impact.monthly_cost_change_usd is not None:
            console.print(
                f"    Monthly difference: "
                f"${impact.monthly_cost_change_usd:.2f}"
            )

        if impact.annual_cost_change_usd is not None:
            console.print(
                f"    Annual difference: "
                f"${impact.annual_cost_change_usd:.2f}"
            )

        if impact.savings_percent is not None:
            console.print(
                f"    Savings: {impact.savings_percent:.2f}%"
            )

    _display_candidate_comparison(
        pricing=pricing,
        deterministic=deterministic,
    )

    _display_pros_cons(impact=impact)


# =============================================================
# MAIN APPLICATION
# =============================================================


def main(
    resource_id: str | None = None,
    analysis_hours: float | None = None,
    report_path: str = "output/analysis-result.json",
    region: str | None = None,
    run_ingestion: bool = True,
) -> int:
    config = load_config()

    # CLI callers may override the analysis window without changing .env.
    if analysis_hours is not None:
        config = replace(
            config,
            analysis=replace(
                config.analysis,
                analysis_hours=analysis_hours,
            ),
        )

    console.print(
        "[bold cyan]AWS Cost & Infrastructure Optimizer[/bold cyan]"
    )

    console.print(
        "[dim]Read-only • Real AWS data • "
        "Deterministic safety validation[/dim]"
    )

    console.print(
        f"[dim]Analysis window: "
        f"{config.analysis.analysis_hours:g} hour(s)[/dim]"
    )

    console.print()

    # =========================================================
    # DATABASE
    # =========================================================

    _info("Initializing database...")

    try:
        initialize_database()
        connection_factory = create_connection_factory()

    except Exception as exc:
        _error(f"Database initialization failed: {exc}")
        return 1

    try:
        # =====================================================
        # AWS IDENTITY
        # =====================================================

        _info("Connecting to AWS...")

        default_aws = get_aws_client(config.aws.default_region)
        identity = default_aws.identity()

        _ok(f"AWS account: {identity.account_id}")
        _ok(f"Identity: {identity.arn}")

        # =====================================================
        # EXECUTION AUDIT
        # =====================================================

        execution_context = create_cli_execution_context(
            command=" ".join(sys.argv)
        )

        execution_session = connection_factory()

        try:
            execution_repository = ExecutionRepository(
                execution_session
            )

            execution_record = execution_repository.create(
                context=execution_context
            )

            execution_repository.update_aws_identity(
                execution_id=execution_context.execution_id,
                account_id=identity.account_id,
                identity=identity.arn,
                region=config.aws.default_region,
            )

            execution_session.commit()

        except Exception:
            execution_session.rollback()
            execution_session.close()
            raise

        execution_session.close()

        _ok(f"Execution ID: {execution_context.execution_id}")

        # =====================================================
        # REGIONS
        # =====================================================

        _info("Discovering AWS regions...")

        if region:
            from app.aws.regions import AwsRegion

            enabled_regions = (
                AwsRegion(
                    name=region,
                    endpoint=f"ec2.{region}.amazonaws.com",
                    opt_in_status="opted-in",
                ),
            )
        else:
            regions = discover_regions(default_aws)

            enabled_regions = tuple(
                available_region
                for available_region in regions
                if available_region.opt_in_status
                in {
                    "opt-in-not-required",
                    "opted-in",
                }
            )

        _ok(f"Regions available: {len(enabled_regions)}")

        # =====================================================
        # EC2 DISCOVERY
        # =====================================================

        _info("Discovering EC2 instances...")

        try:
            all_instances = list(
                discover_instances(
                    aws=default_aws,
                    regions=enabled_regions,
                )
            )

        except Exception as exc:
            _error(f"EC2 discovery failed: {exc}")
            return 1

        if resource_id:
            all_instances = [
                instance
                for instance in all_instances
                if instance.instance_id == resource_id
            ]

            if not all_instances:
                _error(
                    f"EC2 instance {resource_id} was not found"
                    + (
                        f" in region {region}."
                        if region
                        else " in the enabled regions."
                    )
                )
                return 2

        _ok(f"EC2 instances selected: {len(all_instances)}")

        # =====================================================
        # METRIC READINESS REPORT
        # =====================================================

        _info(
            "Checking cached metric coverage and readiness..."
        )

        write_readiness_report(
            analysis_hours=config.analysis.analysis_hours,
            required_evidence_hours=(
                config.analysis.required_evidence_hours
            ),
            output_path="output/analysis-readiness.json",
            console=console,
        )

        if not all_instances:
            _warn("No EC2 instances were discovered.")

        results: list[dict[str, Any]] = []

        # =====================================================
        # INSTANCE ANALYSIS
        # =====================================================

        total_instances = len(all_instances)

        for index, instance in enumerate(all_instances, start=1):
            console.print()

            console.print(
                f"[bold cyan]"
                f"[{index}/{total_instances}] "
                f"{_instance_name(instance)}"
                f"[/bold cyan]"
            )

            console.print(
                f"  [dim]"
                f"{instance.instance_id} | "
                f"{instance.instance_type} | "
                f"{instance.region} | "
                f"{instance.state.upper()}"
                f"[/dim]"
            )

            region_aws = get_aws_client(instance.region)

            session = connection_factory()
            persistence = AnalysisPersistenceService(session)

            try:
                # -------------------------------------------------
                # STOPPED INSTANCE
                # -------------------------------------------------

                if instance.state.lower() != "running":
                    _display_stopped_instance(instance=instance)

                # -------------------------------------------------
                # TRACKING
                # -------------------------------------------------

                _info("Tracking instance configuration...")

                tracking = track_instance(
                    aws=region_aws,
                    instance_id=instance.instance_id,
                    session=session,
                )

                current_configuration_version = (
                    tracking.tracking.snapshot.configuration_version
                )

                _ok("Configuration tracking complete.")

                # -------------------------------------------------
                # METRICS
                # -------------------------------------------------

                _info(
                    "Collecting CloudWatch CPU and memory "
                    f"metrics for the last "
                    f"{config.analysis.analysis_hours:g} hour(s)..."
                )

                metrics = track_metrics(
                    aws=region_aws,
                    instance_id=instance.instance_id,
                    analysis_hours=config.analysis.analysis_hours,
                    session=session,
                    configuration_version=(
                        current_configuration_version
                    ),
                )

                _ok("CloudWatch metrics collected.")

                # -------------------------------------------------
                # EVIDENCE
                # -------------------------------------------------

                _info("Evaluating workload evidence...")

                evidence = evaluate_evidence(
                    session=session,
                    instance_id=instance.instance_id,
                    region=instance.region,
                    current_instance_type=instance.instance_type,
                    instance_state=instance.state,
                    required_evidence_hours=(
                        config.analysis.required_evidence_hours
                    ),
                    configuration_version=(
                        current_configuration_version
                    ),
                )

                if evidence.sufficient:
                    _ok("Evidence is sufficient for analysis.")
                else:
                    _warn(
                        "Evidence is insufficient for a safe "
                        "optimization recommendation."
                    )

                    for reason in evidence.missing_evidence or ():
                        _warn(reason)

                # -------------------------------------------------
                # CURRENT SPEC
                # -------------------------------------------------

                _info(
                    "Reading current EC2 instance specification..."
                )

                current_spec = get_instance_specs(
                    aws=region_aws,
                    instance_type=instance.instance_type,
                )

                _ok(
                    f"Current capacity: "
                    f"{current_spec.vcpu_count} vCPU | "
                    f"{current_spec.memory_mib} MiB"
                )

                # -------------------------------------------------
                # ANALYSIS RUN
                # -------------------------------------------------

                analysis_started_at = datetime.now(timezone.utc)

                analysis_record = persistence.create_analysis(
                    instance_id=instance.instance_id,
                    region=instance.region,
                    execution_run_id=execution_record.id,
                    started_at=analysis_started_at,
                    analysis_version=config.analysis.analysis_version,
                )

                analysis_id = analysis_record.id

                # -------------------------------------------------
                # DETERMINISTIC ANALYSIS
                # -------------------------------------------------

                _info("Running deterministic workload analysis...")

                validate_ec2_analysis_input(
                    evidence_status=evidence,
                    cpu=metrics.cpu,
                    memory=metrics.memory,
                    instance_state=instance.state,
                    current_vcpu=current_spec.vcpu_count,
                    current_memory_mib=current_spec.memory_mib,
                )

                deterministic = analyze_ec2(
                    evidence_status=evidence,
                    cpu=metrics.cpu,
                    memory=metrics.memory,
                    instance_state=instance.state,
                    current_vcpu=current_spec.vcpu_count,
                    current_memory_mib=current_spec.memory_mib,
                )

                validate_ec2_optimization_result(deterministic)

                _ok(
                    f"Initial decision: "
                    f"{deterministic.recommendation}"
                )

                # -------------------------------------------------
                # METRIC DISPLAY
                # -------------------------------------------------

                if instance.state.lower() == "running":
                    _display_metrics(deterministic=deterministic)

                # -------------------------------------------------
                # REAL AWS PRICING + CANDIDATE VALIDATION
                # -------------------------------------------------

                pricing = _pricing_analysis(
                    aws=region_aws,
                    instance=instance,
                    deterministic=deterministic,
                    current_vcpu=current_spec.vcpu_count,
                    current_memory_mib=current_spec.memory_mib,
                )

                # -------------------------------------------------
                # FINAL RECOMMENDATION
                # -------------------------------------------------

                deterministic = _reconcile_final_recommendation(
                    deterministic=deterministic,
                    pricing=pricing,
                )

                _ok(
                    f"Final deterministic decision: "
                    f"{deterministic.recommendation}"
                )

                # -------------------------------------------------
                # OPTIMIZATION IMPACT
                # -------------------------------------------------

                impact = build_optimization_impact(
                    deterministic=deterministic,
                    pricing=pricing,
                    current_vcpu=current_spec.vcpu_count,
                    current_memory_mib=current_spec.memory_mib,
                )

                # -------------------------------------------------
                # PERSIST FINAL DETERMINISTIC ANALYSIS
                # -------------------------------------------------

                analysis_completed_at = datetime.now(timezone.utc)

                metric_starts = [
                    metric.first_datapoint
                    for metric in (metrics.cpu, metrics.memory)
                    if metric is not None
                    and metric.first_datapoint is not None
                ]

                metric_ends = [
                    metric.last_datapoint
                    for metric in (metrics.cpu, metrics.memory)
                    if metric is not None
                    and metric.last_datapoint is not None
                ]

                evidence_start = (
                    min(metric_starts)
                    if metric_starts
                    else None
                )

                evidence_end = (
                    max(metric_ends)
                    if metric_ends
                    else None
                )

                next_eligible_analysis_at = (
                    analysis_completed_at
                    + timedelta(
                        days=config.analysis.analysis_cooldown_days
                    )
                )

                persistence.complete_analysis(
                    analysis_id=analysis_id,
                    status="COMPLETED",
                    recommendation=deterministic.recommendation,
                    evidence_start=evidence_start,
                    evidence_end=evidence_end,
                    next_eligible_analysis_at=(
                        next_eligible_analysis_at
                    ),
                )

                # -------------------------------------------------
                # PERSIST ACTIONABLE RECOMMENDATION
                # -------------------------------------------------

                recommendation_record = None

                if should_create_recommendation(
                    deterministic.recommendation
                ):
                    validate_recommendation_instance(
                        recommendation=deterministic.recommendation,
                        recommended_instance=impact.recommended_instance,
                    )

                    recommendation_record = (
                        persistence.create_recommendation(
                            instance_id=instance.instance_id,
                            region=instance.region,
                            analysis_id=analysis_id,
                            recommendation=(
                                deterministic.recommendation
                            ),
                            recommended_instance=(
                                impact.recommended_instance
                            ),
                            created_at=analysis_completed_at,
                            cooldown_days=(
                                config.analysis.recommendation_cooldown_days
                            ),
                        )
                    )

                # -------------------------------------------------
                # PERSIST IMMUTABLE RECOMMENDATION SNAPSHOT
                # -------------------------------------------------

                def _metric_value(
                    metric: Any,
                    attribute: str,
                ) -> float | None:
                    if metric is None:
                        return None

                    value = getattr(metric, attribute, None)

                    if value is None:
                        return None

                    return float(value)

                def _metric_count(metric: Any) -> int:
                    if metric is None:
                        return 0

                    value = getattr(metric, "datapoint_count", 0)

                    return int(value or 0)

                snapshot = persistence.create_snapshot(
                    instance_id=instance.instance_id,
                    region=instance.region,
                    analysis_id=analysis_id,
                    configuration_version=(
                        current_configuration_version
                    ),
                    instance_type=instance.instance_type,
                    instance_state=instance.state,
                    recommendation=deterministic.recommendation,
                    recommended_instance=(
                        impact.recommended_instance
                        if deterministic.recommendation
                        in {
                            "DOWNSIZE_CANDIDATE",
                            "UPSCALE_CANDIDATE",
                        }
                        else None
                    ),
                    cpu_average=_metric_value(metrics.cpu, "average"),
                    cpu_minimum=_metric_value(metrics.cpu, "minimum"),
                    cpu_maximum=_metric_value(metrics.cpu, "maximum"),
                    memory_average=_metric_value(
                        metrics.memory,
                        "average",
                    ),
                    memory_minimum=_metric_value(
                        metrics.memory,
                        "minimum",
                    ),
                    memory_maximum=_metric_value(
                        metrics.memory,
                        "maximum",
                    ),
                    cpu_datapoint_count=_metric_count(metrics.cpu),
                    memory_datapoint_count=_metric_count(
                        metrics.memory
                    ),
                    evidence_start=evidence_start,
                    evidence_end=evidence_end,
                    reason=deterministic.reason,
                    concerns=(
                        "\n".join(deterministic.concerns)
                        if deterministic.concerns
                        else None
                    ),
                    missing_evidence=(
                        "\n".join(deterministic.missing_evidence)
                        if deterministic.missing_evidence
                        else None
                    ),
                    created_at=analysis_completed_at,
                )

                session.commit()

                _ok(f"Analysis persisted: #{analysis_id}")

                if recommendation_record is not None:
                    _ok("Actionable recommendation persisted.")

                _ok(
                    "Recommendation snapshot persisted: "
                    f"#{snapshot.id}"
                )

                # -------------------------------------------------
                # AI REASONING
                # -------------------------------------------------

                ai_result = None

                if evidence.sufficient and config.openai.api_key:
                    _info("Running AI reasoning...")

                    try:
                        ai = AiReasoning.from_config()

                        ai_result = ai.reason(
                            _to_json_safe(
                                {
                                    "analysis_context": {
                                        "ai_must_analyze_this_instance": True,
                                        "python_is_authoritative": True,
                                        "ai_must_not_override_final_recommendation": True,
                                        "analysis_hours": (
                                            config.analysis.analysis_hours
                                        ),
                                        "required_evidence_hours": (
                                            config.analysis.required_evidence_hours
                                        ),
                                        "configuration_version": (
                                            current_configuration_version
                                        ),
                                    },
                                    "instance": {
                                        "instance_id": instance.instance_id,
                                        "region": instance.region,
                                        "name": instance.name,
                                        "instance_type": (
                                            instance.instance_type
                                        ),
                                        "state": instance.state,
                                        "architecture": (
                                            instance.architecture
                                        ),
                                    },
                                    "evidence": {
                                        "sufficient": evidence.sufficient,
                                        "evidence_score": (
                                            evidence.evidence_score
                                        ),
                                        "configuration_age_days": (
                                            evidence.configuration_age_days
                                        ),
                                        "required_days": (
                                            evidence.required_days
                                        ),
                                        "cpu_data_sufficient": (
                                            evidence.cpu_data_sufficient
                                        ),
                                        "memory_data_sufficient": (
                                            evidence.memory_data_sufficient
                                        ),
                                        "missing_evidence": (
                                            evidence.missing_evidence
                                        ),
                                    },
                                    "cpu": _safe_metric_summary(
                                        metrics.cpu
                                    ),
                                    "memory": _safe_metric_summary(
                                        metrics.memory
                                    ),
                                    "deterministic_analysis": {
                                        "recommendation": (
                                            deterministic.recommendation
                                        ),
                                        "evidence_score": (
                                            deterministic.evidence_score
                                        ),
                                        "reason": deterministic.reason,
                                        "concerns": (
                                            deterministic.concerns
                                        ),
                                        "missing_evidence": (
                                            deterministic.missing_evidence
                                        ),
                                        "capacity": (
                                            deterministic.capacity
                                        ),
                                    },
                                    "optimization": {
                                        "decision": (
                                            deterministic.recommendation
                                        ),
                                        "current_instance": (
                                            impact.current_instance
                                        ),
                                        "recommended_instance": (
                                            impact.recommended_instance
                                        ),
                                        "summary": impact.summary,
                                        "why_effective": (
                                            impact.why_effective
                                        ),
                                        "benefits": impact.benefits,
                                        "risks": impact.risks,
                                    },
                                    "pricing": pricing,
                                }
                            )
                        )

                        _ok("AI reasoning completed.")

                    except Exception as exc:
                        _warn(f"AI reasoning failed: {exc}")

                elif not evidence.sufficient:
                    _warn(
                        "AI reasoning skipped: evidence is insufficient."
                    )

                else:
                    _warn(
                        "AI reasoning unavailable: "
                        "OpenAI API key is not configured."
                    )

                # -------------------------------------------------
                # PYTHON IS AUTHORITATIVE
                # -------------------------------------------------

                final_recommendation = deterministic.recommendation

                # -------------------------------------------------
                # COMPLETE CLI OUTPUT
                # -------------------------------------------------

                _display_optimization(
                    impact=impact,
                    pricing=pricing,
                    deterministic=deterministic,
                )

                # -------------------------------------------------
                # REPORT DATA
                # -------------------------------------------------

                result = _to_json_safe(
                    {
                        "analysis": {
                            "analysis_hours": (
                                config.analysis.analysis_hours
                            ),
                            "required_evidence_hours": (
                                config.analysis.required_evidence_hours
                            ),
                        },
                        "instance": {
                            "instance_id": instance.instance_id,
                            "region": instance.region,
                            "availability_zone": (
                                instance.availability_zone
                            ),
                            "name": instance.name,
                            "instance_type": instance.instance_type,
                            "state": instance.state,
                            "architecture": instance.architecture,
                            "platform": instance.platform,
                            "launch_time": instance.launch_time,
                            "private_ip": instance.private_ip,
                            "public_ip": instance.public_ip,
                            "tags": dict(instance.tags),
                        },
                        "tracking": {
                            "previous_snapshot_found": (
                                tracking.previous_snapshot_found
                            ),
                            "configuration_changed": (
                                tracking.tracking.configuration_changed
                            ),
                            "configuration_version": (
                                current_configuration_version
                            ),
                            "configuration_change": (
                                tracking.tracking.configuration_change
                            ),
                        },
                        "evidence": {
                            "sufficient": evidence.sufficient,
                            "evidence_score": evidence.evidence_score,
                            "configuration_age_days": (
                                evidence.configuration_age_days
                            ),
                            "required_days": evidence.required_days,
                            "cpu_data_sufficient": (
                                evidence.cpu_data_sufficient
                            ),
                            "memory_data_sufficient": (
                                evidence.memory_data_sufficient
                            ),
                            "missing_evidence": evidence.missing_evidence,
                        },
                        "metrics": {
                            "cpu": _safe_metric_summary(metrics.cpu),
                            "memory": _safe_metric_summary(metrics.memory),
                        },
                        "deterministic_analysis": {
                            "recommendation": (
                                deterministic.recommendation
                            ),
                            "evidence_score": (
                                deterministic.evidence_score
                            ),
                            "reason": deterministic.reason,
                            "concerns": deterministic.concerns,
                            "missing_evidence": (
                                deterministic.missing_evidence
                            ),
                            "cpu_statistics": (
                                deterministic.cpu_statistics
                            ),
                            "memory_statistics": (
                                deterministic.memory_statistics
                            ),
                            "cpu_workload": (
                                deterministic.cpu_workload
                            ),
                            "memory_workload": (
                                deterministic.memory_workload
                            ),
                            "capacity": deterministic.capacity,
                        },
                        "pricing": pricing,
                        "optimization": {
                            "decision": deterministic.recommendation,
                            "current_instance": impact.current_instance,
                            "recommended_instance": (
                                impact.recommended_instance
                            ),
                            "current_vcpu": impact.current_vcpu,
                            "recommended_vcpu": (
                                impact.recommended_vcpu
                            ),
                            "current_memory_mib": (
                                impact.current_memory_mib
                            ),
                            "recommended_memory_mib": (
                                impact.recommended_memory_mib
                            ),
                            "current_monthly_cost": (
                                impact.current_monthly_cost
                            ),
                            "recommended_monthly_cost": (
                                impact.recommended_monthly_cost
                            ),
                            "monthly_cost_change_usd": (
                                impact.monthly_cost_change_usd
                            ),
                            "annual_cost_change_usd": (
                                impact.annual_cost_change_usd
                            ),
                            "savings_percent": impact.savings_percent,
                            "current_cpu_headroom_percent": (
                                impact.current_cpu_headroom_percent
                            ),
                            "recommended_cpu_headroom_percent": (
                                impact.recommended_cpu_headroom_percent
                            ),
                            "current_memory_headroom_percent": (
                                impact.current_memory_headroom_percent
                            ),
                            "recommended_memory_headroom_percent": (
                                impact.recommended_memory_headroom_percent
                            ),
                            "summary": impact.summary,
                            "why_effective": impact.why_effective,
                            "benefits": impact.benefits,
                            "risks": impact.risks,
                            "evidence": impact.evidence,
                        },
                        "ai_reasoning": ai_result,
                        "final_recommendation": final_recommendation,
                        "recommended_instance": (
                            impact.recommended_instance
                            if final_recommendation
                            in {
                                "DOWNSIZE_CANDIDATE",
                                "UPSCALE_CANDIDATE",
                            }
                            else None
                        ),
                    }
                )

                results.append(result)

                _ok(
                    f"Instance analysis complete: "
                    f"{final_recommendation}"
                )

            except Exception as exc:
                try:
                    session.rollback()
                except Exception:
                    pass

                _error(f"Instance analysis failed: {exc}")
                traceback.print_exc()

                results.append(
                    _to_json_safe(
                        {
                            "instance": {
                                "instance_id": instance.instance_id,
                                "region": instance.region,
                                "name": instance.name,
                            },
                            "final_recommendation": "INVESTIGATE",
                            "error": str(exc),
                        }
                    )
                )

            finally:
                session.close()

        # =====================================================
        # STEP 1: WRITE THE EC2 ANALYSIS REPORT
        # =====================================================

        _info("Writing JSON analysis report...")

        output_path = write_report(
            output_path=report_path,
            account_id=identity.account_id,
            identity_arn=identity.arn,
            analysis_hours=config.analysis.analysis_hours,
            instances=results,
        )

        _ok(f"Report written: {output_path}")

        console.print()
        console.print("[bold green]EC2 analysis complete[/bold green]")
        console.print(f"  Instances analyzed: {len(results)}")
        console.print(
            f"  Analysis window: "
            f"{config.analysis.analysis_hours:g} hour(s)"
        )
        console.print(f"  Report: {output_path}")

        # =====================================================
        # STEP 2: INGESTION / OPENSEARCH — OPTIONAL
        # =====================================================

        if run_ingestion:
            integration_success = _integrate_ingestion_report(
                report_path=output_path,
            )

            if not integration_success:
                _warn(
                    "EC2 analysis and report generation completed, "
                    "but ingestion/OpenSearch processing failed."
                )

                _warn(
                    f"The EC2 analysis report remains available: "
                    f"{output_path}"
                )

                return 1
        else:
            _info(
                "Skipping ingestion, audit, and OpenSearch "
                "because run_ingestion=False."
            )

        # =====================================================
        # STEP 3: FINAL STATUS
        # =====================================================

        console.print()
        console.print(
            "[bold green]Requested workflow completed successfully.[/bold green]"
        )

        console.print(
            f"  EC2 analysis report: {output_path}"
        )

        if run_ingestion:
            console.print(
                "  Ingestion/OpenSearch JSON files: output/tenants/"
            )

        return 0

    
    finally:
        # Database connections are created and closed per operation.
        # There is no SQLAlchemy engine to dispose in the PyMySQL implementation.
        pass


if __name__ == "__main__":
    raise SystemExit(main())