"""Unit and integration tests for the Trivy adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scanners.models import Finding, _trivy_severity
from scanners.trivy_adapter import run_trivy

FIXTURE_DIR = (Path(__file__).parent / "fixtures" / "trivy_pip").resolve()
FIXTURE_MANIFEST = FIXTURE_DIR / "requirements.txt"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _vuln(
    *,
    vuln_id: str = "CVE-2018-18074",
    pkg_name: str = "requests",
    installed: str = "2.19.0",
    fixed: str | None = "2.20.0",
    severity: str = "MEDIUM",
    title: str = "Redirect from HTTPS to HTTP does not remove Authorization header",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "VulnerabilityID": vuln_id,
        "PkgName": pkg_name,
        "InstalledVersion": installed,
        "PrimaryURL": f"https://avd.aquasec.com/nvd/{vuln_id.lower()}",
        "Title": title,
        "Description": "long description",
        "Severity": severity,
    }
    if fixed is not None:
        entry["FixedVersion"] = fixed
    return entry


def _trivy_payload(
    vulnerabilities: list[dict[str, Any]],
    *,
    target: str = "tests/fixtures/trivy_pip/requirements.txt",
) -> dict[str, Any]:
    return {
        "SchemaVersion": 2,
        "ArtifactName": "tests/fixtures/trivy_pip",
        "ArtifactType": "filesystem",
        "Results": [
            {
                "Target": target,
                "Class": "lang-pkgs",
                "Type": "pip",
                "Vulnerabilities": vulnerabilities,
            }
        ],
    }


def _patch_subprocess_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int,
    stdout: str,
    stderr: str = "",
) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


class TestRunTrivyUnit:
    def test_parses_single_vulnerability(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _trivy_payload([_vuln()])
        _patch_subprocess_run(monkeypatch, returncode=0, stdout=json.dumps(payload))

        findings = run_trivy([str(FIXTURE_DIR)], repo_root=REPO_ROOT)

        assert len(findings) == 1
        f = findings[0]
        assert f.tool == "trivy"
        assert f.rule_id == "CVE-2018-18074"
        assert f.severity == "medium"
        assert f.file_path == "tests/fixtures/trivy_pip/requirements.txt"
        assert "requests" in f.message
        assert f.remediation_hint == "Upgrade requests to 2.20.0 or later."
        assert f.raw["PkgName"] == "requests"

    def test_aggregates_multiple_results_and_vulnerabilities(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _trivy_payload(
            [
                _vuln(vuln_id="CVE-2018-18074", severity="MEDIUM"),
                _vuln(
                    vuln_id="CVE-2023-32681",
                    severity="HIGH",
                    fixed="2.31.0",
                    title="Proxy-Authorization header leak",
                ),
            ]
        )
        _patch_subprocess_run(monkeypatch, returncode=0, stdout=json.dumps(payload))

        findings = run_trivy([str(FIXTURE_DIR)], repo_root=REPO_ROOT)

        assert {f.rule_id for f in findings} == {"CVE-2018-18074", "CVE-2023-32681"}
        assert {f.severity for f in findings} == {"medium", "high"}

    def test_missing_fixed_version_yields_no_remediation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _trivy_payload([_vuln(fixed=None)])
        _patch_subprocess_run(monkeypatch, returncode=0, stdout=json.dumps(payload))

        findings = run_trivy([str(FIXTURE_DIR)], repo_root=REPO_ROOT)

        assert findings[0].remediation_hint is None

    def test_empty_paths_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_subprocess_run(monkeypatch, returncode=0, stdout="")
        assert run_trivy([]) == []
        assert calls == []

    def test_results_without_vulnerabilities_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {
            "Results": [
                {
                    "Target": "x",
                    "Class": "lang-pkgs",
                    "Type": "pip",
                    "Vulnerabilities": None,
                }
            ]
        }
        _patch_subprocess_run(monkeypatch, returncode=0, stdout=json.dumps(payload))
        assert run_trivy([str(FIXTURE_DIR)], repo_root=REPO_ROOT) == []

    def test_missing_results_key_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_subprocess_run(
            monkeypatch, returncode=0, stdout=json.dumps({"SchemaVersion": 2})
        )
        assert run_trivy([str(FIXTURE_DIR)], repo_root=REPO_ROOT) == []

    def test_unexpected_exit_code_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_subprocess_run(
            monkeypatch, returncode=2, stdout="", stderr="db update failed"
        )
        with pytest.raises(RuntimeError, match="exited with code 2"):
            run_trivy([str(FIXTURE_DIR)], repo_root=REPO_ROOT)

    def test_invokes_trivy_fs_with_json_and_quiet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_subprocess_run(
            monkeypatch, returncode=0, stdout=json.dumps({"Results": []})
        )

        run_trivy([str(FIXTURE_DIR)], repo_root=REPO_ROOT)

        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[:2] == ["trivy", "fs"]
        assert cmd[cmd.index("--format") + 1] == "json"
        assert "--quiet" in cmd
        assert cmd[-1] == str(FIXTURE_DIR)


class TestTrivySeverityMapping:
    @pytest.mark.parametrize(
        ("input_severity", "expected"),
        [
            ("CRITICAL", "critical"),
            ("HIGH", "high"),
            ("MEDIUM", "medium"),
            ("LOW", "low"),
            ("UNKNOWN", "info"),
            ("critical", "critical"),
            ("garbage", "info"),
            ("", "info"),
        ],
    )
    def test_severity_table(self, input_severity: str, expected: str) -> None:
        assert _trivy_severity(input_severity) == expected


class TestFromTrivy:
    def test_maps_required_fields(self) -> None:
        finding = Finding.from_trivy(
            _vuln(),
            target="tests/fixtures/trivy_pip/requirements.txt",
            repo_root=REPO_ROOT,
        )

        assert finding.tool == "trivy"
        assert finding.rule_id == "CVE-2018-18074"
        assert finding.severity == "medium"
        assert finding.file_path == "tests/fixtures/trivy_pip/requirements.txt"
        assert finding.line_start == 1
        assert finding.line_end == 1
        assert finding.remediation_hint == "Upgrade requests to 2.20.0 or later."

    def test_unknown_severity_maps_to_info(self) -> None:
        finding = Finding.from_trivy(
            _vuln(severity="UNKNOWN"),
            target="x.txt",
            repo_root=REPO_ROOT,
        )
        assert finding.severity == "info"

    def test_target_empty_yields_empty_file_path(self) -> None:
        finding = Finding.from_trivy(_vuln(), repo_root=REPO_ROOT)
        assert finding.file_path == ""


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("trivy") is None, reason="trivy binary not installed"
)
def test_run_trivy_against_real_fixture() -> None:
    findings = run_trivy([str(FIXTURE_DIR)], repo_root=REPO_ROOT)

    assert len(findings) >= 1
    assert any(f.raw.get("PkgName") == "requests" for f in findings)
    assert all(f.tool == "trivy" for f in findings)
    assert all(f.file_path.endswith("requirements.txt") for f in findings)
