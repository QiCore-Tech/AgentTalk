import { useEffect, useMemo, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import {
  type Agent,
  type AgentContext,
  type Message,
  getAgentContext,
  getMessage,
  listAgents,
  sendMessage,
} from './api'
import './App.css'

type Page = 'agents' | 'context' | 'detail'

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

  useEffect(() => {
    refreshAgents()
  }, [])

  const selectedAgent = agents.find((agent) => agent.short_id === selectedId) || agents[0]

  useEffect(() => {
    if (!selectedId && agents[0]) setSelectedId(agents[0].short_id)
  }, [agents, selectedId])

  useEffect(() => {
    if (selectedAgent) loadContext(selectedAgent.short_id)
  }, [selectedAgent?.short_id])

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

  async function refreshAgents() {
    try {
      setError('')
      const next = await listAgents()
      setAgents(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function loadContext(shortId: string) {
    try {
      const context = await getAgentContext(shortId)
      setContexts((current) => ({ ...current, [shortId]: context }))
    } catch {
      setContexts((current) => ({
        ...current,
        [shortId]: { short_id: shortId, context: '', updated_at: null },
      }))
    }
  }

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
        </nav>
        <div className="sidebarStats">
          <span>{agents.length} registered</span>
          <span>{agents.filter((agent) => agent.status !== 'offline').length} reachable</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{page === 'context' ? 'Context Overview' : page === 'detail' ? 'Agent Detail' : 'Agents'}</h1>
            <p>Monitor, message, and inspect tmux-hosted agents.</p>
          </div>
          <button className="primary" onClick={refreshAgents}>
            Refresh
          </button>
        </header>
        {error ? <div className="error">{error}</div> : null}

        {page === 'agents' && (
          <AgentsHome
            agents={filteredAgents}
            allAgents={agents}
            selectedAgent={selectedAgent}
            selectedId={selectedId}
            query={query}
            statusFilter={statusFilter}
            context={selectedAgent ? contexts[selectedAgent.short_id] : undefined}
            messages={messages}
            onQuery={setQuery}
            onStatusFilter={setStatusFilter}
            onSelect={setSelectedId}
            onOpenDetail={() => setPage('detail')}
            onSend={handleSend}
          />
        )}

        {page === 'detail' && selectedAgent && (
          <AgentDetail
            agent={selectedAgent}
            context={contexts[selectedAgent.short_id]}
            messages={messages.filter((message) => message.target === selectedAgent.short_id)}
            onSend={handleSend}
          />
        )}

        {page === 'context' && (
          <ContextOverview
            agents={agents}
            contexts={contexts}
            onLoadContext={loadContext}
            onSelect={(id) => {
              setSelectedId(id)
              setPage('detail')
            }}
          />
        )}
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
}: {
  agent: Agent
  context?: AgentContext
  messages: Message[]
  onSend: (agent: Agent, body: string, watch: boolean) => Promise<void>
}) {
  return (
    <div className="detailGrid">
      <section className="panel detailMeta">
        <AgentSummary agent={agent} />
        <MessageBox agent={agent} onSend={onSend} />
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
  onLoadContext,
  onSelect,
}: {
  agents: Agent[]
  contexts: Record<string, AgentContext>
  onLoadContext: (id: string) => void
  onSelect: (id: string) => void
}) {
  useEffect(() => {
    agents.forEach((agent) => onLoadContext(agent.short_id))
  }, [agents])

  return (
    <div className="contextList">
      {agents.map((agent) => (
        <section className="panel contextItem" key={agent.short_id}>
          <div className="contextHeader">
            <div>
              <h2>{agent.short_id}</h2>
              <p>
                {agent.kind} · {agent.owner} · {agent.workspace}
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

function AgentSummary({ agent }: { agent: Agent }) {
  return (
    <div className="summary">
      <div className="summaryTop">
        <div>
          <h2>{agent.short_id}</h2>
          <p>
            {agent.owner} · {agent.kind}
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
