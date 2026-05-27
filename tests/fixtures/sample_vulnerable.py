"""Intentionally vulnerable fixture for the Bandit adapter tests.

Do not use this code anywhere outside the test suite. The two issues below
exist so Bandit can report B105 (hardcoded password) and B101 (assert_used)
against a stable, minimal target.
"""

PASSWORD = "hunter2"


def check_positive(value: int) -> None:
    assert value > 0
