"""Unit tests for the unified Finding model."""

from typing import Any

import pytest
from pydantic import ValidationError

from scanners.models import Finding


def _valid_payload() -> dict[str, Any]:
    return {
        "tool": "bandit",
        "rule_id": "B105",
        "severity": "high",
        "file_path": "src/auth.py",
        "line_start": 42,
        "line_end": 42,
        "message": "Possible hardcoded password",
        "remediation_hint": "Move the secret into an environment variable.",
        "raw": {
            "test_id": "B105",
            "issue_severity": "MEDIUM",
            "issue_confidence": "HIGH",
        },
    }


class TestValidConstruction:
    def test_construct_with_all_fields(self) -> None:
        finding = Finding(**_valid_payload())
        assert finding.tool == "bandit"
        assert finding.rule_id == "B105"
        assert finding.severity == "high"
        assert finding.file_path == "src/auth.py"
        assert finding.line_start == 42
        assert finding.line_end == 42
        assert finding.message == "Possible hardcoded password"
        assert finding.remediation_hint is not None
        assert finding.raw["test_id"] == "B105"

    def test_remediation_hint_defaults_to_none(self) -> None:
        payload = _valid_payload()
        del payload["remediation_hint"]
        finding = Finding(**payload)
        assert finding.remediation_hint is None

    def test_model_is_frozen(self) -> None:
        finding = Finding(**_valid_payload())
        with pytest.raises(ValidationError):
            finding.severity = "low"  # type: ignore[misc]


class TestSeverityValidation:
    @pytest.mark.parametrize(
        "severity", ["critical", "high", "medium", "low", "info"]
    )
    def test_accepts_each_valid_severity(self, severity: str) -> None:
        payload = _valid_payload()
        payload["severity"] = severity
        finding = Finding(**payload)
        assert finding.severity == severity

    @pytest.mark.parametrize(
        "severity", ["HIGH", "warning", "fatal", "", "none", "unknown"]
    )
    def test_rejects_invalid_severity(self, severity: str) -> None:
        payload = _valid_payload()
        payload["severity"] = severity
        with pytest.raises(ValidationError):
            Finding(**payload)

    def test_rejects_invalid_tool(self) -> None:
        payload = _valid_payload()
        payload["tool"] = "snyk"
        with pytest.raises(ValidationError):
            Finding(**payload)


class TestSerializationRoundTrip:
    def test_round_trip_via_model_dump_json(self) -> None:
        original = Finding(**_valid_payload())
        serialized = original.model_dump_json()
        restored = Finding.model_validate_json(serialized)
        assert restored == original

    def test_round_trip_preserves_nested_raw(self) -> None:
        payload = _valid_payload()
        payload["raw"] = {"nested": {"k": [1, 2, 3]}, "n": 42, "s": "x"}
        original = Finding(**payload)
        restored = Finding.model_validate_json(original.model_dump_json())
        assert restored.raw == payload["raw"]

    def test_round_trip_preserves_none_remediation_hint(self) -> None:
        payload = _valid_payload()
        payload["remediation_hint"] = None
        original = Finding(**payload)
        restored = Finding.model_validate_json(original.model_dump_json())
        assert restored.remediation_hint is None


class TestClassmethodStubs:
    def test_from_semgrep_is_a_stub(self) -> None:
        with pytest.raises(NotImplementedError):
            Finding.from_semgrep({})
