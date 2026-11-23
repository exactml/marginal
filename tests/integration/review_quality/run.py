"""Run the review-quality benchmark: every attempt reviews every case, N times.

An attempt is one review tool with one provider and model (cases.yml's
`attempts`). For each case, downloads snapshots of the base and head commits
(no clone, no history) and makes them a two-commit repository: the base with
the case's accepted rules and decisions in .marginal/knowledge/, then the head.
It writes the benchmark's marginal-config.yaml into it as .marginal/config.yaml
with the attempt's reviewer, and runs `marginal review --local HEAD~1 --format
json` there, so the review reads that knowledge from the base commit as it
would from a PR's, and the code graph sees the files around the change. Each
review is saved as <out>/<attempt id>/<case-id>/<run>.json with the
wall-clock `seconds` added; score.py turns those into scores. Calls each
attempt's model once per case per run, so it needs that provider's API key
(and GITHUB_TOKEN for PR-Agent's diff).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml
from score import HERE, Attempt, Case, Seed, load_suite

from marginal.context.knowledge import AcceptedClaim, claim_file

# A commit needs an author; these never leave the temporary snapshot.
_GIT = ["git", "-c", "user.name=benchmark", "-c", "user.email=benchmark@localhost"]


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


def build_checkout(case: Case, dest: Path) -> Path:
    """The case as a git repository with two commits: the base snapshot plus
    the case's accepted claims under .marginal/knowledge/, then the head
    snapshot. The working tree is the head; return its root."""
    root = download_snapshot(case.upstream, case.base, dest / "base")
    head = download_snapshot(case.upstream, case.head, dest / "head")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    # run_attempt writes the config per attempt; it's never part of the diff.
    (root / ".git" / "info" / "exclude").write_text(".marginal/config.yaml\n")
    for seed in case.accepted:
        path, text = claim_file(_accepted(case, seed))
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    _commit(root, "base")
    for entry in root.iterdir():
        if entry.name in (".git", ".marginal"):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for entry in head.iterdir():
        shutil.move(entry, root / entry.name)
    _commit(root, "head")
    return root


def _accepted(case: Case, seed: Seed) -> AcceptedClaim:
    return AcceptedClaim(
        # Named like marginal names a claim: a short hash.
        id=hashlib.sha256(f"{seed.kind}|{seed.statement}".encode()).hexdigest()[:6],
        repo=case.upstream.split("/")[1],
        kind=seed.kind,
        statement=seed.statement,
        about=seed.about,
        pr=seed.pr,
    )


def _commit(root: Path, message: str) -> None:
    # --force: a snapshot holds only tracked files, and one its .gitignore matches
    # (generated or vendored) must still be in the diff.
    subprocess.run(_GIT + ["add", "-A", "--force"], cwd=root, check=True)
    subprocess.run(
        _GIT + ["commit", "-q", "--no-verify", "--allow-empty", "-m", message],
        cwd=root,
        check=True,
    )


def review(attempt: Attempt, case: Case, checkout: Path) -> dict:
    """One review of the case by the attempt's tool, timed."""
    review_with = review_with_pr_agent if attempt.tool == "pr-agent" else review_with_marginal
    started = time.monotonic()
    result = review_with(attempt, case, checkout)
    return result | {"seconds": round(time.monotonic() - started, 2)}


def review_with_marginal(attempt: Attempt, case: Case, checkout: Path) -> dict:
    """`marginal review` of the case, with the reviewer run_attempt wrote into
    the snapshot's .marginal/config.yaml."""
    command = ["marginal", "review", "--local", "HEAD~1", "--repo", case.upstream]
    command += ["--format", "json"]
    process = subprocess.run(command, cwd=checkout, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"marginal exited {process.returncode}: {process.stderr.strip()}")
    return json.loads(process.stdout)


# PR-Agent's model prefix, its API-key setting, and where our key comes from.
_PR_AGENT_PROVIDERS = {
    "anthropic": ("anthropic/", "ANTHROPIC__KEY", "ANTHROPIC_API_KEY"),
    "openai": ("openai/", "OPENAI__KEY", "OPENAI_API_KEY"),
}


