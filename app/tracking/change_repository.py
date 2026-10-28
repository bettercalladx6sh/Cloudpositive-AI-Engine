from __future__ import annotations

from app.database.models import ConfigurationChangeRecord
from app.tracking.models import ConfigurationChange


class ConfigurationChangeRepository:
    """Persist and retrieve EC2 configuration changes."""
    def __init__(self, session) -> None: self._connection = session

    def save(self, change: ConfigurationChange) -> ConfigurationChangeRecord:
        with self._connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO configuration_changes
                (instance_id, region, detected_at, previous_instance_type, current_instance_type)
                VALUES (%s, %s, %s, %s, %s)
            """, (change.instance_id, change.region, change.detected_at,
                  change.previous_instance_type, change.current_instance_type))
            record_id = cursor.lastrowid
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM configuration_changes WHERE id=%s", (record_id,))
            row = cursor.fetchone()
        return ConfigurationChangeRecord(**row)

    def get_history(self, instance_id: str, region: str) -> tuple[ConfigurationChangeRecord, ...]:
        if not instance_id.strip(): raise ValueError("EC2 instance ID cannot be empty.")
        if not region.strip(): raise ValueError("AWS region cannot be empty.")
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM configuration_changes
                WHERE instance_id=%s AND region=%s
                ORDER BY detected_at DESC, id DESC
            """, (instance_id, region))
            rows = cursor.fetchall()
        return tuple(ConfigurationChangeRecord(**row) for row in rows)
