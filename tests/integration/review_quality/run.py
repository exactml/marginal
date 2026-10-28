"""Run the review-quality benchmark: every attempt reviews every case, N times.

An attempt is one review tool with one provider and model (cases.yml's
`attempts`). For each case, downloads one snapshot of the head commit (no
clone, no history), writes the benchmark's marginal-config.yaml into it as
.marginal/config.yaml with the attempt's reviewer, and runs `marginal review
--base --head --format json` there, so the code graph sees the files around
the change. Each review is saved as <out>/<attempt id>/<case-id>/<run>.json
with the wall-clock `seconds` added; score.py turns those into scores. Calls
each attempt's model once per case per run, so it needs that provider's API
key (and GITHUB_TOKEN for the diff).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml
from score import HERE, Attempt, Case, RepoSettings, load_suite


def download_snapshot(upstream: str, sha: str, dest: Path) -> Path:
    """Extract the tarball of `upstream` at `sha` into `dest` as a git
    repository; return its root."""
    url = f"https://codeload.github.com/{upstream}/tar.gz/{sha}"
    with (
        urllib.request.urlopen(url, timeout=300) as response,
        tarfile.open(fileobj=response, mode="r|gz") as archive,
    ):
        archive.extractall(dest, filter="data")
    (root,) = dest.iterdir()  # the archive's single <repo>-<sha>/ directory
    # The code graph lists files with `git ls-files`, which needs a repository;
    # untracked files are enough, so nothing is committed.
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def review(case: Case, checkout: Path) -> dict:
    """One `marginal review` of the case, timed."""
    command = [
        "marginal",
        "review",
        "--repo",
        case.upstream,
        "--base",
        case.base,
        "--head",
        case.head,
        "--format",
        "json",
    ]
    started = time.monotonic()
    process = subprocess.run(command, cwd=checkout, capture_output=True, text=True, check=False)
    seconds = time.monotonic() - started
    if process.returncode != 0:
        raise RuntimeError(f"marginal exited {process.returncode}: {process.stderr.strip()}")
    return json.loads(process.stdout) | {"seconds": round(seconds, 2)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=1, help="reviews per case (default 1)")
    parser.add_argument(
        "--case", action="append", metavar="ID", help="run only this case (repeatable)"
    )
    parser.add_argument(
        "--attempt",
        action="append",
        metavar="ID",
        help="run only this attempt, e.g. marginal/anthropic/claude-opus-5-5 (repeatable)",
    )
    parser.add_argument("--out", type=Path, default=HERE / "raw", help="results dir")
    parser.add_argument("--cases", type=Path, default=HERE / "cases.yml")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    suite = load_suite(args.cases)
    unknown = set(args.case or []) - {case.id for case in suite.cases}
    if unknown:
        parser.error(f"unknown case ids: {', '.join(sorted(unknown))}")
    cases = [case for case in suite.cases if not args.case or case.id in args.case]
    unknown = set(args.attempt or []) - {attempt.id for attempt in suite.attempts}
    if unknown:
        parser.error(f"unknown attempt ids: {', '.join(sorted(unknown))}")
    attempts = [a for a in suite.attempts if not args.attempt or a.id in args.attempt]
    config = yaml.safe_load((args.cases.parent / suite.config).read_text())

    failures = 0
    for case in cases:
        for attempt in attempts:
            # Runs left from an earlier, longer benchmark would be scored with these.
            shutil.rmtree(args.out / attempt.id / case.id, ignore_errors=True)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                checkout = download_snapshot(case.upstream, case.head, Path(tmp))
            except (OSError, tarfile.TarError, subprocess.CalledProcessError) as error:
                print(f"{case.id}: download failed: {error}", file=sys.stderr)
                failures += args.runs * len(attempts)
                continue
            (checkout / ".marginal").mkdir(exist_ok=True)
            for attempt in attempts:
                case_config = repo_config(config, suite.repos.get(case.upstream))
                failures += run_attempt(attempt, case, checkout, case_config, args.runs, args.out)
    if failures:
        print(f"{failures} reviews failed", file=sys.stderr)
    return 1 if failures else 0


def repo_config(config: dict, settings: RepoSettings | None) -> dict:
    """marginal's config for one upstream repo's cases: the shared config,
    with that repo's settings from cases.yml's `repos`."""
    if settings is None:
        return config
    review = config.get("review", {}) | {"confidence_threshold": settings.confidence_threshold}
    return config | {"review": review}


def run_attempt(
    attempt: Attempt, case: Case, checkout: Path, config: dict, runs: int, out: Path
) -> int:
    """Review `case` `runs` times with `attempt`'s reviewer; return the failures."""
    reviewer = {"provider": attempt.provider, "model": attempt.model}
    attempt_config = config | {"models": {"reviewer": reviewer}}
    (checkout / ".marginal" / "config.yaml").write_text(yaml.safe_dump(attempt_config))
    case_dir = out / attempt.id / case.id
    case_dir.mkdir(parents=True)
    failures = 0
    for run in range(1, runs + 1):
        label = f"{attempt.id} {case.id}"
        print(f"{label}: run {run}/{runs}", file=sys.stderr)
        try:
            result = review(case, checkout)
        except (OSError, RuntimeError, ValueError) as error:
            print(f"{label}: run {run} failed: {error}", file=sys.stderr)
            failures += 1
            continue
        (case_dir / f"{run}.json").write_text(json.dumps(result, indent=2) + "\n")
    return failures


if __name__ == "__main__":
    sys.exit(main())
