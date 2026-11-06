# agent-index

English | [简体中文](README.zh-CN.md)

Part of [herdr-plugins](../README.md).

**Show each Herdr agent's panel number in the sidebar**, so `focus_agent = "prefix+alt+1..9"` has
visible targets. With saved SSH machines, the numbers continue across machines the way `focus_agent`
counts them.

## The problem

`focus_agent` jumps by **agent-panel position**, but an expanded Agent row has no built-in number
token: Agent rows only support `state_icon`, `state_text`, `machine`, `workspace`, `tab`, `pane`,
`agent`, `terminal_title`, `terminal_title_stripped`, and custom `$tokens`. So before pressing
`prefix+alt+3` you have to count agent rows yourself.

This plugin reports the number from `herdr agent list` as a display-only `$aidx` token, so the panel
renders as:

```
 1 ● Research  Pi
   working
 2 ✓ Desktop   Pi
   done
 3 ● Douban    Pi
   working
```

Those numbers are exactly what `prefix+alt+1..9` targets — the same idea as the sibling
[space-index](../space-index/) plugin for workspaces.

## Install

```bash
herdr plugin install kadaliao/herdr-plugins/agent-index -y
```

Then add `$aidx` to the Agent rows in `~/.config/herdr/config.toml`:

```toml
# `rows` replaces the default layout instead of extending it, so the two
# default rows are written out in full here.
[ui.sidebar.agents]
row_gap = 0
rows = [
  ["$aidx", "state_icon", "machine", "workspace", "tab"],
  ["agent"],
]
```

Bind the jumps too (`next_agent` / `previous_agent` / `focus_agent` are unset by default):

```toml
[keys]
next_agent = "prefix+alt+]"
previous_agent = "prefix+alt+["
focus_agent = "prefix+alt+1..9"
```

Reload with `prefix+shift+r` (reload config) inside Herdr, or:

```bash
herdr server reload-config
```

### Local development

```bash
herdr plugin link ~/workspace/herdr-plugins/agent-index
# or, for a checkout anywhere else:
herdr plugin link /absolute/path/to/herdr-plugins/agent-index
```

## How it works

`sync.py` runs `herdr agent list` and writes each agent's 1-based panel position with:

```bash
herdr pane report-metadata <pane_id> --source agent-index --token aidx=<number>
```

Herdr's own agent list already arrives in panel order — space, then tab, then pane — so the plugin
numbers the list as-is and re-reports whenever that order can change:

| Trigger | Why |
| --- | --- |
| `[[startup]]` | Token metadata is not restored after a server restart, so it has to be repopulated |
| `workspace.created` / `closed` / `moved` / `reordered` | Reordering spaces renumbers the agents inside them |
| `tab.created` / `closed` / `moved` | Tabs order the agents inside a space |
| `pane.created` / `closed` / `moved` / `exited` | Panes order the agents inside a tab |
| `pane.agent_detected` | An agent appearing or leaving shifts every number after it |
| `pane.agent_status_changed` | Only changes the order while `ui.agent_panel_sort = "priority"` |
| `refresh` action | Manual escape hatch — see below |
| `renumber` action | Invoked over `herdr --machine` by a host that saved this machine — see [Across machines](#across-machines) |

The event whitelist is `PLUGIN_HOOK_EVENT_KINDS` in Herdr's `src/api/schema/events.rs`. This cannot
loop on itself: metadata reports do not emit plugin event hooks.

### Panel order

`ui.agent_panel_sort` decides what the numbers mean, and `sync.py` reads it from your config so the
displayed numbers always match what `focus_agent` targets:

| Sort | Order |
| --- | --- |
| `spaces` (default) | Space, then tab, then pane — the order of `herdr agent list` |
| `priority` | `blocked`, `done`, `working`, `idle`, `unknown`; newest state change first inside one status |

Override the detection when you need to:

```bash
python3 sync.py --sort priority --dry-run
```

### Across machines

With [saved SSH machines](https://herdr.dev/docs/connecting-machines/), a window lists Local's agents
first, then each enabled machine's agents in `herdr machine list` order, and `focus_agent` counts
through that combined list. Install the plugin on every machine and the numbers continue across them:

```
 1 ● Local · Research  claude
 2 ● Local · Desktop   claude
 3 ● workbox · api     pi
```

Each server numbers its own agents. A host with saved machines also stores, on each of them, how many
agents its window lists before that machine — as the workspace token `<token>-base` — and invokes that
machine's `renumber` action. The machine then reports `<token> = base + position` on its agent panes
and keeps doing so on its own events, so an agent starting there is numbered without any round trip.
A base is re-sent only when it changes (and re-checked at most every 10 minutes), and the machine keeps
it in its plugin state directory, so it survives a server restart.

**Two hosts that save each other** list agents in opposite orders, but every window renders the same
pane tokens. Give each host's agent rows its own token name; the plugin reads the first `$aidx…` token
from the host's config and reports one number for every window that shows an agent:

```toml
# laptop: ~/.config/herdr/config.toml        # server: ~/.config/herdr/config.toml
["$aidx_laptop", "state_icon", "machine"]     ["$aidx_server", "state_icon", "machine"]
```

If you share one config between machines (chezmoi and the like), template that token name per host.
If both hosts still render the same token, each keeps its own window right — local agents from 1 —
and logs a warning.

Limits:

- Only with `ui.agent_panel_sort = "spaces"`. Priority order interleaves every machine's agents by
  client-side recency, which no server can see, so with `priority` each server numbers its own agents
  from 1.
- A window skips machines it cannot reach, and so does the numbering. A host retries an unreachable
  machine after a minute.
- With two or more saved machines, a change in one machine's agent count reaches the machines listed
  after it only at the host's next change or `refresh`.

### Manual refresh

```bash
# Show what would be reported without writing anything
python3 sync.py --dry-run

# Compare against the authoritative list
herdr agent list

# Check whether hooks ran and what they returned
herdr plugin log list

# Force a refresh through the plugin action: re-reports every number and
# re-sends every saved machine its base
herdr plugin action invoke kadaliao.agent-index.refresh

# What a saved machine reports
herdr --machine <label> agent list
```

Optionally bind that action to a key:

```toml
[[keys.command]]
key = "prefix+alt+i"
type = "plugin_action"
command = "kadaliao.agent-index.refresh"
description = "refresh agent numbers"
```

## Updating

Herdr keeps its own managed checkout, so re-run the install command to move to the latest commit:

```bash
herdr plugin install kadaliao/herdr-plugins/agent-index -y
```

## Requirements and limits

- `python3` must be on `PATH` (plugin commands are argv arrays and do not go through a shell).
  Python 3.11+ reads `ui.agent_panel_sort` and the `$aidx…` token name from your config; older
  versions fall back to `spaces` and `aidx`.
- Cross-machine numbers need this plugin, 0.2.0 or later, on every machine.
- Herdr ≥ 0.9.0, the version this token behavior is written against.
- Only the **expanded desktop sidebar** is affected. The collapsed compact rail and the mobile layout
  keep Herdr's own compact Agent rows.
- Numbers are display-only metadata refreshed by events, so they can lag behind by at most one event.
- A plugin-installed `agent.view.set` projection reorders the panel with its own sort; this plugin
  keeps numbering the config-based order in that case.
- Beyond 9 agents the numbers keep rendering, but only 1–9 have keybindings.

## Uninstall

```bash
herdr plugin uninstall kadaliao.agent-index
# linked locally instead? herdr plugin unlink kadaliao.agent-index
```

Then drop `[ui.sidebar.agents]` from `~/.config/herdr/config.toml`, or just remove the `$aidx…` token
from it.
