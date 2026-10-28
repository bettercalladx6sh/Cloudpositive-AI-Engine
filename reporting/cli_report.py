from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


console = Console()


def _decision_style(
    decision: str,
) -> str:
    styles = {
        "DOWNSIZE_CANDIDATE": "bold green",
        "UPSCALE_CANDIDATE": "bold yellow",
        "KEEP_CURRENT": "bold cyan",
        "INVESTIGATE": "bold yellow",
        "INSUFFICIENT_DATA": "bold red",
    }

    return styles.get(
        decision,
        "bold",
    )


def _fit_text(
    value: bool,
) -> Text:
    if value:
        return Text("YES", style="bold green")

    return Text("NO", style="bold red")


def display_header(
    *,
    account_id: str,
    region: str,
    instance_count: int,
) -> None:
    content = Group(
        Text(
            f"Account: {account_id}",
            style="bold",
        ),
        Text(
            f"Region:  {region}",
        ),
        Text(
            f"Instances: {instance_count}",
        ),
    )

    console.print(
        Panel(
            content,
            title=(
                "[bold cyan]"
                "AWS Cost & Infrastructure Optimizer"
                "[/bold cyan]"
            ),
            border_style="cyan",
        )
    )


def display_instance_summary(
    results: list[dict[str, Any]],
) -> None:
    table = Table(
        title="Optimization Summary",
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("Instance")
    table.add_column("Type")
    table.add_column("State")
    table.add_column("Decision")
    table.add_column(
        "Monthly Cost",
        justify="right",
    )
    table.add_column(
        "Change",
        justify="right",
    )

    for result in results:
        instance = result.get(
            "instance",
            {},
        )

        optimization = result.get(
            "optimization",
            {},
        )

        state = str(
            instance.get(
                "state",
                "unknown",
            )
        ).upper()

        decision = result.get(
            "final_recommendation",
            "INVESTIGATE",
        )

        current_cost = optimization.get(
            "current_monthly_cost"
        )

        monthly_change = optimization.get(
            "monthly_cost_change_usd"
        )

        current_cost_text = (
            f"${current_cost:.2f}"
            if current_cost is not None
            else "-"
        )

        if monthly_change is None:
            change_text = "-"
        elif monthly_change < 0:
            change_text = (
                f"[green]"
                f"-${abs(monthly_change):.2f}"
                f"[/green]"
            )
        elif monthly_change > 0:
            change_text = (
                f"[yellow]"
                f"+${monthly_change:.2f}"
                f"[/yellow]"
            )
        else:
            change_text = "$0.00"

        table.add_row(
            str(
                instance.get(
                    "name"
                )
                or instance.get(
                    "instance_id",
                    "unknown",
                )
            ),
            str(
                instance.get(
                    "instance_type",
                    "-",
                )
            ),
            state,
            (
                f"[{_decision_style(decision)}]"
                f"{decision}"
                f"[/{_decision_style(decision)}]"
            ),
            current_cost_text,
            change_text,
        )

    console.print(table)


def display_instance_analysis(
    *,
    instance: Any,
    metrics: Any,
    deterministic: Any,
    pricing: dict[str, Any],
    impact: Any,
    ai_result: Any,
) -> None:
    console.print()

    state = str(
        instance.state
    ).upper()

    state_style = (
        "bold green"
        if state == "RUNNING"
        else "bold yellow"
    )

    # ---------------------------------------------------------
    # Instance / capacity panel
    # ---------------------------------------------------------

    current_price = pricing.get(
        "current"
    ) or {}

    current_monthly = current_price.get(
        "monthly_usd"
    )

    capacity_lines: list[str] = [
        (
            f"[bold]Instance:[/bold] "
            f"{instance.instance_id}"
        ),
        (
            f"[bold]State:[/bold] "
            f"[{state_style}]{state}"
            f"[/{state_style}]"
        ),
        (
            f"[bold]Current type:[/bold] "
            f"{instance.instance_type}"
        ),
        (
            f"[bold]Architecture:[/bold] "
            f"{instance.architecture}"
        ),
    ]

    if deterministic.capacity is not None:
        capacity = deterministic.capacity

        capacity_lines.extend(
            [
                "",
                "[bold cyan]Current capacity[/bold cyan]",
                (
                    f"  vCPU: "
                    f"{capacity.current_vcpu}"
                ),
                (
                    f"  Memory: "
                    f"{capacity.current_memory_mib:.0f} MiB"
                ),
            ]
        )

    if current_monthly is not None:
        capacity_lines.append(
            f"  Monthly cost: "
            f"${current_monthly:.2f}"
        )

    console.print(
        Panel(
            "\n".join(capacity_lines),
            title=(
                f"[bold]{instance.name or instance.instance_id}"
                "[/bold]"
            ),
            border_style="cyan",
        )
    )

    # ---------------------------------------------------------
    # Stopped instance
    # ---------------------------------------------------------

    if state != "RUNNING":
        console.print(
            Panel(
                "\n".join(
                    [
                        (
                            "[yellow]CPU:[/yellow] "
                            "UNAVAILABLE"
                        ),
                        (
                            "  Instance is stopped, so "
                            "active CPU utilization cannot "
                            "be measured."
                        ),
                        "",
                        (
                            "[yellow]Memory:[/yellow] "
                            "UNAVAILABLE"
                        ),
                        (
                            "  Instance is stopped, so "
                            "active memory utilization cannot "
                            "be measured."
                        ),
                        "",
                        (
                            "[bold]Capacity analysis:[/bold] "
                            "UNAVAILABLE"
                        ),
                        (
                            "  A workload-based resize cannot "
                            "be safely validated."
                        ),
                    ]
                ),
                title="[yellow]Workload Evidence[/yellow]",
                border_style="yellow",
            )
        )

        _display_final_recommendation(
            impact=impact,
            ai_result=ai_result,
        )

        return

    # ---------------------------------------------------------
    # Workload panel
    # ---------------------------------------------------------

    workload_lines: list[str] = []

    cpu_stats = deterministic.cpu_statistics
    memory_stats = deterministic.memory_statistics

    if cpu_stats is not None:
        workload_lines.extend(
            [
                "[bold]CPU[/bold]",
                (
                    f"  Average: "
                    f"{cpu_stats.average:.2f}%"
                ),
                (
                    f"  P95:     "
                    f"{cpu_stats.p95:.2f}%"
                ),
                (
                    f"  Maximum: "
                    f"{cpu_stats.maximum:.2f}%"
                ),
            ]
        )

        if deterministic.cpu_workload is not None:
            workload_lines.extend(
                [
                    (
                        f"  Trend:   "
                        f"{deterministic.cpu_workload.trend}"
                    ),
                    (
                        f"  Spike:   "
                        f"{deterministic.cpu_workload.spike_risk}"
                    ),
                ]
            )

    else:
        workload_lines.extend(
            [
                "[bold]CPU[/bold]",
                "  UNAVAILABLE",
            ]
        )

    workload_lines.append("")

    if memory_stats is not None:
        workload_lines.extend(
            [
                "[bold]Memory[/bold]",
                (
                    f"  Average: "
                    f"{memory_stats.average:.2f}%"
                ),
                (
                    f"  P95:     "
                    f"{memory_stats.p95:.2f}%"
                ),
                (
                    f"  Maximum: "
                    f"{memory_stats.maximum:.2f}%"
                ),
            ]
        )

        if deterministic.memory_workload is not None:
            workload_lines.extend(
                [
                    (
                        f"  Trend:   "
                        f"{deterministic.memory_workload.trend}"
                    ),
                    (
                        f"  Spike:   "
                        f"{deterministic.memory_workload.spike_risk}"
                    ),
                ]
            )

    else:
        workload_lines.extend(
            [
                "[bold]Memory[/bold]",
                "  UNAVAILABLE",
            ]
        )

    console.print(
        Panel(
            "\n".join(workload_lines),
            title="[bold cyan]Workload Evidence[/bold cyan]",
            border_style="cyan",
        )
    )

    # ---------------------------------------------------------
    # Capacity requirement
    # ---------------------------------------------------------

    if deterministic.capacity is not None:
        capacity = deterministic.capacity

        console.print(
            Panel(
                "\n".join(
                    [
                        (
                            f"Estimated CPU required: "
                            f"{capacity.estimated_cpu_required_percent:.2f}%"
                        ),
                        (
                            f"Estimated memory required: "
                            f"{capacity.estimated_memory_required_mib:.2f} MiB"
                        ),
                    ]
                ),
                title="[bold cyan]Estimated Requirement[/bold cyan]",
                border_style="cyan",
            )
        )

    # ---------------------------------------------------------
    # Candidate comparison
    # ---------------------------------------------------------

    _display_candidates(
        pricing=pricing,
        deterministic=deterministic,
        current_instance=instance.instance_type,
        impact=impact,
    )

    # ---------------------------------------------------------
    # Final recommendation
    # ---------------------------------------------------------

    _display_final_recommendation(
        impact=impact,
        ai_result=ai_result,
    )


def _display_candidates(
    *,
    pricing: dict[str, Any],
    deterministic: Any,
    current_instance: str,
    impact: Any,
) -> None:
    candidates = pricing.get(
        "candidates",
        [],
    )

    decision = deterministic.recommendation

    if decision not in {
        "DOWNSIZE_CANDIDATE",
        "UPSCALE_CANDIDATE",
    }:
        return

    title = (
        "Smaller Instance Analysis"
        if decision == "DOWNSIZE_CANDIDATE"
        else "Larger Instance Analysis"
    )

    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("Candidate")
    table.add_column("vCPU")
    table.add_column("Memory")
    table.add_column("CPU Fit")
    table.add_column("Memory Fit")
    table.add_column("Cost", justify="right")
    table.add_column("Change", justify="right")
    table.add_column("Result")

    for candidate in candidates:
        safe = candidate.get(
            "safe",
            False,
        )

        monthly = candidate.get(
            "monthly_usd"
        )

        change = candidate.get(
            "monthly_cost_change_usd"
        )

        if monthly is None:
            monthly_text = "-"
        else:
            monthly_text = f"${monthly:.2f}"

        if change is None:
            change_text = "-"
        elif change < 0:
            change_text = (
                f"[green]"
                f"-${abs(change):.2f}"
                f"[/green]"
            )
        elif change > 0:
            change_text = (
                f"[yellow]"
                f"+${change:.2f}"
                f"[/yellow]"
            )
        else:
            change_text = "$0.00"

        if safe:
            result_text = "[green]VALID[/green]"
        else:
            result_text = "[red]REJECTED[/red]"

        table.add_row(
            candidate.get(
                "instance_type",
                "-",
            ),
            str(
                candidate.get(
                    "vcpus",
                    "-",
                )
            ),
            (
                f"{candidate.get('memory_mib', '-')}"
                " MiB"
            ),
            _fit_text(
                bool(
                    candidate.get(
                        "cpu_sufficient",
                        False,
                    )
                )
            ),
            _fit_text(
                bool(
                    candidate.get(
                        "memory_sufficient",
                        False,
                    )
                )
            ),
            monthly_text,
            change_text,
            result_text,
        )

    console.print(table)

    recommended = pricing.get(
        "recommended_candidate"
    )

    if recommended:
        console.print(
            Panel(
                _candidate_details(
                    candidate=recommended,
                    current_instance=current_instance,
                    decision=decision,
                ),
                title=(
                    "[bold green]"
                    "Best Validated Candidate"
                    "[/bold green]"
                ),
                border_style="green",
            )
        )

    else:
        console.print(
            Panel(
                (
                    "No compatible candidate passed all "
                    "deterministic capacity validation checks.\n\n"
                    "The current instance should not be changed "
                    "based on the available evidence."
                ),
                title="[yellow]Candidate Result[/yellow]",
                border_style="yellow",
            )
        )


def _candidate_details(
    *,
    candidate: dict[str, Any],
    current_instance: str,
    decision: str,
) -> str:
    candidate_type = candidate.get(
        "instance_type",
        "-",
    )

    current_cost = candidate.get(
        "current_monthly_usd"
    )

    candidate_cost = candidate.get(
        "monthly_usd"
    )

    change = candidate.get(
        "monthly_cost_change_usd"
    )

    savings = candidate.get(
        "savings_percent"
    )

    lines = [
        (
            f"[bold]{current_instance}[/bold]"
            " → "
            f"[bold green]{candidate_type}[/bold green]"
        ),
        "",
        (
            f"CPU fit: "
            f"{'YES' if candidate.get('cpu_sufficient') else 'NO'}"
        ),
        (
            f"Memory fit: "
            f"{'YES' if candidate.get('memory_sufficient') else 'NO'}"
        ),
    ]

    if current_cost is not None:
        lines.append(
            f"Current monthly cost: "
            f"${current_cost:.2f}"
        )

    if candidate_cost is not None:
        lines.append(
            f"Candidate monthly cost: "
            f"${candidate_cost:.2f}"
        )

    if change is not None:
        sign = "+" if change > 0 else ""
        lines.append(
            f"Monthly cost change: "
            f"{sign}${change:.2f}"
        )

    if savings is not None:
        if savings > 0:
            lines.append(
                f"Savings: "
                f"{savings:.2f}%"
            )
        elif savings < 0:
            lines.append(
                f"Cost increase: "
                f"{abs(savings):.2f}%"
            )

    pros = candidate.get(
        "pros",
        [],
    )

    cons = candidate.get(
        "cons",
        [],
    )

    if pros:
        lines.extend(
            [
                "",
                "[bold green]Pros[/bold green]",
            ]
        )

        for item in pros:
            lines.append(
                f"  [green]✓[/green] {item}"
            )

    if cons:
        lines.extend(
            [
                "",
                "[bold yellow]Cons[/bold yellow]",
            ]
        )

        for item in cons:
            lines.append(
                f"  [yellow]![/yellow] {item}"
            )

    return "\n".join(lines)


def _display_final_recommendation(
    *,
    impact: Any,
    ai_result: Any,
) -> None:
    decision = impact.decision

    lines = [
        (
            f"[bold]Decision:[/bold] "
            f"[{_decision_style(decision)}]"
            f"{decision}"
            f"[/{_decision_style(decision)}]"
        ),
        (
            f"[bold]Current:[/bold] "
            f"{impact.current_instance}"
        ),
    ]

    if impact.recommended_instance:
        lines.append(
            (
                f"[bold]Recommended:[/bold] "
                f"[green]"
                f"{impact.recommended_instance}"
                f"[/green]"
            )
        )
    else:
        lines.append(
            "[bold]Recommended:[/bold] None"
        )

    if impact.summary:
        lines.extend(
            [
                "",
                (
                    f"[bold]Why:[/bold] "
                    f"{impact.summary}"
                ),
            ]
        )

    if impact.why_effective:
        lines.append(
            (
                f"[bold]Assessment:[/bold] "
                f"{impact.why_effective}"
            )
        )

    if impact.benefits:
        lines.extend(
            [
                "",
                "[bold green]Pros[/bold green]",
            ]
        )

        for benefit in impact.benefits:
            lines.append(
                f"  [green]✓[/green] {benefit}"
            )

    if impact.risks:
        lines.extend(
            [
                "",
                "[bold yellow]Cons / Risks[/bold yellow]",
            ]
        )

        for risk in impact.risks:
            lines.append(
                f"  [yellow]![/yellow] {risk}"
            )

    if ai_result:
        ai_reason = (
            ai_result.get("reason")
            if isinstance(ai_result, dict)
            else None
        )

        if ai_reason:
            lines.extend(
                [
                    "",
                    "[bold magenta]AI Assessment[/bold magenta]",
                    f"  {ai_reason}",
                ]
            )

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]Final Recommendation[/bold]",
            border_style=_decision_style(
                decision
            ).replace(
                "bold ",
                "",
            ),
        )
    )