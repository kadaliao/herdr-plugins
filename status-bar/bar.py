#!/usr/bin/env python3
"""Print one system-info segment for Herdr's tab-bar status area.

Herdr shows `ui.tab_bar_right` entries at the right edge of the tab row, and a
`command` entry displays the last line its command prints. Each call of this
script prints one segment:

    net      Download and upload speed of the default-route interface:
             `↓1.2M ↑ 85K`.
    battery  Charge and power state: `🔋74%`. Prints nothing without a battery.
    cpu      CPU busy share since the previous call: `cpu 23%`.
    mem      Memory in use, as Activity Monitor counts it on macOS: `mem 61%`.
    check    Validate the config file and print every segment.
    setup    Write the `bar` launcher, and a commented config file if there is
             none yet.

The wording of every segment comes from templates in the plugin config file,
~/.config/herdr/plugins/config/kadaliao.status-bar/config.toml; see
config.example.toml for every key and its default.

`net` and `cpu` report a rate between two readings of a cumulative counter.
Each call stores its reading under the plugin state directory, so the next call
measures across the whole refresh interval without sleeping. Only a first call,
or one after a long pause, samples for half a second.

Status commands run on the Herdr server through `/bin/sh -lc`, outside the
plugin runtime, so they cannot see HERDR_PLUGIN_ROOT. The launcher gives
config.toml a stable path to this script; the startup hook and the `setup`
action rewrite it. Empty output hides the entry, and so does a non-zero exit.

Usage:
    python3 bar.py {net,battery,cpu,mem,check} [--config PATH]
    python3 bar.py setup
"""

import argparse
import json
import os
import re
import shlex
import shutil
import string
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

PLUGIN_ID = "kadaliao.status-bar"
LAUNCHER_NAME = "bar"
EXAMPLE_CONFIG = Path(__file__).resolve().with_name("config.example.toml")
MACOS = sys.platform == "darwin"

# Keep in sync with config.example.toml.
DEFAULTS = {
    "net": {
        "format": "↓{down:>4} ↑{up:>4}",
        "interface": "auto",
    },
    "battery": {
        "format": "{icon}{percent}%",
        "charging": "⚡",
        "discharging": "🔋",
        "charged": "🔌",
    },
    "cpu": {
        "format": "cpu {percent:>2}%",
    },
    "mem": {
        "format": "mem {percent:>2}%",
    },
}

# A stored reading older than this no longer describes "now".
MAX_SAMPLE_AGE = 30.0
# Readings closer together than this give a noisy rate.
MIN_SAMPLE_GAP = 0.2
FRESH_SAMPLE_SECONDS = 0.5


class ConfigError(Exception):
    pass


def parse_args(argv):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        help="config file (default: the plugin config directory's config.toml)",
    )

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("net", "network speed"),
        ("battery", "battery charge"),
        ("cpu", "CPU usage"),
        ("mem", "memory usage"),
        ("check", "validate the config and print every segment"),
    ):
        commands.add_parser(name, parents=[common], help=text)
    commands.add_parser("setup", help="write the launcher and a starter config")
    return parser.parse_args(argv)


# ---------------------------------------------------------------- config


def config_file(override=None):
    if override:
        return Path(override).expanduser()
    plugin_dir = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    if plugin_dir:
        return Path(plugin_dir) / "config.toml"
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "herdr" / "plugins" / "config" / PLUGIN_ID / "config.toml"


def read_toml(path):
    try:
        import tomllib
    except ImportError:
        tomllib = None
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if tomllib is None:
        # The starter file is all comments and empty tables, so an old Python
        # can still run with defaults until the user sets something.
        settings = [
            line
            for line in raw.decode("utf-8", "replace").splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "["))
        ]
        if settings:
            raise ConfigError(f"{path}: reading settings needs Python 3.11+ (tomllib)")
        return {}
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load_config(override=None):
    path = config_file(override)
    config = {table: dict(values) for table, values in DEFAULTS.items()}
    for table, values in read_toml(path).items():
        if table not in DEFAULTS:
            raise ConfigError(f"{path}: unknown table `[{table}]`")
        if not isinstance(values, dict):
            raise ConfigError(f"{path}: `{table}` must be a table")
        for key, value in values.items():
            if key not in DEFAULTS[table]:
                raise ConfigError(f"{path}: unknown key `{table}.{key}`")
            if not isinstance(value, str):
                raise ConfigError(f"{path}: `{table}.{key}` must be a string")
            config[table][key] = value
    return config


# ------------------------------------------------------------- templates


def cell_width(text):
    return sum(
        0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        for ch in text
    )


def truncate(text, limit):
    """Cut text to `limit` terminal cells, ending with an ellipsis."""
    if cell_width(text) <= limit:
        return text
    if limit <= 0:
        return ""
    kept, used = [], 0
    for ch in text:
        width = cell_width(ch)
        if used + width > limit - 1:
            break
        kept.append(ch)
        used += width
    return "".join(kept).rstrip() + "…"


