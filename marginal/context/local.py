"""Answer a review's reads from the local git checkout instead of GitHub."""

from __future__ import annotations

import subprocess
import sys

from marginal.github.errors import GitHubError

_STATUSES = {"A": "added", "D": "removed", "R": "renamed", "C": "copied"}


class LocalGitError(GitHubError):
    """A git command failed. A `GitHubError`, so a review reports it the same way."""


class LocalCheckout:
    """The reads a review makes through `GitHubClient`, answered by git in
    `path`, so local work can be reviewed before it's pushed."""

    def __init__(self, path: str = ".") -> None:
        self.root = path
        # Every path git prints is relative to the repo root, so run from there.
        self.root = self._git("rev-parse", "--show-toplevel").strip()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "--literal-pathspecs", "-C", self.root, "-c", "core.quotePath=false", *args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise LocalGitError(f"git {args[0]} failed: {result.stderr.strip()}")
        return result.stdout

    def merge_base(self, ref: str) -> str:
        """Where `HEAD` forked from `ref`: the commit a PR from here would be reviewed against."""
        return self._git("merge-base", ref, "HEAD").strip()

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def get_file(self, path: str, ref: str) -> str | None:
        """The text of `path` as of commit `ref`, or `None` if it isn't a file there."""
        try:
            return self._git("show", f"{ref}:{path}")
        except LocalGitError:
            return None

    def get_workflow_run(self, run_id: int) -> dict[str, object]:
        raise LocalGitError("a local review has no CI run")

    def get_compare_files(self, base: str, head: str) -> list[dict[str, object]]:
        """The files changed from `base` to the working tree, shaped like
        `GitHubClient.get_compare_files`: local commits plus uncommitted
        changes to tracked files. `head` is ignored: the working tree is newer.
        """
        files = []
        for status, *paths in self._name_status(base):
            file: dict[str, object] = {
                "filename": paths[-1],
                "status": _STATUSES.get(status[0], "modified"),
            }
            if len(paths) == 2:
                file["previous_filename"] = paths[0]
            # A type change (e.g. symlink to file) diffs as a delete plus an add,
            # not one patch, so like GitHub for a binary file it gets none.
            if status != "T":
                # GitHub's patches have 3 lines of context, whatever the local git config says.
                diff = self._git(
                    "diff", "-M", "-U3", "--no-color", "--no-ext-diff", base, "--", *paths
                )
                hunk_start = diff.find("\n@@")
                if hunk_start != -1:
                    file["patch"] = diff[hunk_start + 1 :].rstrip("\n")
            files.append(file)
        untracked = self._git("ls-files", "--others", "--exclude-standard").splitlines()
        if untracked:
            print(
                f"marginal review: {len(untracked)} untracked file(s) not reviewed; "
                "`git add -N <file>` to include one",
                file=sys.stderr,
            )
        return files

    def _name_status(self, base: str) -> list[list[str]]:
        """`[status, path]`, or `[status, old, new]` for a rename or copy, per changed file."""
        tokens = self._git("diff", "-M", "--name-status", "-z", base).split("\0")
        entries, i = [], 0
        while i < len(tokens) and tokens[i]:
            width = 3 if tokens[i][0] in "RC" else 2
            entries.append(tokens[i : i + width])
            i += width
        return entries
