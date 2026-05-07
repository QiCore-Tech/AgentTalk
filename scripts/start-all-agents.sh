#!/usr/bin/env bash
set -euo pipefail

# 启动所有已注册 agent 的监控
# 用法: ./start-all-agents.sh [--config ~/.agenttalk/config.json]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

CONFIG_FILE="${HOME}/.agenttalk/config.json"
DAEMON_LOG="/tmp/agenttalk-daemon.log"

# 加载配置
load_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}错误: 配置文件不存在: $CONFIG_FILE${NC}"
        echo -e "${YELLOW}请先运行: agenttalk setup <hub-url> --token <token>${NC}"
        exit 1
    fi

    local hub_url token
    hub_url=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('hub_url', ''))" 2>/dev/null || echo "")
    token=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('token', ''))" 2>/dev/null || echo "")

    if [ -z "$hub_url" ] || [ -z "$token" ]; then
        echo -e "${RED}错误: 配置文件中缺少 hub_url 或 token${NC}"
        exit 1
    fi

    echo -e "${BLUE}Hub URL:${NC} $hub_url"
    echo ""
}

# 列出已注册的 agent
list_agents() {
    echo -e "${BLUE}已注册的 agents:${NC}"
    echo ""

    cd "$REPO_DIR"
    uv run --no-sync agenttalk list 2>/dev/null || echo "  (暂无已注册 agent)"
    echo ""
}

