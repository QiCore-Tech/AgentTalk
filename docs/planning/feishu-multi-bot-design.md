# 多用户飞书机器人与通知路由系统

## 版本: 2026-05-15
## 状态: 待开发

---

## 1. 需求概述

用户希望能：
1. **自己注册飞书机器人**：每个用户可部署独立的飞书机器人应用
2. **私聊交互**：机器人支持一对一私聊，用户直接@机器人发命令
3. **精细化通知路由**：为每个 Agent 独立配置通知目的地
   - Agent A 的 alert → 发到群聊 X
   - Agent B 的 message → 发到私聊（用户自己）
   - Agent C 的 status_change → 发到群聊 Y

## 2. 与现有架构的对比

| 维度 | 现有（main） | 新架构（dev） |
|------|-------------|--------------|
| 机器人数量 | 全局单例（1个） | 多用户多机器人（N个） |
| 配置方式 | 环境变量 | 用户通过 API/CLI 注册 |
| 消息目的地 | 固定群 `FEISHU_ALERT_CHAT_ID` | 每个 Agent 独立配置 |
| 交互模式 | 仅群聊 | 群聊 + 私聊 |
| 命令上下文 | 全局共享 | 按用户隔离 |

## 3. 数据模型

### 3.1 飞书机器人表

```sql
CREATE TABLE feishu_bots (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,              -- 所属用户
    name TEXT NOT NULL,                 -- 机器人名称（如"我的工作助手"）
    app_id TEXT NOT NULL,               -- 飞书应用 ID
    app_secret TEXT NOT NULL,           -- 飞书应用密钥
    status TEXT DEFAULT 'active',       -- active/inactive/error
    created_at TEXT,
    
    UNIQUE(user_id, app_id)
);
```

### 3.2 Agent 通知路由表

```sql
CREATE TABLE agent_notification_routes (
    id INTEGER PRIMARY KEY,
    agent_short_id TEXT NOT NULL,       -- 目标 Agent
    user_id TEXT NOT NULL,              -- 配置者（谁设置的这条路由）
    event_type TEXT NOT NULL,           -- alert / message / status_change / health_report
    destination_type TEXT NOT NULL,     -- group（群聊）/ private（私聊）
    destination_id TEXT NOT NULL,       -- chat_id（群）或 open_id（用户）
    feishu_bot_id INTEGER NOT NULL,     -- 使用哪个机器人发送
    enabled INTEGER DEFAULT 1,
    created_at TEXT,
    
    FOREIGN KEY (feishu_bot_id) REFERENCES feishu_bots(id)
);
```

### 3.3 用户飞书绑定表（用于私聊识别）

```sql
CREATE TABLE user_feishu_bindings (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    open_id TEXT NOT NULL,              -- 飞书用户 open_id
    bot_id INTEGER NOT NULL,            -- 通过哪个机器人绑定的
    bound_at TEXT,
    
    UNIQUE(user_id, bot_id),
    UNIQUE(open_id, bot_id)
);
```

## 4. 架构设计

### 4.1 多机器人管理器

```python
class FeishuBotManager:
    """管理多个用户飞书机器人实例。"""
    
    def __init__(self, store: HubStore):
        self.store = store
        self._bots: dict[int, FeishuBotInstance] = {}  # bot_id -> instance
        
    def register_bot(self, user_id: str, name: str, app_id: str, app_secret: str) -> int:
        """用户注册新机器人。"""
        bot_id = self.store.create_feishu_bot(user_id, name, app_id, app_secret)
        self._start_bot(bot_id, app_id, app_secret)
        return bot_id
    
    def _start_bot(self, bot_id: int, app_id: str, app_secret: str):
        """启动单个机器人的 WebSocket 连接。"""
        instance = FeishuBotInstance(bot_id, app_id, app_secret)
        instance.start()
        self._bots[bot_id] = instance
    
    def send_notification(self, agent_short_id: str, event_type: str, message: str) -> None:
        """根据路由配置发送通知。"""
        routes = self.store.get_notification_routes(agent_short_id, event_type)
        for route in routes:
            if not route.enabled:
                continue
            bot = self._bots.get(route.feishu_bot_id)
            if bot:
                bot.send_to(route.destination_id, route.destination_type, message)
```

### 4.2 私聊命令处理

当用户私聊机器人时：
1. WebSocket 收到事件，提取 `open_id`
2. 查询 `user_feishu_bindings` 找到对应的 `user_id`
3. 命令执行时注入 `user_id` 上下文
4. 用户只能看到自己名下的 Agent、Machine、Task

```python
def handle_private_message(bot_id: int, open_id: str, text: str):
    user_id = store.find_user_by_open_id(open_id, bot_id)
    if not user_id:
        return "请先绑定账号（发送 /bind <token>）"
    
    command = parse_command(text)
    # 注入用户上下文
    context = UserContext(user_id=user_id, bot_id=bot_id)
    return execute_command(command, context)
```

### 4.3 通知路由流程

```
Agent 状态变化 / 新消息 / Alert
    ↓
Hub 触发通知事件
    ↓
查询 agent_notification_routes
    ↓
对每个匹配的路由：
    - 找到对应的 FeishuBotInstance
    - 调用 send_to(destination_id, destination_type, content)
    ↓
飞书消息送达
```

