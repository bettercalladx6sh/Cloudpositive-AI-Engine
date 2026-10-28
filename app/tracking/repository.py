from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.database.models import InstanceSnapshotRecord
from app.tracking.models import InstanceSnapshot


class SnapshotRepository:
    """Persist and retrieve EC2 instance snapshots with direct MySQL SQL."""

    def __init__(self, session) -> None:
        self._connection = session

    def save(self, snapshot: InstanceSnapshot) -> InstanceSnapshotRecord:
        sql = """
            INSERT INTO instance_snapshots
            (instance_id, region, availability_zone, instance_type, state,
             architecture, platform, launch_time, private_ip, public_ip,
             name, tags, configuration_version, observed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        with self._connection.cursor() as cursor:
            cursor.execute(sql, (
                snapshot.instance_id, snapshot.region, snapshot.availability_zone,
                snapshot.instance_type, snapshot.state, snapshot.architecture,
                snapshot.platform, snapshot.launch_time, snapshot.private_ip,
                snapshot.public_ip, snapshot.name, json.dumps(dict(snapshot.tags)),
                snapshot.configuration_version, snapshot.observed_at,
            ))
            record_id = cursor.lastrowid
        return self._get_by_id(int(record_id))

    def get_latest(self, instance_id: str, region: str) -> InstanceSnapshotRecord | None:
        if not instance_id.strip(): raise ValueError("EC2 instance ID cannot be empty.")
        if not region.strip(): raise ValueError("AWS region cannot be empty.")
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM instance_snapshots
                WHERE instance_id=%s AND region=%s
                ORDER BY observed_at DESC, id DESC LIMIT 1
            """, (instance_id, region))
            row = cursor.fetchone()
        return InstanceSnapshotRecord(**row) if row else None

    def get_history(self, instance_id: str, region: str) -> tuple[InstanceSnapshotRecord, ...]:
        if not instance_id.strip(): raise ValueError("EC2 instance ID cannot be empty.")
        if not region.strip(): raise ValueError("AWS region cannot be empty.")
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM instance_snapshots
                WHERE instance_id=%s AND region=%s
                ORDER BY observed_at DESC, id DESC
            """, (instance_id, region))
            rows = cursor.fetchall()
        return tuple(InstanceSnapshotRecord(**row) for row in rows)

    def _get_by_id(self, record_id: int) -> InstanceSnapshotRecord:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM instance_snapshots WHERE id=%s", (record_id,))
            row = cursor.fetchone()
        if not row: raise LookupError(f"Snapshot {record_id} was not found.")
        return InstanceSnapshotRecord(**row)


def record_to_snapshot(record: InstanceSnapshotRecord) -> InstanceSnapshot:
    tags_data: dict[str, str] = {}
    if record.tags:
        decoded_tags = json.loads(record.tags)
        if not isinstance(decoded_tags, dict):
            raise ValueError("Stored snapshot tags must be a JSON object.")
        tags_data = {str(k): str(v) for k, v in decoded_tags.items()}
    return InstanceSnapshot(
        instance_id=record.instance_id, region=record.region,
        availability_zone=record.availability_zone, instance_type=record.instance_type,
        state=record.state, architecture=record.architecture, platform=record.platform,
        launch_time=record.launch_time, private_ip=record.private_ip, public_ip=record.public_ip,
        name=record.name, tags=tuple(sorted(tags_data.items())),
        configuration_version=record.configuration_version, observed_at=record.observed_at,
    )
