# AgentTalk 高级任务系统 - 设计规划

## 版本: 2026-05-09
## 状态: 规划中

---

## 1. 需求概述

实现一个常驻 Hub 的 **Orchestrator Agent**，能够接收用户高级指令（如："帮我在 rabbit 项目新开一个 codex，拉取最新代码，分析差异并生成文档"），并自动完成以下工作流：

1. 在指定项目的 workspace 中创建环境
2. 启动 codex/claude 等 agent
3. 自动拉取代码
4. 执行分析任务
5. 生成总结文档

---

## 2. 核心架构

### 2.1 实体关系

```
User (通过现有 Auth 体系认证)
├── Machines (开发机) [1:N] - 用户通过 Relay 注册
│   └── Workspace (工作空间) [1:N]
│       └── Agent [1:N] ← 注册在该机器的 tmux 中
└── Tasks (工单) [1:N]
    └── 可能跨多个 Machine 执行
```

**关键区别：**
- **用户的 Agent** = 在用户的开发机上，通过 Relay 注册到 Hub
- **Orchestrator** = 在 Hub 端运行，接收高级指令，通过 Relay API 操控用户机器
- **机器注册** = Relay 启动时弹出注册链接，用户通过认证平台登录后完成绑定

### 2.2 执行流程

```
用户通过 Web UI / 飞书机器人 / API 提交任务
         ↓
Hub Orchestrator 接收任务，调用 LLM 解析为结构化步骤
         ↓
查询用户指定的 Machine
         ↓
通过 Relay HTTP API 向目标机器发送指令
         ↓
Relay 在本地执行：tmux new → start codex → register agent
         ↓
新 Agent 注册回 Hub，Relay 开始监控
         ↓
Orchestrator 向新 Agent 发送任务消息
         ↓
监控任务完成（done marker）
         ↓
收集结果，生成文档，通知用户
```

---

## 3. 数据库设计

### 3.1 机器表 (machines)

```sql
CREATE TABLE machines (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,              -- 关联现有 auth 体系的用户ID
    name TEXT NOT NULL,                 -- 机器名称，如 "MacBook-Pro"
    host_name TEXT NOT NULL,            -- 实际 hostname
    relay_machine_id TEXT UNIQUE NOT NULL,  -- 关联 relay.machine_id
    status TEXT DEFAULT 'offline',      -- online/offline
    last_seen_at TEXT,
    capabilities TEXT,                  -- JSON: ["tmux", "codex", "claude", "docker"]
    created_at TEXT,
    
    -- 新增：用户隔离相关
    visibility TEXT DEFAULT 'private',  -- private/shared/public
    shared_with TEXT                    -- JSON: [user_id1, user_id2]
);
```

### 3.2 工作空间表 (workspaces)

```sql
CREATE TABLE workspaces (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,                 -- 绝对路径
    owner_id TEXT NOT NULL,             -- 关联现有 auth 体系
    machine_id INTEGER NOT NULL,
    description TEXT,
    created_at TEXT,
    
    -- 用户隔离
    visibility TEXT DEFAULT 'private',  -- private/shared/public
    shared_with TEXT                    -- JSON: [user_id1, user_id2]
);
```

### 3.3 工单表 (tasks)

```sql
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    task_id TEXT UNIQUE NOT NULL,       -- 如 task-20260509-abc123
    type TEXT NOT NULL,                 -- provision_agent, execute_task, run_command
    status TEXT DEFAULT 'pending',      -- pending/queued/running/completed/failed/cancelled
    owner_id TEXT NOT NULL,             -- 关联现有 auth 体系
    
    -- 目标
    target_workspace_id INTEGER,
    target_machine_id INTEGER,          -- 用户指定的机器
    
    -- 原始请求
    raw_request TEXT,                   -- 用户的自然语言请求
    
    -- LLM 解析后的任务定义
    parsed_steps TEXT NOT NULL,         -- JSON
    
    -- 执行结果
    result TEXT,
    logs TEXT,                          -- 执行日志（追加）
    
    -- 创建的 agent（如果是 provision_agent）
    created_agent_id TEXT,
    
    -- 时间
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    timeout_seconds INTEGER DEFAULT 3600
);
```

