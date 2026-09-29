# status-bar

[English](README.md) | 简体中文

属于 [herdr-plugins](../README.zh-CN.md) 仓库。

**在 Herdr tab 栏右侧状态区显示网速、电量、CPU 和内存**，就像 tmux 状态栏那样。Herdr 的侧栏已经管了
space、agent 和 git，这个插件只补上它留空的那一角：机器本身的状态。

```
 1  2  +                        ↓1.2M ↑ 85K · cpu 23% · mem 61% · 🔋74%
```

| 段 | 显示内容 | 示例 |
| --- | --- | --- |
| `net` | 默认路由所走网卡的下载和上传速度 | `↓1.2M ↑ 85K` |
| `battery` | 电量，图标区分充电中 / 用电池 / 接着电源；没有电池的机器不显示 | `🔋74%` `⚡80%` `🔌100%` |
| `cpu` | 距上次刷新以来所有核心的繁忙比例 | `cpu 23%` |
| `mem` | 已用内存；macOS 上与活动监视器的「已使用内存」同一口径 | `mem 61%` |

所有文案都可以改，见[配置](#配置)。

## 为什么需要插件

Herdr 从 0.8.2 起在 tab 行右侧有一个 tmux 风格的状态区（`ui.tab_bar_right`），内置 `zoom`、
`hostname`、`datetime`、`text` 条目，另有 `command` 条目显示 shell 命令输出的最后一行。它没有系统指标；
而速度需要对计数器读两次，一次性命令又记不住上一次的读数。这个插件提供这些命令，并负责记住读数。

市场上已有的系统信息插件都画在侧栏或终端窗口标题里，而且没有一个显示网速。

状态区有两个限制，决定了输出的样子：

- **只有一种颜色。** Herdr 会剥掉命令输出里的转义序列，所有条目统一用同一种灰色绘制，所以默认用文字和箭头。
  电量图标用 emoji，本身带颜色。
- **要么全显示，要么全隐藏。** tab 行放不下「最小 tab 条 + 整个状态区」时，Herdr 会把整个状态区隐藏。
  只放你真正会看的段。

## 安装

```bash
herdr plugin install kadaliao/herdr-plugins/status-bar -y
# 安装时不会执行 startup 钩子，所以先手动写一次启动器和初始配置：
herdr plugin action invoke kadaliao.status-bar.setup
```

然后在 `~/.config/herdr/config.toml` 的 `[ui]` 里加上条目，留下你想要的：

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

再在 Herdr 里按 `prefix+shift+r`（reload config），或执行：

```bash
herdr server reload-config
```

`interval_seconds` 同时也是 `net` 和 `cpu` 取平均的时间窗口。显示哪些段、什么顺序，都在 `tab_bar_right`
里决定。它可以接任意命令，所以你自己的脚本也能直接和这些段放在一起。

### 本地开发

```bash
herdr plugin link ~/workspace/herdr-plugins/status-bar
herdr plugin action invoke kadaliao.status-bar.setup
```

## 配置

每一段显示什么文字，写在插件自己的配置文件里：

```
~/.config/herdr/plugins/config/kadaliao.status-bar/config.toml
```

`setup` 会生成这个文件，所有键都以默认值注释着。完整说明见 [config.example.toml](config.example.toml)。
每次刷新都会重新读取这个文件，所以改完不用 reload，最多 `interval_seconds` 后生效。

模板用 Python 的 format 语法：`{down:>4}` 补齐到 4 格，数值变化时状态栏不会跳动；`{name:.N}` 把文本截到
N 个终端格并以 `…` 结尾，中日韩字符算 2 格。例如换成中文标签、内存显示成 GB：

```toml
[net]
format = "网 ↓{down:>4} ↑{up:>4}"

[cpu]
format = "处理器 {percent:>2}%"

[mem]
format = "内存 {used}/{total}"
```

| 表 | 键 | 占位符 |
| --- | --- | --- |
| `[net]` | `format`、`interface`（`auto` 跟随默认路由，也可写网卡名如 `en0`） | `{down}` `{up}` `{interface}` |
| `[battery]` | `format`，以及各状态对应的 `{icon}`：`charging`、`discharging`、`charged` | `{percent}` `{icon}` `{state}` `{remaining}` |
| `[cpu]` | `format` | `{percent}` |
| `[mem]` | `format` | `{percent}` `{used}` `{total}` |

数值最多 4 格：`512B`、`9.9K`、`85K`、`1.2M`。速度与 macOS 一样按 1000 进位；内存按 1024 进位，所以 32 GB 内存显示为 `32G`。`{remaining}` 是 macOS
给出的剩余时间估计，如 `4:12`，没有估计时为空。

改完检查一下：

```bash
~/.local/state/herdr/plugins/kadaliao.status-bar/bar check
```

它会打印每一段的结果，或者准确指出错误：未知的键，或未知的占位符（连同可用的占位符一起列出）。配置出错时该段以非零
状态退出，Herdr 会隐藏它，而不是继续显示旧内容。

## 工作原理

Herdr 在 server 上用 `/bin/sh -lc` 执行每个 `command` 条目：最多每 `interval_seconds` 一次，上一次没跑完
不会再起新的，超过 `timeout_seconds`（默认 2 秒）就杀掉。所以显示的是 Herdr server 所在机器的状态，
用 `herdr --remote` 时也一样。

| 段 | macOS | Linux |
| --- | --- | --- |
| `net` | `route -n get default`，再读 `netstat -ibn -I <网卡>` | `/proc/net/route`、`/proc/net/dev` |
| `cpu` | 通过 `ctypes` 调 `host_statistics`，不起子进程 | `/proc/stat` |
| `mem` | `vm_stat`：app 内存（anonymous − purgeable）+ wired + compressed，除以 `hw.memsize` | `/proc/meminfo` 的 `MemTotal − MemAvailable` |
| `battery` | `pmset -g batt` | `/sys/class/power_supply/BAT*` |

`net` 和 `cpu` 把累计计数器换算成速率。每次调用把读数存到
`~/.local/state/herdr/plugins/kadaliao.status-bar/samples/`，下一次调用用两次读数之差除以间隔时间，
单次耗时远低于 0.1 秒。只有第一次调用、隔了 30 秒以上，或网卡变了，才会临时采样半秒。

跟随默认路由意味着开着 VPN 时测的是隧道本身，而不会把同一份流量在隧道和物理网卡上各算一遍。

状态命令在插件运行时之外执行，拿不到 `HERDR_PLUGIN_ROOT`。所以插件在固定路径
`~/.local/state/herdr/plugins/kadaliao.status-bar/bar`（设置了 `XDG_STATE_HOME` 时是
`$XDG_STATE_HOME/herdr/...`）放一个小启动器，用 `exec` 转到插件实际安装位置的 `bar.py`：优先用执行
`setup` 时的那个 Python，找不到再退回 `python3`。`[[startup]]` 钩子在每次 server 启动时重写它，
`setup` action 可以随时手动写入。

某个条目一直是空的，先跑 `bar check`，再去 `~/.config/herdr/herdr-server.log` 里搜
`tab bar status command failed`，日志会写明是超时还是非零退出。

## 升级

重跑安装命令即可。启动器指向的托管副本路径不变，你的配置文件也不会被改动：

```bash
herdr plugin install kadaliao/herdr-plugins/status-bar -y
```

## 要求与限制

- Herdr ≥ 0.9.0（状态区本身在 0.8.2 引入）和 `python3`，没有其他依赖。在配置文件里设置值需要
  Python 3.11+（`tomllib`），更旧的 Python 只能用默认值。
- 值靠轮询获取：`net` 和 `cpu` 是最近 `interval_seconds` 内的平均值，所有值最多滞后一个刷新间隔。
- 只有桌面布局的 tab 行有状态区。设置了 `hide_tab_bar_when_single_tab = true` 时，状态区会随 tab 行一起隐藏。
- emoji 占 2 格；终端不支持彩色 emoji 时会显示成普通字形。不合适的话可以在 `[battery]` 里替换。

## 卸载

```bash
herdr plugin uninstall kadaliao.status-bar
# 本地 link 的用：herdr plugin unlink kadaliao.status-bar
rm -r ~/.local/state/herdr/plugins/kadaliao.status-bar ~/.config/herdr/plugins/config/kadaliao.status-bar
```

再把 `~/.config/herdr/config.toml` 里 `tab_bar_right` 中的 `bar` 条目删掉。
