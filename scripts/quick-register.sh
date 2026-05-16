#!/usr/bin/env bash
set -euo pipefail

# 快速注册当前 tmux pane 为 AgentTalk agent
# 用法: ./quick-register.sh [--short-id <id>] [--kind <kind>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认值
SHORT_ID=""
KIND="claude"
OWNER="$(whoami)"
WORKSPACE="$(pwd)"
HUB_URL=""
TOKEN=""
AUTO_START=false

# 检测是否在 tmux 中
detect_tmux() {
    if [ -z "${TMUX:-}" ]; then
        echo -e "${RED}错误: 必须在 tmux pane 中运行此脚本${NC}"
        echo -e "${YELLOW}提示: 先创建一个 tmux session，然后在此运行${NC}"
        exit 1
    fi

    # 获取当前 tmux target
    local session window pane
    session=$(tmux display-message -p '#{session_name}')
    window=$(tmux display-message -p '#{window_index}')
    pane=$(tmux display-message -p '#{pane_index}')
    TMUX_TARGET="${session}:${window}.${pane}"

    echo -e "${BLUE}检测到 tmux: ${TMUX_TARGET}${NC}"
}

# 加载配置
load_config() {
    local config_file="${HOME}/.agenttalk/config.json"
    if [ -f "$config_file" ]; then
        HUB_URL=$(python3 -c "import json; print(json.load(open('$config_file')).get('hub_url', ''))" 2>/dev/null || echo "")
        TOKEN=$(python3 -c "import json; print(json.load(open('$config_file')).get('token', ''))" 2>/dev/null || echo "")
    fi

    # 从 .env 加载
    local env_file="${REPO_DIR}/.env"
    if [ -f "$env_file" ] && [ -z "$TOKEN" ]; then
        TOKEN=$(grep "AGENTTALK_TOKEN=" "$env_file" | cut -d= -f2 | tr -d '"' | head -1)
    fi

    if [ -z "$HUB_URL" ]; then
        HUB_URL="https://agents.qicore.tech"
    fi
}

# 生成 short-id
generate_short_id() {
    local hostname=$(hostname -s 2>/dev/null || echo "dev")
    local dir_name=$(basename "$WORKSPACE")
    local random_suffix=$(date +%s | tail -c 5)
    echo "${hostname}-${dir_name}-${random_suffix}"
}

# 注册 agent
register_agent() {
    echo -e "${BLUE}正在注册 agent...${NC}"

    cd "$REPO_DIR"

    # 构建命令
    local cmd="uv run --no-sync agenttalk register"
    cmd="$cmd --short-id '$SHORT_ID'"
    cmd="$cmd --tmux-target '$TMUX_TARGET'"
    cmd="$cmd --owner '$OWNER'"
    cmd="$cmd --kind '$KIND'"
    cmd="$cmd --workspace '$WORKSPACE'"

    echo -e "${YELLOW}执行: $cmd${NC}"
    eval "$cmd"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Agent 注册成功: $SHORT_ID${NC}"
    else
        echo -e "${RED}✗ Agent 注册失败${NC}"
        exit 1
    fi
}

# 启动监控
start_monitoring() {
    echo -e "${BLUE}启动监控 daemon...${NC}"

    cd "$REPO_DIR"

    # 检查是否已有 daemon 在运行
    local existing_pid
    existing_pid=$(pgrep -f "agenttalk daemon start" || true)
    if [ -n "$existing_pid" ]; then
        echo -e "${YELLOW}⚠ 已有 daemon 在运行 (PID: $existing_pid)，将重启${NC}"
        kill "$existing_pid" 2>/dev/null || true
        sleep 2
    fi

    # 启动新的 daemon
    nohup bash -c "cd $REPO_DIR && uv run --no-sync agenttalk daemon start --interval 1.0" > /tmp/agenttalk-daemon.log 2>&1 &
    local daemon_pid=$!
    sleep 3

    # 检查 daemon 是否存活
    if kill -0 "$daemon_pid" 2>/dev/null; then
        echo -e "${GREEN}✓ Daemon 启动成功 (PID: $daemon_pid)${NC}"
        echo -e "${BLUE}日志: tail -f /tmp/agenttalk-daemon.log${NC}"
    else
        echo -e "${RED}✗ Daemon 启动失败${NC}"
        echo -e "${YELLOW}查看日志: cat /tmp/agenttalk-daemon.log${NC}"
        exit 1
    fi
}

