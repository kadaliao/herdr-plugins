# space-index

[English](README.md) | 简体中文

属于 [herdr-plugins](../README.zh-CN.md) 仓库。

**在 Herdr 侧栏的每个 workspace 前面显示切换编号**，让 `prefix+shift+1..9` 有看得见的目标。

## 解决的问题

Herdr 的 `switch_workspace = "prefix+shift+1..9"` 是按**侧栏顺序**跳转的，但展开的侧栏里 Space 行
没有内置编号 token —— 只支持 `state_icon`、`state_text`、`workspace`、`branch`、`git_status`
和自定义 `$token`。于是按 `prefix+shift+3` 之前，你得自己在心里数一遍行数。

这个插件把 `herdr workspace list` 里的编号作为只用于显示的 `$idx` token 上报，于是侧栏渲染成：

```
 1 ● Douban
   main
 2 ● Downloads
 3 ● Desktop
   main
```

编号与 `prefix+shift+1..9` 的目标完全一致，也和 `focus_agent = "prefix+alt+1..9"` 给 agent 面板
编号的用法凑成一套。添加了 SSH 机器时，编号沿侧栏跨机器连续，见[跨机器](#跨机器)。

## 安装

```bash
herdr plugin install kadaliao/herdr-plugins/space-index -y
```

然后在 `~/.config/herdr/config.toml` 里给 Space 行加上 `$idx`：

```toml
# `rows` 是「整体替换」而不是追加默认布局，所以这里把默认两行一并写全。
[ui.sidebar.spaces]
row_gap = 0
rows = [
  ["$idx", "state_icon", "workspace"],
  ["branch", "git_status"],
]
```

再在 Herdr 里按 `prefix+shift+r`（reload config），或执行：

```bash
herdr server reload-config
```

## 工作原理

`sync.py` 执行 `herdr workspace list`，再把每个 workspace 的 `number` 写入：

```bash
herdr workspace report-metadata <workspace_id> --source space-index --token idx=<number>
```

编号是**侧栏位置**，所以凡是会改变顺序的操作都要重新上报：

| 触发时机 | 原因 |
| --- | --- |
| `[[startup]]` | token metadata 不会在 server 重启后恢复，必须重新上报 |
| `workspace.created` / `workspace.closed` | 新增或关闭会改变其后所有编号 |
| `workspace.moved` / `workspace.reordered` | 拖动排序改变位置 |
| `workspace.focused`、`tab.created` / `focused`、`pane.created`、`pane.agent_detected` | 最后一个 workspace 关闭后，Herdr 会补开一个新的，但不发 `workspace.created`；靠它之后发生的下一件事给它编号 |
| `refresh` action | 手动兜底，见下 |
| `renumber` action | 添加了本机的另一台主机通过 `herdr --machine` 调用 |

已经正确上报的编号会跳过，所以没有变化时每次只花一次 `herdr workspace list` 调用。

事件白名单见 Herdr 源码 `src/api/schema/events.rs` 的 `PLUGIN_HOOK_EVENT_KINDS`。这不会造成死循环：
`workspace.metadata_updated` 明确不会触发插件事件钩子。

### 跨机器

添加了 [SSH 机器](https://herdr.dev/docs/connecting-machines/)后，一个窗口先列 Local 的
workspace，再按 `herdr machine list` 的顺序列每台已启用机器的，编号沿着这个列表连续往下：

```
▾ Local
  1 ● Douban
  2 ● Desktop
▾ workbox
  3 ● api
```

`switch_workspace` 只在当前所在的机器内切换，所以上面按 `prefix+shift+3` 到不了 `api`：其他机器上的
编号只标出它在窗口里的位置。键盘切到其他机器用 `next_workspace` / `previous_workspace`（它们按侧栏
顺序跨机器），或 `prefix+w`。

做法和 [agent-index](../agent-index/README.zh-CN.md#跨机器) 一样：每台机器都装本插件。添加了机器的
主机在每台机器上存一个数：它的窗口在这台机器之前列了多少个 workspace（workspace token
`<token>-base`），再调用那台机器的 `renumber` action；之后每个 server 为每个能看到它 workspace 的
窗口各写一个编号。**两台主机互相添加了对方**时两个窗口的机器顺序相反，所以给每台主机的 Space 行用
不同的 token 名（`$idx_laptop`、`$idx_server`），插件会从本机配置里读第一个 `$idx…` token。两台仍然
渲染同一个 token 时，各自保证自己的窗口正确，并在日志里给出警告。

### 手动刷新

```bash
# 只打印将要写入的内容，不实际写入
python3 sync.py --dry-run

# 与权威列表对照
herdr workspace list

# 看钩子是否执行、返回了什么
herdr plugin log list

# 通过插件 action 强制刷新：重写所有编号，并给每台已添加的机器重发 base
herdr plugin action invoke kadaliao.space-index.refresh
```

可选：把这个 action 绑到一个键上：

```toml
[[keys.command]]
key = "prefix+alt+i"
type = "plugin_action"
command = "kadaliao.space-index.refresh"
description = "refresh workspace numbers"
```

## 升级

Herdr 自己管理插件副本，所以重跑同一条安装命令即可更新到最新 commit：

```bash
herdr plugin install kadaliao/herdr-plugins/space-index -y
```

## 要求与限制

- 需要 `python3` 在 `PATH` 上（插件命令是 argv 数组，不走 shell）。
- Herdr ≥ 0.9.0（本插件针对该版本的 token 行为编写）。
- 只影响**展开**的桌面侧栏；折叠的 compact 栏和 mobile 布局是 Herdr 原生布局，本来就有编号。
- 编号是靠事件刷新的显示用元数据，最多滞后一次事件。
- 超过 9 个 workspace 时编号继续显示，但只有 1–9 有快捷键。
- Python 3.11+ 才能从配置读取 `$idx…` token 名，更旧的版本按 `idx` 处理。
- 跨机器编号需要每台机器都装本插件 0.2.0 及以上版本。窗口会跳过连不上的机器，编号也一样；主机会在
  一分钟后重试连不上的机器。
- 添加了两台及以上机器时，某台机器的 workspace 数变化，要等主机下一次变化或 `refresh` 才会传到排在
  它后面的机器。

## 卸载

```bash
herdr plugin uninstall kadaliao.space-index
```

再把 `~/.config/herdr/config.toml` 里的 `[ui.sidebar.spaces]` 段删掉，或去掉其中的 `"$idx"`。
