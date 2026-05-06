# AgentTalk MVP Audit

Date: 2026-05-07

Scope: M1-M6 AgentTalk MVP implementation.

## Verdict

ACCEPT with noted blind spots.

## Gate 0: Automated Checks

PASS.

Evidence:

```text
uv run pytest
............................                                             [100%]
28 passed in 2.38s
```

```text
npm run lint
> web@0.0.0 lint
> eslint .
```

```text
npm run build
✓ built in 216ms
```

Build warning:

```text
Some chunks are larger than 500 kB after minification.
```

This is acceptable for MVP because xterm.js is included in the first bundle. It should be revisited with route-level code splitting later.

```text
npm run test:e2e
4 passed (2.4s)
```

## Gate 1: Plan Alignment

PASS.

Evidence:

- M1 implemented Hub registry, SQLite, token auth, and CLI list.
- M2 implemented read-only tmux discovery, local config, relay sync, and registration CLI.
- M3 implemented point-to-point message creation, routing, injection primitive, and CLI send/status.
- M4 implemented response storage, marker completion, context storage, capture support, and CLI watch/response/context.
- M5 implemented React/Vite Agents console with table, preview, detail, structured messaging, and Playwright coverage.
- M6 implemented xterm.js terminal view, Hub WebSocket bridge to registered tmux target, Context overview, and WebSocket tests.

Progress table in `docs/plans/2026-05-07-agenttalk-mvp-implementation-plan.md` records commits through M6.

## Gate 2: Safety Guardrails

PASS.

Protected existing panes were recorded in `docs/plans/acceptance/protected-tmux-panes.md`.

Observed protected panes before final audit:

```text
0:0.0|%0|claude|/workspace/soha_pilot-v2|Fix RC QA unresolved issues with worktree
64:0.0|%71|node|/workspace/soha_pilot-v2|codex exec --dangerously-bypass-approvals-and-sandbox -C
72:0.0|%86|node|/workspace/soha_agentTalk|soha_agentTalk
77:0.0|%84|claude|/workspace/soha_pilot-v2|Debug multi-turn agent issues and identify root causes
78:0.0|%85|claude|/workspace/soha_pilot-v2|Review Agent UX issues and identify additional risks
80:0.0|%87|node|/workspace/soha_pilot-v2|soha_pilot-v2
```

Real tmux tests used dedicated sessions with `agenttalk-e2e-*` prefixes only. Final cleanup check:

```text
tmux list-sessions -F '#{session_name}' | rg '^agenttalk-e2e-' || true
```

returned no sessions.

## Gate 3: Contract Coverage

PASS.

Contract checklists exist:

- `docs/plans/acceptance/m1-contract-checklist.md`
- `docs/plans/acceptance/m2-contract-checklist.md`
- `docs/plans/acceptance/m3-contract-checklist.md`
- `docs/plans/acceptance/m4-contract-checklist.md`
- `docs/plans/acceptance/m5-m6-contract-checklist.md`

Key contract checks covered by tests:

- Auth errors and registry behavior: `tests/test_hub_registry.py`
- tmux discovery parsing: `tests/test_tmux.py`
- local config: `tests/test_config.py`
- relay sync and injection behavior: `tests/test_relay.py`
- message lifecycle: `tests/test_messages.py`
- response/context: `tests/test_m4_feedback_context.py`
- terminal WebSocket target usage: `tests/test_terminal_ws.py`
- Web UI flows: `web/tests/agent-console.spec.ts`

## Gate 4: Negative Space Review

No blocker found.

Important residual risks:

1. Terminal WebSocket is Hub-local and directly controls `tmux_target` from the Hub process. In a true multi-machine deployment, this must route through the target machine relay rather than assuming Hub has access to the pane.
2. The Web UI token currently comes from `VITE_AGENTTALK_TOKEN` or `dev-token`. A production LAN deployment needs explicit token entry/storage and no dev default.
3. Web live terminal has no input lock by design. The UI states recent input actor in design, but full actor tracking is not implemented yet.
4. Bundle size warning exists due to xterm.js in the initial bundle.

These are acceptable for the current MVP but should be tracked before wider team rollout.

## Gate 5: Probe Coverage

PASS for MVP.

Probe-style checks included:

- Offline heartbeat derives offline status.
- Missing target message creation returns `target_not_found`.
- Offline target returns `target_offline`.
- Relay marks missing panes offline.
- Output delta handles prefix and line overlap cases.
- Terminal WebSocket writes to the registered tmux target in test via fake `TmuxClient`.

## Audit Blind Spots

This audit did not perform a multi-machine LAN test. The relay WebSocket design for remote terminal control is not complete; the current M6 terminal bridge works when Hub can access the registered tmux target locally. Web UI tests mock HTTP APIs and verify rendering/interaction, while real WebSocket terminal behavior is covered at backend level plus dedicated local tmux smoke testing.

## Follow-Up Recommendations

1. Implement relay-mediated terminal streaming for true remote machines.
2. Replace Web dev-token default with an explicit login/token prompt.
3. Add terminal input actor tracking.
4. Lazy-load xterm.js on the detail page.
