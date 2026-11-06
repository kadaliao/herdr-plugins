# agent-index

[English](README.md) | 简体中文

属于 [herdr-plugins](../README.zh-CN.md) 仓库。

**在 Herdr 侧栏的每个 agent 前面显示编号**，让 `focus_agent = "prefix+alt+1..9"` 有看得见的目标。
添加了 SSH 机器时，编号按 `focus_agent` 的计数方式跨机器连续。

## 解决的问题

`focus_agent` 是按**agent 面板顺序**跳转的，但展开的 Agent 行没有内置编号 token —— 只支持
`state_icon`、`state_text`、`machine`、`workspace`、`tab`、`pane`、`agent`、
`terminal_title`、`terminal_title_stripped` 和自定义 `$token`。于是按 `prefix+alt+3` 之前，
你得自己在心里数一遍 agent 行数。

这个插件把 `herdr agent list` 里的顺序编号作为只用于显示的 `$aidx` token 上报，于是面板渲染成：

```
 1 ● Research  Pi
   working
 2 ✓ Desktop   Pi
   done
 3 ● Douban    Pi
   working
```

编号与 `prefix+alt+1..9` 的目标完全一致——和姊妹项目
[space-index](../space-index/) 给 workspace 编号是同一套思路。

## 安装

```bash
herdr plugin install kadaliao/herdr-plugins/agent-index -y
```

然后在 `~/.config/herdr/config.toml` 里给 Agent 行加上 `$aidx`：

```toml
# `rows` 是「整体替换」而不是追加默认布局，所以这里把默认两行一并写全。
[ui.sidebar.agents]
row_gap = 0
rows = [
  ["$aidx", "state_icon", "machine", "workspace", "tab"],
  ["agent"],
]
```

顺便把跳转键也绑上（`next_agent` / `previous_agent` / `focus_agent` 默认都没绑）：

```toml
[keys]
next_agent = "prefix+alt+]"
previous_agent = "prefix+alt+["
focus_agent = "prefix+alt+1..9"
```

再在 Herdr 里按 `prefix+shift+r`（reload config），或执行：

```bash
herdr server reload-config
```

### 本地开发

```bash
herdr plugin link ~/workspace/herdr-plugins/agent-index
# 或者指向任意路径的仓库：
herdr plugin link /absolute/path/to/herdr-plugins/agent-index
```

## 工作原理

`sync.py` 执行 `herdr agent list`，再把每个 agent 的 1-based 面板位置写入：

```bash
herdr pane report-metadata <pane_id> --source agent-index --token aidx=<number>
```

Herdr 自己的 agent list 本来就是面板顺序——先 space，再 tab，再 pane——所以插件直接按这个顺序编号，
凡是会改变顺序的操作都要重新上报：

