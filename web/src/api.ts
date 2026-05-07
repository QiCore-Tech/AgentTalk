export type AgentStatus = 'offline' | 'online' | 'active' | 'working' | 'stale'
export type ReceiveMode = 'auto_submit' | 'paste_only'

export interface Agent {
  short_id: string
  machine_id: string
  owner: string
  kind: string
  workspace: string
  tmux_target: string
  receive_mode: ReceiveMode
  status: AgentStatus
  updated_at: string
  relay_last_seen_at?: string | null
  auto_resume_enabled?: boolean
  auto_resume_message?: string
}

export interface Message {
  message_id: string
  sender: string
  target: string
  target_machine_id: string
  body: string
  done_marker: string
  status: string
  error: string
  created_at: string
  updated_at: string
}

export interface AgentContext {
  short_id: string
  context: string
  updated_at: string | null
}

const API_BASE = import.meta.env.VITE_AGENTTALK_API_BASE || ''
const TOKEN = import.meta.env.VITE_AGENTTALK_TOKEN || ''

function headers() {
  return {
    Authorization: `Bearer ${TOKEN}`,
    'Content-Type': 'application/json',
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...headers(), ...(init?.headers || {}) },
  })
  if (!response.ok) {
    throw new Error(await response.text())
  }
  return response.json() as Promise<T>
}

export async function listAgents(): Promise<Agent[]> {
  const payload = await request<{ agents: Agent[] }>('/api/agents')
  return payload.agents
}

export async function getAgentContext(shortId: string): Promise<AgentContext> {
  return request<AgentContext>(`/api/agents/${encodeURIComponent(shortId)}/context`)
}

export async function sendMessage(target: string, body: string, sender = 'web'): Promise<Message> {
  return request<Message>('/api/messages', {
    method: 'POST',
    body: JSON.stringify({ to: target, body, sender }),
  })
}

export async function getMessage(messageId: string): Promise<Message> {
  return request<Message>(`/api/messages/${encodeURIComponent(messageId)}`)
}

export async function deleteAgent(shortId: string): Promise<void> {
  await request<void>(`/api/agents/${encodeURIComponent(shortId)}`, {
    method: 'DELETE',
  })
}

export async function sendToPTY(shortId: string, text: string): Promise<void> {
  // Send directly to PTY via WebSocket or API
  const response = await fetch(`${API_BASE}/api/agents/${encodeURIComponent(shortId)}/pty`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ text }),
  })
  if (!response.ok) {
    throw new Error(await response.text())
  }
}

export interface LLMConfig {
  base_url: string
  api_key: string
  model: string
  enabled: boolean
}

export async function getLLMConfig(): Promise<LLMConfig> {
  return request<LLMConfig>('/api/config/llm')
}

export async function setLLMConfig(config: LLMConfig): Promise<void> {
  await request<void>('/api/config/llm', {
    method: 'POST',
    body: JSON.stringify(config),
  })
}

export interface AutoResumeConfig {
  enabled: boolean
  message: string
}

export async function getAgentAutoResume(shortId: string): Promise<AutoResumeConfig> {
  return request<AutoResumeConfig>(`/api/agents/${encodeURIComponent(shortId)}/auto_resume`)
}

export async function setAgentAutoResume(shortId: string, config: AutoResumeConfig): Promise<void> {
  await request<void>(`/api/agents/${encodeURIComponent(shortId)}/auto_resume`, {
    method: 'POST',
    body: JSON.stringify(config),
  })
}