### 3.4 Agent 权限表

```sql
CREATE TABLE agent_permissions (
    id INTEGER PRIMARY KEY,
    agent_short_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    permission TEXT NOT NULL,           -- view/manage/admin
    granted_by TEXT NOT NULL,           -- 谁授权的
    created_at TEXT
);
```

---

## 4. API 设计

### 4.1 机器管理

```python
# 列出我的机器
GET /api/machines
→ [{id, name, host_name, status, last_seen_at, capabilities}]

# Relay 注册机器（启动时调用，返回注册链接）
POST /api/machines/register-request
{"host_name": "...", "machine_id": "..."}
→ {"registration_url": "https://agents.qicore.tech/auth/register?token=xyz", "expires_at": "..."}

# 完成机器注册（用户点击链接后，认证平台回调）
POST /api/machines/complete-registration
{"token": "xyz", "user_id": "...", "machine_name": "..."}
→ {"success": true, "machine_id": 1}

# 删除机器
DELETE /api/machines/{id}
```

### 4.2 Workspace 管理

```python
GET    /api/workspaces                    # 列出我有权限的 workspace
POST   /api/workspaces                    # 创建 workspace
{"name": "rabbit", "path": "/workspace/rabbit", "machine_id": 1}
DELETE /api/workspaces/{id}
```

### 4.3 任务系统

```python
# 提交任务（自然语言）
POST /api/tasks
{
    "raw_request": "帮我在 rabbit 项目新开一个 codex，拉取最新代码，分析差异并生成文档",
    "target_machine_id": 1,           # 用户指定
    "target_workspace_id": 2          # 可选
}
→ {"task_id": "task-20260509-abc123", "status": "queued"}

# 查询任务状态
GET /api/tasks/{task_id}
→ {
    "task_id": "...",
    "status": "running",
    "current_step": 3,
    "logs": "...",
    "created_agent_id": "rabbit-codex-123"
}

# 列出我的任务
GET /api/tasks?status=running&limit=10
```

### 4.4 Agent 权限

```python
# 分享 agent
POST /api/agents/{short_id}/permissions
{"user_id": "...", "permission": "view"}

# 修改 agent 可见性
PATCH /api/agents/{short_id}
{"visibility": "shared", "shared_with": ["user1", "user2"]}
```

---

## 5. Orchestrator 执行引擎

### 5.1 LLM 任务解析

```python
# src/agenttalk/hub/task_parser.py

TASK_PARSE_PROMPT = """
你是一个 AgentTalk 任务解析器。请将用户的自然语言请求解析为结构化的执行步骤。

可用步骤类型：
- ensure_workspace: 确保 workspace 存在
- git_sync: 拉取代码
- provision_agent: 创建并启动 agent
- send_message: 向 agent 发送任务消息
- wait_for_done_marker: 等待任务完成标记
- verify_output: 验证输出文件
- shell: 执行 shell 命令

用户请求：{request}
目标 workspace：{workspace}
目标机器：{machine}

请输出 JSON：
{
    "description": "任务描述",
    "steps": [
        {"step": 1, "action": "...", "...": "..."}
    ],
    "estimated_duration": "预计时间（秒）"
}
"""

class TaskParser:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
    
    async def parse(self, request: str, workspace: str = None, machine: str = None) -> dict:
        """使用 LLM 解析自然语言请求。"""
        prompt = TASK_PARSE_PROMPT.format(
            request=request,
            workspace=workspace or "未指定",
            machine=machine or "未指定"
        )
        response = await self.llm.complete(prompt)
        return json.loads(response)
```

### 5.2 任务执行器

