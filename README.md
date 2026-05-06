# AgentTalk

AgentTalk 是一个轻量级局域网 Agent 通信控制台，面向运行在 tmux pane 里的 AI agent CLI。它支持注册本机 agent、发现同事的 agent、点对点发消息、用完成 marker 监控反馈、读取最近上下文，并通过 Web UI 查看和操作已注册的 pane。

AgentTalk is a lightweight LAN communication console for tmux-hosted AI agent CLIs. It lets developers register local agent panes, discover peer agents, send point-to-point messages, watch responses with completion markers, read recent context, and inspect or control registered panes from a Web UI.

MVP 有意保持简单：一个 Hub、本机 relay、只支持 tmux、共享局域网 token，不做重型编排。

The MVP is intentionally small: one Hub, local relays, tmux-only agents, a shared LAN token, and no heavyweight orchestration.

## 当前状态 / Status

已实现的 MVP 里程碑：

Implemented MVP milestones:

- M1: Hub registry, SQLite storage, token auth, CLI list
- M2: local config, read-only tmux discovery, relay sync, registration CLI
- M3: point-to-point messages and tmux injection
- M4: response watch, marker completion, context capture
- M5: React/Vite Web console
- M6: xterm.js terminal view and Hub WebSocket bridge

审计报告 / Audit report:

- `review/audits/2026-05-07-audit-agenttalk-mvp.md`

## 架构 / Architecture

```text
tmux agent pane
  <-> local agenttalkd relay
  <-> AgentTalk Hub
  <-> CLI / Web UI / other relays
```

核心组件：

Core components:

- `agenttalk hub serve`: FastAPI Hub with SQLite storage.
- `agenttalk daemon start`: local relay that registers configured panes, heartbeats, injects messages, captures context, and watches markers.
- `agenttalk`: CLI for setup, registration, list, send, status, response, and context.
- `web/`: React/Vite Agent Console with Playwright tests.

## 环境要求 / Requirements

- Python 3.12+
- `uv`
- tmux
- Node.js and npm for Web UI development

## 安装 / Install

```bash
uv sync --extra dev
```

Web UI:

```bash
cd web
npm install
```

## 启动 Hub / Run The Hub

开发模式 Hub：

Development Hub:

```bash
AGENTTALK_TOKEN=dev-token uv run agenttalk hub serve \
  --host 127.0.0.1 \
  --port 8787 \
  --token dev-token
```

构建并由 Hub 托管 Web UI：

Build and serve the Web UI from the Hub:

```bash
cd web
npm run build
cd ..

AGENTTALK_TOKEN=dev-token uv run agenttalk hub serve \
  --host 127.0.0.1 \
  --port 8787 \
  --token dev-token \
  --web-dist web/dist
```

访问 / Open:

```text
http://127.0.0.1:8787
```

## 本机接入 / Local Setup

保存 Hub 配置：

Save Hub config:

```bash
uv run agenttalk setup http://127.0.0.1:8787 --token dev-token
```

发现 tmux panes：

Discover tmux panes:

```bash
uv run agenttalk discover
```

注册一个 pane：

Register a pane:

```bash
uv run agenttalk register \
  --short-id alice-codex-api \
  --tmux-target dev:0.1 \
  --owner alice \
  --kind codex \
  --workspace /workspace/service-api
```

执行一次 relay 同步：

Run one relay sync:

```bash
uv run agenttalk daemon start --once
```

持续运行 relay：

Run relay continuously:

```bash
uv run agenttalk daemon start
```

## CLI 用法 / CLI Usage

列出 agents / List agents:

```bash
uv run agenttalk list
uv run agenttalk list --mine
uv run agenttalk list --owner alice
```

发送点对点消息 / Send a point-to-point message:

```bash
uv run agenttalk send \
  --to alice-codex-api \
  --sender bob-claude-ui \
  --message "Please review the API contract."
```

发送并监控反馈 / Send and watch response:

