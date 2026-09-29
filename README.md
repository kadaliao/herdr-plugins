# herdr-plugins

English | [简体中文](README.zh-CN.md)

Sidebar plugins for [Herdr](https://herdr.dev). Each plugin lives in its own directory with its own
`herdr-plugin.toml`, so it installs separately and shows up as its own row on the
[Herdr marketplace](https://herdr.dev/plugins/).

| Plugin | What it does | Install |
| --- | --- | --- |
| [space-index](space-index/) | Number each workspace in the sidebar so `prefix+shift+1..9` has visible targets | `herdr plugin install kadaliao/herdr-plugins/space-index -y` |
| [agent-index](agent-index/) | Number each agent in the sidebar so `focus_agent = "prefix+alt+1..9"` has visible targets | `herdr plugin install kadaliao/herdr-plugins/agent-index -y` |

Each directory's README covers configuration, how it works, and limits. All plugins need Herdr ≥ 0.9.0
and `python3` on `PATH`.

## Moved from separate repositories

`space-index` and `agent-index` used to be the standalone repositories `kadaliao/herdr-space-index`
and `kadaliao/herdr-agent-index`. If you installed from one of those, reinstall from this repository;
the plugin ids (`kadaliao.space-index`, `kadaliao.agent-index`), your config, and any key bindings stay
the same:

```bash
herdr plugin uninstall kadaliao.space-index
herdr plugin install kadaliao/herdr-plugins/space-index -y
```

## Local development

```bash
git clone git@github.com:kadaliao/herdr-plugins.git ~/workspace/herdr-plugins
herdr plugin link ~/workspace/herdr-plugins/space-index
herdr plugin link ~/workspace/herdr-plugins/agent-index
```

Reinstalling from GitHub replaces the managed checkout, so re-run the install command to update.
