#!/usr/bin/env bash
set -euo pipefail

# 一键检查 AgentTalk 环境并安装依赖
# 用法: ./check-env.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

check_python() {
    echo -n -e "${BLUE}检查 Python 3.12+... ${NC}"
    if command -v python3 > /dev/null 2>&1; then
        local version
        version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        if [[ "$(echo "$version >= 3.12" | bc 2>/dev/null || echo "0")" == "1" ]]; then
            echo -e "${GREEN}✓ Python $version${NC}"
            return 0
        else
            echo -e "${YELLOW}⚠ Python $version (建议 3.12+)${NC}"
            return 1
        fi
    else
        echo -e "${RED}✗ 未安装${NC}"
        return 1
    fi
}

check_tmux() {
    echo -n -e "${BLUE}检查 tmux... ${NC}"
    if command -v tmux > /dev/null 2>&1; then
        local version
        version=$(tmux -V 2>&1 | grep -oP '\d+\.\d+' | head -1)
        echo -e "${GREEN}✓ tmux $version${NC}"
        return 0
    else
        echo -e "${RED}✗ 未安装${NC}"
        return 1
    fi
}

check_uv() {
    echo -n -e "${BLUE}检查 uv... ${NC}"
    if command -v uv > /dev/null 2>&1; then
        echo -e "${GREEN}✓ $(uv --version 2>&1 | head -1)${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ 未安装 (用于快速安装依赖)${NC}"
        return 1
    fi
}

check_git() {
    echo -n -e "${BLUE}检查 Git... ${NC}"
    if command -v git > /dev/null 2>&1; then
        echo -e "${GREEN}✓ $(git --version 2>&1 | head -1)${NC}"
        return 0
    else
        echo -e "${RED}✗ 未安装${NC}"
        return 1
    fi
}

check_tmux_session() {
    echo -n -e "${BLUE}检查当前是否在 tmux... ${NC}"
    if [ -n "${TMUX:-}" ]; then
        local session window pane
        session=$(tmux display-message -p '#{session_name}' 2>/dev/null)
        window=$(tmux display-message -p '#{window_index}' 2>/dev/null)
        pane=$(tmux display-message -p '#{pane_index}' 2>/dev/null)
        echo -e "${GREEN}✓ ${session}:${window}.${pane}${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ 否 (agent 必须运行在 tmux 中)${NC}"
        return 1
    fi
}

check_config() {
    echo -n -e "${BLUE}检查 AgentTalk 配置... ${NC}"
    local config_file="${HOME}/.agenttalk/config.json"
    if [ -f "$config_file" ]; then
        local hub_url token
        hub_url=$(python3 -c "import json; print(json.load(open('$config_file')).get('hub_url', ''))" 2>/dev/null || echo "")
        token=$(python3 -c "import json; print(json.load(open('$config_file')).get('token', ''))" 2>/dev/null || echo "")

        if [ -n "$hub_url" ] && [ -n "$token" ]; then
            echo -e "${GREEN}✓ 已配置 (${hub_url})${NC}"
            return 0
        else
            echo -e "${YELLOW}⚠ 配置不完整${NC}"
            return 1
        fi
    else
        echo -e "${YELLOW}⚠ 未配置${NC}"
        return 1
    fi
}

check_agenttalk_deps() {
    echo -n -e "${BLUE}检查 AgentTalk 依赖... ${NC}"
    if [ -d "$REPO_DIR/.venv" ]; then
        echo -e "${GREEN}✓ 虚拟环境已创建${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ 未安装${NC}"
        return 1
    fi
}

install_deps() {
    echo ""
    echo -e "${BLUE}安装依赖...${NC}"
    cd "$REPO_DIR"

    if command -v uv > /dev/null 2>&1; then
        echo -e "${YELLOW}使用 uv 安装...${NC}"
        uv sync --extra feishu
    else
        echo -e "${YELLOW}使用 pip 安装...${NC}"
        pip install -e ".[feishu]"
    fi

    echo -e "${GREEN}✓ 依赖安装完成${NC}"
}

show_summary() {
    local all_ok=true

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  AgentTalk 环境检查${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    check_python || all_ok=false
    check_tmux || all_ok=false
    check_uv || true  # uv 是可选的
    check_git || all_ok=false
    check_tmux_session || true  # 不在 tmux 中只是警告
    check_config || all_ok=false
    check_agenttalk_deps || all_ok=false

    echo ""
    if [ "$all_ok" = true ]; then
        echo -e "${GREEN}✓ 所有检查通过！可以开始使用 AgentTalk${NC}"
        echo ""
        echo -e "${YELLOW}快速开始:${NC}"
        echo -e "  1. ${GREEN}./scripts/quick-register.sh${NC}    注册当前 tmux pane"
        echo -e "  2. ${GREEN}./scripts/start-all-agents.sh${NC}  启动监控"
        echo ""
    else
        echo -e "${YELLOW}⚠ 部分检查未通过，请参考上文解决${NC}"
        echo ""

        echo -n -e "${YELLOW}是否自动安装缺失的依赖? [y/N]: ${NC}"
        read -r confirm
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
            install_deps
        fi
    fi
}

show_help() {
    cat << EOF
用法: $(basename "$0") [选项]

检查 AgentTalk 运行环境

选项:
  --install    自动安装缺失的依赖
  --help, -h   显示此帮助
EOF
}

main() {
    if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
        show_help
        exit 0
    fi

    if [ "${1:-}" = "--install" ]; then
        install_deps
        exit 0
    fi

    show_summary
}

main "$@"
