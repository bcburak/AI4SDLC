"""Unit and integration tests for the Bandit adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scanners.bandit_adapter import run_bandit
from scanners.models import Finding, _bandit_severity

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "sample_vulnerable.py"
).resolve()
REPO_ROOT = Path(__file__).resolve().parents[1]


def _bandit_issue(
    *,
    test_id: str,
    severity: str,
    confidence: str,
    line_number: int,
    text: str,
    filename: Path = FIXTURE_PATH,
) -> dict[str, Any]:
    return {
        "code": "",
        "col_offset": 0,
        "filename": str(filename),
        "issue_confidence": confidence,
        "issue_severity": severity,
        "issue_text": text,
        "line_number": line_number,
        "line_range": [line_number],
        "more_info": f"https://bandit.readthedocs.io/en/latest/plugins/{test_id.lower()}.html",
        "test_id": test_id,
        "test_name": "stub",
    }


def _patch_subprocess_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int,
    stdout: str,
    stderr: str = "",
) -> list[list[str]]:
    """Patch subprocess.run to return a canned result and record the cmd."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


class TestRunBanditUnit:
    def test_parses_two_findings_with_expected_rule_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {
            "results": [
                _bandit_issue(
                    test_id="B101",
                    severity="LOW",
                    confidence="HIGH",
                    line_number=12,
                    text="Use of assert detected.",
                ),
                _bandit_issue(
                    test_id="B105",
                    severity="LOW",
                    confidence="MEDIUM",
                    line_number=8,
                    text="Possible hardcoded password: 'hunter2'",
                ),
            ],
            "errors": [],
        }
        _patch_subprocess_run(monkeypatch, returncode=1, stdout=json.dumps(payload))

        findings = run_bandit([str(FIXTURE_PATH)], repo_root=REPO_ROOT)

        assert len(findings) == 2
        assert {f.rule_id for f in findings} == {"B101", "B105"}
        assert all(f.tool == "bandit" for f in findings)
        assert all(
            f.file_path == "tests/fixtures/sample_vulnerable.py" for f in findings
        )

    def test_preserves_raw_issue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        issue = _bandit_issue(
            test_id="B101",
            severity="LOW",
            confidence="HIGH",
            line_number=3,
            text="assert used",
        )
        _patch_subprocess_run(
            monkeypatch, returncode=1, stdout=json.dumps({"results": [issue]})
        )

        findings = run_bandit([str(FIXTURE_PATH)], repo_root=REPO_ROOT)

        assert findings[0].raw == issue
        assert findings[0].remediation_hint == issue["more_info"]

    def test_empty_paths_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_subprocess_run(monkeypatch, returncode=0, stdout="")
        assert run_bandit([]) == []
        assert calls == []

    def test_empty_results_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_subprocess_run(
            monkeypatch, returncode=0, stdout=json.dumps({"results": []})
        )
        assert run_bandit([str(FIXTURE_PATH)], repo_root=REPO_ROOT) == []

    def test_zero_exit_with_findings_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Some bandit versions still return 0 when only LOW issues are present;
        # the adapter should not depend on the exit code to determine success.
        _patch_subprocess_run(
            monkeypatch,
            returncode=0,
            stdout=json.dumps(
                {
                    "results": [
                        _bandit_issue(
                            test_id="B101",
                            severity="LOW",
                            confidence="HIGH",
                            line_number=1,
                            text="assert",
                        )
                    ]
                }
            ),
        )

        findings = run_bandit([str(FIXTURE_PATH)], repo_root=REPO_ROOT)
        assert len(findings) == 1

    def test_unexpected_exit_code_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_subprocess_run(
            monkeypatch, returncode=2, stdout="", stderr="usage error"
        )
        with pytest.raises(RuntimeError, match="exited with code 2"):
            run_bandit([str(FIXTURE_PATH)], repo_root=REPO_ROOT)

    def test_invokes_bandit_recursively_with_json_format(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_subprocess_run(
            monkeypatch, returncode=0, stdout=json.dumps({"results": []})
        )

        run_bandit(["a.py", "b.py"], repo_root=REPO_ROOT)

        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[0] == "bandit"
        assert "-r" in cmd
        assert cmd[cmd.index("-f") + 1] == "json"
        assert cmd[-2:] == ["a.py", "b.py"]


class TestBanditSeverityMapping:
    @pytest.mark.parametrize(
        ("severity", "confidence", "expected"),
        [
            ("HIGH", "HIGH", "high"),
            ("HIGH", "MEDIUM", "medium"),
            ("MEDIUM", "HIGH", "medium"),
            ("LOW", "LOW", "info"),
            ("LOW", "HIGH", "low"),
            ("HIGH", "LOW", "low"),
            ("MEDIUM", "MEDIUM", "low"),
            ("MEDIUM", "LOW", "low"),
        ],
    )
    def test_severity_table(
        self, severity: str, confidence: str, expected: str
    ) -> None:
        assert _bandit_severity(severity, confidence) == expected


class TestFromBandit:
    def test_maps_required_fields(self) -> None:
        issue = _bandit_issue(
            test_id="B105",
            severity="LOW",
            confidence="MEDIUM",
            line_number=8,
            text="Possible hardcoded password",
        )

        finding = Finding.from_bandit(issue, repo_root=REPO_ROOT)

        assert finding.tool == "bandit"
        assert finding.rule_id == "B105"
        assert finding.severity == "low"
        assert finding.file_path == "tests/fixtures/sample_vulnerable.py"
        assert finding.line_start == 8
        assert finding.line_end == 8
        assert finding.message == "Possible hardcoded password"
        assert finding.remediation_hint is not None

    def test_uses_full_line_range_when_provided(self) -> None:
        issue = _bandit_issue(
            test_id="B608",
            severity="MEDIUM",
            confidence="MEDIUM",
            line_number=20,
            text="SQL injection",
        )
        issue["line_range"] = [20, 21, 22]

        finding = Finding.from_bandit(issue, repo_root=REPO_ROOT)

        assert finding.line_start == 20
        assert finding.line_end == 22


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("bandit") is None, reason="bandit binary not installed"
)
def test_run_bandit_against_real_fixture() -> None:
    findings = run_bandit([str(FIXTURE_PATH)], repo_root=REPO_ROOT)

    rule_ids = {f.rule_id for f in findings}
    assert "B101" in rule_ids
    assert "B105" in rule_ids
    assert all(f.tool == "bandit" for f in findings)
    assert all(
        f.file_path == "tests/fixtures/sample_vulnerable.py" for f in findings
    )
