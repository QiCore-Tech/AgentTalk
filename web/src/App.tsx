import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import {
  type Agent,
  type AgentContext,
  type Message,
  deleteAgent,
  getAgentContext,
  getMessage,
  listAgents,
  sendMessage,
} from './api'
import './App.css'

type Page = 'agents' | 'context' | 'detail' | 'quickstart'

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

  useEffect(() => {
    void refreshAgents()
  }, [refreshAgents])

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
    const created = await sendMessage(agent.short_id, body)
    setMessages((current) => [created, ...current].slice(0, 12))
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
        <nav>
          <button className={page === 'agents' ? 'active' : ''} onClick={() => setPage('agents')}>
            Agents
          </button>
          <button className={page === 'context' ? 'active' : ''} onClick={() => setPage('context')}>
            Context
          </button>
          <button
            className={page === 'detail' ? 'active' : ''}
            disabled={!selectedAgent}
            onClick={() => setPage('detail')}
          >
            Detail
          </button>
          <button className={page === 'quickstart' ? 'active' : ''} onClick={() => setPage('quickstart')}>
            Quick Start
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
            context={contexts[selectedAgent.short_id]}
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
      </section>
    </main>
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
        {!props.allAgents.length ? <div className="empty">No agents registered.</div> : null}
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
  context,
  messages,
  onSend,
  onDelete,
}: {
  agent: Agent
  context?: AgentContext
  messages: Message[]
  onSend: (agent: Agent, body: string, watch: boolean) => Promise<void>
  onDelete: (shortId: string) => void
}) {
  return (
    <div className="detailGrid">
      <section className="panel detailMeta">
        <AgentSummary agent={agent} />
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
        <LiveTerminal agent={agent} initialText={context?.context || 'Waiting for terminal stream...'} />
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

        <h3>1. 前置要求</h3>
        <ul>
          <li>Python 3.12+</li>
          <li>tmux（agent 必须运行在 tmux pane 中）</li>
          <li>Git（克隆代码仓库）</li>
        </ul>

        <h3>2. 安装 AgentTalk</h3>
        <pre className="codeBlock">
{`# 克隆仓库
git clone https://git.qicore.tech/wenda.sheng/soha_agentTalk
cd agenttalk

# 安装依赖（使用 uv 或 pip）
uv sync --extra feishu
# 或
pip install -e ".[feishu]"`}
        </pre>

        <h3>3. 配置 Hub 连接</h3>
        <pre className="codeBlock">
{`# 设置 Hub 地址和 Token
agenttalk setup ${hubUrl} --token ${token}`}
        </pre>

        <h3>4. 发现 tmux pane</h3>
        <pre className="codeBlock">
{`# 查看可用的 tmux pane
agenttalk discover

# 或使用脚本
scripts/start-client.sh --discover`}
        </pre>

        <h3>5. 注册 Agent</h3>
        <pre className="codeBlock">
{`# 方法 1：使用 CLI
agenttalk register \\
  --short-id my-agent-001 \\
  --tmux-target dev:0.1 \\
  --owner $(whoami) \\
  --kind codex \\
  --workspace /path/to/project

# 方法 2：使用启动脚本
scripts/start-client.sh \\
  --hub-url ${hubUrl} \\
  --token ${token} \\
  --short-id my-agent-001 \\
  --tmux-target dev:0.1 \\
  --owner $(whoami) \\
  --kind codex \\
  --workspace /path/to/project`}
        </pre>

        <h3>6. 启动 Relay（守护进程）</h3>
        <pre className="codeBlock">
{`# 启动后台 relay，定期同步 agent 状态
agenttalk daemon start

# 或一次性同步
agenttalk daemon start --once

# 使用脚本启动
scripts/start-client.sh \\
  --hub-url ${hubUrl} \\
  --token ${token} \\
  --short-id my-agent-001 \\
  --tmux-target dev:0.1`}
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
          <li>Agent 必须运行在 tmux pane 中才能接收远程消息</li>
          <li>auto_submit 模式会自动提交消息，paste_only 仅粘贴不提交</li>
          <li>Relay 需要保持运行才能维持 agent 在线状态</li>
          <li>每个 agent 的 short-id 必须全局唯一</li>
        </ul>
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

function LiveTerminal({ agent, initialText }: { agent: Agent; initialText: string }) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: 13,
      rows: 22,
      theme: { background: '#0f172a', foreground: '#dbeafe' },
    })
    terminal.open(ref.current)
    terminal.writeln(`AgentTalk terminal: ${agent.short_id}`)
    terminal.writeln('WebSocket bridge ready for live tmux streaming.')
    terminal.writeln('')
    initialText.split('\n').slice(-18).forEach((line) => terminal.writeln(line))
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/terminal/${agent.short_id}`)
    socket.addEventListener('message', (event) => {
      terminal.write(String(event.data))
    })
    terminal.onData((data) => {
      terminal.write(data)
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(data)
      }
    })
    return () => {
      socket.close()
      terminal.dispose()
    }
  }, [agent.short_id, initialText, ref])

  return <div className="terminal" data-testid="live-terminal" ref={ref} />
}

export default App