def review_with_pr_agent(attempt: Attempt, case: Case, checkout: Path) -> dict:
    """PR-Agent's review of the case's diff, in its plain-diff mode.

    Plain-diff mode never talks to GitHub, so PR-Agent can't post anything on
    the upstream PR. It runs from $PR_AGENT_PYTHON, its own environment, since
    its dependencies would clash with marginal's.
    """
    if attempt.provider not in _PR_AGENT_PROVIDERS:
        raise ValueError(f"pr-agent attempts support {sorted(_PR_AGENT_PROVIDERS)} only")
    prefix, key_setting, key_env = _PR_AGENT_PROVIDERS[attempt.provider]
    work = checkout.parent
    (work / "case.diff").write_bytes(download_diff(case))
    output = work / "pr-agent.json"
    # An earlier run's review must never be read back as this run's.
    output.unlink(missing_ok=True)
    env = os.environ | {
        "CONFIG__MODEL": prefix + attempt.model,
        # The same model only: the default fallback is another provider's model.
        "CONFIG__FALLBACK_MODELS": "[]",
        key_setting: os.environ.get(key_env, ""),
    }
    command = [
        os.environ.get("PR_AGENT_PYTHON", sys.executable),
        "-m",
        "pr_agent.cli",
        "--diff-file",
        "case.diff",
        "--json-output",
        "pr-agent.json",
        "review",
    ]
    process = subprocess.run(
        command, cwd=work, env=env, capture_output=True, text=True, check=False
    )
    if process.returncode != 0 or not output.is_file():
        # PR-Agent can fail with exit code 0 and its error on stdout (seen: an
        # API key out of credit), so the missing JSON is what counts.
        log = (process.stderr + process.stdout).strip()[-2000:]
        raise RuntimeError(f"pr-agent wrote no review (exit {process.returncode}): {log}")
    return pr_agent_result(json.loads(output.read_text()), attempt)


def download_diff(case: Case) -> bytes:
    """The case's base...head diff from GitHub's compare API."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{case.upstream}/compare/{case.base}...{case.head}",
        headers={"Accept": "application/vnd.github.diff"},
    )
    if token := os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def pr_agent_result(data: dict, attempt: Attempt) -> dict:
    """PR-Agent's structured review in the shape score.py reads.

    Each of its key issues names a file and a line range, but carries no
    severity or quoted evidence: severity stays None rather than being guessed.
    """
    findings = []
    for issue in (data.get("review") or {}).get("key_issues_to_review") or []:
        start, end = _line(issue.get("start_line")), _line(issue.get("end_line"))
        header = str(issue.get("issue_header") or "").strip()
        content = str(issue.get("issue_content") or "").strip()
        findings.append(
            {
                "file": str(issue.get("relevant_file") or "").strip(),
                "line": start,
                "end_line": end or start,
                "severity": None,
                "message": f"{header}: {content}" if header else content,
            }
        )
    usage = data.get("usage") or {}
    return {
        "findings": findings,
        "dropped_findings": [],
        "usage": {
            "model": f"{attempt.provider}:{attempt.model}",
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        },
    }


def _line(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


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
                checkout = build_checkout(case, Path(tmp))
            except (OSError, tarfile.TarError, subprocess.CalledProcessError) as error:
                print(f"{case.id}: download failed: {error}", file=sys.stderr)
                failures += args.runs * len(attempts)
                continue
            (checkout / ".marginal").mkdir(exist_ok=True)
            for attempt in attempts:
                failures += run_attempt(attempt, case, checkout, config, args.runs, args.out)
    if failures:
        print(f"{failures} reviews failed", file=sys.stderr)
    return 1 if failures else 0


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
            result = review(attempt, case, checkout)
        except (OSError, RuntimeError, ValueError) as error:
            print(f"{label}: run {run} failed: {error}", file=sys.stderr)
            failures += 1
            continue
        (case_dir / f"{run}.json").write_text(json.dumps(result, indent=2) + "\n")
    return failures


if __name__ == "__main__":
    sys.exit(main())
