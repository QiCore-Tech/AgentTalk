#!/usr/bin/env bash
set -euo pipefail

# 快速设置：创建 tmux session，注册 pane，启动监控
# 不启动 AI agent（用户自己启动）
# 用法: ./setup-pane.sh [--session <name>] [--kind <kind>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 默认值
SESSION_NAME=""
KIND="claude"
OWNER="$(whoami)"
WORKSPACE="$(pwd)"
SHORT_ID=""
AUTO_MODE=false

# 加载配置
load_config() {
    local config_file="${HOME}/.agenttalk/config.json"
    if [ -f "$config_file" ]; then
        local hub_url token
        hub_url=$(python3 -c "import json; print(json.load(open('$config_file')).get('hub_url', ''))" 2>/dev/null || echo "")
        token=$(python3 -c "import json; print(json.load(open('$config_file')).get('token', ''))" 2>/dev/null || echo "")

        if [ -z "$hub_url" ] || [ -z "$token" ]; then
            echo -e "${RED}错误: 未配置 Hub 连接${NC}"
            echo -e "${YELLOW}请先运行: agenttalk setup <hub-url> --token <token>${NC}"
            exit 1
        fi
    else
        echo -e "${RED}错误: 未找到配置文件${NC}"
        echo -e "${YELLOW}请先运行: agenttalk setup <hub-url> --token <token>${NC}"
        exit 1
    fi
}

# 检测或创建 tmux session
setup_tmux() {
    if [ -z "$SESSION_NAME" ]; then
        # 根据目录名生成 session 名
        SESSION_NAME="agent-$(basename "$WORKSPACE" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]-')"
    fi

    echo -e "${BLUE}检查 tmux session: ${SESSION_NAME}${NC}"

    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        echo -e "${GREEN}✓ Session 已存在: ${SESSION_NAME}${NC}"

        # 检查是否已有 pane
        local pane_count
        pane_count=$(tmux list-panes -t "$SESSION_NAME" 2>/dev/null | wc -l)
        echo -e "${BLUE}  已有 ${pane_count} 个 pane${NC}"

        echo -e "${YELLOW}提示: 在此 session 中启动您的 agent${NC}"
    else
        echo -e "${BLUE}创建新的 tmux session: ${SESSION_NAME}${NC}"

        # 创建 session，在后台运行一个 shell
        tmux new-session -d -s "$SESSION_NAME" -c "$WORKSPACE"

        # 设置窗口标题
        tmux rename-window -t "$SESSION_NAME:0" "$KIND"

        echo -e "${GREEN}✓ Session 创建成功${NC}"
        echo -e "${YELLOW}提示: 请附加到此 session 启动您的 agent${NC}"
    fi

    # 获取 target
    TMUX_TARGET="${SESSION_NAME}:0.0"
}

# 生成 short-id
generate_short_id() {
    local dir_name=$(basename "$WORKSPACE")
    local timestamp=$(date +%s | tail -c 4)
    echo "${OWNER}-${dir_name}-${timestamp}"
}

# 注册 agent
register_agent() {
    if [ -z "$SHORT_ID" ]; then
        SHORT_ID=$(generate_short_id)
    fi

    echo ""
    echo -e "${BLUE}注册 pane 到 Hub...${NC}"
    echo -e "  ID:        ${SHORT_ID}"
    echo -e "  Kind:      ${KIND}"
    echo -e "  Owner:     ${OWNER}"
    echo -e "  Workspace: ${WORKSPACE}"
    echo -e "  tmux:      ${TMUX_TARGET}"
    echo ""

    # 获取 token
    local token
    token=$(python3 -c "import json; print(json.load(open('${HOME}/.agenttalk/config.json')).get('token', ''))" 2>/dev/null || echo "")

    if [ -z "$token" ]; then
        echo -e "${RED}错误: 无法获取 token${NC}"
        exit 1
    fi

    # 使用 API 直接注册（避免 CLI 的 sync 操作）
    local hub_url
    hub_url=$(python3 -c "import json; print(json.load(open('${HOME}/.agenttalk/config.json')).get('hub_url', ''))" 2>/dev/null || echo "https://agents.qicore.tech")

    local response
    response=$(curl -s -w "\n%{http_code}" -X PUT \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "{
            \"short_id\": \"${SHORT_ID}\",
            \"machine_id\": \"$(hostname):$(whoami)\",
            \"owner\": \"${OWNER}\",
            \"kind\": \"${KIND}\",
            \"workspace\": \"${WORKSPACE}\",
            \"tmux_target\": \"${TMUX_TARGET}\",
            \"receive_mode\": \"auto_submit\",
            \"status\": \"idle\"
        }" \
        "${hub_url}/api/agents")

    local http_code
    http_code=$(echo "$response" | tail -1)
    local body
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
        echo -e "${GREEN}✓ 注册成功${NC}"
        # 保存到本地配置
        cd "$REPO_DIR"
        uv run --no-sync agenttalk register \
            --short-id "$SHORT_ID" \
            --tmux-target "$TMUX_TARGET" \
            --owner "$OWNER" \
            --kind "$KIND" \
            --workspace "$WORKSPACE" 2>/dev/null || true
    else
        echo -e "${RED}✗ 注册失败 (HTTP $http_code)${NC}"
        echo -e "${YELLOW}响应: $body${NC}"
        exit 1
    fi
}

