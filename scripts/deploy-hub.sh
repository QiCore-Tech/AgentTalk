#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-hub.sh [options]

Options:
  --bind <ip>             Host IP to bind. Default: 0.0.0.0
  --port <port>           Host port. Default: 8787
  --public-base-url <url> Public Web URL shown in integrations.
  --token <token>         Shared AgentTalk token. Generated if omitted.
  --feishu               Enable Feishu bot. Requires app id and secret.
  --feishu-app-id <id>    Feishu app id.
  --feishu-app-secret <s> Feishu app secret.
  --no-build              Start without rebuilding the image.
  -h, --help              Show this help.

The script creates .env on first run, starts the Hub with Docker Compose,
and prints the Web URL and token.
EOF
}

detect_lan_ip() {
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [[ -n "${ip}" ]]; then
    printf '%s\n' "${ip}"
    return
  fi
  printf '127.0.0.1\n'
}

generate_token() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
    return
  fi
  if [[ -r /proc/sys/kernel/random/uuid ]]; then
    tr -d '-' </proc/sys/kernel/random/uuid
    return
  fi
  date +%s%N
}

load_existing_env() {
  local line key value
  [[ -f "${ENV_FILE}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line}" || "${line}" == \#* || "${line}" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    case "${key}" in
      AGENTTALK_BIND) BIND="${value}" ;;
      AGENTTALK_PORT) PORT="${value}" ;;
      AGENTTALK_TOKEN) TOKEN="${value}" ;;
      AGENTTALK_PUBLIC_BASE_URL) PUBLIC_BASE_URL="${value}" ;;
      FEISHU_ENABLE) FEISHU_ENABLE="${value}" ;;
      FEISHU_APP_ID) FEISHU_APP_ID="${value}" ;;
      FEISHU_APP_SECRET) FEISHU_APP_SECRET="${value}" ;;
    esac
  done <"${ENV_FILE}"
}

BIND="${AGENTTALK_BIND:-0.0.0.0}"
PORT="${AGENTTALK_PORT:-8787}"
TOKEN="${AGENTTALK_TOKEN:-}"
PUBLIC_BASE_URL="${AGENTTALK_PUBLIC_BASE_URL:-}"
FEISHU_ENABLE="${FEISHU_ENABLE:-0}"
FEISHU_APP_ID="${FEISHU_APP_ID:-}"
FEISHU_APP_SECRET="${FEISHU_APP_SECRET:-}"
BUILD_FLAG="--build"

load_existing_env

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bind)
      BIND="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --public-base-url)
      PUBLIC_BASE_URL="$2"
      shift 2
      ;;
    --token)
      TOKEN="$2"
      shift 2
      ;;
    --feishu)
      FEISHU_ENABLE="1"
      shift
      ;;
    --feishu-app-id)
      FEISHU_APP_ID="$2"
      shift 2
      ;;
    --feishu-app-secret)
      FEISHU_APP_SECRET="$2"
      shift 2
      ;;
    --no-build)
      BUILD_FLAG=""
      shift
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

TOKEN="${TOKEN:-$(generate_token)}"
if [[ -z "${PUBLIC_BASE_URL}" ]]; then
  PUBLIC_BASE_URL="http://$(detect_lan_ip):${PORT}"
fi

cat >"${ENV_FILE}" <<EOF
AGENTTALK_TOKEN=${TOKEN}
AGENTTALK_BIND=${BIND}
AGENTTALK_PORT=${PORT}
AGENTTALK_PUBLIC_BASE_URL=${PUBLIC_BASE_URL}

FEISHU_ENABLE=${FEISHU_ENABLE}
FEISHU_APP_ID=${FEISHU_APP_ID}
FEISHU_APP_SECRET=${FEISHU_APP_SECRET}
EOF

if [[ "${FEISHU_ENABLE}" == "1" && ( -z "${FEISHU_APP_ID}" || -z "${FEISHU_APP_SECRET}" ) ]]; then
  echo "FEISHU_ENABLE=1 requires FEISHU_APP_ID and FEISHU_APP_SECRET." >&2
  exit 2
fi

cd "${ROOT_DIR}"
docker compose up -d ${BUILD_FLAG}

echo
echo "AgentTalk Hub is starting."
echo "Web URL: ${PUBLIC_BASE_URL:-http://127.0.0.1:${PORT}}"
echo "Token: ${TOKEN}"
echo
echo "Health check:"
echo "  curl ${PUBLIC_BASE_URL:-http://127.0.0.1:${PORT}}/health"
