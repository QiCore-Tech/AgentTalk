#!/usr/bin/env sh
set -eu

if [ -z "${AGENTTALK_TOKEN:-}" ]; then
  echo "AGENTTALK_TOKEN is required" >&2
  exit 2
fi

if [ "${FEISHU_ENABLE:-0}" = "1" ] || [ "${FEISHU_ENABLE:-}" = "true" ] || [ "${FEISHU_ENABLE:-}" = "yes" ]; then
  FEISHU_FLAG="--feishu-enable"
else
  FEISHU_FLAG="--no-feishu-enable"
fi

# Link host tmux socket for WebSocket terminal access
if [ -S /tmp/tmux-1000/default ] && [ ! -e /tmp/tmux-0/default ]; then
  mkdir -p /tmp/tmux-0
  chmod 700 /tmp/tmux-0
  ln -sf /tmp/tmux-1000/default /tmp/tmux-0/default
fi

exec uv run --no-sync agenttalk hub serve \
  --host "${AGENTTALK_HOST:-0.0.0.0}" \
  --port "${AGENTTALK_PORT:-8787}" \
  --token "${AGENTTALK_TOKEN}" \
  --database "${AGENTTALK_DATABASE:-/data/agenttalk.sqlite3}" \
  --web-dist "${AGENTTALK_WEB_DIST:-/app/web/dist}" \
  --public-base-url "${AGENTTALK_PUBLIC_BASE_URL:-}" \
  ${FEISHU_FLAG} \
  --feishu-app-id "${FEISHU_APP_ID:-}" \
  --feishu-app-secret "${FEISHU_APP_SECRET:-}"
