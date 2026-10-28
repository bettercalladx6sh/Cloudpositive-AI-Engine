from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


console = Console()


# =============================================================
# COLORS / SYMBOLS
# =============================================================

DECISION_STYLES = {
    "DOWNSIZE_CANDIDATE": "green",
    "UPSCALE_CANDIDATE": "red",
    "KEEP_CURRENT": "cyan",
    "INVESTIGATE": "yellow",
    "INSUFFICIENT_DATA": "yellow",
}


def print_header() -> None:
    console.print(
        "[bold]AWS Cost & Infrastructure Optimizer[/bold]"
    )
    console.print(
        "[dim]Read-only | Real AWS data | Deterministic safety validation[/dim]"
    )
    console.print()


def print_initialization() -> None:
    console.print("[cyan]Initializing database...[/cyan]")


def print_identity(
    *,
    account_id: str,
    arn: str,
) -> None:
    console.print(
        f"[green]✓[/green] Account: [bold]{account_id}[/bold]"
    )
    console.print(
        f"[green]✓[/green] Identity: [bold]{arn}[/bold]"
    )


def print_regions_discovered(
    *,
    count: int,
) -> None:
    console.print(
        f"[green]✓[/green] AWS regions available: [bold]{count}[/bold]"
    )


def print_instances_discovered(
    *,
    count: int,
) -> None:
    console.print(
        f"[green]✓[/green] EC2 instances discovered: [bold]{count}[/bold]"
    )
    console.print()
    console.print("[bold]Analyzing EC2 instances...[/bold]")
    console.print()


def print_discovery_error(
    *,
    message: str,
) -> None:
    console.print(
        f"[red]✗ EC2 discovery failed:[/red] {message}"
    )


def print_instance_start(
    *,
    index: int,
    total: int,
    instance: Any,
) -> None:
    name = instance.name or "unnamed"

    console.print(
        f"[bold cyan]→ [{index}/{total}] {name}[/bold cyan] "
        f"[dim]({instance.instance_id})[/dim]"
    )

    console.print(
        f"  Type: [bold]{instance.instance_type}[/bold]  "
        f"Region: {instance.region}  "
        f"State: {instance.state.upper()}"
    )


def print_stopped_instance() -> None:
    console.print(
        "  [yellow]! Instance is STOPPED[/yellow]"
    )
    console.print(
        "  [yellow]! CPU evidence unavailable[/yellow]"
    )
    console.print(
        "  [yellow]! Memory evidence unavailable[/yellow]"
    )
    console.print(
        "  → [yellow]INVESTIGATE[/yellow]"
    )
    console.print(
        "    No resize decision made without active workload evidence."
    )


def _metric_line(
    *,
    label: str,
    statistics: Any,
    workload: Any,
) -> None:
    console.print(
        f"  [green]✓[/green] "
        f"{label:<8} "
        f"avg {statistics.average:.2f}% | "
        f"p95 {statistics.p95:.2f}% | "
        f"max {statistics.maximum:.2f}% | "
        f"{workload.trend.lower()} | "
        f"{workload.spike_risk.lower()} risk"
    )


def print_metrics(
    *,
    deterministic: Any,
) -> None:
    if (
        deterministic.cpu_statistics is None
        or deterministic.memory_statistics is None
        or deterministic.cpu_workload is None
        or deterministic.memory_workload is None
    ):
        return

    _metric_line(
        label="CPU",
        statistics=deterministic.cpu_statistics,
        workload=deterministic.cpu_workload,
    )

    _metric_line(
        label="Memory",
        statistics=deterministic.memory_statistics,
        workload=deterministic.memory_workload,
    )


def print_ai_start() -> None:
    console.print(
        "  [cyan]→ Running AI reasoning...[/cyan]"
    )


def print_ai_failed(
    *,
    message: str,
) -> None:
    console.print(
        f"  [yellow]! AI reasoning failed:[/yellow] {message}"
    )


def print_ai_skipped() -> None:
    console.print(
        "  [yellow]! AI reasoning skipped: evidence is insufficient[/yellow]"
    )


def print_ai_unavailable() -> None:
    console.print(
        "  [yellow]! AI reasoning unavailable: "
        "OpenAI API key is not configured[/yellow]"
    )


def print_decision(
    *,
    deterministic: Any,
) -> None:
    decision = deterministic.recommendation
    style = DECISION_STYLES.get(decision, "yellow")

    console.print()
    console.print(
        f"  → [{style}][bold]{decision}[/bold][/{style}]"
    )


def print_reason(
    *,
    impact: Any,
) -> None:
    console.print(
        f"    Why: {impact.summary}"
    )

    console.print(
        f"    Why this matters: {impact.why_effective}"
    )