| 触发时机 | 原因 |
| --- | --- |
| `[[startup]]` | token metadata 不会在 server 重启后恢复，必须重新上报 |
| `workspace.created` / `closed` / `moved` / `reordered` | space 顺序变了，里面的 agent 全部重排 |
| `tab.created` / `closed` / `moved` | tab 决定了 space 内 agent 的顺序 |
| `pane.created` / `closed` / `moved` / `exited` | pane 决定了 tab 内 agent 的顺序 |
| `pane.agent_detected` | agent 出现或退出会改变其后所有编号 |
| `pane.agent_status_changed` | 只有在 `ui.agent_panel_sort = "priority"` 时才会改变顺序 |
| `refresh` action | 手动兜底，见下 |
| `renumber` action | 添加了本机的另一台主机通过 `herdr --machine` 调用，见[跨机器](#跨机器) |

事件白名单见 Herdr 源码 `src/api/schema/events.rs` 的 `PLUGIN_HOOK_EVENT_KINDS`。这不会造成死循环：
metadata 上报不会触发插件事件钩子。

### 面板顺序

`ui.agent_panel_sort` 决定编号的含义，`sync.py` 会读你的配置，保证显示的数字和 `focus_agent`
的目标一致：

| 取值 | 顺序 |
| --- | --- |
| `spaces`（默认） | 先 space，再 tab，再 pane——即 `herdr agent list` 的顺序 |
| `priority` | `blocked`、`done`、`working`、`idle`、`unknown`；同一状态内最近一次状态变化优先 |

需要时可以手动指定：

```bash
python3 sync.py --sort priority --dry-run
```

### 跨机器

添加了 [SSH 机器](https://herdr.dev/docs/connecting-machines/)后，一个窗口先列 Local 的 agent，
再按 `herdr machine list` 的顺序列每台已启用机器的 agent，`focus_agent` 也按这个合并后的列表计数。
每台机器都装上本插件，编号就会跨机器连续：

```
 1 ● Local · Research  claude
 2 ● Local · Desktop   claude
 3 ● workbox · api     pi
```

每个 server 给自己的 agent 编号。添加了机器的主机还会在每台机器上存一个数：它的窗口在这台机器之前
列了多少个 agent（workspace token `<token>-base`），然后调用那台机器的 `renumber` action。那台机器
于是在自己的 agent pane 上写 `<token> = base + 位置`，之后它自己的事件也照此编号，所以那边新起的
agent 不用来回通信就能编上号。base 只在变化时重发（事件触发时最多每 10 分钟复核一次），机器会把它存进
插件 state 目录，server 重启后仍然有效。

**两台主机互相添加了对方**时，两个窗口的 agent 顺序相反，但所有窗口渲染的是同一份 pane token。
给每台主机的 Agent 行用不同的 token 名；插件会从本机配置里读第一个 `$aidx…` token，并为每个能看到
这个 agent 的窗口各写一个编号：

```toml
# 笔记本：~/.config/herdr/config.toml          # 服务器：~/.config/herdr/config.toml
["$aidx_laptop", "state_icon", "machine"]     ["$aidx_server", "state_icon", "machine"]
```

如果多台机器共用一份配置（chezmoi 之类），把这个 token 名按主机做成模板。两台主机仍然渲染同一个
token 时，各自保证自己的窗口正确（本机 agent 从 1 开始），并在日志里给出警告。

限制：

- 只适用于 `ui.agent_panel_sort = "spaces"`。priority 顺序按客户端看到的先后把所有机器的 agent
  交错排列，server 无从得知，所以 `priority` 下每个 server 只给自己的 agent 从 1 编号。
- 窗口会跳过连不上的机器，编号也一样。主机会在一分钟后重试连不上的机器。
- 添加了两台及以上机器时，某台机器的 agent 数变化，要等主机下一次变化或 `refresh` 才会传到排在它
  后面的机器。

### 手动刷新

```bash
# 只打印将要写入的内容，不实际写入
python3 sync.py --dry-run

# 与权威列表对照
herdr agent list

# 看钩子是否执行、返回了什么
herdr plugin log list

# 通过插件 action 强制刷新：重写所有编号，并给每台已添加的机器重发 base
herdr plugin action invoke kadaliao.agent-index.refresh

# 看某台已添加机器上报的内容
herdr --machine <label> agent list
```

可选：把这个 action 绑到一个键上：

```toml
[[keys.command]]
key = "prefix+alt+i"
type = "plugin_action"
command = "kadaliao.agent-index.refresh"
description = "refresh agent numbers"
```

## 升级

Herdr 自己管理插件副本，所以重跑同一条安装命令即可更新到最新 commit：

```bash
herdr plugin install kadaliao/herdr-plugins/agent-index -y
```

## 要求与限制

- 需要 `python3` 在 `PATH` 上（插件命令是 argv 数组，不走 shell）。Python 3.11+ 才能从配置读取
  `ui.agent_panel_sort` 和 `$aidx…` token 名，更旧的版本按 `spaces` 和 `aidx` 处理。
- 跨机器编号需要每台机器都装本插件 0.2.0 及以上版本。
- Herdr ≥ 0.9.0（本插件针对该版本的 token 行为编写）。
- 只影响**展开**的桌面侧栏；折叠的 compact 栏和 mobile 布局保持 Herdr 原生紧凑 Agent 行。
- 编号是靠事件刷新的显示用元数据，最多滞后一次事件。
- 如果某个插件用 `agent.view.set` 安装了自己的排序视图，本插件仍然给配置里的顺序编号。
- 超过 9 个 agent 时编号继续显示，但只有 1–9 有快捷键。

## 卸载

```bash
herdr plugin uninstall kadaliao.agent-index
# 本地 link 的用：herdr plugin unlink kadaliao.agent-index
```

再把 `~/.config/herdr/config.toml` 里的 `[ui.sidebar.agents]` 段删掉，或去掉其中的 `$aidx…` token。