# 检查 agent 对应的 tmux pane 是否活跃
check_panes() {
    echo -e "${BLUE}检查 tmux pane 状态...${NC}"

    local agents_json
    agents_json=$(python3 -c "
import json
with open('$CONFIG_FILE') as f:
    config = json.load(f)
for agent in config.get('agents', []):
    print(f\"{agent['short_id']}|{agent['tmux_target']}\")
" 2>/dev/null)

    if [ -z "$agents_json" ]; then
        echo -e "${YELLOW}  没有找到已注册的 agent${NC}"
        return 1
    fi

    local all_alive=true
    while IFS='|' read -r short_id tmux_target; do
        if tmux has-session -t "${tmux_target%%:*}" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $short_id ($tmux_target) - 活跃"
        else
            echo -e "  ${RED}✗${NC} $short_id ($tmux_target) - ${RED}未找到${NC}"
            all_alive=false
        fi
    done <<< "$agents_json"

    echo ""
    if [ "$all_alive" = false ]; then
        echo -e "${YELLOW}警告: 部分 agent 的 tmux pane 未找到${NC}"
        echo -e "${YELLOW}请先启动对应的 tmux session${NC}"
        echo ""
        return 1
    fi

    return 0
}

# 停止现有 daemon
stop_existing_daemon() {
    local pids
    pids=$(pgrep -f "agenttalk daemon start" || true)
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}停止现有 daemon...${NC}"
        echo "$pids" | while read -r pid; do
            kill "$pid" 2>/dev/null || true
        done
        sleep 2
    fi
}

# 启动 daemon
start_daemon() {
    echo -e "${BLUE}启动监控 daemon...${NC}"

    cd "$REPO_DIR"

    # 清空日志
    > "$DAEMON_LOG"

    # 启动 daemon
    nohup bash -c "cd $REPO_DIR && uv run --no-sync agenttalk daemon start --interval 5.0" > "$DAEMON_LOG" 2>&1 &
    local daemon_pid=$!

    # 等待启动
    sleep 5

    # 检查是否存活
    if kill -0 "$daemon_pid" 2>/dev/null; then
        echo -e "${GREEN}✓ Daemon 启动成功 (PID: $daemon_pid)${NC}"
        echo ""

        # 显示最近日志
        echo -e "${BLUE}最近日志:${NC}"
        tail -n 5 "$DAEMON_LOG" | sed 's/^/  /'
        echo ""

        echo -e "${YELLOW}日志文件: tail -f $DAEMON_LOG${NC}"
        return 0
    else
        echo -e "${RED}✗ Daemon 启动失败${NC}"
        echo -e "${YELLOW}日志:${NC}"
        cat "$DAEMON_LOG" | sed 's/^/  /'
        return 1
    fi
}

# 显示状态
show_status() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  AgentTalk 监控已启动${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    # 获取 daemon PID
    local daemon_pid
    daemon_pid=$(pgrep -f "agenttalk daemon start" | head -1 || echo "未知")
    echo -e "${BLUE}Daemon PID:${NC} $daemon_pid"
    echo -e "${BLUE}日志文件:${NC} $DAEMON_LOG"
    echo ""

    # 显示 agent 状态
    echo -e "${BLUE}Agent 状态:${NC}"
    cd "$REPO_DIR"
    uv run --no-sync agenttalk list 2>/dev/null | sed 's/^/  /' || echo "  (无法获取状态)"
    echo ""

    echo -e "${YELLOW}常用命令:${NC}"
    echo -e "  ${GREEN}tail -f $DAEMON_LOG${NC}     查看实时日志"
    echo -e "  ${GREEN}agenttalk list${NC}            查看 agent 列表"
    echo -e "  ${GREEN}agenttalk status <id>${NC}      查看 agent 状态"
    echo ""
}

# 监控模式
monitor_mode() {
    echo -e "${BLUE}启动实时监控模式 (按 Ctrl+C 退出)...${NC}"
    echo ""
    tail -f "$DAEMON_LOG"
}

# 显示帮助
show_help() {
    cat << EOF
用法: $(basename "$0") [选项]

启动所有已注册 agent 的监控 daemon

选项:
  --config <file>     指定配置文件 (默认: ~/.agenttalk/config.json)
  --monitor           启动后进入实时监控模式
  --stop              停止现有 daemon
  --status            显示当前状态
  --help, -h          显示此帮助

示例:
  # 启动监控
  ./start-all-agents.sh

  # 启动并进入实时监控
  ./start-all-agents.sh --monitor

  # 停止监控
  ./start-all-agents.sh --stop
EOF
}

# 停止 daemon
stop_daemon() {
    local pids
    pids=$(pgrep -f "agenttalk daemon start" || true)
    if [ -z "$pids" ]; then
        echo -e "${YELLOW}没有运行中的 daemon${NC}"
        return 0
    fi

    echo -e "${BLUE}停止 daemon...${NC}"
    echo "$pids" | while read -r pid; do
        echo -e "  停止 PID: $pid"
        kill "$pid" 2>/dev/null || true
    done

    sleep 2

    # 确认已停止
    local remaining
    remaining=$(pgrep -f "agenttalk daemon start" || true)
    if [ -z "$remaining" ]; then
        echo -e "${GREEN}✓ Daemon 已停止${NC}"
    else
        echo -e "${YELLOW}强制停止...${NC}"
        echo "$remaining" | xargs kill -9 2>/dev/null || true
    fi
}

# 显示状态
show_quick_status() {
    local pids
    pids=$(pgrep -f "agenttalk daemon start" || true)

    echo -e "${GREEN}AgentTalk 状态${NC}"
    echo ""

    if [ -n "$pids" ]; then
        echo -e "${GREEN}Daemon: 运行中${NC}"
        echo "$pids" | while read -r pid; do
            echo -e "  PID: $pid"
        done
    else
        echo -e "${YELLOW}Daemon: 未运行${NC}"
    fi

    echo ""
    echo -e "${BLUE}已注册 Agents:${NC}"
    cd "$REPO_DIR" 2>/dev/null && uv run --no-sync agenttalk list 2>/dev/null | sed 's/^/  /' || echo "  (无法获取)"
    echo ""
}

# 主逻辑
main() {
    local monitor=false
    local stop=false
    local status=false

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            --config)
                CONFIG_FILE="$2"
                shift 2
                ;;
            --monitor)
                monitor=true
                shift
                ;;
            --stop)
                stop=true
                shift
                ;;
            --status)
                status=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                echo -e "${RED}未知参数: $1${NC}"
                show_help
                exit 1
                ;;
        esac
    done

    # 处理命令
    if [ "$stop" = true ]; then
        stop_daemon
        exit 0
    fi

    if [ "$status" = true ]; then
        show_quick_status
        exit 0
    fi

    # 正常启动流程
    echo -e "${GREEN}AgentTalk 监控启动工具${NC}"
    echo ""

    load_config
    list_agents

    if ! check_panes; then
        echo -e "${YELLOW}是否仍要继续启动? [y/N]: ${NC}"
        read -r confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            exit 0
        fi
    fi

    stop_existing_daemon

    if start_daemon; then
        show_status

        if [ "$monitor" = true ]; then
            monitor_mode
        fi
    else
        exit 1
    fi
}

main "$@"