def print_cost(
    *,
    impact: Any,
) -> None:
    if (
        impact.current_monthly_cost is None
        or impact.recommended_monthly_cost is None
    ):
        return

    console.print()
    console.print("    [bold]Cost impact[/bold]")

    console.print(
        f"      Current: "
        f"${impact.current_monthly_cost:.2f}/month"
    )

    console.print(
        f"      Recommended: "
        f"${impact.recommended_monthly_cost:.2f}/month"
    )

    if impact.monthly_cost_change_usd is not None:
        console.print(
            f"      Monthly difference: "
            f"${impact.monthly_cost_change_usd:.2f}"
        )

    if impact.annual_cost_change_usd is not None:
        console.print(
            f"      Annual difference: "
            f"${impact.annual_cost_change_usd:.2f}"
        )

    if impact.savings_percent is not None:
        console.print(
            f"      Savings: "
            f"{impact.savings_percent:.2f}%"
        )


def print_candidates(
    *,
    pricing: dict[str, Any],
    deterministic: Any,
) -> None:
    candidates = pricing.get("candidates", [])

    if not candidates:
        if deterministic.recommendation == "KEEP_CURRENT":
            concern = pricing.get("missing_evidence", [])

            if concern:
                console.print(
                    f"    [yellow]! {concern[-1]}[/yellow]"
                )

            return

        if deterministic.recommendation == "DOWNSIZE_CANDIDATE":
            console.print(
                "    [yellow]! No smaller compatible real AWS "
                "instance passed validation[/yellow]"
            )

        elif deterministic.recommendation == "UPSCALE_CANDIDATE":
            console.print(
                "    [yellow]! No larger compatible real AWS "
                "instance passed validation[/yellow]"
            )

        return

    console.print()
    console.print("    [bold]Candidate validation[/bold]")

    for candidate in candidates:
        instance_type = candidate["instance_type"]

        if candidate["safe"]:
            symbol = "[green]✓[/green]"
            status = "valid"
        else:
            symbol = "[red]✗[/red]"
            status = "rejected"

        console.print(
            f"      {symbol} {instance_type:<12} "
            f"{candidate['vcpus']} vCPU | "
            f"{candidate['memory_mib']} MiB | "
            f"${candidate['monthly_usd']:.2f}/month | "
            f"{status}"
        )

        if not candidate["safe"]:
            for reason in candidate["validation_reasons"]:
                console.print(
                    f"        [dim]↳ {reason}[/dim]"
                )

    recommended = pricing.get("recommended_candidate")
    current = pricing.get("current")

    if recommended is None or current is None:
        return

    console.print()
    console.print(
        f"    [green]✓ Validated candidate: "
        f"{recommended['instance_type']}[/green]"
    )

    console.print(
        f"      Current: "
        f"{current['instance_type']} "
        f"(${current['monthly_usd']:.2f}/month)"
    )

    console.print(
        f"      Recommended: "
        f"{recommended['instance_type']} "
        f"(${recommended['monthly_usd']:.2f}/month)"
    )

    console.print(
        f"      Savings: "
        f"${abs(recommended['monthly_cost_change_usd']):.2f}/month "
        f"({recommended['savings_percent']:.2f}%)"
    )

    console.print(
        f"      CPU sufficient: "
        f"{recommended['cpu_sufficient']}"
    )

    console.print(
        f"      Memory sufficient: "
        f"{recommended['memory_sufficient']}"
    )

    for reason in recommended["validation_reasons"]:
        console.print(
            f"      [green]✓[/green] {reason}"
        )


def print_benefits_and_risks(
    *,
    impact: Any,
) -> None:
    if impact.benefits:
        console.print()
        console.print("    [bold green]Benefits[/bold green]")

        for benefit in impact.benefits:
            console.print(
                f"      [green]✓[/green] {benefit}"
            )

    if impact.risks:
        console.print()
        console.print("    [bold yellow]Risks / trade-offs[/bold yellow]")

        for risk in impact.risks:
            console.print(
                f"      [yellow]![/yellow] {risk}"
            )


def print_optimization(
    *,
    impact: Any,
    pricing: dict[str, Any],
    deterministic: Any,
) -> None:
    print_decision(
        deterministic=deterministic,
    )

    print_reason(
        impact=impact,
    )

    print_cost(
        impact=impact,
    )

    print_candidates(
        pricing=pricing,
        deterministic=deterministic,
    )

    print_benefits_and_risks(
        impact=impact,
    )

    console.print()


def print_instance_error(
    *,
    message: str,
) -> None:
    console.print(
        f"  [red]✗ Instance analysis failed:[/red] {message}"
    )


def print_complete(
    *,
    result_count: int,
    output_path: str,
) -> None:
    console.print()
    console.print(
        "[bold green]Analysis complete[/bold green]"
    )
    console.print(
        f"[green]✓[/green] Instances analyzed: "
        f"[bold]{result_count}[/bold]"
    )
    console.print(
        f"[green]✓[/green] Report: {output_path}"
    )