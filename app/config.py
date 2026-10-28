from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Final

from dotenv import load_dotenv


load_dotenv()


# ---------------------------------------------------------------------------
# Supported ranges
# ---------------------------------------------------------------------------

MIN_ANALYSIS_HOURS: Final[float] = 1.0
MAX_ANALYSIS_HOURS: Final[float] = 2160.0  # 90 days

MIN_EVIDENCE_HOURS: Final[float] = 0.25
MAX_EVIDENCE_DAYS: Final[int] = 90

MIN_PRODUCTION_EVIDENCE_DAYS: Final[int] = 30

MIN_COOLDOWN_DAYS: Final[int] = 0
MAX_COOLDOWN_DAYS: Final[int] = 365

ANALYSIS_VERSION = "ec2-v1"


# ---------------------------------------------------------------------------
# Development defaults
# ---------------------------------------------------------------------------
#
# These defaults intentionally preserve the current development/testing
# configuration.
#
# Production can use, for example:
#
#     ANALYSIS_DAYS=30
#     REQUIRED_EVIDENCE=30d
#
# The business logic must never hardcode those values.
# ---------------------------------------------------------------------------
ANALYSIS_HOURS: Final[float] = 1.0
REQUIRED_EVIDENCE: Final[str] = "1h"

RECOMMENDATION_COOLDOWN_DAYS: Final[int] = 30
ANALYSIS_COOLDOWN_DAYS: Final[int] = 30

MONTHLY_HOURS: Final[float] = 730.0

CPU_SAFETY_FACTOR: Final[float] = 1.25
MEMORY_SAFETY_FACTOR: Final[float] = 1.25


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""


# ---------------------------------------------------------------------------
# Evidence parsing
# ---------------------------------------------------------------------------


def _parse_evidence_requirement(value: str) -> float:
    """
    Convert an evidence requirement into hours.

    Supported formats:

        1h
        24h
        1d
        7d
        30d
        90d
        1.5d
    """

    normalized = value.strip().lower()

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)(h|d)",
        normalized,
    )

    if not match:
        raise ConfigurationError(
            "REQUIRED_EVIDENCE must use hours or days, "
            "for example '1h', '24h', or '30d'."
        )

    amount = float(match.group(1))
    unit = match.group(2)

    if amount <= 0:
        raise ConfigurationError(
            "REQUIRED_EVIDENCE must be greater than zero."
        )

    if unit == "h":
        hours = amount
    else:
        hours = amount * 24.0

    if hours < MIN_EVIDENCE_HOURS:
        raise ConfigurationError(
            f"REQUIRED_EVIDENCE must be at least "
            f"{MIN_EVIDENCE_HOURS} hours."
        )

    if hours > MAX_EVIDENCE_DAYS * 24:
        raise ConfigurationError(
            f"REQUIRED_EVIDENCE cannot exceed "
            f"{MAX_EVIDENCE_DAYS} days."
        )

    return hours


# ---------------------------------------------------------------------------
# Integer configuration parsing
# ---------------------------------------------------------------------------


