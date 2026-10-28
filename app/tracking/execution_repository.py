from __future__ import annotations

from datetime import datetime, timezone

from app.database.models import ExecutionRunRecord
from app.tracking.execution_context import ExecutionContext


class ExecutionRepository:
    """Persistence operations for execution audit records."""
    def __init__(self, session) -> None: self.connection = session

    def create(self, *, context: ExecutionContext) -> ExecutionRunRecord:
        with self.connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO execution_runs
                (execution_id, username, client_ip, command, source, started_at,
                 completed_at, status, aws_account_id, aws_identity, aws_region,
                 resources_discovered, resources_analyzed, resources_skipped,
                 resources_collecting_data, recommendations_created, error_message, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,NULL,'RUNNING',NULL,NULL,NULL,0,0,0,0,0,NULL,%s)
            """, (context.execution_id, context.username, context.client_ip,
                  context.command, context.source, context.started_at, datetime.now(timezone.utc)))
            record_id = cursor.lastrowid
        return self._get_by_id(int(record_id))

    def get_by_execution_id(self, execution_id: str) -> ExecutionRunRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM execution_runs WHERE execution_id=%s", (execution_id,))
            row = cursor.fetchone()
        return ExecutionRunRecord(**row) if row else None

    def complete(self, *, execution_id: str, status: str,
                 completed_at: datetime | None = None,
                 error_message: str | None = None) -> ExecutionRunRecord:
        record = self.get_by_execution_id(execution_id)
        if record is None: raise LookupError(f"Execution {execution_id} was not found.")
        completed_at = completed_at or datetime.now(timezone.utc)
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE execution_runs SET status=%s, completed_at=%s, error_message=%s WHERE execution_id=%s",
                           (status, completed_at, error_message, execution_id))
        return self.get_by_execution_id(execution_id)

    def update_counters(self, *, execution_id: str, resources_discovered: int | None = None,
                        resources_analyzed: int | None = None, resources_skipped: int | None = None,
                        resources_collecting_data: int | None = None,
                        recommendations_created: int | None = None) -> ExecutionRunRecord:
        self._require(execution_id)
        updates, values = [], []
        for column, value in (("resources_discovered", resources_discovered),
                              ("resources_analyzed", resources_analyzed),
                              ("resources_skipped", resources_skipped),
                              ("resources_collecting_data", resources_collecting_data),
                              ("recommendations_created", recommendations_created)):
            if value is not None: updates.append(f"{column}=%s"); values.append(value)
        if updates:
            values.append(execution_id)
            with self.connection.cursor() as cursor:
                cursor.execute(f"UPDATE execution_runs SET {', '.join(updates)} WHERE execution_id=%s", values)
        return self.get_by_execution_id(execution_id)

    def update_aws_identity(self, *, execution_id: str, account_id: str | None,
                            identity: str | None, region: str | None) -> ExecutionRunRecord:
        self._require(execution_id)
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE execution_runs SET aws_account_id=%s, aws_identity=%s, aws_region=%s WHERE execution_id=%s",
                           (account_id, identity, region, execution_id))
        return self.get_by_execution_id(execution_id)

    def _require(self, execution_id: str) -> None:
        if self.get_by_execution_id(execution_id) is None:
            raise LookupError(f"Execution {execution_id} was not found.")

    def _get_by_id(self, record_id: int) -> ExecutionRunRecord:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM execution_runs WHERE id=%s", (record_id,))
            row = cursor.fetchone()
        if not row: raise LookupError(f"Execution record {record_id} was not found.")
        return ExecutionRunRecord(**row)
