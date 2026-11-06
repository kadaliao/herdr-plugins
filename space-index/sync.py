#!/usr/bin/env python3
"""Report every Herdr workspace's sidebar number as a display-only token.

A workspace's number is its 1-based position in sidebar order, which is exactly
what `switch_workspace = "prefix+shift+1..9"` targets. Reporting it as a token
lets an expanded sidebar row render the number in front of the workspace name,
which Herdr has no built-in token for.

Across machines
---------------
A window with saved SSH machines lists Local's workspaces first, then each
enabled machine's in `herdr machine list` order, and the numbers continue down
that list. `switch_workspace` only switches within the machine you are on, so
a saved machine's numbers mark its place in the window rather than a key.

Every window renders the same workspace tokens. When two hosts save each other,
their windows list machines in opposite orders, so give each host its own token
name in its space rows (`$idx_mbp`, `$idx_mm`); this script reads the name from
the host's config. Each run then:

1. numbers this server's workspaces for every window that shows them: this
   host's own window from 1, and other windows from the base they stored here
   as a `<token>-base` workspace token;
2. if this host has saved machines, stores this window's base on each of them
   and asks their copy of this plugin to renumber (the `renumber` action, which
   runs with --local-only). A base is only re-sent when it changes.

Numbers that are already reported correctly are skipped, so a run without
changes costs a few local `herdr` calls.

Herdr injects HERDR_BIN_PATH for plugin commands; without it the `herdr` binary
on PATH is used.

Usage:
    python3 sync.py [--dry-run] [--force] [--local-only]
                    [--token NAME] [--source ID]
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_SOURCE = "space-index"
DEFAULT_TOKEN = "idx"
BASE_SUFFIX = "-base"
RENUMBER_ACTION = "kadaliao.space-index.renumber"

# Herdr token keys are 1-32 characters of [A-Za-z0-9_-]; leave room for the
# "-base" suffix so a window's base can be stored under a related key.
TOKEN_NAME = re.compile(r"^[A-Za-z0-9_-]{1,27}$")
# Herdr accepts at most 16 tokens in one metadata report.
MAX_TOKENS_PER_REPORT = 16

# A saved-machine call is one non-interactive SSH round trip. Herdr's own SSH
# config gives up connecting after 10 seconds.
REMOTE_TIMEOUT_SECONDS = 15
# After a failed push, leave an unreachable machine alone for a while so every
# local event does not wait on SSH again.
RETRY_AFTER_FAILURE_SECONDS = 60
# Re-check a pushed base now and then, in case the machine lost it.
RECHECK_AFTER_SECONDS = 600


def window_token(name):
    """Whether `name` can be another window's workspace token.

    agent-index stores its own `aidx…-base` tokens on the same workspaces, so
    only `idx…` names count here.
    """
    return bool(TOKEN_NAME.match(name)) and name.startswith(DEFAULT_TOKEN)


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the reports that would be sent and exit",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-report every token and re-send every base",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="only number this server's workspaces; do not update saved machines",
    )
    parser.add_argument(
        "--token",
        help=(
            "token this host's window renders "
            f"(default: the first $idx… token in config.toml, else {DEFAULT_TOKEN})"
        ),
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"metadata source id (default: {DEFAULT_SOURCE})",
    )
    return parser.parse_args(argv)


def herdr_bin():
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def run(*args, machine=None):
    """Run a herdr command, on a saved machine when `machine` is given."""
    command = [herdr_bin(), *(["--machine", machine] if machine else []), *args]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=REMOTE_TIMEOUT_SECONDS if machine else None,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            command, 124, "", f"timed out after {REMOTE_TIMEOUT_SECONDS}s"
        )
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def run_json(*args, machine=None):
    result = run(*args, machine=machine)
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or f"herdr {' '.join(args)} failed"
        )
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError(f"unexpected `herdr {' '.join(args)}` output: {exc}") from exc


def config_path():
    override = os.environ.get("HERDR_CONFIG_PATH")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "herdr" / "config.toml"


def table(value):
    return value if isinstance(value, dict) else {}


def configured_token():
    """Return the $idx… token this host's space rows render, without the `$`."""
    try:
        import tomllib
    except ImportError:
        return DEFAULT_TOKEN
    try:
        with open(config_path(), "rb") as handle:
            config = tomllib.load(handle)
    except (OSError, ValueError):
        return DEFAULT_TOKEN
    spaces = table(table(table(config.get("ui")).get("sidebar")).get("spaces"))
    rows = spaces.get("rows")
    for row in rows if isinstance(rows, list) else []:
        for entry in row if isinstance(row, list) else []:
            name = table(entry).get("token") if isinstance(entry, dict) else entry
            if isinstance(name, str) and name.startswith("$" + DEFAULT_TOKEN):
                return name[1:]
    return DEFAULT_TOKEN


