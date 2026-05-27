"""Trivy SAST scanner adapter (filesystem mode)."""

import json
import subprocess
from pathlib import Path

import structlog

from scanners.models import Finding

logger = structlog.get_logger(__name__)

# Trivy returns 0 by default whether or not vulnerabilities are found.
# With ``--exit-code 1`` it returns 1 on findings; we keep that variant in the
# accepted set so callers who opt into stricter exit codes still work.
_OK_EXIT_CODES = frozenset({0, 1})


def run_trivy(
    paths: list[str],
    *,
    repo_root: Path | None = None,
) -> list[Finding]:
    """Run ``trivy fs`` on the given paths and return normalized findings.

    Args:
        paths: Files or directories to scan. Empty paths return an empty list
            without invoking Trivy.
        repo_root: Repository root used to normalize Trivy's ``Target`` paths.
            Defaults to the current working directory.

    Returns:
        One Finding per vulnerability across all scanned targets. Returns an
        empty list if Trivy reports nothing.

    Raises:
        RuntimeError: If Trivy exits with a code outside the documented "ok"
            set (anything other than 0 or 1).
    """
    if not paths:
        return []

    root = (repo_root or Path.cwd()).resolve()
    cmd = ["trivy", "fs", "--format", "json", "--quiet", *paths]
    logger.info("running_trivy", cmd=cmd, cwd=str(root))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )

    if proc.returncode not in _OK_EXIT_CODES:
        logger.error(
            "trivy_failed",
            returncode=proc.returncode,
            stderr=proc.stderr.strip(),
        )
        raise RuntimeError(
            f"trivy exited with code {proc.returncode}: {proc.stderr.strip()}"
        )

    if not proc.stdout.strip():
        return []

    data = json.loads(proc.stdout)
    findings: list[Finding] = []
    for result in data.get("Results") or []:
        target = result.get("Target", "")
        for vuln in result.get("Vulnerabilities") or []:
            findings.append(
                Finding.from_trivy(vuln, target=target, repo_root=root)
            )
    return findings