```python
# src/agenttalk/hub/orchestrator.py

class TaskOrchestrator:
    """Hub-side task execution engine."""
    
    def __init__(self, store: HubStore, relay_client: RelayClient, task_parser: TaskParser):
        self.store = store
        self.relay = relay_client
        self.parser = task_parser
        
    async def submit_task(self, user_id: str, raw_request: str, target_machine_id: int, target_workspace_id: int = None) -> str:
        """提交新任务。"""
        # 1. 解析任务
        workspace = None
        if target_workspace_id:
            workspace = self.store.get_workspace(target_workspace_id)
        
        parsed = await self.parser.parse(raw_request, workspace=workspace.name if workspace else None)
        
        # 2. 创建任务记录
        task_id = f"task-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        self.store.create_task(
            task_id=task_id,
            owner_id=user_id,
            target_machine_id=target_machine_id,
            target_workspace_id=target_workspace_id,
            raw_request=raw_request,
            parsed_steps=json.dumps(parsed["steps"]),
            status="queued"
        )
        
        # 3. 异步执行
        asyncio.create_task(self._execute_task(task_id))
        
        return task_id
    
    async def _execute_task(self, task_id: str):
        """执行任务的各个步骤。"""
        task = self.store.get_task(task_id)
        steps = json.loads(task.parsed_steps)
        
        self.store.update_task_status(task_id, "running")
        
        context = {}  # 步骤间上下文（如 step_3 生成的 short_id）
        
        for step in steps:
            try:
                result = await self._execute_step(task, step, context)
                context[f"step_{step['step']}"] = result
                self.store.append_task_log(task_id, f"✓ Step {step['step']}: {step['action']}")
            except Exception as e:
                self.store.update_task_status(task_id, "failed", error=str(e))
                self.store.append_task_log(task_id, f"✗ Step {step['step']}: {str(e)}")
                return
        
        self.store.update_task_status(task_id, "completed")
    
    async def _execute_step(self, task, step, context):
        """执行单个步骤。"""
        machine = self.store.get_machine(task.target_machine_id)
        
        # 解析模板变量（如 {{step_3.short_id}}）
        step = self._resolve_templates(step, context)
        
        if step["action"] == "provision_agent":
            instruction = {
                "type": "provision_agent",
                "kind": step["kind"],
                "short_id": step["short_id"],
                "workspace": step["workspace"],
                "receive_mode": step.get("receive_mode", "auto_submit")
            }
            result = await self.relay.send_instruction(machine.relay_machine_id, instruction)
            
            # 等待 agent 注册
            agent = await self._wait_for_agent(step["short_id"], timeout=60)
            return {"short_id": step["short_id"], "status": "created"}
            
        elif step["action"] == "send_message":
            message = await self._send_agent_message(step["to"], step["body"])
            return {"message_id": message.message_id}
            
        elif step["action"] == "wait_for_done_marker":
            return await self._wait_for_completion(step["agent_id"], timeout=step.get("timeout", 3600))
            
        elif step["action"] == "git_sync":
            instruction = {
                "type": "shell",
                "command": f"cd {step['workspace']} && git pull origin {step.get('branch', 'main')}"
            }
            return await self.relay.send_instruction(machine.relay_machine_id, instruction)
            
        elif step["action"] == "shell":
            instruction = {
                "type": "shell",
                "command": step["command"]
            }
            return await self.relay.send_instruction(machine.relay_machine_id, instruction)
    
    def _resolve_templates(self, step, context):
        """解析步骤中的模板变量。"""
        step_json = json.dumps(step)
        for key, value in context.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    step_json = step_json.replace(f"{{{{{key}.{sub_key}}}}}", str(sub_value))
        return json.loads(step_json)
```

---

## 6. Relay 端指令处理

### 6.1 新增指令接收 API

Relay 现有轮询机制 `GET /api/relays/{machine_id}/messages/next` 需要扩展支持任务指令：