def _parse_integer(
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Read and validate an integer environment variable."""

    raw_value = os.getenv(
        name,
        str(default),
    ).strip()

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be an integer."
        ) from exc

    if not minimum <= value <= maximum:
        raise ConfigurationError(
            f"{name} must be between "
            f"{minimum} and {maximum}."
        )

    return value


# ---------------------------------------------------------------------------
# Float configuration parsing
# ---------------------------------------------------------------------------


def _parse_positive_float(
    *,
    name: str,
    default: float,
    minimum: float,
) -> float:
    """Read and validate a positive floating-point environment variable."""

    raw_value = os.getenv(
        name,
        str(default),
    ).strip()

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be a number."
        ) from exc

    if value < minimum:
        raise ConfigurationError(
            f"{name} must be at least {minimum}."
        )

    return value


# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AwsConfig:
    default_region: str


@dataclass(frozen=True)
class AnalysisConfig:
    analysis_hours: float
    required_evidence_hours: float
    enabled_services: tuple[str, ...]
    recommendation_cooldown_days: int
    analysis_cooldown_days: int
    monthly_hours: float
    cpu_safety_factor: float
    memory_safety_factor: float
    analysis_version: str

    
@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str | None
    model: str


@dataclass(frozen=True)
class DatabaseConfig:
    url: str


@dataclass(frozen=True)
class LoggingConfig:
    level: str


@dataclass(frozen=True)
class AppConfig:
    aws: AwsConfig
    analysis: AnalysisConfig
    openai: OpenAIConfig
    database: DatabaseConfig
    logging: LoggingConfig


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------


def load_config() -> AppConfig:
    """
    Load and validate application configuration.

    Environment variables override the application defaults.

    AWS credentials are intentionally not loaded here.
    boto3 handles AWS credential resolution separately.
    """

    # -----------------------------------------------------------------------
    # Analysis window
    # -----------------------------------------------------------------------

    analysis_hours = _parse_positive_float(
        name="ANALYSIS_HOURS",
        default=ANALYSIS_HOURS,
        minimum=MIN_ANALYSIS_HOURS,
    )

    if analysis_hours > MAX_ANALYSIS_HOURS:
        raise ConfigurationError(
            f"ANALYSIS_HOURS cannot exceed "
            f"{MAX_ANALYSIS_HOURS} hours (90 days)."
        )

    # -----------------------------------------------------------------------
    # Evidence requirement
    # -----------------------------------------------------------------------

    required_evidence = os.getenv(
        "REQUIRED_EVIDENCE",
        REQUIRED_EVIDENCE,
    ).strip()

    required_evidence_hours = _parse_evidence_requirement(
        required_evidence
    )

    # -----------------------------------------------------------------------
    # Recommendation lifecycle
    # -----------------------------------------------------------------------

    recommendation_cooldown_days = _parse_integer(
        name="RECOMMENDATION_COOLDOWN_DAYS",
        default=RECOMMENDATION_COOLDOWN_DAYS,
        minimum=MIN_COOLDOWN_DAYS,
        maximum=MAX_COOLDOWN_DAYS,
    )

    analysis_cooldown_days = _parse_integer(
        name="ANALYSIS_COOLDOWN_DAYS",
        default=ANALYSIS_COOLDOWN_DAYS,
        minimum=MIN_COOLDOWN_DAYS,
        maximum=MAX_COOLDOWN_DAYS,
    )

    # -----------------------------------------------------------------------
    # Pricing
    # -----------------------------------------------------------------------

    monthly_hours = _parse_positive_float(
        name="MONTHLY_HOURS",
        default=MONTHLY_HOURS,
        minimum=1.0,
    )

    # -----------------------------------------------------------------------
    # Capacity safety
    # -----------------------------------------------------------------------

    cpu_safety_factor = _parse_positive_float(
        name="CPU_SAFETY_FACTOR",
        default=CPU_SAFETY_FACTOR,
        minimum=1.0,
    )

    memory_safety_factor = _parse_positive_float(
        name="MEMORY_SAFETY_FACTOR",
        default=MEMORY_SAFETY_FACTOR,
        minimum=1.0,
    )

    # -----------------------------------------------------------------------
    # AWS
    # -----------------------------------------------------------------------

    default_region = os.getenv(
        "AWS_DEFAULT_REGION",
        "us-east-1",
    ).strip()

    if not default_region:
        raise ConfigurationError(
            "AWS_DEFAULT_REGION cannot be empty."
        )

    # -----------------------------------------------------------------------
    # OpenAI
    # -----------------------------------------------------------------------

    openai_api_key = os.getenv(
        "OPENAI_API_KEY"
    )

    openai_model = os.getenv(
        "OPENAI_MODEL",
        "gpt-5.6-luna",
    ).strip()

    if not openai_model:
        raise ConfigurationError(
            "OPENAI_MODEL cannot be empty."
        )

    # -----------------------------------------------------------------------
    # MySQL
    # -----------------------------------------------------------------------

    database_url = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://optimizer:"
        "optimizer_dev_password@127.0.0.1:3306/"
        "cost_optimizer",
    ).strip()

    if not database_url:
        raise ConfigurationError(
            "DATABASE_URL cannot be empty."
        )

    if not database_url.startswith(
        "mysql+pymysql://"
    ):
        raise ConfigurationError(
            "DATABASE_URL must use MySQL with PyMySQL "
            "(mysql+pymysql://)."
        )

    # -----------------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------------

    log_level = os.getenv(
        "LOG_LEVEL",
        "INFO",
    ).strip().upper()

    if not log_level:
        raise ConfigurationError(
            "LOG_LEVEL cannot be empty."
        )

    # -----------------------------------------------------------------------
    # Final configuration
    # -----------------------------------------------------------------------

    return AppConfig(
        aws=AwsConfig(
            default_region=default_region,
        ),
        analysis=AnalysisConfig(
            analysis_hours=analysis_hours,
            required_evidence_hours=required_evidence_hours,
            enabled_services=("ec2",),
            recommendation_cooldown_days=(
                recommendation_cooldown_days
            ),
            analysis_cooldown_days=(
                analysis_cooldown_days
            ),
            monthly_hours=monthly_hours,
            cpu_safety_factor=cpu_safety_factor,
            memory_safety_factor=memory_safety_factor,
            analysis_version=ANALYSIS_VERSION,
        ),
        openai=OpenAIConfig(
            api_key=openai_api_key,
            model=openai_model,
        ),
        database=DatabaseConfig(
            url=database_url,
        ),
        logging=LoggingConfig(
            level=log_level,
        ),
    )