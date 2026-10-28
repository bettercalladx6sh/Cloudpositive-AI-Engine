
from __future__ import annotations

import pytest

from app.config import (
    ANALYSIS_HOURS,
    REQUIRED_EVIDENCE,
    _parse_evidence_requirement,
    load_config,
)


def test_default_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default configuration should follow config.py defaults."""

    monkeypatch.delenv("ANALYSIS_HOURS", raising=False)
    monkeypatch.delenv("ANALYSIS_DAYS", raising=False)
    monkeypatch.delenv("REQUIRED_EVIDENCE", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    config = load_config()

    assert config.analysis.analysis_hours == ANALYSIS_HOURS

    assert (
        config.analysis.required_evidence_hours
        == _parse_evidence_requirement(REQUIRED_EVIDENCE)
    )

    assert config.aws.default_region == "us-east-1"
    assert config.openai.model == "gpt-5.6-luna"
    assert config.logging.level == "INFO"
    assert config.analysis.enabled_services == ("ec2",)


def test_custom_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment variables should override config.py defaults."""

    monkeypatch.setenv("ANALYSIS_HOURS", "168")
    monkeypatch.setenv("REQUIRED_EVIDENCE", "7d")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    config = load_config()

    assert config.analysis.analysis_hours == 168.0
    assert config.analysis.required_evidence_hours == 168.0
    assert config.aws.default_region == "ap-south-1"
    assert config.openai.model == "test-model"
    assert config.logging.level == "DEBUG"


def test_evidence_requirement_hours() -> None:
    """Evidence parser should convert supported units to hours."""

    assert _parse_evidence_requirement("1h") == 1.0
    assert _parse_evidence_requirement("24h") == 24.0
    assert _parse_evidence_requirement("1d") == 24.0
    assert _parse_evidence_requirement("7d") == 168.0
    assert _parse_evidence_requirement("30d") == 720.0
    assert _parse_evidence_requirement("90d") == 2160.0


def test_evidence_requirement_decimal_days() -> None:
    """Decimal day values should be supported."""

    assert _parse_evidence_requirement("1.5d") == 36.0


def test_invalid_evidence_requirement() -> None:
    """Invalid evidence formats should raise ConfigurationError."""

    from app.config import ConfigurationError

    with pytest.raises(ConfigurationError):
        _parse_evidence_requirement("abc")

    with pytest.raises(ConfigurationError):
        _parse_evidence_requirement("10m")

    with pytest.raises(ConfigurationError):
        _parse_evidence_requirement("0h")


def test_analysis_hours_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Analysis hours must remain within the configured range."""

    from app.config import ConfigurationError

    monkeypatch.setenv("ANALYSIS_HOURS", "2161")

    with pytest.raises(ConfigurationError):
        load_config()


def test_evidence_requirement_maximum() -> None:
    """Evidence requirement must not exceed 90 days."""

    from app.config import ConfigurationError

    with pytest.raises(ConfigurationError):
        _parse_evidence_requirement("91d")