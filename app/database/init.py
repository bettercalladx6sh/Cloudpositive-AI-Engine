from __future__ import annotations

from app.database.connection import create_database_connection


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS instance_snapshots (
        id INT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(32) NOT NULL,
        region VARCHAR(32) NOT NULL,
        availability_zone VARCHAR(32) NOT NULL,
        instance_type VARCHAR(64) NOT NULL,
        state VARCHAR(32) NOT NULL,
        architecture VARCHAR(32) NULL,
        platform VARCHAR(64) NULL,
        launch_time DATETIME NULL,
        private_ip VARCHAR(45) NULL,
        public_ip VARCHAR(45) NULL,
        name VARCHAR(255) NULL,
        tags TEXT NULL,
        configuration_version VARCHAR(128) NOT NULL DEFAULT 'legacy',
        observed_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        INDEX ix_instance_snapshots_instance_id (instance_id),
        INDEX ix_instance_snapshots_region (region),
        INDEX ix_instance_snapshots_configuration_version (configuration_version),
        INDEX ix_instance_snapshots_observed_at (observed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS configuration_changes (
        id INT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(32) NOT NULL,
        region VARCHAR(32) NOT NULL,
        detected_at DATETIME NOT NULL,
        previous_instance_type VARCHAR(64) NOT NULL,
        current_instance_type VARCHAR(64) NOT NULL,
        PRIMARY KEY (id),
        INDEX ix_configuration_changes_instance_id (instance_id),
        INDEX ix_configuration_changes_region (region),
        INDEX ix_configuration_changes_detected_at (detected_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS metric_observations (
        id INT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(32) NOT NULL,
        region VARCHAR(32) NOT NULL,
        namespace VARCHAR(128) NOT NULL,
        metric_name VARCHAR(128) NOT NULL,
        configuration_version VARCHAR(128) NOT NULL DEFAULT 'legacy',
        average DOUBLE NULL,
        minimum DOUBLE NULL,
        maximum DOUBLE NULL,
        datapoint_count INT NOT NULL,
        first_datapoint DATETIME NULL,
        last_datapoint DATETIME NULL,
        coverage_hours DOUBLE NOT NULL,
        analysis_start DATETIME NOT NULL,
        analysis_end DATETIME NOT NULL,
        observed_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        INDEX ix_metric_observations_instance_id (instance_id),
        INDEX ix_metric_observations_region (region),
        INDEX ix_metric_observations_configuration_version (configuration_version),
        INDEX ix_metric_observations_observed_at (observed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS metric_datapoints (
        id INT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(32) NOT NULL,
        region VARCHAR(32) NOT NULL,
        namespace VARCHAR(128) NOT NULL,
        metric_name VARCHAR(128) NOT NULL,
        configuration_version VARCHAR(128) NOT NULL DEFAULT 'legacy',
        timestamp DATETIME NOT NULL,
        average DOUBLE NULL,
        minimum DOUBLE NULL,
        maximum DOUBLE NULL,
        observed_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uq_metric_datapoint (instance_id, region, namespace, metric_name, configuration_version, timestamp),
        INDEX ix_metric_datapoints_instance_id (instance_id),
        INDEX ix_metric_datapoints_region (region),
        INDEX ix_metric_datapoints_configuration_version (configuration_version),
        INDEX ix_metric_datapoints_timestamp (timestamp)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS metric_collection_checkpoints (
        id INT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(32) NOT NULL,
        region VARCHAR(32) NOT NULL,
        namespace VARCHAR(128) NOT NULL,
        metric_name VARCHAR(128) NOT NULL,
        configuration_version VARCHAR(128) NOT NULL,
        checkpoint_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uq_metric_collection_checkpoint (instance_id, region, namespace, metric_name, configuration_version),
        INDEX ix_metric_checkpoint_resource_metric (instance_id, region, metric_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS metric_cumulative_summaries (
        id BIGINT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(64) NOT NULL,
        region VARCHAR(32) NOT NULL,
        namespace VARCHAR(128) NOT NULL,
        metric_name VARCHAR(128) NOT NULL,
        configuration_version VARCHAR(128) NOT NULL,
        evidence_start DATETIME NULL,
        evidence_end DATETIME NULL,
        datapoint_count INT NOT NULL DEFAULT 0,
        value_sum DOUBLE NOT NULL DEFAULT 0,
        average DOUBLE NULL,
        minimum DOUBLE NULL,
        maximum DOUBLE NULL,
        p50 DOUBLE NULL,
        p95 DOUBLE NULL,
        p99 DOUBLE NULL,
        standard_deviation DOUBLE NULL,
        trend VARCHAR(32) NULL,
        volatility VARCHAR(32) NULL,
        coverage_percent DOUBLE NOT NULL DEFAULT 0,
        gap_count INT NOT NULL DEFAULT 0,
        last_updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uq_metric_cumulative_summary (instance_id, region, namespace, metric_name, configuration_version),
        INDEX ix_metric_cumulative_instance_metric (instance_id, region, namespace, metric_name),
        INDEX ix_metric_cumulative_configuration (instance_id, configuration_version)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_runs (
        id INT NOT NULL AUTO_INCREMENT,
        execution_id VARCHAR(36) NOT NULL,
        username VARCHAR(255) NOT NULL,
        client_ip VARCHAR(45) NULL,
        command VARCHAR(255) NOT NULL,
        source VARCHAR(32) NOT NULL,
        started_at DATETIME NOT NULL,
        completed_at DATETIME NULL,
        status VARCHAR(32) NOT NULL,
        aws_account_id VARCHAR(32) NULL,
        aws_identity VARCHAR(512) NULL,
        aws_region VARCHAR(32) NULL,
        resources_discovered INT NOT NULL DEFAULT 0,
        resources_analyzed INT NOT NULL DEFAULT 0,
        resources_skipped INT NOT NULL DEFAULT 0,
        resources_collecting_data INT NOT NULL DEFAULT 0,
        recommendations_created INT NOT NULL DEFAULT 0,
        error_message TEXT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uq_execution_run_execution_id (execution_id),
        INDEX ix_execution_runs_username (username),
        INDEX ix_execution_runs_client_ip (client_ip),
        INDEX ix_execution_runs_source (source),
        INDEX ix_execution_runs_started_at (started_at),
        INDEX ix_execution_runs_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_runs (
        id INT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(32) NOT NULL,
        region VARCHAR(32) NOT NULL,
        execution_run_id INT NOT NULL,
        started_at DATETIME NOT NULL,
        completed_at DATETIME NULL,
        status VARCHAR(32) NOT NULL,
        recommendation VARCHAR(64) NOT NULL,
        evidence_start DATETIME NULL,
        evidence_end DATETIME NULL,
        next_eligible_analysis_at DATETIME NULL,
        analysis_version VARCHAR(64) NOT NULL,
        error_message TEXT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        INDEX ix_analysis_runs_instance_id (instance_id),
        INDEX ix_analysis_runs_region (region),
        INDEX ix_analysis_runs_execution_run_id (execution_run_id),
        INDEX ix_analysis_runs_status (status),
        INDEX ix_analysis_runs_next_eligible_analysis_at (next_eligible_analysis_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendations (
        id INT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(32) NOT NULL,
        region VARCHAR(32) NOT NULL,
        analysis_id INT NOT NULL,
        recommendation VARCHAR(64) NOT NULL,
        recommended_instance VARCHAR(64) NULL,
        created_at DATETIME NOT NULL,
        status VARCHAR(32) NOT NULL,
        actioned_at DATETIME NULL,
        expired_at DATETIME NULL,
        next_eligible_analysis_at DATETIME NULL,
        PRIMARY KEY (id),
        INDEX ix_recommendations_instance_id (instance_id),
        INDEX ix_recommendations_region (region),
        INDEX ix_recommendations_analysis_id (analysis_id),
        INDEX ix_recommendations_created_at (created_at),
        INDEX ix_recommendations_status (status),
        INDEX ix_recommendations_next_eligible_analysis_at (next_eligible_analysis_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_snapshots (
        id INT NOT NULL AUTO_INCREMENT,
        instance_id VARCHAR(32) NOT NULL,
        region VARCHAR(32) NOT NULL,
        analysis_id INT NOT NULL,
        configuration_version VARCHAR(128) NOT NULL,
        instance_type VARCHAR(64) NOT NULL,
        instance_state VARCHAR(32) NOT NULL,
        recommendation VARCHAR(64) NOT NULL,
        recommended_instance VARCHAR(64) NULL,
        cpu_average DOUBLE NULL,
        cpu_minimum DOUBLE NULL,
        cpu_maximum DOUBLE NULL,
        memory_average DOUBLE NULL,
        memory_minimum DOUBLE NULL,
        memory_maximum DOUBLE NULL,
        cpu_datapoint_count INT NOT NULL DEFAULT 0,
        memory_datapoint_count INT NOT NULL DEFAULT 0,
        evidence_start DATETIME NULL,
        evidence_end DATETIME NULL,
        reason TEXT NOT NULL,
        concerns TEXT NULL,
        missing_evidence TEXT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        INDEX ix_recommendation_snapshots_instance_id (instance_id),
        INDEX ix_recommendation_snapshots_region (region),
        INDEX ix_recommendation_snapshots_analysis_id (analysis_id),
        INDEX ix_recommendation_snapshots_configuration_version (configuration_version),
        INDEX ix_recommendation_snapshots_recommendation (recommendation),
        INDEX ix_recommendation_snapshots_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
)


def initialize_database() -> None:
    """Create missing MySQL tables without altering existing tables/data."""
    connection = create_database_connection()
    try:
        with connection.cursor() as cursor:
            for statement in _SCHEMA_STATEMENTS:
                cursor.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
