#!/usr/bin/env python3
"""Report every Herdr workspace's sidebar number as a display-only token.

A workspace's number is its 1-based position in sidebar order, which is exactly
what `switch_workspace = "prefix+shift+1..9"` targets. Reporting it as a token
lets an expanded sidebar row render the number in front of the workspace name,
which Herdr has no built-in token for.

Usage:
    python3 sync.py [--dry-run] [--token NAME] [--source ID]

Herdr injects HERDR_BIN_PATH for plugin commands; without it the `herdr` binary
on PATH is used.
"""

import argparse
import json
import os
import subprocess
import sys

DEFAULT_SOURCE = "space-index"
DEFAULT_TOKEN = "idx"


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the reports that would be sent and exit",
    )
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help=f"token name to report (default: {DEFAULT_TOKEN})",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"metadata source id (default: {DEFAULT_SOURCE})",
    )
    return parser.parse_args(argv)


def herdr_bin():
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def run(*args):
    return subprocess.run([herdr_bin(), *args], capture_output=True, text=True)


def workspace_numbers():
    """Return [(workspace_id, number)] in sidebar order."""
    listed = run("workspace", "list")
    if listed.returncode != 0:
        raise RuntimeError(listed.stderr.strip() or "herdr workspace list failed")
    try:
        workspaces = json.loads(listed.stdout)["result"]["workspaces"]
    except (ValueError, KeyError) as exc:
        raise RuntimeError(f"unexpected `herdr workspace list` output: {exc}") from exc

    numbers = []
    for workspace in workspaces:
        workspace_id = workspace.get("workspace_id")
        number = workspace.get("number")
        if isinstance(workspace_id, str) and number is not None:
            numbers.append((workspace_id, number))
    return numbers


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    try:
        numbers = workspace_numbers()
    except RuntimeError as exc:
        print(f"space-index: {exc}", file=sys.stderr)
        return 1

    if not numbers:
        print("space-index: no workspaces to report", file=sys.stderr)
        return 0

    failures = []
    for workspace_id, number in numbers:
        if args.dry_run:
            print(f"{workspace_id} {args.token}={number}")
            continue
        reported = run(
            "workspace",
            "report-metadata",
            workspace_id,
            "--source",
            args.source,
            "--token",
            f"{args.token}={number}",
        )
        if reported.returncode != 0:
            failures.append(
                f"{workspace_id}: {reported.stderr.strip() or 'report-metadata failed'}"
            )

    for failure in failures:
        print(f"space-index: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
