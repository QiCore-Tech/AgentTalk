#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  scripts/start-client.sh --hub-url <url> --token <token> --short-id <id> --tmux-target <target> [options]

Required:
  --hub-url <url>       Hub server URL, for example http://192.168.1.20:8787
  --token <token>       Shared AgentTalk token from the Hub server
  --short-id <id>       Globally unique local agent id
  --tmux-target <t>     Explicit tmux target, for example dev:0.1

Options:
  --owner <name>        Owner label. Default: current user
  --kind <kind>         Agent kind. Default: unknown
  --workspace <path>    Workspace path. Default: current directory
  --pane-id <id>        tmux pane id if known
  --receive-mode <mode> auto_submit or paste_only. Default: auto_submit
  --once                Sync once and exit instead of running the relay
  --discover            Print read-only tmux pane candidates and exit
  -h, --help            Show this help.

This script configures the local client, registers exactly the tmux target
you pass, then starts the local relay.
EOF
}

HUB_URL=""
TOKEN=""
SHORT_ID=""
TMUX_TARGET=""
OWNER="${USER:-unknown}"
KIND="unknown"
WORKSPACE="$(pwd)"
PANE_ID=""
RECEIVE_MODE="auto_submit"
ONCE="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hub-url)
      HUB_URL="$2"
      shift 2
      ;;
    --token)
      TOKEN="$2"
      shift 2
      ;;
    --short-id)
      SHORT_ID="$2"
      shift 2
      ;;
    --tmux-target)
      TMUX_TARGET="$2"
      shift 2
      ;;
    --owner)
      OWNER="$2"
      shift 2
      ;;
    --kind)
      KIND="$2"
      shift 2
      ;;
    --workspace)
      WORKSPACE="$2"
      shift 2
      ;;
    --pane-id)
      PANE_ID="$2"
      shift 2
      ;;
    --receive-mode)
      RECEIVE_MODE="$2"
      shift 2
      ;;
    --once)
      ONCE="1"
      shift
      ;;
    --discover)
      cd "${ROOT_DIR}"
      uv run agenttalk discover
      exit 0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${HUB_URL}" || -z "${TOKEN}" || -z "${SHORT_ID}" || -z "${TMUX_TARGET}" ]]; then
  echo "Missing required option." >&2
  usage >&2
  exit 2
fi

cd "${ROOT_DIR}"

uv run agenttalk setup "${HUB_URL}" --token "${TOKEN}"
uv run agenttalk register \
  --short-id "${SHORT_ID}" \
  --tmux-target "${TMUX_TARGET}" \
  --owner "${OWNER}" \
  --kind "${KIND}" \
  --workspace "${WORKSPACE}" \
  --pane-id "${PANE_ID}" \
  --receive-mode "${RECEIVE_MODE}"

if [[ "${ONCE}" == "1" ]]; then
  uv run agenttalk daemon start --once
else
  uv run agenttalk daemon start
fi
