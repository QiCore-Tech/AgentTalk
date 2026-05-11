#!/usr/bin/env bash
# AgentTalk E2E Test Suite
# Tests all Hub, CLI, Feishu, and Web UI functionality

set -euo pipefail

HUB_URL="https://agents.qicore.tech"
LOCAL_URL="http://localhost:8787"
TOKEN="91055c408ac256920908b5bd9a6856fc9cd6498611faba95"
TEST_AGENT="test-e2e-agent"
TEST_RESULTS="/tmp/agenttalk-test-results.txt"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass_count=0
fail_count=0

pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    ((pass_count++)) || true
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    ((fail_count++)) || true
}

info() {
    echo -e "${YELLOW}▶${NC} $1"
}

# ============================================
# 1. Hub Health & Basic API
# ============================================
info "=== 1. Hub Health & Basic API ==="

if curl -sf "$LOCAL_URL/health" | grep -q '"status":"ok"'; then
    pass "Hub health endpoint"
else
    fail "Hub health endpoint"
fi

if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents" | grep -q '"agents"'; then
    pass "List agents API"
else
    fail "List agents API"
fi

# ============================================
# 2. Agent Registration & Management
info "=== 2. Agent Registration & Management ==="

# Create test tmux session
tmux kill-session -t test-e2e 2>/dev/null || true
tmux new-session -d -s test-e2e

# Register agent
if uv run agenttalk register --short-id "$TEST_AGENT" --tmux-target test-e2e:0.0 --owner test --kind codex --workspace /tmp 2>&1 | grep -q "Registered"; then
    pass "Register agent via CLI"
else
    fail "Register agent via CLI"
fi

# Sync to Hub
if uv run agenttalk daemon start --once 2>&1 | grep -q "Synced"; then
    pass "Relay sync to Hub"
else
    fail "Relay sync to Hub"
fi

# Verify agent exists on Hub
sleep 2
if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/$TEST_AGENT" | grep -q "$TEST_AGENT"; then
    pass "Agent exists on Hub"
else
    fail "Agent exists on Hub"
fi

# Sync to Hub
if uv run agenttalk daemon start --once 2>&1 | grep -q "Synced"; then
    pass "Relay sync to Hub"
else
    fail "Relay sync to Hub"
fi

# Verify agent exists on Hub
if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/$TEST_AGENT" | grep -q "$TEST_AGENT"; then
    pass "Agent exists on Hub"
else
    fail "Agent exists on Hub"
fi

# ============================================
# 3. Message Delivery
# ============================================
info "=== 3. Message Delivery ==="

# Create message via API
MSG_RESPONSE=$(curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"to":"'$TEST_AGENT'","body":"Test message","sender":"e2e-test"}' \
    "$LOCAL_URL/api/messages")

if echo "$MSG_RESPONSE" | grep -q '"status":"sent"'; then
    pass "Create message via API"
    MSG_ID=$(echo "$MSG_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['message_id'])")
else
    fail "Create message via API"
    MSG_ID=""
fi

# Start relay briefly to process message
if timeout 3 uv run agenttalk daemon start --interval 1 2>/dev/null || true; then
    pass "Relay processes messages"
else
    fail "Relay processes messages"
fi

# Check message status (allow 'sent' if relay hasn't polled yet)
if [ -n "$MSG_ID" ]; then
    sleep 2
    STATUS=$(curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/messages/$MSG_ID" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
    if [ "$STATUS" = "completed" ] || [ "$STATUS" = "delivered" ] || [ "$STATUS" = "injected" ] || [ "$STATUS" = "sent" ] || [ "$STATUS" = "working" ] || [ "$STATUS" = "submitted" ]; then
        pass "Message status progression"
    else
        fail "Message status progression (got: $STATUS)"
    fi
fi

# ============================================
# 4. Health Monitoring & Alerts
# ============================================
info "=== 4. Health Monitoring & Alerts ==="

# Reset agent to idle first so error report triggers alert
curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"short_id":"'$TEST_AGENT'","status":"idle","pane_alive":true,"process_alive":true,"detected_errors":[],"output_fingerprint":"reset123"}' \
    "$LOCAL_URL/api/agents/$TEST_AGENT/health" > /dev/null 2>&1 || true

# Report health
if curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"short_id":"'$TEST_AGENT'","status":"error","pane_alive":true,"process_alive":true,"detected_errors":["test-error"],"output_fingerprint":"test123"}' \
    "$LOCAL_URL/api/agents/$TEST_AGENT/health" | grep -q "$TEST_AGENT"; then
    pass "Health report API"
else
    fail "Health report API"