def state_dir():
    configured = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if configured:
        return Path(configured)
    # Run by hand, outside Herdr.
    path = Path(tempfile.gettempdir()) / "kadaliao.space-index"
    path.mkdir(exist_ok=True)
    return path


def load_state(name):
    try:
        with open(state_dir() / name) as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_state(name, value):
    path = state_dir() / name
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
    except OSError as exc:
        print(f"space-index: could not save {path}: {exc}", file=sys.stderr)


@contextlib.contextmanager
def serialized(name):
    """Serialize concurrent hook runs with an advisory lock."""
    try:
        handle = open(state_dir() / f"space-index.{name}.lock", "w")
    except OSError:
        yield
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def list_workspaces(machine=None):
    """Return one server's workspaces that have a sidebar number."""
    try:
        workspaces = run_json("workspace", "list", machine=machine)["result"][
            "workspaces"
        ]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"unexpected `herdr workspace list` output: {exc}") from exc
    return [
        workspace
        for workspace in workspaces
        if isinstance(workspace.get("workspace_id"), str)
        and isinstance(workspace.get("number"), int)
    ]


def saved_machines():
    """Return enabled saved machines in the order a window lists them."""
    try:
        machines = run_json("machine", "list", "--json")
    except RuntimeError:
        return []
    if not isinstance(machines, list):
        return []
    return [
        machine
        for machine in machines
        if isinstance(machine, dict)
        and machine.get("enabled")
        and isinstance(machine.get("id"), str)
    ]


def stored_bases(workspaces):
    """Return the bases other windows stored on this server's workspaces."""
    bases = {}
    for workspace in workspaces:
        for key, value in table(workspace.get("tokens")).items():
            token = key[: -len(BASE_SUFFIX)]
            if (
                key.endswith(BASE_SUFFIX)
                and window_token(token)
                and isinstance(value, str)
                and value.isdigit()
            ):
                bases.setdefault(token, int(value))
    return bases


def window_bases(own_token, workspaces, is_hub, dry_run):
    """Return {token: base} for every window that shows this server's workspaces.

    Bases are also kept in the plugin state directory, because workspace
    tokens do not survive a server restart.
    """
    saved = {
        token: base
        for token, base in load_state("bases.json").items()
        if window_token(token) and isinstance(base, int) and base >= 0
    }
    bases = {**saved, **stored_bases(workspaces)}
    if bases != saved and not dry_run:
        save_state("bases.json", bases)

    if own_token in bases and is_hub:
        # Another window renders the same token as this host's own window, so
        # one of them would be wrong; this host's window wins.
        print(
            f"space-index: another machine's window also renders ${own_token}; "
            "give each host its own $idx… token so both windows can be numbered",
            file=sys.stderr,
        )
        bases[own_token] = 0
    bases.setdefault(own_token, 0)
    return bases


def number_local_workspaces(workspaces, bases, args):
    """Report every window's number on this server's workspaces."""
    failures = []
    for workspace in workspaces:
        workspace_id = workspace["workspace_id"]
        number = workspace["number"]
        wanted = {token: str(base + number) for token, base in sorted(bases.items())}
        if args.dry_run:
            pairs = " ".join(f"{token}={value}" for token, value in wanted.items())
            print(f"{workspace_id} {pairs}")
            continue
        current = table(workspace.get("tokens"))
        if not args.force and all(current.get(t) == v for t, v in wanted.items()):
            continue
        items = list(wanted.items())
        for start in range(0, len(items), MAX_TOKENS_PER_REPORT):
            command = [
                "workspace",
                "report-metadata",
                workspace_id,
                "--source",
                args.source,
            ]
            for token, value in items[start : start + MAX_TOKENS_PER_REPORT]:
                command += ["--token", f"{token}={value}"]
            reported = run(*command)
            if reported.returncode != 0:
                failures.append(
                    f"{workspace_id}: "
                    f"{reported.stderr.strip() or 'report-metadata failed'}"
                )
                break
    return failures


