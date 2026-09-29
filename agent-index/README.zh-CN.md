# herdr-agent-index

[English](README.md) | 简体中文

**在 Herdr 侧栏的每个 agent 前面显示编号**，让 `focus_agent = "prefix+alt+1..9"` 有看得见的目标。

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
[herdr-space-index](https://github.com/kadaliao/herdr-space-index) 给 workspace 编号是同一套思路。

## 安装

```bash
herdr plugin install kadaliao/herdr-agent-index -y
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
herdr plugin link ~/workspace/herdr-agent-index
# 或者指向任意路径的仓库：
herdr plugin link /absolute/path/to/herdr-agent-index
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

### 手动刷新

```bash
# 只打印将要写入的内容，不实际写入
python3 sync.py --dry-run

# 与权威列表对照
herdr agent list

# 看钩子是否执行、返回了什么
herdr plugin log list

# 通过插件 action 强制刷新
herdr plugin action invoke kadaliao.agent-index.refresh
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
herdr plugin install kadaliao/herdr-agent-index -y
```

## 要求与限制

- 需要 `python3` 在 `PATH` 上（插件命令是 argv 数组，不走 shell）。Python 3.11+ 才能读取
  `ui.agent_panel_sort`，更旧的版本按 `spaces` 处理。
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

再把 `~/.config/herdr/config.toml` 里的 `[ui.sidebar.agents]` 段删掉，或去掉其中的 `"$aidx"`。
