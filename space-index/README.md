# herdr-space-index

**给 Herdr 侧栏的每个 workspace 显示编号** —— 让 `prefix+shift+1..9` 这个「按编号跳转」有了看得见的目标。

---

## 它解决什么问题

Herdr 的 `switch_workspace = "prefix+shift+1..9"` 按**侧栏顺序**跳转，但展开的侧栏里 Space 行只支持
`state_icon` / `state_text` / `workspace` / `branch` / `git_status` / 自定义 `$token`，**没有内置编号 token**。
于是你按 `prefix+shift+3` 之前，得自己在心里数一遍。

这个插件把编号作为自定义 token `$idx` 上报，侧栏就能渲染成：

```
 1 ● Douban
   main
 2 ● Downloads
 3 ● Desktop
   main
```

编号与 `prefix+shift+1..9` 的目标完全一致，也顺便和 `focus_agent = "prefix+alt+1..9"` 的用法凑成一套。

## 安装

```bash
herdr plugin install kadaliao/herdr-space-index -y
```

然后在 `~/.config/herdr/config.toml` 里给 Space 行加上 `$idx`：

```toml
# rows 是「整体替换」而不是追加，所以把默认两行一并写全。
[ui.sidebar.spaces]
row_gap = 0
rows = [
  ["$idx", "state_icon", "workspace"],
  ["branch", "git_status"],
]
```

再在 Herdr 里按 `prefix+shift+r`（reload config），或执行 `herdr server reload-config`。

## 工作原理

`sync.py` 执行 `herdr workspace list`，把每个 workspace 的 `number` 用
`herdr workspace report-metadata <id> --source space-index --token idx=<n>` 写入。

编号是**侧栏位置**，所以凡是会改变顺序的操作都要重新上报：

| 触发时机 | 原因 |
| --- | --- |
| `[[startup]]` | token metadata 不会在 server 重启后恢复，必须重新上报 |
| `workspace.created` / `workspace.closed` | 新增/关闭会改变其后所有编号 |
| `workspace.moved` / `workspace.reordered` | 拖动排序改变编号 |
| `refresh` action（可自行绑键） | 手动兜底 |

事件白名单见 Herdr 源码 `src/api/schema/events.rs` 的 `PLUGIN_HOOK_EVENT_KINDS`；这不构成死循环，
因为 `workspace.metadata_updated` 明确不会触发插件钩子。

手动刷新 / 排查：

```bash
# 看会写入什么，不实际写入
python3 sync.py --dry-run
herdr workspace list   # 对照 number 字段
herdr plugin log list  # 看钩子是否执行成功
```

可选：把 refresh action 绑到一个键上：

```toml
[[keys.command]]
key = "prefix+alt+i"
type = "plugin_action"
command = "kadaliao.space-index.refresh"
description = "refresh workspace numbers"
```

## 要求与限制

- 需要 `python3` 在 `PATH` 上（插件命令是 argv 数组，不走 shell）。
- Herdr ≥ 0.9.0（`workspace.report_metadata` 的 token 行为以此版本为准）。
- 只影响**展开**的桌面侧栏；折叠（compact）与 mobile 视图是 Herdr 原生布局，本来就有编号。
- 数字靠事件刷新，属于「显示用元数据」，不参与任何语义状态；极端情况下可能滞后一次事件。
- 超过 9 个 workspace 时编号继续显示,但只有 1–9 有快捷键。

## 卸载

```bash
herdr plugin uninstall kadaliao.space-index
# 再把 config.toml 里的 [ui.sidebar.spaces] 段删掉或去掉 "$idx"
```

---

## English

**Show each Herdr workspace's switch number in the sidebar**, so `prefix+shift+1..9` has visible targets.

Herdr's `switch_workspace` indexes workspaces by sidebar position, but the expanded sidebar has no
built-in number token for Space rows. This plugin reports `herdr workspace list`'s `number` field as a
display-only `$idx` token, refreshed on `workspace.created` / `closed` / `moved` / `reordered` and once
per server start.

```bash
herdr plugin install kadaliao/herdr-space-index -y
```

```toml
[ui.sidebar.spaces]
row_gap = 0
rows = [
  ["$idx", "state_icon", "workspace"],
  ["branch", "git_status"],
]
```

Requires `python3` on `PATH` and Herdr ≥ 0.9.0. Only the expanded desktop sidebar is affected; the
collapsed compact rail already numbers workspaces natively.