# 启动 relay daemon
start_relay() {
    echo ""
    echo -e "${BLUE}启动 relay daemon...${NC}"

    # 检查是否已有 daemon
    local existing_pids
    existing_pids=$(pgrep -f "agenttalk daemon start" || true)
    if [ -n "$existing_pids" ]; then
        echo -e "${YELLOW}⚠ 已有 relay 在运行${NC}"
        echo "$existing_pids" | while read -r pid; do
            echo -e "  PID: $pid"
        done

        if [ "$AUTO_MODE" = false ]; then
            echo -n -e "${YELLOW}是否重启? [y/N]: ${NC}"
            read -r confirm
            if [[ "$confirm" =~ ^[Yy]$ ]]; then
                echo "$existing_pids" | while read -r pid; do
                    kill "$pid" 2>/dev/null || true
                done
                sleep 2
            else
                echo -e "${BLUE}保持现有 relay${NC}"
                return 0
            fi
        fi
    fi

    # 启动新的 relay
    cd "$REPO_DIR"
    nohup bash -c "cd $REPO_DIR && uv run --no-sync agenttalk daemon start --interval 5.0" > /tmp/agenttalk-daemon.log 2>&1 &
    local relay_pid=$!

    sleep 3

    if kill -0 "$relay_pid" 2>/dev/null; then
        echo -e "${GREEN}✓ Relay 启动成功 (PID: $relay_pid)${NC}"
    else
        echo -e "${RED}✗ Relay 启动失败${NC}"
        echo -e "${YELLOW}查看日志: cat /tmp/agenttalk-daemon.log${NC}"
    fi
}

# 显示完成信息
show_summary() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  tmux + PTY 环境准备完成${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${BLUE}tmux Session:${NC}  ${SESSION_NAME}"
    echo -e "${BLUE}tmux Target:${NC}   ${TMUX_TARGET}"
    echo -e "${BLUE}Agent ID:${NC}      ${SHORT_ID}"
    echo -e "${BLUE}Kind:${NC}          ${KIND}"
    echo -e "${BLUE}Workspace:${NC}     ${WORKSPACE}"
    echo ""
    echo -e "${YELLOW}下一步 - 请手动启动您的 AI Agent:${NC}"
    echo ""
    echo -e "  1. ${GREEN}附加到 tmux session:${NC}"
    echo -e "     tmux attach -t ${SESSION_NAME}"
    echo ""
    echo -e "  2. ${GREEN}在 session 中启动 agent，例如:${NC}"
    echo -e "     # Claude Code"
    echo -e "     claude"
    echo ""
    echo -e "     # 或 Codex"
    echo -e "     codex"
    echo ""
    echo -e "     # 或其他 agent CLI"
    echo ""
    echo -e "  3. ${GREEN}验证状态:${NC}"
    echo -e "     ./scripts/check-env.sh"
    echo -e "     ./scripts/start-all-agents.sh --status"
    echo ""
    echo -e "${YELLOW}Web UI:${NC} https://agents.qicore.tech"
    echo ""
}

# 解析参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --session)
                SESSION_NAME="$2"
                shift 2
                ;;
            --kind)
                KIND="$2"
                shift 2
                ;;
            --owner)
                OWNER="$2"
                shift 2
                ;;
            --workspace)
                WORKSPACE="$2"
                shift 2
                ;;
            --short-id)
                SHORT_ID="$2"
                shift 2
                ;;
            --auto)
                AUTO_MODE=true
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
}

show_help() {
    cat << EOF
用法: $(basename "$0") [选项]

一键设置：创建 tmux session，注册 pane，启动 relay 监控
不启动 AI agent（用户自己启动）

选项:
  --session <name>    指定 tmux session 名称 (默认: 基于目录名)
  --kind <kind>       指定 agent 类型: claude|codex|cursor (默认: claude)
  --owner <owner>     指定所有者 (默认: $(whoami))
  --workspace <path>  指定工作目录 (默认: 当前目录)
  --short-id <id>     指定 agent ID (默认: 自动生成)
  --auto               自动模式（不询问，适合脚本调用）
  --help, -h           显示此帮助

示例:
  # 交互式设置（推荐）
  ./setup-pane.sh

  # 指定 session 名
  ./setup-pane.sh --session my-api --kind codex

  # 自动模式（CI/CD 使用）
  ./setup-pane.sh --session api-service --kind claude --auto

  # 在特定项目中
  cd /path/to/project && ./setup-pane.sh --kind codex

快速命令:
  # 查看状态
  ./scripts/start-all-agents.sh --status

  # 停止监控
  ./scripts/start-all-agents.sh --stop

  # 环境检查
  ./scripts/check-env.sh
EOF
}

main() {
    echo -e "${GREEN}AgentTalk 环境设置工具${NC}"
    echo -e "${YELLOW}（只设置 tmux + PTY，不启动 AI agent）${NC}"
    echo ""

    parse_args "$@"
    load_config
    setup_tmux

    if [ "$AUTO_MODE" = false ]; then
        echo ""
        echo -n -e "${YELLOW}确认注册并启动监控? [Y/n]: ${NC}"
        read -r confirm
        if [[ "$confirm" =~ ^[Nn]$ ]]; then
            echo -e "${YELLOW}已取消${NC}"
            exit 0
        fi
    fi

    register_agent
    start_relay
    show_summary
}

main "$@"