class CellFormatter(string.Formatter):
    """str.format, except `{text:.N}` cuts text to N terminal cells with `…`."""

    PRECISION = re.compile(r"\.(\d+)")

    def format_field(self, value, format_spec):
        match = self.PRECISION.fullmatch(format_spec)
        if isinstance(value, str) and match:
            return truncate(value, int(match.group(1)))
        return super().format_field(value, format_spec)


def render(template, where, **fields):
    try:
        return CellFormatter().format(template, **fields).strip()
    except KeyError as exc:
        available = " ".join(f"{{{name}}}" for name in fields)
        raise ConfigError(f"`{where}` uses unknown {{{exc.args[0]}}}; available: {available}") from exc
    except (ValueError, IndexError) as exc:
        raise ConfigError(f"`{where}` is not a valid template: {exc}") from exc


def human_bytes(value, base=1000):
    """Four cells at most: `512B`, `9.9K`, `85K`, `1.2M`.

    Speeds are 1000-based, as macOS shows them; memory is 1024-based, so
    32 GiB of RAM reads `32G` the way it is sold.
    """
    units = ("B", "K", "M", "G", "T")
    index = 0
    while value >= 999.5 and index < len(units) - 1:
        value /= base
        index += 1
    if index == 0:
        return f"{int(value)}B"
    return f"{value:.1f}{units[index]}" if value < 9.95 else f"{value:.0f}{units[index]}"


# ---------------------------------------------------------------- probes


def output(*argv):
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"`{' '.join(argv)}` failed: {result.stderr.strip()}")
    return result.stdout


def default_interface():
    if MACOS:
        match = re.search(r"interface:\s*(\S+)", output("route", "-n", "get", "default"))
        return match.group(1) if match else None
    with open("/proc/net/route") as handle:
        for line in handle.read().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 3 and fields[1] == "00000000" and int(fields[3], 16) & 2:
                return fields[0]
    return None


def interface_bytes(interface):
    """Cumulative (received, sent) bytes of one interface."""
    if MACOS:
        for line in output("netstat", "-ibn", "-I", interface).splitlines()[1:]:
            fields = line.split()
            # Address rows repeat the counters; the link row always exists.
            # Count from the end: an interface without a MAC has no address column.
            if len(fields) >= 7 and fields[2].startswith("<Link#"):
                return int(fields[-5]), int(fields[-2])
        raise RuntimeError(f"no counters for interface {interface}")
    with open("/proc/net/dev") as handle:
        for line in handle.read().splitlines()[2:]:
            name, _, counters = line.partition(":")
            if name.strip() == interface:
                values = counters.split()
                return int(values[0]), int(values[8])
    raise RuntimeError(f"no counters for interface {interface}")


def cpu_ticks():
    """Cumulative (busy, total) CPU ticks across all cores."""
    if MACOS:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        libc.mach_host_self.restype = ctypes.c_uint
        info = (ctypes.c_uint * 4)()  # user, system, idle, nice
        count = ctypes.c_uint(4)
        host_cpu_load_info = 3
        if libc.host_statistics(libc.mach_host_self(), host_cpu_load_info, info, ctypes.byref(count)):
            raise RuntimeError("host_statistics failed")
        user, system, idle, nice = info
        return user + system + nice, user + system + idle + nice
    with open("/proc/stat") as handle:
        values = [int(v) for v in handle.readline().split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    return sum(values) - idle, sum(values)


def memory_bytes():
    """(used, total) bytes of physical memory."""
    if MACOS:
        text = output("vm_stat")
        page = int(re.search(r"page size of (\d+) bytes", text).group(1))
        pages = {
            key.strip().strip('"'): int(value.strip().rstrip("."))
            for key, value in re.findall(r"^([^:\n]+):\s+(\d+)\.?$", text, re.MULTILINE)
        }
        # Activity Monitor's "Memory Used": app memory + wired + compressed.
        app = pages["Anonymous pages"] - pages["Pages purgeable"]
        used = (app + pages["Pages wired down"] + pages["Pages occupied by compressor"]) * page
        total = int(output("sysctl", "-n", "hw.memsize"))
        return used, total
    fields = {}
    with open("/proc/meminfo") as handle:
        for line in handle:
            key, _, value = line.partition(":")
            fields[key] = int(value.split()[0]) * 1024
    return fields["MemTotal"] - fields["MemAvailable"], fields["MemTotal"]


def battery_state():
    """(percent, state, remaining) or None; state is charging, discharging, or charged."""
    if MACOS:
        text = output("pmset", "-g", "batt")
        match = re.search(r"(\d+)%;\s*([^;]+);\s*([^\n]*)", text)
        if not match:
            return None
        percent, raw_state, rest = int(match.group(1)), match.group(2).strip(), match.group(3)
        if raw_state in ("charging", "finishing charge"):
            state = "charging"
        elif raw_state == "discharging":
            state = "discharging"
        else:  # "charged", "AC attached"
            state = "charged"
        remaining = re.match(r"(\d+:\d+) remaining", rest)
        clock = remaining.group(1) if remaining and remaining.group(1) != "0:00" else ""
        return percent, state, clock
    for supply in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            percent = int((supply / "capacity").read_text())
            raw_state = (supply / "status").read_text().strip().lower()
        except (OSError, ValueError):
            continue
        state = raw_state if raw_state in ("charging", "discharging") else "charged"
        return percent, state, ""
    return None


# --------------------------------------------------------------- samples


def state_dir():
    override = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "herdr" / "plugins" / PLUGIN_ID


def write_atomic(path, content, mode):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as handle:
        handle.write(content)
    os.chmod(temp, mode)
    os.replace(temp, path)


def rates(name, key, read):
    """Per-second change of the counters `read()` returns since the last call.

    `key` names what is being counted (an interface, say); a stored reading
    for another key, too old, too recent, or larger than now (a counter reset)
    is replaced by a fresh half-second sample.
    """
    path = state_dir() / "samples" / f"{name}.json"
    now, current = time.time(), read()
    try:
        stored = json.loads(path.read_text())
        before, then = stored["counters"], stored["time"]
        usable = (
            stored["key"] == key
            and MIN_SAMPLE_GAP <= now - then <= MAX_SAMPLE_AGE
            and len(before) == len(current)
            and all(b <= c for b, c in zip(before, current))
        )
    except (OSError, ValueError, KeyError, TypeError):
        usable = False
    if not usable:
        before, then = current, now
        time.sleep(FRESH_SAMPLE_SECONDS)
        now, current = time.time(), read()

    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps({"key": key, "time": now, "counters": current}), 0o644)
    elapsed = max(now - then, 1e-6)
    return [(c - b) / elapsed for b, c in zip(before, current)], [c - b for b, c in zip(before, current)]


