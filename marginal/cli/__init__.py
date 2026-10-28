"""Command entry points."""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import get_args

from marginal.cli.compact import run_compact
from marginal.cli.doctor import run_doctor
from marginal.cli.help import run_help
from marginal.cli.init import run_init
from marginal.cli.review import OutputFormat, run_review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marginal")
    try:
        installed = version("marginal-review")
    except PackageNotFoundError:
        # Running from a checkout that isn't pip-installed; don't break every command.
        installed = "unknown"
    parser.add_argument("--version", action="version", version=f"marginal {installed}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Scaffold a repository for marginal")
    init_parser.add_argument(
        "path", nargs="?", default=".", help="Target directory (default: current directory)"
    )
    init_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing scaffolded files"
    )

    review_parser = subparsers.add_parser(
        "review", help="Fetch and summarize a pull request, or the diff between two commits"
    )
    review_parser.add_argument("--repo", required=True, help="GitHub repository as owner/name")
    review_target = review_parser.add_mutually_exclusive_group(required=True)
    review_target.add_argument("--pr", type=int, dest="pr_number", help="Pull request number")
    review_target.add_argument(
        "--base", help="Base commit SHA; with --head, review base...head instead of a PR"
    )
    review_parser.add_argument("--head", help="Head commit SHA, used with --base")
    review_parser.add_argument(
        "--comment", action="store_true", help="Post the summary as a PR comment"
    )
    review_parser.add_argument(
        "--format",
        choices=get_args(OutputFormat),
        default="text",
        dest="output_format",
        help="Output format for stdout (default: text)",
    )

    compact_parser = subparsers.add_parser(
        "compact", help="Re-check marginal's open findings and close the stale ones"
    )
    compact_parser.add_argument("--repo", required=True, help="GitHub repository as owner/name")
    compact_parser.add_argument(
        "--pr", type=int, required=True, dest="pr_number", help="Pull request number"
    )
    compact_parser.add_argument(
        "--comment", action="store_true", help="Reply in each resolved finding's thread"
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Check config, credentials, and GitHub access before a review"
    )
    doctor_parser.add_argument(
        "--repo", help="GitHub repository as owner/name, to check GITHUB_TOKEN can reach it"
    )

    help_parser = subparsers.add_parser("help", help="Show help for a command")
    help_parser.add_argument(
        "topic", nargs="?", help="Command to show help for (default: top-level usage)"
    )

    args = parser.parse_args(argv)

    if args.command == "help":
        return run_help(parser, subparsers, args.topic)
    if args.command == "compact":
        return run_compact(args.repo, args.pr_number, comment=args.comment)
    if args.command == "doctor":
        return run_doctor(args.repo)
    if args.command == "init":
        return run_init(args.path, force=args.force)
    if args.command == "review":
        if (args.base is None) != (args.head is None):
            review_parser.error("--base and --head must be given together")
        if args.base is not None and args.comment:
            review_parser.error("--comment needs --pr: there's no pull request to post to")
        return run_review(
            args.repo,
            args.pr_number,
            base=args.base,
            head=args.head,
            comment=args.comment,
            output_format=args.output_format,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