## 5. API 设计

### 5.1 机器人管理

```python
# 注册机器人
POST /api/feishu/bots
{
    "name": "我的工作助手",
    "app_id": "cli_xxx",
    "app_secret": "xxx"
}
→ {"id": 1, "status": "active"}

# 列出我的机器人
GET /api/feishu/bots
→ [{"id": 1, "name": "...", "status": "active", "created_at": "..."}]

# 删除机器人
DELETE /api/feishu/bots/{id}
→ {"ok": true}

# 测试机器人连接
POST /api/feishu/bots/{id}/test
→ {"ok": true, "bot_info": {"name": "...", "status": "..."}}
```

### 5.2 通知路由

```python
# 配置 Agent 通知路由
POST /api/agents/{short_id}/notifications
{
    "event_type": "alert",
    "destination_type": "group",
    "destination_id": "oc_xxx",
    "feishu_bot_id": 1
}
→ {"route_id": 1, "enabled": true}

# 查看 Agent 的路由
GET /api/agents/{short_id}/notifications
→ [{"id": 1, "event_type": "alert", "destination": "群聊X", "bot_name": "..."}]

# 更新路由
PATCH /api/agents/{short_id}/notifications/{route_id}
{"enabled": false}

# 删除路由
DELETE /api/agents/{short_id}/notifications/{route_id}
```

### 5.3 用户绑定

```python
# 飞书用户绑定 Hub 账号（私聊发送 /bind <token>）
POST /api/auth/feishu-bind
{
    "open_id": "ou_xxx",
    "bot_id": 1,
    "token": "用户JWT或临时绑定码"
}
→ {"user_id": "...", "status": "bound"}
```

## 6. CLI 设计

```bash
# 机器人管理
agenttalk feishu bot add --name "我的工作助手" --app-id cli_xxx --app-secret xxx
agenttalk feishu bot list
agenttalk feishu bot remove --id 1
agenttalk feishu bot test --id 1

# 通知路由
agenttalk notification route add \
    --agent codex-misc \
    --event alert \
    --to group \
    --destination oc_xxx \
    --bot 1

agenttalk notification route list --agent codex-misc
agenttalk notification route remove --route-id 1

# 查看我的通知设置概览
agenttalk notification status
```

## 7. Web UI 设计

### 7.1 飞书机器人管理页
- 已注册机器人列表（名称、状态、AppID）
- "添加机器人"表单（名称、AppID、AppSecret）
- 测试按钮（发送测试消息）
- 删除按钮

### 7.2 Agent 通知设置页
- Agent 列表
- 每个 Agent 的通知路由卡片：
  - 事件类型（alert/message/status_change）
  - 目的地（群聊名称/私聊用户）
  - 使用的机器人
  - 开关（启用/禁用）
- "添加路由"按钮

### 7.3 用户绑定引导
- 首次私聊机器人时，发送绑定指引
- Web UI 显示绑定二维码/链接

## 8. 私聊命令

用户私聊自己的机器人时，支持以下命令：

```
/bind <token>        - 绑定 Hub 账号
/agents              - 查看我的 Agent 列表
/agent <id>          - 查看 Agent 详情
/context <id>        - 查看 Agent 上下文
/send <id> <msg>     - 给 Agent 发消息
/status <msg-id>     - 查看消息状态
/tasks               - 查看我的任务
/task <id>           - 查看任务详情
/help                - 帮助
```

与群聊命令的区别：
- 自动过滤只显示该用户的 Agent
- 命令执行结果私发给用户
- 支持绑定/解绑操作

## 9. 实现路线图

### Phase 1: 数据层 + API（2-3 天）
- [ ] 创建 `feishu_bots`, `agent_notification_routes`, `user_feishu_bindings` 表
- [ ] Store 层方法实现
- [ ] API 端点实现（机器人 CRUD、路由 CRUD、绑定）
- [ ] 测试用例

### Phase 2: 多机器人引擎（2-3 天）
- [ ] `FeishuBotManager` 实现
- [ ] 动态启动/停止机器人 WebSocket
- [ ] 消息路由逻辑
- [ ] 私聊事件处理

### Phase 3: CLI + Web UI（2-3 天）
- [ ] CLI 命令实现
- [ ] Web UI 页面（机器人管理、路由配置）
- [ ] 用户绑定流程

### Phase 4: 集成测试（1-2 天）
- [ ] 端到端测试（注册机器人 → 配置路由 → 发送通知）
- [ ] 多用户隔离测试
- [ ] 性能测试（N 个机器人并发）

## 10. 安全考虑

1. **AppSecret 加密存储**：数据库中加密保存 `app_secret`
2. **用户隔离**：用户只能看到自己的机器人和路由配置
3. **命令权限**：私聊命令按用户权限过滤（只能操作自己的 Agent）
4. **Rate Limiting**：每个机器人限制消息发送频率
5. **Token 验证**：绑定流程使用临时 token，过期失效

## 11. 与 Orchestrator 的协同

当 Orchestrator 系统完成后：
- 任务状态变化可通过用户自己的机器人通知
- 用户私聊机器人提交任务（自然语言）
- 任务完成结果推送到用户指定的目的地

---

**记录时间**: 2026-05-15
**优先级**: 高（与 Orchestrator 并行开发）
