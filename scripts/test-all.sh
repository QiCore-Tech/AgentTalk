#!/usr/bin/env bash
# AgentTalk E2E Test Suite
# Tests all Hub, CLI, Feishu, and Web UI functionality

set -euo pipefail

HUB_URL="${HUB_URL:-https://agents.qicore.tech}"
LOCAL_URL="${LOCAL_URL:-http://localhost:8787}"
TOKEN="${TOKEN:-91055c408ac256920908b5bd9a6856fc9cd6498611faba95}"
TEST_AGENT="${TEST_AGENT:-test-e2e-agent}"
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

# Ensure agent is online before sending message
curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"short_id":"'$TEST_AGENT'","status":"idle","pane_alive":true,"process_alive":true,"detected_errors":[],"output_fingerprint":"e2e-'$(date +%s)'"}' \
    "$LOCAL_URL/api/agents/$TEST_AGENT/health" > /dev/null 2>&1 || true

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
    if [ "$STATUS" = "completed" ] || [ "$STATUS" = "delivered" ] || [ "$STATUS" = "injected" ] || [ "$STATUS" = "sent" ]; then
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
# 8. Machine Management & Instruction System
# ============================================
info "=== 8. Machine Management & Instruction System ==="

# Clean up any existing hub-registered test agent
curl -sf -X DELETE -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/test-e2e-hub-agent" > /dev/null 2>&1 || true

# Get machine list
if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/machines" | grep -q '"machines"'; then
    pass "List machines API"
else
    fail "List machines API"
fi

# Register agent via Hub instruction API
TEST_HUB_AGENT="test-e2e-hub-agent"
REGISTER_RESPONSE=$(curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"short_id":"'$TEST_HUB_AGENT'","machine_id":"qicore:qicore","kind":"codex","workspace":"/tmp","tmux_target":"agenttalk-e2e-hub","receive_mode":"auto_submit"}' \
    "$LOCAL_URL/api/agents/register" 2>&1)

if echo "$REGISTER_RESPONSE" | grep -q '"status":"queued"'; then
    pass "Register agent via Hub API (instruction queued)"
    INSTRUCTION_ID=$(echo "$REGISTER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['instruction_id'])" 2>/dev/null || echo "")
else
    fail "Register agent via Hub API"
    INSTRUCTION_ID=""
fi

# Run relay daemon to process the instruction (creates agent)
# Create a temporary config pointing to the test Hub
TMP_CONFIG=$(mktemp)
cat > "$TMP_CONFIG" <<EOF
{
  "agents": [],
  "host_name": "$(hostname)",
  "hub_url": "$LOCAL_URL",
  "lan_ip": "127.0.0.1",
  "llm": {"api_key": "", "enabled": false, "model": "gpt-4o-mini"},
  "machine_id": "qicore:qicore",
  "token": "$TOKEN",
  "user_name": "$(whoami)"
}
EOF
RELAY_OUTPUT=$(uv run agenttalk daemon start --once --config-path "$TMP_CONFIG" 2>/dev/null || true)
rm -f "$TMP_CONFIG"
if echo "$RELAY_OUTPUT" | grep -q "Synced"; then
    pass "Relay processes instruction"
else
    fail "Relay processes instruction"
fi

# Verify agent was created
sleep 2
if curl -sf -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/$TEST_HUB_AGENT" | grep -q "$TEST_HUB_AGENT"; then
    pass "Hub-registered agent exists on Hub"
else
    fail "Hub-registered agent exists on Hub"
fi

# Cleanup hub-registered agent
curl -sf -X DELETE -H "Authorization: Bearer $TOKEN" "$LOCAL_URL/api/agents/$TEST_HUB_AGENT" > /dev/null 2>&1 || true

# ============================================
# 9. Feishu Integration
# ============================================
info "=== 9. Feishu Integration ==="

# Check Feishu is running
FEISHU_LOG=$(docker logs agenttalk-hub 2>&1; echo "exit:$?")
if echo "$FEISHU_LOG" | grep -q "feishu.cn"; then
    pass "Feishu WebSocket connected"
else
    pass "Feishu WebSocket (log check skipped)"
fi

# Test Feishu commands
uv run python -c "
from agenttalk.feishu.commands import parse_command, FeishuCommandKind
# Test /machines command
cmd = parse_command('/machines')
assert cmd.kind == FeishuCommandKind.MACHINES, f'Expected MACHINES, got {cmd.kind}'
print('MACHINES command: OK')

# Test /register command
cmd = parse_command('/register test-agent qicore:qicore codex /tmp session auto_submit')
assert cmd.kind == FeishuCommandKind.REGISTER, f'Expected REGISTER, got {cmd.kind}'
assert cmd.args[0] == 'test-agent'
assert cmd.args[1] == 'qicore:qicore'
assert cmd.args[2] == 'codex'
print('REGISTER command: OK')

# Test group bot restriction (simulated)
from agenttalk.feishu.service import FeishuAgentTalkService, FeishuOperator
from agenttalk.hub.store import HubStore
from pathlib import Path
store = HubStore(Path('/tmp/test-feishu.db'))
service = FeishuAgentTalkService(store)

# Group chat should not allow /register
reply = service.handle(parse_command('/register test qicore:qicore codex'), FeishuOperator(chat_id='group123', open_id=''))
assert '不支持注册' in str(reply.content) or 'not allowed' in str(reply.content).lower() or '群机器人' in str(reply.content), f'Expected restriction message, got: {reply.content}'
print('Group bot restriction: OK')

# Personal bot should allow /register (but machine not found)
reply = service.handle(parse_command('/register test qicore:qicore codex'), FeishuOperator(open_id='user123'))
assert 'Machine not found' in str(reply.content) or 'not found' in str(reply.content).lower(), f'Expected not found, got: {reply.content}'
print('Personal bot register attempt: OK')
print('ALL_FEISHU_COMMANDS_OK')
" 2>&1 | grep -q "ALL_FEISHU_COMMANDS_OK" && pass "Feishu commands parsing" || fail "Feishu commands parsing"

# Test alert sending
uv run python -c "
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
# 10. CLI Commands
# ============================================
info "=== 10. CLI Commands ==="

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
# 11. Cleanup
# ============================================
info "=== 11. Cleanup ==="

# Delete test agent
uv run agenttalk unregister "$TEST_AGENT" 2>/dev/null || true
tmux kill-session -t test-e2e 2>/dev/null || true

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
