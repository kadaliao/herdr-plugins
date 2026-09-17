# herdr-space-index

English | [简体中文](README.zh-CN.md)

**Show each Herdr workspace's switch number in the sidebar**, so `prefix+shift+1..9` has visible targets.

## The problem

Herdr's `switch_workspace = "prefix+shift+1..9"` jumps by **sidebar position**, but an expanded sidebar
row has no built-in number token: Space rows only support `state_icon`, `state_text`, `workspace`,
`branch`, `git_status`, and custom `$tokens`. So before pressing `prefix+shift+3` you have to count rows
yourself.

This plugin reports the number from `herdr workspace list` as a display-only `$idx` token, so a row
renders as:

```
 1 ● Douban
   main
 2 ● Downloads
 3 ● Desktop
   main
```

Those numbers are exactly what `prefix+shift+1..9` targets, matching how
`focus_agent = "prefix+alt+1..9"` numbers the agent panel.

## Install

```bash
herdr plugin install kadaliao/herdr-space-index -y
```

Then add `$idx` to the Space rows in `~/.config/herdr/config.toml`:

```toml
# `rows` replaces the default layout instead of extending it, so the two
# default rows are written out in full here.
[ui.sidebar.spaces]
row_gap = 0
rows = [
  ["$idx", "state_icon", "workspace"],
  ["branch", "git_status"],
]
```

Reload with `prefix+shift+r` (reload config) inside Herdr, or:

```bash
herdr server reload-config
```

## How it works

`sync.py` runs `herdr workspace list` and writes each workspace's `number` with:

```bash
herdr workspace report-metadata <workspace_id> --source space-index --token idx=<number>
```

A number is a 1-based sidebar position, so every operation that changes the order has to re-report it:

| Trigger | Why |
| --- | --- |
| `[[startup]]` | Token metadata is not restored after a server restart, so it has to be repopulated |
| `workspace.created` / `workspace.closed` | Creating or closing a workspace renumbers everything after it |
| `workspace.moved` / `workspace.reordered` | Reordering changes the positions |
| `refresh` action | Manual escape hatch — see below |

The event whitelist is `PLUGIN_HOOK_EVENT_KINDS` in Herdr's `src/api/schema/events.rs`. This cannot loop
on itself: `workspace.metadata_updated` never invokes plugin event hooks.

### Manual refresh

```bash
# Show what would be reported without writing anything
python3 sync.py --dry-run

# Compare against the authoritative list
herdr workspace list

# Check whether hooks ran and what they returned
herdr plugin log list

# Force a refresh through the plugin action
herdr plugin action invoke kadaliao.space-index.refresh
```

Optionally bind that action to a key:

```toml
[[keys.command]]
key = "prefix+alt+i"
type = "plugin_action"
command = "kadaliao.space-index.refresh"
description = "refresh workspace numbers"
```

## Updating

Herdr keeps its own managed checkout, so re-run the install command to move to the latest commit:

```bash
herdr plugin install kadaliao/herdr-space-index -y
```

## Requirements and limits

- `python3` must be on `PATH` (plugin commands are argv arrays and do not go through a shell).
- Herdr ≥ 0.9.0, the version this token behavior is written against.
- Only the **expanded desktop sidebar** is affected. The collapsed compact rail and the mobile layout
  are Herdr's own and already number workspaces natively.
- Numbers are display-only metadata refreshed by events, so they can lag behind by at most one event.
- Beyond 9 workspaces the numbers keep rendering, but only 1–9 have keybindings.

## Uninstall

```bash
herdr plugin uninstall kadaliao.space-index
```

Then drop the `[ui.sidebar.spaces]` block from `~/.config/herdr/config.toml`, or remove `"$idx"` from it.
