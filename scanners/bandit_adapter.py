"""Bandit SAST scanner adapter."""

import json
import subprocess
from pathlib import Path

import structlog

from scanners.models import Finding

logger = structlog.get_logger(__name__)

# Bandit exits 0 when no issues are found and 1 when issues are detected.
# Anything outside this set is a real failure (config error, crash, etc.).
_OK_EXIT_CODES = frozenset({0, 1})


def run_bandit(
    paths: list[str],
    *,
    repo_root: Path | None = None,
) -> list[Finding]:
    """Run Bandit on the given paths and return normalized findings.

    Args:
        paths: Files or directories to scan. Empty paths return an empty list
            without invoking Bandit.
        repo_root: Repository root used to normalize the file paths reported by
            Bandit. Defaults to the current working directory.

    Returns:
        One Finding per issue Bandit reports. Returns an empty list if Bandit
        finds nothing.

    Raises:
        RuntimeError: If Bandit exits with a code outside the documented
            "ok" set (anything other than 0 or 1).
    """
    if not paths:
        return []

    root = (repo_root or Path.cwd()).resolve()
    cmd = ["bandit", "-r", "-f", "json", *paths]
    logger.info("running_bandit", cmd=cmd, cwd=str(root))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )

    if proc.returncode not in _OK_EXIT_CODES:
        logger.error(
            "bandit_failed",
            returncode=proc.returncode,
            stderr=proc.stderr.strip(),
        )
        raise RuntimeError(
            f"bandit exited with code {proc.returncode}: {proc.stderr.strip()}"
        )

    if not proc.stdout.strip():
        return []

    data = json.loads(proc.stdout)
    issues = data.get("results", [])
    return [Finding.from_bandit(issue, repo_root=root) for issue in issues]