```python
# src/agenttalk/relay.py

class InstructionPoller:
    """Poll instructions from Hub."""
    
    def __init__(self, hub_client: HubClient, machine_id: str):
        self.hub = hub_client
        self.machine_id = machine_id
        
    async def poll(self):
        """轮询新指令。"""
        while True:
            try:
                instructions = await self.hub.get_instructions(self.machine_id)
                for instruction in instructions:
                    await self.execute(instruction)
                await asyncio.sleep(5)
            except Exception:
                await asyncio.sleep(10)
    
    async def execute(self, instruction: dict):
        """执行指令。"""
        action = instruction["type"]
        
        if action == "provision_agent":
            executor = AgentProvisioner()
            return await executor.provision(instruction)
            
        elif action == "shell":
            result = subprocess.run(
                instruction["command"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=instruction.get("timeout", 300)
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
```

### 6.2 Agent 创建器

```python
# src/agenttalk/relay.py

class AgentProvisioner:
    """在本地创建并启动 agent。"""
    
    async def provision(self, instruction: dict) -> dict:
        short_id = instruction["short_id"]
        kind = instruction["kind"]
        workspace = instruction["workspace"]
        receive_mode = instruction.get("receive_mode", "auto_submit")
        
        # 1. 确保 workspace 目录存在
        os.makedirs(workspace, exist_ok=True)
        
        # 2. 创建 tmux session
        session_name = f"agent-{short_id}"
        subprocess.run([
            "tmux", "new-session", "-d", "-s", session_name,
            "-c", workspace
        ], check=True)
        
        # 3. 启动 agent CLI
        if kind == "codex":
            subprocess.run([
                "tmux", "send-keys", "-t", f"{session_name}:0.0",
                "codex", "Enter"
            ])
        elif kind == "claude":
            subprocess.run([
                "tmux", "send-keys", "-t", f"{session_name}:0.0",
                "claude", "Enter"
            ])
        elif kind == "gemini":
            subprocess.run([
                "tmux", "send-keys", "-t", f"{session_name}:0.0",
                "gemini", "Enter"
            ])
        
        # 4. 等待 agent 启动
        await asyncio.sleep(5)
        
        # 5. 自动注册到 Hub
        subprocess.run([
            "agenttalk", "register",
            "--short-id", short_id,
            "--tmux-target", f"{session_name}:0.0",
            "--workspace", workspace,
            "--kind", kind,
            "--receive-mode", receive_mode
        ], check=True)
        
        # 6. 启动 relay 监控（如果还没运行）
        # 这通常由 relay daemon 自动处理
        
        return {
            "short_id": short_id,
            "status": "created",
            "session": session_name
        }
```

---

## 7. 机器注册流程（基于用户回答 #2）

### 7.1 流程设计

```
1. 用户在开发机上首次运行 agenttalk relay
   $ agenttalk relay start
   
2. Relay 检测到未注册，生成临时 token
   → POST /api/machines/register-request
   → 返回注册链接
   
3. 终端显示：
   ┌─────────────────────────────────────────────┐
   │  AgentTalk Relay 注册                         │
   │                                              │
   │  请访问以下链接完成注册：                       │
   │  https://agents.qicore.tech/auth/register?    │
   │  token=xyz123&machine_id=abc456              │
   │                                              │
   │  或者扫描二维码：                              │
   │  [QR Code]                                    │
   │                                              │
   │  此链接将在 10 分钟后过期                     │
   └─────────────────────────────────────────────┘
   
4. 用户点击链接，跳转认证平台登录
   - OAuth / SSO 登录
   - 选择或创建用户账号
   
5. 认证平台回调 Hub
   POST /api/auth/callback
   {"token": "xyz123", "user_id": "...", "user_info": {...}}
   
6. Hub 完成机器绑定
   - 创建 machine 记录
   - 关联 user_id
   - 标记为 online
   
7. Relay 检测到注册完成
   - 开始正常心跳
   - 接收任务指令
```

