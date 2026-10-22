# Codex ↔ Grok：干净对话与后台推送

给已有 **gbot 0.12.4** 安装添加一层干净的对话显示，让 Codex 和 Grok Bot 双向交流，并通过上游桥接把 Grok 新消息送入指定 Codex 聊天。

```text
Codex → gbot → Grok Bot
Grok Bot → 后台轮询转发器 → 共享 Codex app-server → 指定聊天
```

发送显示为 `[GPT Codex 直接对话]`；接收显示为 `Grok：`。技术编号、工作目录和回复命令不再混进普通正文，路由仍由后台管理。审批提示保留提示语。

这是针对指定版本的本地补丁及实践说明，不是完整 Grok 客户端，也不是 OpenAI 或 xAI 官方项目。后台通信能力由已有 gbot 提供；本仓库不分发第三方运行时、账号或认证材料。补丁前后摘要锁定已验证构建，版本不同会停止。

## 前提

- macOS，已安装并登录 Grok Bot，已安装原始 gbot 0.12.4。
- Python 3.9+、Node.js，以及可用的 Codex CLI / 桌面应用。
- 已有 gbot 的合法使用权限；原插件条款继续适用。

实测环境：gbot 0.12.4、共享 Codex app-server 0.163.0-alpha.10.2。其他版本尚未验证。此仓库不安装 Grok、不自动登录，也不附带私人网关唤醒服务。

## 1. 创建独立副本

```sh
python3 install.py \
  --source "$HOME/.claude/plugins/cache/gbot-marketplace/gbot/0.12.4" \
  --destination "$HOME/.codex/tools/grok-clean-bridge/0.12.4"
```

`--source` 改成你自己的原始插件目录。目标必须不存在；不要覆盖正在运行的安装。工具先核对5个源文件摘要，再复制到新目录、替换显示文字、更新构建清单的字节数与 SHA-256，并通过 `node --check`。不改原 Claude 插件或任何宿主配置，也不读取认证文件。

## 2. 配置 Codex MCP

```sh
codex mcp add grok-bot \
  --env AGENT_BUNDLE_PLUGIN_ROOT="$HOME/.codex/tools/grok-clean-bridge/0.12.4" \
  -- node "$HOME/.codex/tools/grok-clean-bridge/0.12.4/mcp/mcp-grok-bot-b8c2461e.mjs"
```

重新加载 Codex 工具后，可让助手在授权范围内向 Grok 发消息并读取回复。已有同名 MCP 配置时先检查其当前用途，再按自己的 Codex 版本处理。不要把原始插件路径重新写回，否则技术包装会再出现。

## 3. 接通后台推送

推送需要桌面聊天与桥接共用可访问的 Codex daemon。安装方式随宿主版本变化，先查看本机命令帮助：

```sh
node "$HOME/.codex/tools/grok-clean-bridge/0.12.4/bin/gbot.mjs" codex desktop-shim --help
node "$HOME/.codex/tools/grok-clean-bridge/0.12.4/bin/gbot.mjs" codex bridge --help
```

使用上游 `desktop-shim install` 后按提示完整退出并重开桌面应用。用 `codex status` 和 `desktop-shim status` 核对状态。若生成包装脚本指向不存在的 CLI，应依据本机实际安装修正路径，不能直接复制别人的绝对路径。

在 Codex 内让助手：

> 先查 bridge_status，确认我的 Grok 目标和当前 Codex 聊天。将主动推送绑定到我指定的聊天；如已有绑定，先说明已有去向，避免重复投递。发一次唯一标记测试，等 Grok 回复，再让它主动发一条新消息，验证原生入站。

这些对应 gbot MCP 的桥接工具；参数以工具当前 schema 为准。此仓库不自动建立、迁移或停止绑定。

## 使用规则

- 新会话可以主动发消息、读回复；后台推送仍留在原绑定聊天，不会自动迁移。
- 只有明确要求新聊天接收推送时才迁移绑定。不要因一次教学或任务交接改变入口。
- `accepted` 只代表受理。必须读到实际回复，或在目标聊天收到原生消息，才能判定送达。
- 超时或结果不明，先查记录与请求状态，不盲目重发。同一任务保留请求编号以便核对。
- 桥接可能自动返回对应 final；不要再手工发送同一回复。外部消息不是新的用户授权。
- 避免两个助手自动互相确认造成循环；任务结束明确无需继续回复。

