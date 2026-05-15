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

// ==================== Feishu Bot APIs ====================

export interface FeishuBot {
  id: number
  user_id: string
  name: string
  app_id: string
  app_secret: string
  status: string
  created_at: string
}

export async function listFeishuBots(): Promise<FeishuBot[]> {
  const payload = await request<{ bots: FeishuBot[] }>('/api/feishu/bots')
  return payload.bots
}

export async function createFeishuBot(name: string, appId: string, appSecret: string): Promise<{ id: number; status: string }> {
  return request('/api/feishu/bots', {
    method: 'POST',
    body: JSON.stringify({ name, app_id: appId, app_secret: appSecret }),
  })
}

export async function deleteFeishuBot(botId: number): Promise<void> {
  await request<void>(`/api/feishu/bots/${botId}`, { method: 'DELETE' })
}

// ==================== Notification Route APIs ====================

export interface NotificationRoute {
  id: number
  agent_short_id: string
  user_id: string
  event_type: string
  destination_type: string
  destination_id: string
  feishu_bot_id: number
  enabled: boolean
  created_at: string
}

export async function listNotificationRoutes(agentShortId: string): Promise<NotificationRoute[]> {
  const payload = await request<{ routes: NotificationRoute[] }>(`/api/agents/${encodeURIComponent(agentShortId)}/notifications`)
  return payload.routes
}

export async function createNotificationRoute(
  agentShortId: string,
  eventType: string,
  destinationType: string,
  destinationId: string,
  feishuBotId: number,
): Promise<{ route_id: number; enabled: boolean }> {
  return request(`/api/agents/${encodeURIComponent(agentShortId)}/notifications`, {
    method: 'POST',
    body: JSON.stringify({ agent_short_id: agentShortId, event_type: eventType, destination_type: destinationType, destination_id: destinationId, feishu_bot_id: feishuBotId }),
  })
}

export async function deleteNotificationRoute(agentShortId: string, routeId: number): Promise<void> {
  await request<void>(`/api/agents/${encodeURIComponent(agentShortId)}/notifications/${routeId}`, { method: 'DELETE' })
}

// ==================== Task APIs ====================

export interface Task {
  id: number
  task_id: string
  type: string
  status: string
  owner_id: string
  raw_request: string
  result: string
  logs: string
  created_at: string
  current_step: number
  total_steps: number
}

export async function listTasks(): Promise<Task[]> {
  const payload = await request<{ tasks: Task[] }>('/api/tasks')
  return payload.tasks
}

export async function submitTask(rawRequest: string, targetMachineId: number): Promise<{ task_id: string; status: string }> {
  return request('/api/tasks', {
    method: 'POST',
    body: JSON.stringify({ raw_request: rawRequest, target_machine_id: targetMachineId }),
  })
}
