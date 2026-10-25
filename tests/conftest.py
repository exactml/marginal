from pathlib import Path


def working_tree_file(path: str, ref: str) -> str | None:
    """Stand-in for `GitHubClient.get_file`: the test's working directory plays
    the PR's base commit, so `.marginal/` files a test writes are what a
    review loads."""
    file = Path(path)
    return file.read_text() if file.is_file() else None
