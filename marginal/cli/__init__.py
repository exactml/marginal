"""Command entry points."""

from __future__ import annotations

import argparse
import sys
from typing import get_args

from marginal.cli.init import run_init
from marginal.cli.review import OutputFormat, run_review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marginal")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Scaffold a repository for marginal")
    init_parser.add_argument(
        "path", nargs="?", default=".", help="Target directory (default: current directory)"
    )
    init_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing scaffolded files"
    )

    review_parser = subparsers.add_parser("review", help="Fetch and summarize a pull request")
    review_parser.add_argument("--repo", required=True, help="GitHub repository as owner/name")
    review_parser.add_argument(
        "--pr", type=int, required=True, dest="pr_number", help="Pull request number"
    )
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

    args = parser.parse_args(argv)

    if args.command == "init":
        return run_init(args.path, force=args.force)
    if args.command == "review":
        return run_review(
            args.repo, args.pr_number, comment=args.comment, output_format=args.output_format
        )

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
