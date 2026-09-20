"""Throwaway file to force a non-empty marginal review finding.

DO NOT MERGE. Verifying v0.2.4's strict-mode fix handles a real, non-empty
`findings` payload cleanly, not just an empty one. Deleted before this PR
closes.
"""


def is_even(n: int) -> bool:
    """Return whether `n` is even."""
    return n % 2 == 1
