#!/usr/bin/env python3
"""Report every Herdr agent's panel number as a display-only pane token.

An agent's number is its 1-based position in the agent panel, which is exactly
what `focus_agent = "prefix+alt+1..9"` targets. Agent rows have no built-in
number token, so this plugin reports one that an expanded sidebar row can
render as `$aidx`.

The panel order comes from `ui.agent_panel_sort`:

    spaces    (default)  `herdr agent list` order: space, then tab, then pane.
    priority             blocked, done, working, idle, unknown; within one
                         status the most recent state change first.

Across machines (spaces order only)
-----------------------------------
A window with saved SSH machines lists Local's agents first, then each enabled
machine's agents in `herdr machine list` order, and `focus_agent` counts
through that combined list. So an agent on a saved machine is numbered after
every agent listed before its machine.

Every window renders the same pane tokens. When two hosts save each other,
their windows count in opposite orders, so give each host its own token name in
its sidebar rows (`$aidx_mbp`, `$aidx_mm`); this script reads the name from the
host's config. Each run then:

1. numbers this server's agents for every window that shows them: this host's
   own window from 1, and any other window from the base it stored here as a
   `<token>-base` workspace token;
2. if this host has saved machines, stores this window's base on each of them
   and asks their copy of this plugin to renumber (the `renumber` action, which
   runs with --local-only). A base is only re-sent when it changes.

Herdr injects HERDR_BIN_PATH for plugin commands; without it the `herdr` binary
on PATH is used.

Usage:
    python3 sync.py [--dry-run] [--force] [--local-only]
                    [--token NAME] [--source ID] [--sort SORT]
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

DEFAULT_SOURCE = "agent-index"
DEFAULT_TOKEN = "aidx"
BASE_SUFFIX = "-base"
RENUMBER_ACTION = "kadaliao.agent-index.renumber"

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
        "--force",
        action="store_true",
        help="re-report every token and re-send every base",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="only number this server's agents; do not update saved machines",
    )
    parser.add_argument(
        "--token",
        help=(
            "token this host's window renders "
            f"(default: the first $aidx… token in config.toml, else {DEFAULT_TOKEN})"
        ),
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


def load_config():
    try:
        import tomllib
    except ImportError:
        return {}
    try:
        with open(config_path(), "rb") as handle:
            return tomllib.load(handle)
    except (OSError, ValueError):
        return {}


def table(value):
    return value if isinstance(value, dict) else {}


def configured_sort(config):
    """Read ui.agent_panel_sort so numbers match what focus_agent targets."""
    value = table(config.get("ui")).get("agent_panel_sort", "")
    return "priority" if str(value).strip().lower() == "priority" else "spaces"


def configured_token(config):
    """Return the $aidx… token this host's agent rows render, without the `$`."""
    agents = table(table(table(config.get("ui")).get("sidebar")).get("agents"))
    layouts = [agents.get("rows"), *table(agents.get("rows_by_agent")).values()]
    for rows in layouts:
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
    path = Path(tempfile.gettempdir()) / "kadaliao.agent-index"
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
        print(f"agent-index: could not save {path}: {exc}", file=sys.stderr)


@contextlib.contextmanager
def serialized(name):
    """Serialize concurrent hook runs with an advisory lock.

    State is read after the lock is taken, so the run that writes last is
    working from the freshest order instead of a stale snapshot.
    """
    try:
        handle = open(state_dir() / f"agent-index.{name}.lock", "w")
    except OSError:
        yield
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def ordered_agents(sort, machine=None):
    """Return the agents of one server in agent-panel order."""
    try:
        agents = run_json("agent", "list", machine=machine)["result"]["agents"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"unexpected `herdr agent list` output: {exc}") from exc

    if sort == "priority":
        agents = sorted(
            agents,
            key=lambda agent: (
                -STATUS_PRIORITY.get(str(agent.get("agent_status", "")).lower(), 0),
                -int(agent.get("state_change_seq") or 0),
            ),
        )
    return [agent for agent in agents if isinstance(agent.get("pane_id"), str)]


def list_workspaces(machine=None):
    try:
        return run_json("workspace", "list", machine=machine)["result"]["workspaces"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"unexpected `herdr workspace list` output: {exc}") from exc


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
                and TOKEN_NAME.match(token)
                and isinstance(value, str)
                and value.isdigit()
            ):
                bases.setdefault(token, int(value))
    return bases


def window_bases(own_token, sort, is_hub, dry_run):
    """Return {token: base} for every window that shows this server's agents.

    Bases are also kept in the plugin state directory, because workspace
    tokens do not survive a server restart.
    """
    if sort != "spaces":
        return {own_token: 0}

    saved = {
        token: base
        for token, base in load_state("bases.json").items()
        if TOKEN_NAME.match(token) and isinstance(base, int) and base >= 0
    }
    bases = {**saved, **stored_bases(list_workspaces())}
    if bases != saved and not dry_run:
        save_state("bases.json", bases)

    if own_token in bases and is_hub:
        # Another window renders the same token as this host's own window, so
        # one of them would be wrong; this host's window wins.
        print(
            f"agent-index: another machine's window also renders ${own_token}; "
            "give each host its own $aidx… token so both windows can be numbered",
            file=sys.stderr,
        )
        bases[own_token] = 0
    bases.setdefault(own_token, 0)
    return bases


