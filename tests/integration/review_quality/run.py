"""Run the review-quality benchmark: `marginal review` on every case, N times.

For each case, downloads one snapshot of the head commit (no clone, no
history), puts the benchmark's marginal-config.yaml in it as
.marginal/config.yaml, and runs `marginal review --base --head --format json`
there, so the code graph sees the files around the change. Each review is
saved as <out>/<case-id>/<run>.json with the wall-clock `seconds` added;
score.py turns those into scores. Calls the reviewer model once per case per
run, so it needs that provider's API key (and GITHUB_TOKEN for the diff).
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

from score import HERE, Case, load_suite


def download_snapshot(upstream: str, sha: str, dest: Path) -> Path:
    """Extract the tarball of `upstream` at `sha` into `dest`; return its root."""
    url = f"https://codeload.github.com/{upstream}/tar.gz/{sha}"
    with (
        urllib.request.urlopen(url, timeout=300) as response,
        tarfile.open(fileobj=response, mode="r|gz") as archive,
    ):
        archive.extractall(dest, filter="data")
    (root,) = dest.iterdir()  # the archive's single <repo>-<sha>/ directory
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
    parser.add_argument("--runs", type=int, default=3, help="reviews per case (default 3)")
    parser.add_argument(
        "--case", action="append", metavar="ID", help="run only this case (repeatable)"
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
    config = (args.cases.parent / suite.config).read_text()

    failures = 0
    for case in cases:
        case_dir = args.out / case.id
        # Runs left from an earlier, longer benchmark would be scored with these.
        shutil.rmtree(case_dir, ignore_errors=True)
        case_dir.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                checkout = download_snapshot(case.upstream, case.head, Path(tmp))
            except (OSError, tarfile.TarError) as error:
                print(f"{case.id}: download failed: {error}", file=sys.stderr)
                failures += args.runs
                continue
            (checkout / ".marginal").mkdir(exist_ok=True)
            (checkout / ".marginal" / "config.yaml").write_text(config)
            for run in range(1, args.runs + 1):
                print(f"{case.id}: run {run}/{args.runs}", file=sys.stderr)
                try:
                    result = review(case, checkout)
                except (OSError, RuntimeError, ValueError) as error:
                    print(f"{case.id}: run {run} failed: {error}", file=sys.stderr)
                    failures += 1
                    continue
                (case_dir / f"{run}.json").write_text(json.dumps(result, indent=2) + "\n")
    if failures:
        print(f"{failures} reviews failed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