### 7.2 API 设计

```python
# Relay 启动时请求注册
POST /api/machines/register-request
Request:
{
    "machine_id": "env-wenda:coder",      # 自动生成或从系统获取
    "host_name": "coder.local",
    "os": "linux",
    "capabilities": ["tmux", "codex", "claude"]
}

Response:
{
    "registration_token": "xyz123",
    "registration_url": "https://agents.qicore.tech/auth/register?token=xyz123",
    "qr_code_url": "https://agents.qicore.tech/auth/register?token=xyz123&format=qr",
    "expires_at": "2026-05-09T12:00:00Z",
    "polling_interval": 5  # 轮询间隔（秒）
}

# Relay 轮询注册状态
GET /api/machines/register-status/{token}
Response (pending):
{"status": "pending", "message": "等待用户完成认证"}

Response (completed):
{
    "status": "completed",
    "user_id": "user-123",
    "machine_id": 1,
    "api_key": "ak-xxx"  # Relay 后续使用的 API key
}

# 认证平台回调（OAuth callback）
POST /api/auth/callback
{
    "registration_token": "xyz123",
    "user_id": "user-123",
    "auth_provider": "sso",
    "auth_token": "oauth-token"
}
```

---

## 8. 用户隔离与权限

### 8.1 可见性模型

```python
class Visibility(StrEnum):
    PRIVATE = "private"    # 仅 owner 可见
    SHARED = "shared"      # 指定用户可见（通过 shared_with）
    PUBLIC = "public"      # 所有人可见

class Permission(StrEnum):
    VIEW = "view"          # 查看状态、上下文
    MANAGE = "manage"      # 发送消息、删除
    ADMIN = "admin"        # 修改配置、分享、授权
```

### 8.2 权限检查逻辑

```python
def can_access(user_id: str, resource: Agent | Machine | Workspace) -> bool:
    """检查用户是否可以访问资源。"""
    # 1. Owner 始终有权限
    if resource.owner_id == user_id:
        return True
    
    # 2. 检查可见性
    if resource.visibility == Visibility.PUBLIC:
        return True
    
    if resource.visibility == Visibility.SHARED:
        return user_id in (resource.shared_with or [])
    
    # 3. 检查显式授权
    if hasattr(resource, 'permissions'):
        for perm in resource.permissions:
            if perm.user_id == user_id and perm.permission in [Permission.VIEW, Permission.MANAGE, Permission.ADMIN]:
                return True
    
    return False

def can_manage(user_id: str, resource: Agent | Machine | Workspace) -> bool:
    """检查用户是否可以管理资源。"""
    if resource.owner_id == user_id:
        return True
    
    if hasattr(resource, 'permissions'):
        for perm in resource.permissions:
            if perm.user_id == user_id and perm.permission in [Permission.MANAGE, Permission.ADMIN]:
                return True
    
    return False
```

### 8.3 Web UI 权限控制

- **Agents 列表页**：只显示我有权限的（我的 + 分享给我的 + public）
- **Agent 详情页**：根据权限显示不同操作按钮
  - VIEW: 只能看状态和上下文
  - MANAGE: 可以发送消息、删除
  - ADMIN: 可以修改配置、分享给别人
- **设置分享**：ADMIN 可以设置 visibility 和 shared_with

---

## 9. Web UI 设计

### 9.1 新增页面

1. **登录页** `/login`
   - 支持 OAuth / SSO 登录
   - API Key 登录（用于脚本）

2. **仪表盘** `/dashboard`
   - 我的 Machines（在线状态、最后活跃）
   - 我的 Workspaces
   - 最近任务（运行中/最近完成）

3. **机器管理** `/machines`
   - 列出已注册机器
   - 查看机器详情（capabilities、agents）
   - 删除机器

