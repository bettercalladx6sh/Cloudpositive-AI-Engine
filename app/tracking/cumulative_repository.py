from __future__ import annotations

from datetime import datetime

from app.database.cumulative_models import MetricCumulativeSummaryRecord


class MetricCumulativeRepository:
    """Persistence operations for rebuildable cumulative metric summaries."""
    def __init__(self, session) -> None: self.connection = session

    def get(self, *, instance_id: str, region: str, namespace: str,
            metric_name: str, configuration_version: str) -> MetricCumulativeSummaryRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM metric_cumulative_summaries
                WHERE instance_id=%s AND region=%s AND namespace=%s
                  AND metric_name=%s AND configuration_version=%s
            """, (instance_id, region, namespace, metric_name, configuration_version))
            row = cursor.fetchone()
        return MetricCumulativeSummaryRecord(**row) if row else None

    def save(self, *, instance_id: str, region: str, namespace: str,
             metric_name: str, configuration_version: str,
             evidence_start: datetime | None, evidence_end: datetime | None,
             datapoint_count: int, value_sum: float, average: float | None,
             minimum: float | None, maximum: float | None, p50: float | None,
             p95: float | None, p99: float | None, standard_deviation: float | None,
             trend: str | None, volatility: str | None, coverage_percent: float,
             gap_count: int, last_updated_at: datetime) -> MetricCumulativeSummaryRecord:
        sql = """
            INSERT INTO metric_cumulative_summaries
            (instance_id, region, namespace, metric_name, configuration_version,
             evidence_start, evidence_end, datapoint_count, value_sum, average,
             minimum, maximum, p50, p95, p99, standard_deviation, trend, volatility,
             coverage_percent, gap_count, last_updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              evidence_start=VALUES(evidence_start), evidence_end=VALUES(evidence_end),
              datapoint_count=VALUES(datapoint_count), value_sum=VALUES(value_sum),
              average=VALUES(average), minimum=VALUES(minimum), maximum=VALUES(maximum),
              p50=VALUES(p50), p95=VALUES(p95), p99=VALUES(p99),
              standard_deviation=VALUES(standard_deviation), trend=VALUES(trend),
              volatility=VALUES(volatility), coverage_percent=VALUES(coverage_percent),
              gap_count=VALUES(gap_count), last_updated_at=VALUES(last_updated_at)
        """
        values=(instance_id, region, namespace, metric_name, configuration_version,
                evidence_start, evidence_end, datapoint_count, value_sum, average,
                minimum, maximum, p50, p95, p99, standard_deviation, trend, volatility,
                coverage_percent, gap_count, last_updated_at)
        with self.connection.cursor() as cursor: cursor.execute(sql, values)
        return self.get(instance_id=instance_id, region=region, namespace=namespace,
                        metric_name=metric_name, configuration_version=configuration_version)

    def get_for_instance(self, *, instance_id: str, region: str,
                         configuration_version: str) -> list[MetricCumulativeSummaryRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM metric_cumulative_summaries
                WHERE instance_id=%s AND region=%s AND configuration_version=%s
                ORDER BY namespace, metric_name
            """, (instance_id, region, configuration_version))
            rows=cursor.fetchall()
        return [MetricCumulativeSummaryRecord(**row) for row in rows]
