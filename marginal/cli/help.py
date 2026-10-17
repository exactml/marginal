"""`marginal help` and `marginal help <command>`."""

from __future__ import annotations

import argparse


def run_help(
    parser: argparse.ArgumentParser,
    subparsers: argparse._SubParsersAction,
    topic: str | None,
) -> int:
    """Print top-level usage, or the usage for a known subcommand.

    Unknown topics go through ``parser.error`` and exit 2, matching argparse.
    """
    if topic is None:
        parser.print_help()
        return 0
    command_parser = subparsers.choices.get(topic)
    if command_parser is None:
        parser.error(f"unknown command: {topic}")
        return 2
    command_parser.print_help()
    return 0
