# AgentTalk

## Language / 语言

- [中文说明](#中文说明)
- [English README](#english-readme)

---

## 中文说明

AgentTalk 是一个轻量级局域网 Agent 通信系统，面向运行在 tmux pane 里的 AI agent CLI。Hub 是 server，开发者机器是 client。Hub 提供注册中心、消息路由、Web UI（含原生 PTY 终端）和可选飞书机器人；client relay 负责本机 tmux 注册、消息注入、上下文采集和反馈监控。

> **架构说明**：tmux 用于 agent 进程保活和多窗口管理，PTY 用于 Web UI 中的原生交互式终端。两者互补共存。

### 快速开始

#### 1. 部署 Hub Server

```bash
scripts/deploy-hub.sh
```

#### 2. 设置 Agent（推荐：使用便捷脚本）

**检查环境：**
```bash
./scripts/check-env.sh
```

**一键设置 tmux + PTY（不启动 AI agent）：**
```bash
# 进入项目目录
cd /path/to/project

# 交互式设置（创建 tmux session，注册 pane，启动监控）
./scripts/setup-pane.sh

# 或指定参数
./scripts/setup-pane.sh --session my-api --kind codex
```

**在 tmux 中启动您的 AI Agent：**
```bash
# 附加到刚创建的 session
tmux attach -t my-api

# 启动 Claude Code
claude

# 或启动其他 agent CLI
codex
```

#### 3. 启动/管理监控

```bash
# 查看所有 agent 状态
./scripts/start-all-agents.sh --status

# 启动所有已注册 agent 的监控
./scripts/start-all-agents.sh

# 停止监控
./scripts/start-all-agents.sh --stop

# 实时监控日志
./scripts/start-all-agents.sh --monitor
```

#### 传统方式（手动注册）

```bash
scripts/start-client.sh \
  --hub-url http://192.168.1.20:8787 \
  --token <token> \
  --short-id alice-codex-api \
  --tmux-target dev:0.1 \
  --owner alice \
  --kind codex \
  --workspace /workspace/service-api
```

### 常用入口

- [Server quickstart](docs/guides/server-quickstart.md)
- [Client quickstart](docs/guides/client-quickstart.md)
- [Docker deployment](docs/guides/docker-deployment.md)
- [Feishu bot setup](docs/guides/feishu-bot-setup.md)
- [CLI reference](docs/reference/cli.md)
- [Project overview](docs/overview.md)
- [Agent skill usage](docs/guides/agent-skill-usage.md)

### Agent Skill

仓库内置 agent 入口和 skill：

- [Agent instructions](AGENTS.md)
- [AgentTalk skill](.agents/skills/agenttalk/SKILL.md)

### 安全注意事项

`scripts/start-client.sh --discover` 和 `agenttalk discover` 只读 tmux pane 元数据。消息投递会写入已注册 pane。只注册明确允许 AgentTalk 输入的 pane。

测试 tmux 时只使用：

```text
agenttalk-e2e-*
```

### 验证

最近验证结果：

```text
uv run pytest        47 passed
npm run lint         passed
npm run build        passed
npm run test:e2e     4 passed
docker build         passed
docker smoke         passed
```

---

## English README

AgentTalk is a lightweight LAN communication system for tmux-hosted AI agent CLIs. The Hub is the server, and each developer machine is a client. The Hub provides registry, message routing, Web UI (with native PTY terminal), and an optional Feishu bot; the client relay handles local tmux registration, message injection, context capture, and response monitoring.

> **Architecture Note**: tmux is used for agent process keepalive and multi-window management, while PTY provides native interactive terminals in the Web UI. They complement each other.

### Quick Start

Deploy the Hub server:

```bash
scripts/deploy-hub.sh
```

Start a local client relay:

```bash
scripts/start-client.sh \
  --hub-url http://192.168.1.20:8787 \
  --token <token> \
  --short-id alice-codex-api \
  --tmux-target dev:0.1 \
  --owner alice \
  --kind codex \
  --workspace /workspace/service-api
```

Discover local tmux panes read-only:

```bash
scripts/start-client.sh --discover
```

### Main Docs

- [Server quickstart](docs/guides/server-quickstart.md)
- [Client quickstart](docs/guides/client-quickstart.md)
- [Docker deployment](docs/guides/docker-deployment.md)
- [Feishu bot setup](docs/guides/feishu-bot-setup.md)
- [CLI reference](docs/reference/cli.md)
- [Project overview](docs/overview.md)
- [Agent skill usage](docs/guides/agent-skill-usage.md)

### Agent Skill

Repository-bundled agent entry point and skill:

- [Agent instructions](AGENTS.md)
- [AgentTalk skill](.agents/skills/agenttalk/SKILL.md)

### Safety

`scripts/start-client.sh --discover` and `agenttalk discover` only read tmux pane metadata. Message delivery writes to registered panes. Only register panes that are intended to receive AgentTalk input.

For tmux tests, only use:

```text
agenttalk-e2e-*
```

### Verification

Latest verified results:

```text
uv run pytest        47 passed
npm run lint         passed
npm run build        passed
npm run test:e2e     4 passed
docker build         passed
docker smoke         passed
```