4. **Workspace 管理** `/workspaces`
   - 创建 workspace（选择 machine，设置路径）
   - 查看 workspace 下的 agents
   - 设置可见性

5. **任务中心** `/tasks`
   - 提交任务（自然语言输入框）
   - 任务列表（状态筛选）
   - 任务详情（实时日志流、进度条）

6. **创建 Agent 向导** `/agents/new`
   ```
   Step 1: 选择 Workspace
   Step 2: 选择 Machine（用户指定）
   Step 3: 选择 Agent 类型（codex/claude/gemini）
   Step 4: 配置（auto_submit / paste_only）
   Step 5: 初始任务（可选，自然语言）
   ```

7. **Agent 详情页增强**
   - 分享按钮（设置 visibility 和 shared_with）
   - 权限管理面板

### 9.2 组件设计

```tsx
// TaskCard.tsx - 任务卡片
function TaskCard({ task }: { task: Task }) {
  return (
    <div className={`task-card task-${task.status}`}>
      <div className="task-header">
        <span className="task-id">{task.task_id}</span>
        <StatusBadge status={task.status} />
      </div>
      <p className="task-request">{task.raw_request}</p>
      <div className="task-meta">
        <span>Machine: {task.target_machine_name}</span>
        <span>Step: {task.current_step}/{task.total_steps}</span>
      </div>
      {task.status === 'running' && <ProgressBar percent={task.progress} />}
      <div className="task-actions">
        <button onClick={() => viewTask(task.task_id)}>查看详情</button>
        {task.status === 'running' && <button onClick={() => cancelTask(task.task_id)}>取消</button>}
      </div>
    </div>
  )
}

// TaskSubmitForm.tsx - 任务提交表单
function TaskSubmitForm() {
  const [request, setRequest] = useState('')
  const [machineId, setMachineId] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  
  async function handleSubmit() {
    setIsSubmitting(true)
    try {
      const task = await submitTask({
        raw_request: request,
        target_machine_id: parseInt(machineId)
      })
      router.push(`/tasks/${task.task_id}`)
    } finally {
      setIsSubmitting(false)
    }
  }
  
  return (
    <div className="task-submit-form">
      <textarea
        value={request}
        onChange={(e) => setRequest(e.target.value)}
        placeholder="描述你想让 agent 完成的任务，例如：帮我在 rabbit 项目分析代码差异..."
        rows={4}
      />
      <select value={machineId} onChange={(e) => setMachineId(e.target.value)}>
        <option value="">选择执行机器</option>
        {machines.map(m => (
          <option key={m.id} value={m.id}>{m.name} ({m.host_name})</option>
        ))}
      </select>
      <button onClick={handleSubmit} disabled={isSubmitting || !request || !machineId}>
        {isSubmitting ? '提交中...' : '提交任务'}
      </button>
    </div>
  )
}
```

---

## 10. 实现路线图

### Phase 1: 基础架构（Week 1-2）

**目标**：数据库 + API + 机器注册

**Day 1-2: 数据库变更**
- [ ] 创建 `machines`, `workspaces`, `tasks`, `agent_permissions` 表
- [ ] 修改 `agents` 表添加 `workspace_id`, `created_by`
- [ ] 数据库迁移脚本

**Day 3-4: 认证集成**
- [ ] 集成现有 auth 体系（复用现有 JWT/token）
- [ ] 用户上下文注入（所有 API 需要 user_id）
- [ ] 权限中间件 `require_permission`

**Day 5-6: 机器注册 API**
- [ ] `POST /api/machines/register-request`
- [ ] `GET /api/machines/register-status/{token}`
- [ ] `POST /api/auth/callback`（OAuth callback）
- [ ] 终端注册链接显示（QR code）

**Day 7: 机器管理 API**
- [ ] `GET /api/machines`
- [ ] `DELETE /api/machines/{id}`
- [ ] Relay 心跳更新 machine 状态