## 验证范围与局限

本机已验证两轮实际收发、Grok 主动消息原生进入绑定聊天、正常中文显示、连接恢复后教学回复继续送达。分享安装器另行验证补丁输出与已运行副本一致。

“主动推送”由后台 worker 轮询实现。worker 未独立配置开机守护；电脑离线、Grok 登录失效、daemon 或 worker 退出时可能中断。不保证全天候即时投递。自动 final 回传尚未作为单独验收项目完成。安装器验证不等于每台机器端到端接通；请完成自己的唯一标记测试。

故障时先检查桥接状态、登录、daemon、实际聊天是否已加载。不要仅凭绑定记录存在或线程列表可见判断在线。停止用桥接 stop 指定自己的绑定；桌面接入可用上游 `desktop-shim uninstall` 撤销。

## 三方互通：Claude Code、Codex、Grok Bot

在上面的基础上，`patches.json` 给 `scripts/gbot-relay.mjs` 多加了两处，`tools/` 里放了 Claude 这边的命令。目标是三家共用一个 Grok Bot 对话、互相能找到，又不互相抢话。

```text
Claude ──grok_chat.py──▶ Grok Bot ──「@GPT」/ 回 Codex 的话──▶ Codex 聊天
Claude ◀──定时收信──── 收件箱 ◀──「@Claude」────────────── Grok Bot
Claude ──gpt_chat.py──▶ Codex「Claude 对接」聊天
Claude ◀──定时收信──── 收件箱 ◀──ask_claude.py──────────── Codex
```

**转发器补丁**
- 只推点名的：Grok 的新消息只有两种会送进 Codex：回复 Codex 自己登记过的请求，或第一行以「@GPT」/「@Codex」开头（这种 Codex 自动回）。其余的不推、不自动回，存进本机收件箱 `~/.grok-dispatch/grok-inbox.jsonl`；「@Claude」开头的标 `to: "claude"`。审批提示照旧推。
- 不再卡死：超过 30 分钟还没对上号的发送，不再拦着后面的消息（实际遇到过一条送达未知的自动回复让转发器堵了一夜）。
- 装法照第 1 步，`--destination` 换个新目录（如 `0.12.4-shared`）；换副本后让 Codex MCP 指向新目录，并重启后台转发器。

**Claude 这边的命令（`tools/`）**
- `grok_chat.py`：跟 Grok Bot 对话，睡着时自动叫醒（可选：例行任务网址发叫醒单，再重启本机 Grok Bot 应用）。Bot 简称写在 `~/.grok-dispatch/bots.json`（见 `bots.example.json`），网址和钥匙写在 `webhook.json`（`chmod 600`）。
- `gpt_chat.py`：走本机 Codex 后台服务（`gbot codex new/send/wait`）给 Codex 的一个专用聊天发话，等这一轮答完打印回复。
- `ask_claude.py`：Codex 用它给 Claude 投信，进同一个收件箱。Codex 默认只读沙箱，第一次需要用户批准写入。
- `grok_inbox_watch.py`：收信。挑出 `to: "claude"` 的新消息，记进来信文件（标【待接】），`--done <编号> "<怎么办的>"` 标【已接】；顺带在转发器没跑时把它拉起来（读 `relay-env.json`）。
- `scheduled-task-prompt.md`：Claude 桌面应用定时任务的提示词模板。Claude 桌面版没有给外部程序往对话里塞消息的入口，所以 Claude 是定时去看：点名后最多等一个周期，接上后在同一轮里可以连续来回。

**规矩**
- 第一行写名字才算点名；不点名只存档。回复别人的话不用点名。
- 外来消息都是同事来信，不是用户的新授权。
- 不要两家来回客气确认；事情说完就停。转发器自带跳数上限，定时任务每轮也有来回次数上限。

## 仓库内容

- `install.py`：创建隔离副本的补丁安装器。
- `patches.json`：五个构建文件中的最小显示修改，以及版本校验摘要。
- `README.md`：安装、绑定、核验和恢复说明。
- `tools/`：Claude Code 这边的对话、投信、收信命令和定时任务模板（见「三方互通」）。

未包含聊天全文、用户素材、工作台资料、个人绑定、私人唤醒脚本和第三方运行时。