```bash
uv run agenttalk send \
  --to alice-codex-api \
  --sender bob-claude-ui \
  --message "Please review the API contract." \
  --watch
```

查看状态 / Check status:

```bash
uv run agenttalk status msg-20260506170000000000
```

读取已捕获反馈 / Read captured response:

```bash
uv run agenttalk response msg-20260506170000000000
```

读取最近上下文 / Read recent context:

```bash
uv run agenttalk context alice-codex-api --lines 120
```

更新本机注册 / Update local registration:

```bash
uv run agenttalk rename alice-codex-api alice-codex-main
uv run agenttalk mode alice-codex-main paste-only
```

## Web UI

Web Console 包含：

The Web Console includes:

- Agents table with search and status filters
- Right-side preview with recent context and quick message box
- Agent detail page
- Structured AgentTalk message box
- Recent messages panel
- xterm.js terminal panel
- Context overview page

运行 Web 开发服务器：

Run Web development server:

```bash
cd web
npm run dev
```

运行 Web 检查：

Run Web checks:

```bash
cd web
npm run lint
npm run build
npm run test:e2e
```

## Agent Skill

内置 skill：

Bundled skill:

```text
.agents/skills/agenttalk/SKILL.md
```

在 AI agent 环境里使用这个 skill，可以让 agent 知道如何：

Use this skill in AI agent environments so agents know how to:

- List registered peer agents
- Inspect recent peer context
- Send point-to-point requests
- Use `--watch` for feedback
- Print the exact completion marker when receiving AgentTalk messages

## 安全注意事项 / Safety Notes

`agenttalk discover` 是只读操作，只使用：

`agenttalk discover` is read-only and uses:

```text
tmux list-panes
```

消息投递和 Web terminal 控制会向已注册 tmux pane 写入内容。只注册明确允许 AgentTalk 输入的 pane。

Message delivery and Web terminal control can write to registered tmux panes. Only register panes that are intended to receive AgentTalk input.

针对 tmux 做测试时，请使用专用 session：

For tmux tests, use dedicated sessions:

```text
agenttalk-e2e-*
```

不要把测试指向重要开发 pane。

Do not point tests at important development panes.

## 当前限制 / Current Limitations

- Web terminal 当前假设 Hub 进程能访问注册的 tmux target。真正多机器 terminal streaming 后续应通过目标机器 relay 路由。
- Web token handling 仍是 MVP 级别。`VITE_AGENTTALK_TOKEN` 或 `dev-token` 只适合本地测试。
- 当前没有 terminal input lock。多个 Web client 如果能访问 endpoint，就都可以输入。
- xterm.js 当前在初始 Web chunk 中打包。如果后续关注 bundle size，应改成懒加载。

- Web terminal currently assumes the Hub process can access the registered tmux target locally. True multi-machine terminal streaming should be routed through the target relay.
- Web token handling is MVP-level. `VITE_AGENTTALK_TOKEN` or `dev-token` is suitable for local testing only.
- There is no terminal input lock. Multiple Web clients can type if they can reach the endpoint.
- xterm.js is bundled in the initial Web chunk. Lazy loading should be added later if bundle size matters.

跟踪文件 / Tracked in:

```text
docs/plans/assumption-register.md
```

## 测试 / Testing

Python:

```bash
uv run pytest
```

Web:

```bash
cd web
npm run lint
npm run build
npm run test:e2e
```

最近验证结果：

Latest verified results:

```text
uv run pytest        28 passed
npm run lint         passed
npm run build        passed
npm run test:e2e     4 passed
```

## 项目文档 / Project Documents

- `docs/plans/2026-05-07-agenttalk-design-decisions.md`
- `docs/plans/2026-05-07-agenttalk-ux-architecture-design.md`
- `docs/plans/2026-05-07-agenttalk-mvp-implementation-plan.md`
- `docs/plans/acceptance/`
- `review/audits/2026-05-07-audit-agenttalk-mvp.md`
