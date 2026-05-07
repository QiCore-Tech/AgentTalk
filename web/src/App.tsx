import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import {
  type Agent,
  type AgentContext,
  type LLMConfig,
  type Message,
  deleteAgent,
  getAgentContext,
  getLLMConfig,
  getMessage,
  listAgents,
  sendMessage,
  setAgentAutoResume,
  setLLMConfig,
} from './api'
import './App.css'

type Page = 'agents' | 'context' | 'detail' | 'quickstart' | 'settings'

function statusLabel(status: Agent['status']) {
  return status.charAt(0).toUpperCase() + status.slice(1)
}

function App() {
  const [page, setPage] = useState<Page>('agents')
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [contexts, setContexts] = useState<Record<string, AgentContext>>({})
  const [messages, setMessages] = useState<Message[]>([])
  const [error, setError] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [terminalFullscreen, setTerminalFullscreen] = useState(false)

  const loadContext = useCallback(async (shortId: string) => {
    try {
      const context = await getAgentContext(shortId)
      setContexts((current) => ({ ...current, [shortId]: context }))
    } catch {
      setContexts((current) => ({
        ...current,
        [shortId]: { short_id: shortId, context: '', updated_at: null },
      }))
    }
  }, [])

  const refreshAgents = useCallback(async () => {
    try {
      setError('')
      const next = await listAgents()
      setAgents(next)
      await Promise.all(next.map((agent) => loadContext(agent.short_id)))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [loadContext])

  // Initial load
  useEffect(() => {
    void refreshAgents()
  }, [refreshAgents])

  // Auto-refresh context every 5 seconds
  useEffect(() => {
    if (agents.length === 0) return
    const interval = window.setInterval(() => {
      agents.forEach((agent) => {
        void loadContext(agent.short_id)
      })
    }, 5000)
    return () => window.clearInterval(interval)
  }, [agents, loadContext])

  const effectiveSelectedId = selectedId || agents[0]?.short_id || ''
  const selectedAgent = agents.find((agent) => agent.short_id === effectiveSelectedId)

  const filteredAgents = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return agents.filter((agent) => {
      const matchesQuery =
        !needle ||
        [agent.short_id, agent.owner, agent.kind, agent.workspace, agent.machine_id]
          .join(' ')
          .toLowerCase()
          .includes(needle)
      const matchesStatus = statusFilter === 'all' || agent.status === statusFilter
      return matchesQuery && matchesStatus
    })
  }, [agents, query, statusFilter])

  async function handleSend(agent: Agent, body: string, watch: boolean) {
    // Send directly to PTY for immediate terminal interaction
    try {
      const response = await fetch(`${window.location.origin}/api/agents/${encodeURIComponent(agent.short_id)}/pty`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${import.meta.env.VITE_AGENTTALK_TOKEN || ''}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ text: body + '\r' }),
      })
      if (!response.ok) {
        throw new Error(await response.text())
      }
      // Also create a message record for tracking
      const created = await sendMessage(agent.short_id, body)
      setMessages((current) => [created, ...current].slice(0, 12))
      // Refresh context after sending message
      setTimeout(() => {
        void loadContext(agent.short_id)
      }, 1000)
      if (watch) {
        const timer = window.setInterval(async () => {
          const updated = await getMessage(created.message_id)
          setMessages((current) =>
            current.map((message) => (message.message_id === updated.message_id ? updated : message)),
          )
          if (['completed', 'failed', 'timeout'].includes(updated.status)) {
            window.clearInterval(timer)
          }
        }, 1200)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleDeleteAgent(shortId: string) {
    if (!confirm(`确定要删除 agent "${shortId}" 吗？`)) return
    try {
      await deleteAgent(shortId)
      setAgents((current) => current.filter((a) => a.short_id !== shortId))
      if (selectedId === shortId) {
        setSelectedId('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark">AT</span>
          <div>
            <strong>AgentTalk</strong>
            <span>LAN Agent Console</span>
          </div>
        </div>
        <button className="menuToggle" onClick={() => setMenuOpen(!menuOpen)} aria-label="Menu">
          {menuOpen ? '✕' : '☰'}
        </button>
        <nav className={menuOpen ? 'open' : ''}>
          <button className={page === 'agents' ? 'active' : ''} onClick={() => { setPage('agents'); setMenuOpen(false) }}>
            Agents
          </button>
          <button className={page === 'context' ? 'active' : ''} onClick={() => { setPage('context'); setMenuOpen(false) }}>
            Context
          </button>
          <button
            className={page === 'detail' ? 'active' : ''}
            disabled={!selectedAgent}
            onClick={() => { setPage('detail'); setMenuOpen(false) }}
          >
            Detail
          </button>
          <button className={page === 'quickstart' ? 'active' : ''} onClick={() => { setPage('quickstart'); setMenuOpen(false) }}>
            Quick Start
          </button>
          <button className={page === 'settings' ? 'active' : ''} onClick={() => { setPage('settings'); setMenuOpen(false) }}>
            Settings
          </button>
        </nav>
        <div className="sidebarStats">
          <span>{agents.length} registered</span>
          <span>{agents.filter((agent) => agent.status !== 'offline').length} reachable</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>
              {page === 'context'
                ? 'Context Overview'
                : page === 'detail'
                  ? 'Agent Detail'
                  : page === 'quickstart'
                    ? 'Quick Start Guide'
                    : 'Agents'}
            </h1>
            <p>
              {page === 'quickstart'
                ? 'Learn how to register and manage agents'
                : 'Monitor, message, and inspect tmux-hosted agents.'}
            </p>
          </div>
          {page !== 'quickstart' && (
            <button className="primary" onClick={refreshAgents}>
              Refresh
            </button>
          )}
        </header>
        {error ? <div className="error">{error}</div> : null}

        {page === 'agents' && (
          <AgentsHome
            agents={filteredAgents}
            allAgents={agents}
            selectedAgent={selectedAgent}
            selectedId={effectiveSelectedId}
            query={query}
            statusFilter={statusFilter}
            context={selectedAgent ? contexts[selectedAgent.short_id] : undefined}
            messages={messages}
            onQuery={setQuery}
            onStatusFilter={setStatusFilter}
            onSelect={setSelectedId}
            onOpenDetail={() => setPage('detail')}
            onSend={handleSend}
            onDelete={handleDeleteAgent}
          />
        )}

        {page === 'detail' && selectedAgent && (
          <AgentDetail
            agent={selectedAgent}
            messages={messages.filter((message) => message.target === selectedAgent.short_id)}
            onSend={handleSend}
            onDelete={handleDeleteAgent}
          />
        )}

        {page === 'context' && (
          <ContextOverview
            agents={agents}
            contexts={contexts}
            onSelect={(id) => {
              setSelectedId(id)
              setPage('detail')
            }}
          />
        )}

        {page === 'quickstart' && <QuickStart />}

        {page === 'settings' && <SettingsPage />}

        {/* Mobile Bottom Navigation */}
        <nav className="bottomNav">
          <button className={page === 'agents' ? 'active' : ''} onClick={() => setPage('agents')}>
            <span className="bottomNavIcon">📊</span>
            Agents
          </button>
          <button className={page === 'context' ? 'active' : ''} onClick={() => setPage('context')}>
            <span className="bottomNavIcon">📝</span>
            Context
          </button>
          <button
            className={page === 'detail' ? 'active' : ''}
            disabled={!selectedAgent}
            onClick={() => setPage('detail')}
          >
            <span className="bottomNavIcon">🔍</span>
            Detail
          </button>
          <button className={page === 'quickstart' ? 'active' : ''} onClick={() => setPage('quickstart')}>
            <span className="bottomNavIcon">📖</span>
            Guide
          </button>
          <button className={page === 'settings' ? 'active' : ''} onClick={() => setPage('settings')}>
            <span className="bottomNavIcon">⚙️</span>
            Settings
          </button>
        </nav>

        {/* Fullscreen Terminal Modal */}
        {terminalFullscreen && selectedAgent && (
          <div className="terminalModal">
            <div className="terminalModalHeader">
              <h2>Terminal: {selectedAgent.short_id}</h2>
              <button className="terminalModalClose" onClick={() => setTerminalFullscreen(false)}>
                ✕
              </button>
            </div>
            <div className="terminalModalContent">
              <LiveTerminal agent={selectedAgent} />
            </div>
          </div>
        )}
      </section>
    </main>
  )
}

function AutoResumeToggle({ agent }: { agent: Agent }) {
  const [config, setConfig] = useState({
    enabled: agent.auto_resume_enabled ?? true,
    message: agent.auto_resume_message ?? '继续',
  })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setConfig({
      enabled: agent.auto_resume_enabled ?? true,
      message: agent.auto_resume_message ?? '继续',
    })
  }, [agent])

  async function handleToggle(enabled: boolean) {
    const newConfig = { ...config, enabled }
    setConfig(newConfig)
    setSaving(true)
    try {
      await setAgentAutoResume(agent.short_id, newConfig)
    } catch (err) {
      console.error('Failed to save auto-resume:', err)
      setConfig(config)
    } finally {
      setSaving(false)
    }
  }

  return (
    <label
      className="toggle"
      title={`Auto-resume: ${config.enabled ? 'on' : 'off'} (${config.message})`}
      style={{ opacity: saving ? 0.5 : 1 }}
    >
      <input
        type="checkbox"
        checked={config.enabled}
        onChange={(e) => handleToggle(e.target.checked)}
      />
      <span className="toggleLabel">{config.enabled ? 'On' : 'Off'}</span>
    </label>
  )
}

interface AgentsHomeProps {
  agents: Agent[]
  allAgents: Agent[]
  selectedAgent?: Agent
  selectedId: string
  query: string
  statusFilter: string
  context?: AgentContext
  messages: Message[]
  onQuery: (value: string) => void
  onStatusFilter: (value: string) => void
  onSelect: (value: string) => void
  onOpenDetail: () => void
  onSend: (agent: Agent, body: string, watch: boolean) => Promise<void>
  onDelete: (shortId: string) => void
}

function AgentsHome(props: AgentsHomeProps) {
  return (
    <div className="agentsLayout">
      <section className="panel tablePanel">
        <div className="toolbar">
          <input
            aria-label="Search agents"
            placeholder="Search short id, owner, workspace"
            value={props.query}
            onChange={(event) => props.onQuery(event.target.value)}
          />
          <select
            aria-label="Filter status"
            value={props.statusFilter}
            onChange={(event) => props.onStatusFilter(event.target.value)}
          >
            <option value="all">All statuses</option>
            <option value="online">Online</option>
            <option value="active">Active</option>
            <option value="working">Working</option>
            <option value="stale">Stale</option>
            <option value="offline">Offline</option>
          </select>
        </div>
        <table>
          <thead>
            <tr>
              <th>Short id</th>
              <th>Owner</th>
              <th>Kind</th>
              <th>Workspace</th>
              <th>Status</th>
              <th>Mode</th>
              <th>Auto Resume</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {props.agents.map((agent) => (
              <tr
                key={agent.short_id}
                className={agent.short_id === props.selectedId ? 'selected' : ''}
                onClick={() => props.onSelect(agent.short_id)}
              >
                <td className="strong">{agent.short_id}</td>
                <td>{agent.owner}</td>
                <td>{agent.kind}</td>
                <td className="mono">{agent.workspace}</td>
                <td>
                  <StatusBadge status={agent.status} />
                </td>
                <td>{agent.receive_mode}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  <AutoResumeToggle agent={agent} />
                </td>
                <td>
                  <button
                    className="danger small"
                    onClick={(e) => {
                      e.stopPropagation()
                      props.onDelete(agent.short_id)
                    }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Mobile Card View */}
        <div className="agentCards">
          {props.agents.map((agent) => (
            <div
              key={agent.short_id}
              className={`agentCard ${agent.short_id === props.selectedId ? 'selected' : ''}`}
              onClick={() => props.onSelect(agent.short_id)}
            >
              <div className="agentCardHeader">
                <span className="agentCardTitle">{agent.short_id}</span>
                <StatusBadge status={agent.status} />
              </div>
              <div className="agentCardMeta">
                <div className="agentCardMetaItem">
                  <span className="agentCardMetaLabel">Kind</span>
                  <span>{agent.kind}</span>
                </div>
                <div className="agentCardMetaItem">
                  <span className="agentCardMetaLabel">Owner</span>
                  <span>{agent.owner}</span>
                </div>
                <div className="agentCardMetaItem">
                  <span className="agentCardMetaLabel">Workspace</span>
                  <span className="mono">{agent.workspace}</span>
                </div>
                <div className="agentCardMetaItem">
                  <span className="agentCardMetaLabel">Mode</span>
                  <span>{agent.receive_mode}</span>
                </div>
                <div className="agentCardMetaItem" onClick={(e) => e.stopPropagation()}>
                  <span className="agentCardMetaLabel">Auto Resume</span>
                  <AutoResumeToggle agent={agent} />
                </div>
              </div>
              <div className="agentCardActions">
                <button className="secondary" onClick={(e) => { e.stopPropagation(); props.onOpenDetail(); }}>
                  Terminal
                </button>
                <button className="danger" onClick={(e) => { e.stopPropagation(); props.onDelete(agent.short_id); }}>
                  Delete
                </button>
              </div>
            </div>
          ))}
          {!props.allAgents.length ? <div className="empty">No agents registered.</div> : null}
        </div>

        {!props.allAgents.length ? <div className="empty desktop-only">No agents registered.</div> : null}
      </section>

      <aside className="panel preview">
        {props.selectedAgent ? (
          <>
            <AgentSummary agent={props.selectedAgent} />
            <MessageBox agent={props.selectedAgent} onSend={props.onSend} compact />
            <ContextBlock context={props.context?.context || ''} />
            <button className="secondary full" onClick={props.onOpenDetail}>
              View Terminal
            </button>
            <button
              className="danger full"
              onClick={() => props.onDelete(props.selectedAgent!.short_id)}
            >
              Delete Agent
            </button>
            <RecentMessages messages={props.messages.filter((message) => message.target === props.selectedAgent?.short_id)} />
          </>
        ) : (
          <div className="empty">Select an agent.</div>
        )}
      </aside>
    </div>
  )
}

function AgentDetail({
  agent,
  messages,
  onSend,
  onDelete,
}: {
  agent: Agent
  messages: Message[]
  onSend: (agent: Agent, body: string, watch: boolean) => Promise<void>
  onDelete: (shortId: string) => void
}) {
  return (
    <div className="detailGrid">
      <section className="panel detailMeta">
        <AgentSummary agent={agent} />
        <AutoResumeEditor agent={agent} />
        <MessageBox agent={agent} onSend={onSend} />
        <button className="danger full" onClick={() => onDelete(agent.short_id)}>
          Delete Agent
        </button>
        <RecentMessages messages={messages} />
      </section>
      <section className="panel terminalPanel">
        <div className="panelHeader">
          <div>
            <h2>Live Terminal</h2>
            <p>Direct tmux control. Last web input: none</p>
          </div>
          <StatusBadge status={agent.status} />
        </div>
        <LiveTerminal agent={agent} />
      </section>
    </div>
  )
}

function ContextOverview({
  agents,
  contexts,
  onSelect,
}: {
  agents: Agent[]
  contexts: Record<string, AgentContext>
  onSelect: (id: string) => void
}) {
  return (
    <div className="contextList">
      {agents.map((agent) => (
        <section className="panel contextItem" key={agent.short_id}>
          <div className="contextHeader">
            <div>
              <h2>{agent.short_id}</h2>
              <p>
                {agent.kind} &middot; {agent.owner} &middot; {agent.workspace}
              </p>
            </div>
            <button className="secondary" onClick={() => onSelect(agent.short_id)}>
              Open
            </button>
          </div>
          <ContextBlock context={contexts[agent.short_id]?.context || ''} tall />
        </section>
      ))}
    </div>
  )
}

function QuickStart() {
  const hubUrl = window.location.origin
  const token = import.meta.env.VITE_AGENTTALK_TOKEN || 'your-token'

  return (
    <div className="quickStart">
      <section className="panel">
        <h2>Agent 端快速开始指南</h2>
        <p>在您的开发机器上注册 agent，使其可以被 Hub 管理和远程控制。</p>

        <h3>架构说明</h3>
        <p><strong>tmux + PTY 双模式架构：</strong></p>
        <ul>
          <li><strong>tmux</strong>：负责 agent 进程保活、多窗口管理、会话恢复</li>
          <li><strong>PTY</strong>：Web UI 中的原生交互式终端（支持 vim、光标、颜色等）</li>
          <li>两者互补共存，tmux 不可少，PTY 提供更佳的终端体验</li>
        </ul>

        <h3>1. 前置要求</h3>
        <ul>
          <li>Python 3.12+</li>
          <li>tmux（agent 必须运行在 tmux pane 中，用于保活）— <strong>Windows 用户除外</strong></li>
          <li>Git（克隆代码仓库）</li>
        </ul>

        <h3>2. Windows 用户快速开始</h3>
        <p>AgentTalk 支持 Windows 原生运行，无需 WSL 或 tmux。</p>

        <h4>安装</h4>
        <pre className="codeBlock">
{`# 克隆仓库
git clone https://git.qicore.tech/QiCore/soha_agentTalk.git
cd soha_agentTalk

# 安装依赖
pip install -e ".[feishu,llm,windows]"

# 配置 Hub 连接
agenttalk setup ${hubUrl} --token ${token}`}
        </pre>

        <h4>注册 Agent（Windows）</h4>
        <p>Windows 版不依赖 tmux，<code>--tmux-target</code> 只是一个<strong>标识符字符串</strong>（如 <code>main</code>、<code>api-project</code>），不需要对应真实的 tmux session。</p>
        <pre className="codeBlock">
{`# 方式 1：使用简单标识符
agenttalk register --short-id my-claude --tmux-target "main" --owner "your-name" --kind claude

# 方式 2：使用项目路径作为标识
agenttalk register --short-id api-agent --tmux-target "project-api" --workspace "C:\\Users\\you\\projects\\api"

# 启动 relay
agenttalk daemon start`}
        </pre>

        <p><strong>注意事项：</strong></p>
        <ul>
          <li>先在终端窗口中启动您的 AI Agent（如 <code>claude</code>、<code>codex</code>）</li>
          <li>保持终端窗口打开，relay 才能正常工作</li>
          <li>每个 agent 的 <code>short-id</code> 必须全局唯一</li>
          <li>支持 <code>auto_submit</code> 和 <code>paste_only</code> 两种接收模式</li>
        </ul>

        <h3>3. Linux/macOS 安装 AgentTalk</h3>
        <pre className="codeBlock">
{`# 克隆仓库
git clone https://git.qicore.tech/wenda.sheng/soha_agentTalk
cd agenttalk

# 安装依赖（使用 uv 或 pip）
uv sync --extra feishu
# 或
pip install -e ".[feishu]"

# 配置 Hub 连接
agenttalk setup ${hubUrl} --token ${token}`}
        </pre>

        <h3>4. Linux/macOS 快速设置（推荐）</h3>
        <p>使用便捷脚本一键创建 tmux session、注册 pane、启动监控。AI agent 由您自己启动。</p>

        <pre className="codeBlock">
{`# 1. 检查环境
./scripts/check-env.sh

# 2. 一键设置 tmux + 注册 + 监控（不启动 AI agent）
cd /path/to/your/project
./scripts/setup-pane.sh

# 3. 在 tmux 中启动您的 AI Agent
tmux attach -t <session-name>

# 启动 Claude Code
claude

# 或启动 Codex
codex`}
        </pre>

        <h3>4. 管理监控</h3>
        <pre className="codeBlock">
{`# 查看所有 agent 状态
./scripts/start-all-agents.sh --status

# 启动所有已注册 agent 的监控
./scripts/start-all-agents.sh

# 停止监控
./scripts/start-all-agents.sh --stop

# 实时查看日志
./scripts/start-all-agents.sh --monitor`}
        </pre>

        <h3>5. Linux/macOS 手动注册（高级）</h3>
        <p>如果需要更精细的控制，可以手动注册：</p>
        <pre className="codeBlock">
{`# 先创建 tmux session
tmux new-session -d -s my-session

# 注册 pane
agenttalk register \\
  --short-id my-agent-001 \\
  --tmux-target my-session:0.0 \\
  --owner $(whoami) \\
  --kind codex \\
  --workspace /path/to/project

# 启动 relay
agenttalk daemon start`}
        </pre>

        <h3>6. Agent 间协作（Skill）</h3>
        <p>AgentTalk 支持 AI agent 之间直接通信。将 Skill 文件放在您的 agent 配置目录中即可启用。</p>

        <pre className="codeBlock">
{`# 1. 将 skill 文件复制到 agent 配置目录
# 对于 Claude Code:
cp .agents/skills/agenttalk/SKILL.md ~/.claude/skills/

# 对于其他 agent，放在其可读取的 skills 目录`}
        </pre>

        <p>启用后，agent 可以：</p>
        <ul>
          <li>发现其他在线 agent</li>
          <li>查看其他 agent 的终端上下文</li>
          <li>向其他 agent 发送协作请求</li>
          <li>在飞书中通过机器人交互</li>
        </ul>

        <pre className="codeBlock">
{`# Agent 发现 peers
agenttalk list

# 查看目标 agent 的上下文（避免打扰正在忙碌的 agent）
agenttalk context alice-codex-api --lines 120

# 发送协作请求
agenttalk send --to alice-codex-api --message "请检查 docs/api.md 的接口契约"

# 等待响应（--watch 模式）
agenttalk send --to alice-codex-api --message "请检查 docs/api.md" --watch`}
        </pre>

        <h3>7. 常用命令</h3>
        <pre className="codeBlock">
{`# 列出所有 agent
agenttalk list

# 查看 agent 状态
agenttalk status <message-id>

# 发送消息给 agent
agenttalk send --to my-agent-001 --message "检查接口契约"

# 删除 agent 注册
agenttalk unregister --short-id my-agent-001

# 修改接收模式
agenttalk mode my-agent-001 auto_submit
agenttalk mode my-agent-001 paste_only`}
        </pre>

        <h3>8. 飞书机器人命令</h3>
        <p>在飞书中与机器人交互：</p>
        <pre className="codeBlock">
{`/help                    # 显示帮助
/agents                  # 列出所有 agent
/agents online           # 列出在线 agent
/agent <agent-id>        # 查看 agent 详情
/context <agent-id>      # 查看 agent 上下文
/send <agent-id> <msg>   # 发送消息
/status <message-id>     # 查看消息状态
/response <message-id>   # 查看响应内容`}
        </pre>

        <h3>9. 配置说明</h3>
        <table className="configTable">
          <thead>
            <tr>
              <th>参数</th>
              <th>说明</th>
              <th>示例</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>short-id</td>
              <td>全局唯一 agent ID</td>
              <td>alice-codex-api</td>
            </tr>
            <tr>
              <td>tmux-target</td>
              <td>tmux 目标 pane</td>
              <td>dev:0.1</td>
            </tr>
            <tr>
              <td>owner</td>
              <td>所有者标识</td>
              <td>alice</td>
            </tr>
            <tr>
              <td>kind</td>
              <td>Agent 类型</td>
              <td>codex, claude, cursor</td>
            </tr>
            <tr>
              <td>workspace</td>
              <td>工作目录</td>
              <td>/workspace/service-api</td>
            </tr>
            <tr>
              <td>receive-mode</td>
              <td>消息接收模式</td>
              <td>auto_submit / paste_only</td>
            </tr>
          </tbody>
        </table>

        <h3>10. 注意事项</h3>
        <ul>
          <li>Agent 必须运行在 tmux pane 中才能接收远程消息（tmux 用于保活）</li>
          <li>Web UI 中的 Live Terminal 使用原生 PTY，支持完整的终端交互（vim、光标、ANSI 颜色）</li>
          <li>PTY 终端是独立的，不影响 tmux 中的 agent 进程</li>
          <li>auto_submit 模式会自动提交消息，paste_only 仅粘贴不提交</li>
          <li>Relay 需要保持运行才能维持 agent 在线状态</li>
          <li>每个 agent 的 short-id 必须全局唯一</li>
        </ul>
      </section>
    </div>
  )
}

function AutoResumeEditor({ agent }: { agent: Agent }) {
  const [config, setConfig] = useState({
    enabled: agent.auto_resume_enabled ?? true,
    message: agent.auto_resume_message ?? '继续',
  })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setConfig({
      enabled: agent.auto_resume_enabled ?? true,
      message: agent.auto_resume_message ?? '继续',
    })
  }, [agent])

  async function handleToggle(enabled: boolean) {
    const newConfig = { ...config, enabled }
    setConfig(newConfig)
    setSaving(true)
    try {
      await setAgentAutoResume(agent.short_id, newConfig)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save auto-resume:', err)
    } finally {
      setSaving(false)
    }
  }

  async function handleSave() {
    setSaving(true)
    try {
      await setAgentAutoResume(agent.short_id, config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save auto-resume:', err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="autoResumeCard">
      <div className="autoResumeHeader">
        <h3>Auto Resume</h3>
        <span className={`badge ${config.enabled ? 'success' : 'neutral'}`}>
          {config.enabled ? 'Enabled' : 'Disabled'}
        </span>
      </div>
      <p className="helpText">
        Automatically send resume message when agent is paused due to LLM/network issues.
      </p>
      <label className="toggleRow">
        <input
          type="checkbox"
          checked={config.enabled}
          onChange={(e) => handleToggle(e.target.checked)}
        />
        <span>Enable auto-resume</span>
      </label>
      <div className="inputRow">
        <label>Resume message:</label>
        <input
          type="text"
          value={config.message}
          onChange={(e) => setConfig({ ...config, message: e.target.value })}
          placeholder="继续"
          disabled={!config.enabled}
        />
      </div>
      <button 
        className="primary small" 
        onClick={handleSave} 
        disabled={saving}
      >
        {saving ? 'Saving...' : saved ? 'Saved!' : 'Save'}
      </button>
    </div>
  )
}

function SettingsPage() {
  const [llmConfig, setLlmConfig] = useState<LLMConfig>({
    base_url: '',
    api_key: '',
    model: 'gpt-4o-mini',
    enabled: false,
  })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getLLMConfig()
      .then((llm) => setLlmConfig(llm))
      .catch(() => setMessage('Failed to load config'))
  }, [])

  async function handleSaveLLM() {
    setSaving(true)
    setMessage('')
    try {
      await setLLMConfig(llmConfig)
      setMessage('LLM config saved successfully')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="quickstart">
      <section>
        <h2>Settings</h2>

        <h3 style={{ marginTop: '2rem' }}>LLM Configuration</h3>
        <p>Configure the LLM for agent status analysis.</p>
        <div style={{ marginTop: '1rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
            <input
              type="checkbox"
              checked={llmConfig.enabled}
              onChange={(e) => setLlmConfig({ ...llmConfig, enabled: e.target.checked })}
            />
            Enable LLM analysis
          </label>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>Base URL</label>
            <input
              type="text"
              value={llmConfig.base_url}
              onChange={(e) => setLlmConfig({ ...llmConfig, base_url: e.target.value })}
              placeholder="https://api.openai.com/v1 or http://localhost:8000/v1"
              style={{ width: '100%', maxWidth: '400px' }}
              disabled={!llmConfig.enabled}
            />
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>API Key</label>
            <input
              type="password"
              value={llmConfig.api_key}
              onChange={(e) => setLlmConfig({ ...llmConfig, api_key: e.target.value })}
              placeholder="sk-..."
              style={{ width: '100%', maxWidth: '400px' }}
              disabled={!llmConfig.enabled}
            />
          </div>

          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>Model</label>
            <input
              type="text"
              value={llmConfig.model}
              onChange={(e) => setLlmConfig({ ...llmConfig, model: e.target.value })}
              placeholder="gpt-4o-mini"
              style={{ width: '100%', maxWidth: '400px' }}
              disabled={!llmConfig.enabled}
            />
          </div>
        </div>

        <button className="primary" onClick={handleSaveLLM} disabled={saving}>
          {saving ? 'Saving...' : 'Save LLM Config'}
        </button>

        {message && (
          <div style={{ marginTop: '1rem', color: message.includes('success') ? 'green' : 'red' }}>
            {message}
          </div>
        )}
      </section>
    </div>
  )
}

function AgentSummary({ agent }: { agent: Agent }) {
  return (
    <div className="summary">
      <div className="summaryTop">
        <div>
          <h2>{agent.short_id}</h2>
          <p>
            {agent.owner} &middot; {agent.kind}
          </p>
        </div>
        <StatusBadge status={agent.status} />
      </div>
      <dl>
        <div>
          <dt>Machine</dt>
          <dd>{agent.machine_id}</dd>
        </div>
        <div>
          <dt>Workspace</dt>
          <dd>{agent.workspace}</dd>
        </div>
        <div>
          <dt>tmux</dt>
          <dd>{agent.tmux_target}</dd>
        </div>
        <div>
          <dt>Receive</dt>
          <dd>{agent.receive_mode}</dd>
        </div>
      </dl>
    </div>
  )
}

function MessageBox({
  agent,
  onSend,
  compact = false,
}: {
  agent: Agent
  onSend: (agent: Agent, body: string, watch: boolean) => Promise<void>
  compact?: boolean
}) {
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(watch: boolean) {
    if (!body.trim()) return
    setBusy(true)
    try {
      await onSend(agent, body.trim(), watch)
      setBody('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={compact ? 'messageBox compact' : 'messageBox'}>
      <label htmlFor={`message-${agent.short_id}`}>AgentTalk Message</label>
      <textarea
        id={`message-${agent.short_id}`}
        placeholder="Ask this agent to review, inspect, or coordinate..."
        value={body}
        onChange={(event) => setBody(event.target.value)}
      />
      <div className="buttonRow">
        <button className="primary" disabled={busy || !body.trim()} onClick={() => submit(false)}>
          Send
        </button>
        <button className="secondary" disabled={busy || !body.trim()} onClick={() => submit(true)}>
          Send & Watch
        </button>
      </div>
    </div>
  )
}

function RecentMessages({ messages }: { messages: Message[] }) {
  return (
    <div className="recentMessages">
      <h2>Recent Messages</h2>
      {messages.length ? (
        messages.map((message) => (
          <div className="messageRow" key={message.message_id}>
            <span className="mono">{message.message_id}</span>
            <StatusPill label={message.status} />
          </div>
        ))
      ) : (
        <p>No recent messages.</p>
      )}
    </div>
  )
}

function ContextBlock({ context, tall = false }: { context: string; tall?: boolean }) {
  return <pre className={tall ? 'contextBlock tall' : 'contextBlock'}>{context || 'No context captured yet.'}</pre>
}

function StatusBadge({ status }: { status: Agent['status'] }) {
  return <span className={`status ${status}`}>{statusLabel(status)}</span>
}

function StatusPill({ label }: { label: string }) {
  return <span className="status neutral">{label}</span>
}

function LiveTerminal({ agent }: { agent: Agent }) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: 13,
      theme: { background: '#0f172a', foreground: '#dbeafe' },
      scrollback: 1000,
      rows: 24,
      cols: 80,
    })
    terminal.open(ref.current)
    terminal.focus()

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/pty/${agent.short_id}`)
    socket.binaryType = 'arraybuffer'

    socket.addEventListener('open', () => {
      terminal.writeln('\x1b[32m[Connected to PTY]\x1b[0m')
      // Send initial terminal size
      socket.send(`\x01${terminal.rows}:${terminal.cols}`)
    })

    socket.addEventListener('message', (event) => {
      const data = new Uint8Array(event.data)
      terminal.write(data)
    })

    socket.addEventListener('close', () => {
      terminal.writeln('\x1b[31m[Disconnected]\x1b[0m')
    })

    socket.addEventListener('error', (err) => {
      console.error('WebSocket error:', err)
      terminal.writeln('\x1b[31m[Connection error]\x1b[0m')
    })

    terminal.onData((data) => {
      console.log('Terminal input:', JSON.stringify(data))
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(data)
      } else {
        console.warn('WebSocket not open, cannot send:', socket.readyState)
      }
    })

    // Ensure terminal is focusable and focused
    const terminalContainer = ref.current
    if (terminalContainer) {
      terminalContainer.addEventListener('click', () => {
        terminal.focus()
        console.log('Terminal focused via click')
      })
      // Auto-focus after a short delay
      setTimeout(() => {
        terminal.focus()
        console.log('Terminal auto-focused')
      }, 500)
    }

    const handleResize = () => {
      // Update terminal size on window resize
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(`\x01${terminal.rows}:${terminal.cols}`)
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      socket.close()
      terminal.dispose()
    }
  }, [agent.short_id])

  return <div className="terminal" data-testid="live-terminal" ref={ref} tabIndex={0} role="textbox" aria-label="Terminal" />
}

export default App
