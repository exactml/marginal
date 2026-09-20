"""Command entry points."""

from __future__ import annotations

import argparse
import sys

from marginal.cli.init import run_init
from marginal.cli.review import run_review


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

    help_parser = subparsers.add_parser("help", help="Show help for a command")
    help_parser.add_argument(
        "topic", nargs="?", help="Command to show help for (default: top-level usage)"
    )

    args = parser.parse_args(argv)

    if args.command == "help":
        return _run_help(parser, subparsers, args.topic)
    if args.command == "init":
        return run_init(args.path, force=args.force)
    if args.command == "review":
        return run_review(args.repo, args.pr_number, comment=args.comment)

    parser.error(f"unknown command: {args.command}")
    return 2


def _run_help(
    parser: argparse.ArgumentParser,
    subparsers: argparse._SubParsersAction,
    topic: str | None,
) -> int:
    if topic is None:
        parser.print_help()
        return 0
    command_parser = subparsers.choices.get(topic)
    if command_parser is None:
        parser.error(f"unknown command: {topic}")
        return 2
    command_parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
