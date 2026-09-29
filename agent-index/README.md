# herdr-agent-index

English | [简体中文](README.zh-CN.md)

**Show each Herdr agent's panel number in the sidebar**, so `focus_agent = "prefix+alt+1..9"` has
visible targets.

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
[herdr-space-index](https://github.com/kadaliao/herdr-space-index) plugin for workspaces.

## Install

```bash
herdr plugin install kadaliao/herdr-agent-index -y
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
herdr plugin link ~/workspace/herdr-agent-index
# or, for a checkout anywhere else:
herdr plugin link /absolute/path/to/herdr-agent-index
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

### Manual refresh

```bash
# Show what would be reported without writing anything
python3 sync.py --dry-run

# Compare against the authoritative list
herdr agent list

# Check whether hooks ran and what they returned
herdr plugin log list

# Force a refresh through the plugin action
herdr plugin action invoke kadaliao.agent-index.refresh
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
herdr plugin install kadaliao/herdr-agent-index -y
```

## Requirements and limits

- `python3` must be on `PATH` (plugin commands are argv arrays and do not go through a shell).
  Python 3.11+ reads `ui.agent_panel_sort` from your config; older versions fall back to `spaces`.
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

Then drop `[ui.sidebar.agents]` from `~/.config/herdr/config.toml`, or just remove `"$aidx"` from it.