def push_base(machine, label, own_token, base, args):
    """Store this window's base on a saved machine and ask it to renumber.

    Returns the machine's workspace count, which the next machine starts after.
    """
    key = f"{own_token}{BASE_SUFFIX}"
    workspaces = list_workspaces(machine)
    if not workspaces:
        raise RuntimeError("no workspaces to store the base on")
    for workspace in workspaces:
        if table(workspace.get("tokens")).get(key) == str(base):
            continue
        if args.dry_run:
            print(f"{label}:{workspace['workspace_id']} {key}={base}")
            continue
        reported = run(
            "workspace",
            "report-metadata",
            workspace["workspace_id"],
            "--source",
            args.source,
            "--token",
            f"{key}={base}",
            machine=machine,
        )
        if reported.returncode != 0:
            raise RuntimeError(reported.stderr.strip() or "report-metadata failed")
    if not args.dry_run:
        # Ask even when the base was already there: the machine may have stored
        # it while its plugin was missing or too old to renumber.
        invoked = run("plugin", "action", "invoke", RENUMBER_ACTION, machine=machine)
        if invoked.returncode != 0:
            # The base is stored, so the machine's own plugin picks it up on its
            # next event once it is installed and up to date there.
            print(
                f"space-index: stored {key}={base} on {label}, but could not ask "
                f"it to renumber: {invoked.stderr.strip() or 'action invoke failed'}",
                file=sys.stderr,
            )
    return len(workspaces)


def push_bases(own_token, local_count, machines, args):
    """Tell each saved machine where its workspaces start in this host's window."""
    pushed = {} if args.dry_run else load_state("pushed.json")
    now = time.time()
    offset = local_count
    failures = []
    for index, machine in enumerate(machines):
        machine_id = machine["id"]
        label = str(machine.get("label") or machine_id)
        entry = table(pushed.get(machine_id))
        current = entry.get("token") == own_token and entry.get("base") == offset
        age = now - float(entry.get("at") or 0)
        count = None
        if not args.force and entry.get("ok") is False and age < RETRY_AFTER_FAILURE_SECONDS:
            count = 0
        elif args.force or not (entry.get("ok") and current and age < RECHECK_AFTER_SECONDS):
            try:
                count = push_base(machine_id, label, own_token, offset, args)
                pushed[machine_id] = {"token": own_token, "base": offset, "ok": True, "at": now}
            except RuntimeError as exc:
                failures.append(f"{label}: {exc}")
                pushed[machine_id] = {"ok": False, "at": now}
                count = 0

        # A window skips machines it cannot reach, so they add no workspaces.
        if index + 1 < len(machines):
            if count is None:
                try:
                    count = len(list_workspaces(machine_id))
                except RuntimeError as exc:
                    failures.append(f"{label}: {exc}")
                    count = 0
            offset += count

    if not args.dry_run:
        save_state("pushed.json", pushed)
    return failures


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    own_token = args.token or configured_token()
    if not TOKEN_NAME.match(own_token):
        print(
            f"space-index: invalid token name {own_token!r}: use 1-27 letters, "
            "digits, `_` or `-`",
            file=sys.stderr,
        )
        return 2

    saved = saved_machines()
    machines = [] if args.local_only else saved

    try:
        with serialized("local"):
            workspaces = list_workspaces()
            bases = window_bases(own_token, workspaces, bool(saved), args.dry_run)
            failures = number_local_workspaces(workspaces, bases, args)
    except RuntimeError as exc:
        print(f"space-index: {exc}", file=sys.stderr)
        return 1

    # Saved machines go last and under their own lock, so a slow or
    # unreachable machine never holds up this server's own numbers.
    if machines:
        with serialized("push"):
            try:
                local_count = len(list_workspaces())
            except RuntimeError as exc:
                failures.append(str(exc))
            else:
                failures += push_bases(own_token, local_count, machines, args)

    for failure in failures:
        print(f"space-index: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
