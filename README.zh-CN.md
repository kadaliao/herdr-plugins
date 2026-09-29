# herdr-plugins

[English](README.md) | 简体中文

[Herdr](https://herdr.dev) 侧栏插件合集。每个插件占一个目录，各自带 `herdr-plugin.toml`，
可以单独安装，在 [Herdr 插件市场](https://herdr.dev/plugins/) 里也各自显示为一行。

| 插件 | 作用 | 安装 |
| --- | --- | --- |
| [space-index](space-index/) | 给侧栏里的每个 workspace 编号，让 `prefix+shift+1..9` 有看得见的目标 | `herdr plugin install kadaliao/herdr-plugins/space-index -y` |
| [agent-index](agent-index/) | 给侧栏里的每个 agent 编号，让 `focus_agent = "prefix+alt+1..9"` 有看得见的目标 | `herdr plugin install kadaliao/herdr-plugins/agent-index -y` |

配置方法、工作原理和限制见各目录的 README。所有插件都需要 Herdr ≥ 0.9.0 和 `PATH` 上的 `python3`。

## 从独立仓库迁移

`space-index` 和 `agent-index` 原先是独立仓库 `kadaliao/herdr-space-index` 和
`kadaliao/herdr-agent-index`。如果你从旧仓库安装过，改从本仓库重装即可；插件 id
（`kadaliao.space-index`、`kadaliao.agent-index`）、你的配置和快捷键绑定都不变：

```bash
herdr plugin uninstall kadaliao.space-index
herdr plugin install kadaliao/herdr-plugins/space-index -y
```

## 本地开发

```bash
git clone git@github.com:kadaliao/herdr-plugins.git ~/workspace/herdr-plugins
herdr plugin link ~/workspace/herdr-plugins/space-index
herdr plugin link ~/workspace/herdr-plugins/agent-index
```

从 GitHub 重装会替换 Herdr 托管的副本，所以更新就是重跑安装命令。