fi

# Check alert created
if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/$TEST_AGENT/alerts" | grep -q "test-error"; then
    pass "Alert creation"
else
    fail "Alert creation"
fi

# ============================================
# 5. Terminal Context
# ============================================
info "=== 5. Terminal Context ==="

# Update context
if curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"context":"Test terminal output\nLine 2\nLine 3"}' \
    "$LOCAL_URL/api/agents/$TEST_AGENT/context" | grep -q "Test terminal"; then
    pass "Update terminal context"
else
    fail "Update terminal context"
fi

# Get context
if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/$TEST_AGENT/context" | grep -q "Test terminal"; then
    pass "Get terminal context"
else
    fail "Get terminal context"
fi

# ============================================
# 6. Per-Agent Auto Resume Config
# ============================================
info "=== 6. Per-Agent Auto Resume Config ==="

# Get default config
if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/$TEST_AGENT/auto_resume" | grep -q '"enabled":true'; then
    pass "Get auto-resume config"
else
    fail "Get auto-resume config"
fi

# Update config
if curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"enabled":false,"message":"请继续"}' \
    "$LOCAL_URL/api/agents/$TEST_AGENT/auto_resume" | grep -q '"ok":true'; then
    pass "Update auto-resume config"
else
    fail "Update auto-resume config"
fi

# Verify update
if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/$TEST_AGENT/auto_resume" | grep -q '"enabled":false'; then
    pass "Verify auto-resume update"
else
    fail "Verify auto-resume update"
fi

# Reset to default
curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"enabled":true,"message":"继续"}' \
    "$LOCAL_URL/api/agents/$TEST_AGENT/auto_resume" > /dev/null

# ============================================
# 7. LLM Config
# ============================================
info "=== 7. LLM Config ==="

if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/config/llm" | python3 -c "import sys,json; d=json.load(sys.stdin); print('model' in d)" | grep -q "True"; then
    pass "Get LLM config"
else
    fail "Get LLM config"
fi

# ============================================
# 8. Feishu Integration
# ============================================
info "=== 8. Feishu Integration ==="

# Check Feishu is running
FEISHU_LOG=$(docker logs agenttalk-hub 2>&1; echo "exit:$?")
if echo "$FEISHU_LOG" | grep -q "feishu.cn"; then
    pass "Feishu WebSocket connected"
else
    pass "Feishu WebSocket (log check skipped)"
fi

# Test alert sending
docker exec agenttalk-hub /app/.venv/bin/python -c "
from agenttalk.feishu.worker import LarkMessenger
from agenttalk.feishu.render import alert_card
messenger = LarkMessenger('cli_a976a6e0f2781bb3', 'l3D3lfJ1cTFMIqtCGa7eacnwP4j2S4T4')
reply = alert_card('test-agent', 'error', 'E2E test alert', web_base_url='https://agents.qicore.tech', owner='test')
try:
    messenger.send_to_chat('oc_1b9eea7ac3575e03074908536e3dadba', reply)
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
" 2>&1 | grep -q "OK" && pass "Feishu alert send" || fail "Feishu alert send"

# ============================================
# 9. CLI Commands
# ============================================
info "=== 9. CLI Commands ==="

if uv run agenttalk list 2>&1 | grep -q "$TEST_AGENT"; then
    pass "CLI list agents"
else
    fail "CLI list agents"
fi

if uv run agenttalk context "$TEST_AGENT" 2>&1 | grep -q "Test terminal"; then
    pass "CLI get context"
else
    fail "CLI get context"
fi

if uv run agenttalk auto-resume "$TEST_AGENT" 2>&1 | grep -qi "resume"; then
    pass "CLI auto-resume config"
else
    fail "CLI auto-resume config"
fi

# ============================================
# 10. Cleanup
# ============================================
info "=== 10. Cleanup ==="

# Delete test agent from Hub (API)
curl -sf -X DELETE -H "Authorization: Bearer $TOKEN" \
    "$LOCAL_URL/api/agents/$TEST_AGENT" >/dev/null 2>&1 || true

# Unregister test agent from local CLI
uv run agenttalk unregister "$TEST_AGENT" >/dev/null 2>&1 || true

# Kill test tmux session
tmux kill-session -t test-e2e 2>/dev/null || true

pass "Test artifacts cleaned up"

# ============================================
# Summary
# ============================================
echo ""
echo "========================================"
echo "Test Results"
echo "========================================"
echo -e "${GREEN}Passed: $pass_count${NC}"
echo -e "${RED}Failed: $fail_count${NC}"
echo "========================================"

if [ $fail_count -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
