"""DO NOT MERGE -- throwaway file, part of a verification test."""


def get_last_n(items: list, n: int) -> list:
    """Return the last `n` items of `items`."""
    return items[len(items) - n - 1 :]
