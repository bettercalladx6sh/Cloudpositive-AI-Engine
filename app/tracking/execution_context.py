from __future__ import annotations

import getpass
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ExecutionContext:
    """
    Immutable identity for one application execution.

    CLI:
        username = local OS user
        client_ip = local machine/network IP when available

    Future API:
        these values can be supplied by the API authentication layer.
    """

    execution_id: str
    username: str
    client_ip: str | None
    started_at: datetime
    source: str
    command: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _detect_client_ip() -> str | None:
    """
    Determine the local machine's network address.

    This is intentionally not inferred from AWS.
    """

    try:
        hostname = socket.gethostname()
        address = socket.gethostbyname(hostname)

        if address:
            return address
    except OSError:
        pass

    return None


def create_cli_execution_context(
    *,
    command: str,
) -> ExecutionContext:
    """
    Create an execution context for a CLI invocation.
    """

    normalized_command = command.strip()

    if not normalized_command:
        raise ValueError(
            "command cannot be empty."
        )

    return ExecutionContext(
        execution_id=str(uuid.uuid4()),
        username=getpass.getuser(),
        client_ip=_detect_client_ip(),
        started_at=_utc_now(),
        source="CLI",
        command=normalized_command,
    )