# -------------------------------------------------------------- segments


def segment_net(config):
    settings = config["net"]
    interface = default_interface() if settings["interface"] == "auto" else settings["interface"]
    if not interface:
        return ""
    (down, up), _ = rates("net", interface, lambda: list(interface_bytes(interface)))
    return render(
        settings["format"],
        "net.format",
        down=human_bytes(down),
        up=human_bytes(up),
        interface=interface,
    )


def segment_battery(config):
    settings = config["battery"]
    battery = battery_state()
    if battery is None:
        return ""
    percent, state, remaining = battery
    return render(
        settings["format"],
        "battery.format",
        percent=percent,
        state=state,
        icon=settings[state],
        remaining=remaining,
    )


def segment_cpu(config):
    _, (busy, total) = rates("cpu", "all", lambda: list(cpu_ticks()))
    percent = round(100 * busy / total) if total > 0 else 0
    return render(config["cpu"]["format"], "cpu.format", percent=percent)


def segment_mem(config):
    used, total = memory_bytes()
    return render(
        config["mem"]["format"],
        "mem.format",
        percent=round(100 * used / total),
        used=human_bytes(used, base=1024),
        total=human_bytes(total, base=1024),
    )


SEGMENTS = {
    "net": segment_net,
    "battery": segment_battery,
    "cpu": segment_cpu,
    "mem": segment_mem,
}


# --------------------------------------------------------- setup / check


def setup():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    launcher = directory / LAUNCHER_NAME
    # Prefer the interpreter running this setup: a login shell's first
    # python3 can be an older system Python without tomllib.
    content = (
        "#!/bin/sh\n"
        f"# Written by {PLUGIN_ID}; ui.tab_bar_right commands call this launcher.\n"
        f"py={shlex.quote(sys.executable)}\n"
        '[ -x "$py" ] || py=python3\n'
        f'exec "$py" {shlex.quote(str(Path(__file__).resolve()))} "$@"\n'
    )
    try:
        current = launcher.read_text()
    except OSError:
        current = None
    if current != content:
        # Replace atomically so a status command never runs a half-written file.
        write_atomic(launcher, content, 0o755)
    print(launcher)

    config = config_file()
    if not config.exists():
        config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(EXAMPLE_CONFIG, config)
    print(config)


def check(override):
    path = config_file(override)
    print(f"config: {path}{'' if path.exists() else ' (missing, using defaults)'}")
    config = load_config(override)
    failed = False
    for name, segment in SEGMENTS.items():
        try:
            print(f"{name:<8} {segment(config)!r}")
        except (ConfigError, RuntimeError, OSError) as exc:
            failed = True
            print(f"{name:<8} error: {exc}")
    return 1 if failed else 0


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        if args.command == "setup":
            setup()
            return 0
        if args.command == "check":
            return check(args.config)
        text = SEGMENTS[args.command](load_config(args.config))
    except (ConfigError, RuntimeError, OSError) as exc:
        print(f"status-bar: {exc}", file=sys.stderr)
        return 1
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
