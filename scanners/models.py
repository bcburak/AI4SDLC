"""Unified Finding model for SAST scanner outputs."""

import os
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict

Tool = Literal["bandit", "trivy", "semgrep"]
Severity = Literal["critical", "high", "medium", "low", "info"]


# Bandit reports both severity and confidence. We collapse the pair into our
# single Severity enum using the mapping documented in
# .claude/skills/sast-adapter/SKILL.md. Unlisted combinations fall back to "low".
_BANDIT_SEVERITY_TABLE: dict[tuple[str, str], Severity] = {
    ("HIGH", "HIGH"): "high",
    ("HIGH", "MEDIUM"): "medium",
    ("MEDIUM", "HIGH"): "medium",
    ("LOW", "LOW"): "info",
}


def _bandit_severity(issue_severity: str, issue_confidence: str) -> Severity:
    return _BANDIT_SEVERITY_TABLE.get(
        (issue_severity.upper(), issue_confidence.upper()), "low"
    )


# Trivy uses CRITICAL/HIGH/MEDIUM/LOW/UNKNOWN. Anything we don't recognize
# (including UNKNOWN) falls back to "info" per the skill convention.
_TRIVY_SEVERITY_MAP: dict[str, Severity] = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "UNKNOWN": "info",
}


def _trivy_severity(value: str) -> Severity:
    return _TRIVY_SEVERITY_MAP.get(value.upper(), "info")


def _to_relative_posix(filename: str, repo_root: Path) -> str:
    try:
        rel = os.path.relpath(filename, repo_root)
    except ValueError:
        rel = filename
    return Path(rel).as_posix()


class Finding(BaseModel):
    """A normalized SAST finding produced by one of the supported scanners.

    All adapters under ``scanners/`` emit instances of this model so downstream
    agent nodes don't need to know which tool produced a given issue.
    """

    model_config = ConfigDict(frozen=True)

    tool: Tool
    rule_id: str
    severity: Severity
    file_path: str
    line_start: int
    line_end: int
    message: str
    remediation_hint: str | None = None
    raw: dict[str, Any]

    @classmethod
    def from_bandit(
        cls,
        raw_issue: dict[str, Any],
        *,
        repo_root: Path | str | None = None,
    ) -> Self:
        """Build a Finding from a single Bandit JSON issue.

        The severity is derived from Bandit's ``issue_severity`` and
        ``issue_confidence`` fields. See the mapping table at the top of this
        module for the full collapse rules.

        Args:
            raw_issue: One entry from Bandit's ``results`` array.
            repo_root: Repository root used to normalize ``filename`` into a
                path relative to the project root. Defaults to the current
                working directory.

        Returns:
            A populated Finding with ``tool="bandit"``.
        """
        root = Path(repo_root) if repo_root is not None else Path.cwd()
        line_range = raw_issue.get("line_range") or [raw_issue["line_number"]]
        return cls(
            tool="bandit",
            rule_id=raw_issue["test_id"],
            severity=_bandit_severity(
                raw_issue["issue_severity"], raw_issue["issue_confidence"]
            ),
            file_path=_to_relative_posix(raw_issue["filename"], root),
            line_start=line_range[0],
            line_end=line_range[-1],
            message=raw_issue["issue_text"],
            remediation_hint=raw_issue.get("more_info"),
            raw=raw_issue,
        )

    @classmethod
    def from_trivy(
        cls,
        raw_issue: dict[str, Any],
        *,
        target: str = "",
        repo_root: Path | str | None = None,
    ) -> Self:
        """Build a Finding from a single Trivy vulnerability entry.

        Trivy reports per-dependency vulnerabilities without precise line
        numbers, so ``line_start`` and ``line_end`` both default to ``1``
        (top of manifest). The unique rule_id is ``VulnerabilityID``
        (e.g., ``CVE-2018-18074``).

        Args:
            raw_issue: One vulnerability from Trivy's
                ``Results[].Vulnerabilities`` array.
            target: The ``Target`` field of the enclosing Result (the manifest
                file path Trivy scanned).
            repo_root: Repository root used to normalize ``target`` into a
                project-relative path. Defaults to the current working
                directory.

        Returns:
            A populated Finding with ``tool="trivy"``.
        """
        root = Path(repo_root) if repo_root is not None else Path.cwd()
        pkg = raw_issue.get("PkgName", "")
        installed = raw_issue.get("InstalledVersion", "")
        fixed = raw_issue.get("FixedVersion")
        title = raw_issue.get("Title") or raw_issue.get("Description", "")
        message = f"{pkg} {installed}: {title}" if pkg else title
        remediation = (
            f"Upgrade {pkg} to {fixed} or later." if pkg and fixed else None
        )
        return cls(
            tool="trivy",
            rule_id=raw_issue["VulnerabilityID"],
            severity=_trivy_severity(raw_issue.get("Severity", "UNKNOWN")),
            file_path=_to_relative_posix(target, root) if target else "",
            line_start=1,
            line_end=1,
            message=message,
            remediation_hint=remediation,
            raw=raw_issue,
        )

    @classmethod
    def from_semgrep(cls, raw_issue: dict[str, Any]) -> Self:
        """Build a Finding from a single Semgrep result.

        Args:
            raw_issue: One entry from Semgrep's ``results`` array.

        Returns:
            A populated Finding with ``tool="semgrep"``.
        """
        raise NotImplementedError("Implemented when the Semgrep adapter lands")
