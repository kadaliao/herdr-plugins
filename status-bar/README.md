# status-bar

English | [简体中文](README.zh-CN.md)

Part of [herdr-plugins](../README.md).

**Network speed, battery, CPU, and memory in Herdr's tab-bar status area**, the way a tmux status
line shows them. Herdr's sidebar already covers spaces, agents, and git; this fills the corner it
leaves empty with the machine itself.

```
 1  2  +                        ↓1.2M ↑ 85K · cpu 23% · mem 61% · 🔋74%
```

| Segment | Shows | Example |
| --- | --- | --- |
| `net` | Download and upload speed of the interface carrying the default route | `↓1.2M ↑ 85K` |
| `battery` | Charge, with an icon for charging / on battery / plugged in. Hidden without a battery | `🔋74%` `⚡80%` `🔌100%` |
| `cpu` | Busy share of all cores since the previous refresh | `cpu 23%` |
| `mem` | Memory in use; on macOS the same figure as Activity Monitor's "Memory Used" | `mem 61%` |

All wording is configurable; see [Configuration](#configuration).

## Why a plugin

Since 0.8.2 Herdr has a tmux-style status area at the right edge of the tab row (`ui.tab_bar_right`),
with built-in `zoom`, `hostname`, `datetime`, and `text` entries plus `command` entries that show the
last line a shell command prints. It has no system metrics, and speeds need two readings of a
counter, which a one-shot command does not keep. This plugin supplies the commands and remembers the
readings.

Existing system-info plugins draw into the sidebar or the terminal window title instead, and none of
them shows network speed.

Two limits of the status area shape the output:

- **One color.** Herdr strips escape sequences from command output and draws every entry in the same
  muted color, so the defaults use words and arrows. The battery icons are emoji, which carry their
  own color.
- **All or nothing.** When the tab row is too narrow for a minimal tab strip plus the whole status
  area, Herdr hides the entire area. Pick the segments you look at.

## Install

```bash
herdr plugin install kadaliao/herdr-plugins/status-bar -y
# Startup hooks do not run on install, so write the launcher and a starter config once:
herdr plugin action invoke kadaliao.status-bar.setup
```

Then add entries to `[ui]` in `~/.config/herdr/config.toml`, keeping the ones you want:

```toml
[ui]
tab_bar_right = [
  { type = "command", command = "~/.local/state/herdr/plugins/kadaliao.status-bar/bar net", interval_seconds = 2 },
  { type = "command", command = "~/.local/state/herdr/plugins/kadaliao.status-bar/bar cpu", interval_seconds = 2 },
  { type = "command", command = "~/.local/state/herdr/plugins/kadaliao.status-bar/bar mem", interval_seconds = 5 },
  { type = "command", command = "~/.local/state/herdr/plugins/kadaliao.status-bar/bar battery", interval_seconds = 30 },
  { type = "zoom" },
]
tab_bar_right_separator = " · "
```

Reload with `prefix+shift+r` (reload config) inside Herdr, or:

```bash
herdr server reload-config
```

`interval_seconds` is also the window `net` and `cpu` average over. Which segments appear, and in what
order, is set in `tab_bar_right` itself. It accepts any command, so your own scripts can sit between
these segments.

### Local development

```bash
herdr plugin link ~/workspace/herdr-plugins/status-bar
herdr plugin action invoke kadaliao.status-bar.setup
```

## Configuration

What each segment says lives in the plugin's own config file:

```
~/.config/herdr/plugins/config/kadaliao.status-bar/config.toml
```

`setup` writes it with every key commented out at its default. The full reference is
[config.example.toml](config.example.toml). The file is read on every refresh, so edits show up within
`interval_seconds` without a reload.

Templates use Python format syntax: `{down:>4}` pads to four cells so the bar does not jitter as values
change, and `{name:.N}` cuts text to N terminal cells with `…`, counting CJK characters as two cells.
For example, Chinese labels and memory in gigabytes:

```toml
[net]
format = "网 ↓{down:>4} ↑{up:>4}"

[cpu]
format = "处理器 {percent:>2}%"

[mem]
format = "内存 {used}/{total}"
```

| Table | Keys | Placeholders |
| --- | --- | --- |
| `[net]` | `format`, `interface` (`auto` follows the default route, or a name such as `en0`) | `{down}` `{up}` `{interface}` |
| `[battery]` | `format`, and the `{icon}` for each state: `charging`, `discharging`, `charged` | `{percent}` `{icon}` `{state}` `{remaining}` |
| `[cpu]` | `format` | `{percent}` |
| `[mem]` | `format` | `{percent}` `{used}` `{total}` |

Values are at most four cells: `512B`, `9.9K`, `85K`, `1.2M`. Speeds are 1000-based as macOS shows them;
memory is 1024-based, so 32 GB of RAM reads `32G`.
`{remaining}` is macOS's time estimate, such as `4:12`, or empty while there is none.

After editing, check the file:

```bash
~/.local/state/herdr/plugins/kadaliao.status-bar/bar check
```

It prints every segment, or the exact error: an unknown key, or an unknown placeholder together with
the available ones. A config error makes that segment exit non-zero, and Herdr then hides it rather
than showing stale text.

## How it works

Herdr runs each `command` entry on the server through `/bin/sh -lc`, at most once per
`interval_seconds`, without overlapping runs, and kills it after `timeout_seconds` (default 2).
Values therefore describe the machine the Herdr server runs on, including under
`herdr --remote`.

| Segment | macOS | Linux |
| --- | --- | --- |
| `net` | `route -n get default`, then `netstat -ibn -I <interface>` | `/proc/net/route`, `/proc/net/dev` |
| `cpu` | `host_statistics` through `ctypes`, no subprocess | `/proc/stat` |
| `mem` | `vm_stat`: app memory (anonymous − purgeable) + wired + compressed, over `hw.memsize` | `MemTotal − MemAvailable` from `/proc/meminfo` |
| `battery` | `pmset -g batt` | `/sys/class/power_supply/BAT*` |

`net` and `cpu` turn cumulative counters into rates. Each call stores its reading in
`~/.local/state/herdr/plugins/kadaliao.status-bar/samples/`, and the next call divides the difference
by the time between them. A call takes well under 0.1 s. Only a first call, a call after more than
30 seconds, or a change of interface takes a fresh half-second sample instead.

Following the default route means a VPN tunnel is measured while it carries your traffic, rather than
counting the same bytes twice on the tunnel and the physical interface.

Status commands run outside the plugin runtime, so they cannot see `HERDR_PLUGIN_ROOT`. The plugin
keeps a small launcher at a stable path, `~/.local/state/herdr/plugins/kadaliao.status-bar/bar`
(`$XDG_STATE_HOME/herdr/...` when that is set). The launcher `exec`s `bar.py` from wherever the plugin
is installed, using the Python that ran `setup` and falling back to `python3`. The `[[startup]]` hook
rewrites it on every server start, and the `setup` action writes it on demand.

If an entry stays empty, run `bar check`, then look for `tab bar status command failed` in
`~/.config/herdr/herdr-server.log`, which says whether the command timed out or exited non-zero.

## Updating

Re-run the install command. The launcher points at the managed checkout, which keeps the same path,
and your config file is left alone:

```bash
herdr plugin install kadaliao/herdr-plugins/status-bar -y
```

## Requirements and limits

- Herdr ≥ 0.9.0 (the status area itself arrived in 0.8.2) and `python3`, with no other dependencies.
  Setting values in the config file needs Python 3.11+ (`tomllib`); an older Python runs with the
  defaults.
- Values are polled: `net` and `cpu` are averages over the last `interval_seconds`, and every value
  lags by up to that interval.
- Only the desktop tab row has a status area. With `hide_tab_bar_when_single_tab = true` it goes away
  together with the tab row.
- Emoji take two cells; a terminal without color emoji shows them as plain glyphs. Replace them in
  `[battery]` if they do not fit your font.

## Uninstall

```bash
herdr plugin uninstall kadaliao.status-bar
# linked locally instead? herdr plugin unlink kadaliao.status-bar
rm -r ~/.local/state/herdr/plugins/kadaliao.status-bar ~/.config/herdr/plugins/config/kadaliao.status-bar
```

Then drop the `bar` entries from `tab_bar_right` in `~/.config/herdr/config.toml`.
