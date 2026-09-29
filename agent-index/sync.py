#!/usr/bin/env python3
"""Report every Herdr agent's panel number as a display-only pane token.

An agent's number is its 1-based position in the agent panel, which is exactly
what `focus_agent = "prefix+alt+1..9"` targets. Agent rows have no built-in
number token, so this plugin reports one as `$aidx`, which an expanded sidebar
row can render.

The panel order comes from `ui.agent_panel_sort`:

    spaces    (default)  `herdr agent list` order: space, then tab, then pane.
    priority             blocked, done, working, idle, unknown; within one
                         status the most recent state change first.

Herdr injects HERDR_BIN_PATH for plugin commands; without it the `herdr` binary
on PATH is used.

Usage:
    python3 sync.py [--dry-run] [--token NAME] [--source ID] [--sort SORT]
"""

import argparse
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_SOURCE = "agent-index"
DEFAULT_TOKEN = "aidx"

# Mirrors status_priority() in Herdr's src/client/shell.rs.
STATUS_PRIORITY = {"blocked": 4, "done": 3, "working": 2, "idle": 1}


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
    parser.add_argument(
        "--sort",
        default="auto",
        choices=["auto", "spaces", "priority"],
        help="panel order to number (default: auto, read from config.toml)",
    )
    return parser.parse_args(argv)


def herdr_bin():
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def run(*args):
    return subprocess.run([herdr_bin(), *args], capture_output=True, text=True)


def config_path():
    override = os.environ.get("HERDR_CONFIG_PATH")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "herdr" / "config.toml"


def configured_sort():
    """Read ui.agent_panel_sort so numbers match what focus_agent targets."""
    try:
        import tomllib
    except ImportError:
        return "spaces"
    try:
        with open(config_path(), "rb") as handle:
            config = tomllib.load(handle)
    except (OSError, ValueError):
        return "spaces"
    value = config.get("ui", {}).get("agent_panel_sort", "")
    return "priority" if str(value).strip().lower() == "priority" else "spaces"


def agent_numbers(sort):
    """Return [(pane_id, number)] in agent-panel order."""
    listed = run("agent", "list")
    if listed.returncode != 0:
        raise RuntimeError(listed.stderr.strip() or "herdr agent list failed")
    try:
        agents = json.loads(listed.stdout)["result"]["agents"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"unexpected `herdr agent list` output: {exc}") from exc

    if sort == "priority":
        agents = sorted(
            agents,
            key=lambda agent: (
                -STATUS_PRIORITY.get(str(agent.get("agent_status", "")).lower(), 0),
                -int(agent.get("state_change_seq") or 0),
            ),
        )

    numbers = []
    for number, agent in enumerate(agents, start=1):
        pane_id = agent.get("pane_id")
        if isinstance(pane_id, str):
            numbers.append((pane_id, number))
    return numbers


@contextlib.contextmanager
def serialized():
    """Serialize concurrent hook runs with an advisory lock.

    The agent list is read after the lock is taken, so the writer that reports
    last is working from the freshest order instead of a stale snapshot.
    """
    state_dir = os.environ.get("HERDR_PLUGIN_STATE_DIR") or tempfile.gettempdir()
    try:
        handle = open(Path(state_dir) / "agent-index.lock", "w")
    except OSError:
        yield
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    sort = configured_sort() if args.sort == "auto" else args.sort

    try:
        with serialized():
            numbers = agent_numbers(sort)
            failures = []
            for pane_id, number in numbers:
                if args.dry_run:
                    print(f"{pane_id} {args.token}={number} (sort={sort})")
                    continue
                reported = run(
                    "pane",
                    "report-metadata",
                    pane_id,
                    "--source",
                    args.source,
                    "--token",
                    f"{args.token}={number}",
                )
                if reported.returncode != 0:
                    failures.append(
                        f"{pane_id}: "
                        f"{reported.stderr.strip() or 'report-metadata failed'}"
                    )
    except RuntimeError as exc:
        print(f"agent-index: {exc}", file=sys.stderr)
        return 1

    if not numbers:
        print("agent-index: no agents to report", file=sys.stderr)
        return 0

    for failure in failures:
        print(f"agent-index: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