# 显示信息
show_info() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Agent 注册完成！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${BLUE}Agent ID:${NC}   $SHORT_ID"
    echo -e "${BLUE}Kind:${NC}       $KIND"
    echo -e "${BLUE}Owner:${NC}      $OWNER"
    echo -e "${BLUE}Workspace:${NC}  $WORKSPACE"
    echo -e "${BLUE}tmux:${NC}       $TMUX_TARGET"
    echo -e "${BLUE}Hub:${NC}        $HUB_URL"
    echo ""
    echo -e "${YELLOW}可用命令:${NC}"
    echo -e "  ${GREEN}agenttalk list${NC}                  查看所有 agent"
    echo -e "  ${GREEN}agenttalk unregister --short-id $SHORT_ID${NC}  注销此 agent"
    echo -e "  ${GREEN}tail -f /tmp/agenttalk-daemon.log${NC}  查看监控日志"
    echo ""
    echo -e "${YELLOW}Web UI:${NC} ${HUB_URL}"
    echo ""
}

# 解析参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --short-id)
                SHORT_ID="$2"
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
            --hub-url)
                HUB_URL="$2"
                shift 2
                ;;
            --token)
                TOKEN="$2"
                shift 2
                ;;
            --auto-start)
                AUTO_START=true
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

快速注册当前 tmux pane 为 AgentTalk agent

选项:
  --short-id <id>      指定 agent ID (默认: 自动生成)
  --kind <kind>        指定 agent 类型: claude|codex|cursor (默认: claude)
  --owner <owner>      指定所有者 (默认: $(whoami))
  --workspace <path>   指定工作目录 (默认: 当前目录)
  --hub-url <url>      指定 Hub URL
  --token <token>      指定认证 Token
  --auto-start          自动启动监控 daemon
  --help, -h           显示此帮助

示例:
  # 快速注册当前 pane (交互式)
  ./quick-register.sh

  # 指定参数注册
  ./quick-register.sh --short-id my-api --kind codex --auto-start

  # 在特定项目中注册
  cd /path/to/project && ./quick-register.sh --kind claude
EOF
}

# 主逻辑
main() {
    echo -e "${GREEN}AgentTalk 快速注册工具${NC}"
    echo ""

    parse_args "$@"
    detect_tmux
    load_config

    # 生成或确认 short-id
    if [ -z "$SHORT_ID" ]; then
        if [ "$AUTO_START" = true ]; then
            SHORT_ID=$(generate_short_id)
            echo -e "${BLUE}自动分配 Agent ID: ${SHORT_ID}${NC}"
        else
            local suggested=$(generate_short_id)
            echo -n -e "${YELLOW}请输入 Agent ID [${suggested}]: ${NC}"
            read -r user_input
            SHORT_ID="${user_input:-$suggested}"
        fi
    fi

    # 确认 kind (auto-start 时跳过)
    if [ "$AUTO_START" = false ]; then
        echo -n -e "${YELLOW}请选择 Agent 类型 [${KIND}]: ${NC}"
        read -r user_kind
        KIND="${user_kind:-$KIND}"
    fi

    # 确认信息
    echo ""
    echo -e "${BLUE}注册信息:${NC}"
    echo "  ID:        $SHORT_ID"
    echo "  Kind:      $KIND"
    echo "  Owner:     $OWNER"
    echo "  Workspace: $WORKSPACE"
    echo "  tmux:      $TMUX_TARGET"
    echo ""

    if [ "$AUTO_START" = false ]; then
        echo -n -e "${YELLOW}确认注册并启动监控? [Y/n]: ${NC}"
        read -r confirm
        if [[ "$confirm" =~ ^[Nn]$ ]]; then
            echo -e "${YELLOW}已取消${NC}"
            exit 0
        fi
    else
        echo -e "${BLUE}自动模式: 跳过确认${NC}"
    fi

    register_agent
    start_monitoring
    show_info
}

main "$@"