**Day 8-10: Workspace API**
- [ ] `GET/POST/DELETE /api/workspaces`
- [ ] 修改 `register_agent` 关联 workspace
- [ ] 权限检查

### Phase 2: Orchestrator 核心（Week 3-4）

**Day 11-12: LLM 任务解析**
- [ ] 设计 task parser prompt
- [ ] 实现 `TaskParser` 类
- [ ] 集成现有 LLM 配置（复用 settings 中的 LLM）
- [ ] 测试用例

**Day 13-15: 任务引擎**
- [ ] `TaskOrchestrator` 类
- [ ] 任务状态机（pending → queued → running → completed/failed）
- [ ] 步骤执行器（provision_agent, send_message, shell, git_sync）
- [ ] 模板变量解析（`{{step_3.short_id}}`）

**Day 16-17: Relay 指令处理**
- [ ] 扩展 Relay 轮询支持指令
- [ ] `AgentProvisioner` 实现
- [ ] Shell 指令执行
- [ ] 结果回传

**Day 18-20: 集成测试**
- [ ] 完整工作流测试
- [ ] 错误处理测试
- [ ] 超时测试

### Phase 3: Web UI（Week 5-6）

**Day 21-23: 基础页面**
- [ ] 登录页（OAuth）
- [ ] 仪表盘
- [ ] 机器管理页

**Day 24-26: Workspace + Agent**
- [ ] Workspace 管理
- [ ] 创建 Agent 向导
- [ ] Agent 详情页增强（分享、权限）

**Day 27-29: 任务中心**
- [ ] 任务提交表单
- [ ] 任务列表（实时状态）
- [ ] 任务详情（日志流、进度条）

**Day 30: 集成测试**
- [ ] E2E 测试更新
- [ ] 性能测试

### Phase 4: 安全 + 优化（Week 7）

**Day 31-33: 安全加固**
- [ ] 指令白名单（限制可执行命令）
- [ ] 资源限制（并发任务数、超时）
- [ ] 审计日志

**Day 34-35: 监控 + 告警**
- [ ] 任务失败告警（飞书）
- [ ] 机器离线告警
- [ ] 资源使用监控

**Day 36-38: 文档 + 部署**
- [ ] API 文档
- [ ] 用户手册
- [ ] Docker 部署更新

**Day 39-40: 验收测试**
- [ ] 用户场景测试
- [ ] 性能基准测试
- [ ] 安全审计

---

## 11. 风险与应对

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|----------|
| LLM 解析不准确 | 中 | 高 | 增加人工确认步骤；允许用户编辑解析结果；fallback 到模板匹配 |
| Relay 指令执行安全风险 | 高 | 高 | 指令白名单；沙箱执行；审计日志；禁止 rm / 等危险命令 |
| 任务长时间挂起 | 中 | 中 | 超时机制；心跳检测；手动取消；资源清理 |
| 多用户并发冲突 | 中 | 中 | 任务队列；锁机制；资源隔离 |
| 认证平台集成复杂 | 低 | 中 | 先支持 API Key；OAuth 作为可选增强 |

---

## 12. 待决策事项

1. **LLM 解析失败时如何处理？**
   - A. 直接报错，让用户重新描述
   - B. 用最简默认步骤执行（如只创建 agent）
   - C. 人工审核队列（管理员确认后执行）

2. **任务执行超时后如何清理？**
   - A. 自动 kill agent
   - B. 保留 agent，只标记任务失败
   - C. 询问用户是否保留

3. **多步骤任务中某步失败时？**
   - A. 整体失败，回滚已创建资源
   - B. 跳过失败步骤，继续执行
   - C. 暂停，等待用户决策

4. **Agent 创建后是否需要自动销毁？**
   - A. 任务完成后自动销毁（一次性 agent）
   - B. 保留，用户手动管理
   - C. 空闲 N 分钟后自动销毁

---

**记录时间**: 2026-05-09
**下次更新**: 完成 Phase 1 后