def number_local_agents(agents, bases, args):
    """Report every window's number on this server's agent panes."""
    failures = []
    for position, agent in enumerate(agents, start=1):
        pane_id = agent["pane_id"]
        wanted = {token: str(base + position) for token, base in sorted(bases.items())}
        if args.dry_run:
            pairs = " ".join(f"{token}={value}" for token, value in wanted.items())
            print(f"{pane_id} {pairs}")
            continue
        current = table(agent.get("tokens"))
        if not args.force and all(current.get(t) == v for t, v in wanted.items()):
            continue
        items = list(wanted.items())
        for start in range(0, len(items), MAX_TOKENS_PER_REPORT):
            command = ["pane", "report-metadata", pane_id, "--source", args.source]
            for token, value in items[start : start + MAX_TOKENS_PER_REPORT]:
                command += ["--token", f"{token}={value}"]
            reported = run(*command)
            if reported.returncode != 0:
                failures.append(
                    f"{pane_id}: {reported.stderr.strip() or 'report-metadata failed'}"
                )
                break
    return failures


def push_base(machine, label, own_token, base, args):
    """Store this window's base on a saved machine and ask it to renumber."""
    key = f"{own_token}{BASE_SUFFIX}"
    workspaces = list_workspaces(machine)
    if not workspaces:
        raise RuntimeError("no workspaces to store the base on")
    for workspace in workspaces:
        if table(workspace.get("tokens")).get(key) == str(base):
            continue
        if args.dry_run:
            print(f"{label}:{workspace.get('workspace_id')} {key}={base}")
            continue
        reported = run(
            "workspace",
            "report-metadata",
            str(workspace.get("workspace_id")),
            "--source",
            args.source,
            "--token",
            f"{key}={base}",
            machine=machine,
        )
        if reported.returncode != 0:
            raise RuntimeError(reported.stderr.strip() or "report-metadata failed")
    if args.dry_run:
        return
    # Ask even when the base was already there: the machine may have stored it
    # while its plugin was missing or too old to renumber.
    invoked = run("plugin", "action", "invoke", RENUMBER_ACTION, machine=machine)
    if invoked.returncode != 0:
        # The base is stored, so the machine's own plugin picks it up on its
        # next event once it is installed and up to date there.
        print(
            f"agent-index: stored {key}={base} on {label}, but could not ask it "
            f"to renumber: {invoked.stderr.strip() or 'action invoke failed'}",
            file=sys.stderr,
        )


def push_bases(own_token, local_count, machines, args):
    """Tell each saved machine where its agents start in this host's window."""
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
        reachable = True
        if not args.force and entry.get("ok") is False and age < RETRY_AFTER_FAILURE_SECONDS:
            reachable = False
        elif args.force or not (entry.get("ok") and current and age < RECHECK_AFTER_SECONDS):
            try:
                push_base(machine_id, label, own_token, offset, args)
                pushed[machine_id] = {"token": own_token, "base": offset, "ok": True, "at": now}
            except RuntimeError as exc:
                failures.append(f"{label}: {exc}")
                pushed[machine_id] = {"ok": False, "at": now}
                reachable = False

        # A window skips machines it cannot reach, so they add no agents.
        if reachable and index + 1 < len(machines):
            try:
                offset += len(ordered_agents("spaces", machine=machine_id))
            except RuntimeError as exc:
                failures.append(f"{label}: {exc}")

    if not args.dry_run:
        save_state("pushed.json", pushed)
    return failures


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    config = load_config()
    sort = configured_sort(config) if args.sort == "auto" else args.sort
    own_token = args.token or configured_token(config)
    if not TOKEN_NAME.match(own_token):
        print(
            f"agent-index: invalid token name {own_token!r}: use 1-27 letters, "
            "digits, `_` or `-`",
            file=sys.stderr,
        )
        return 2

    # Cross-machine numbering follows spaces order; priority order interleaves
    # every machine's agents by client-side recency, which a server cannot see.
    saved = saved_machines() if sort == "spaces" else []
    machines = [] if args.local_only else saved

    try:
        with serialized("local"):
            agents = ordered_agents(sort)
            bases = window_bases(own_token, sort, bool(saved), args.dry_run)
            failures = number_local_agents(agents, bases, args)
    except RuntimeError as exc:
        print(f"agent-index: {exc}", file=sys.stderr)
        return 1

    # Saved machines go last and under their own lock, so a slow or
    # unreachable machine never holds up this server's own numbers.
    if machines:
        with serialized("push"):
            try:
                local_count = len(ordered_agents(sort))
            except RuntimeError as exc:
                failures.append(str(exc))
            else:
                failures += push_bases(own_token, local_count, machines, args)

    for failure in failures:
        print(f"agent-index: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
