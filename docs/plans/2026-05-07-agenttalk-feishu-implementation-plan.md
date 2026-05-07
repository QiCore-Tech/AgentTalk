# AgentTalk Feishu Integration Implementation Plan

Date: 2026-05-07

## Inputs

- `docs/plans/2026-05-07-agenttalk-feishu-design.md`
- `docs/plans/2026-05-07-agenttalk-design-decisions.md`
- Existing Hub/API implementation

## Milestones

### F1: Feishu Settings and Startup Wiring

Goal: Add Feishu configuration to Hub startup without changing core Hub behavior when disabled.

Tasks:

1. Add optional dependency for Feishu SDK.
2. Add Hub settings:
   - `feishu_enable`
   - `feishu_app_id`
   - `feishu_app_secret`
3. Add CLI flags and environment variable resolution.
4. Start Feishu worker during Hub lifespan only when enabled.
5. Add tests that Feishu disabled by default and enabled settings are passed to worker.

Acceptance:

- Existing Hub tests pass unchanged.
- `agenttalk hub serve` works without Feishu settings.
- Missing app id/secret with `--feishu-enable` returns clear startup error.

### F2: Command Parser and AgentTalk Service Facade

Goal: Parse Feishu text commands and map them to AgentTalk operations.

Tasks:

1. Add command parser for `/help`, `/agents`, `/agent`, `/context`, `/send`, `/status`, `/response`.
2. Add response models independent from Feishu SDK.
3. Add service facade over Hub store/client functions.
4. Add unit tests for command parsing, missing args, and truncation.

Acceptance:

- Parser is deterministic and covered by tests.
- Command handlers do not import Feishu SDK directly.

### F3: Feishu Message Rendering

Goal: Render command results as Feishu text and interactive card payloads.

Tasks:

1. Add text renderers.
2. Add card renderers for agents list and agent detail.
3. Add truncation helpers.
4. Add unit tests with snapshot-style assertions for payload shape.

Acceptance:

- `/agents` can render a card list.
- `/agent <id>` can render a detail card.
- Long context/response values are bounded.

### F4: Long-Connection Worker

Goal: Receive Feishu events and send replies.

Tasks:

1. Implement worker wrapper around Feishu long-connection SDK.
2. Extract operator/chat/message text from event payload.
3. Dispatch parsed commands.
4. Send text or card replies through Feishu API.
5. Add fake-SDK tests for event handling and reply dispatch.

Acceptance:

- Fake event `/agents` produces Feishu reply.
- Fake event `/send <id> <msg>` creates AgentTalk message through service.
- Feishu SDK failures are caught and logged.

### F5: Integration Docs and Manual Validation

Goal: Document setup and perform manual Feishu validation when credentials are available.

Tasks:

1. Update bilingual README.
2. Add Feishu setup section:
   - app credentials
   - bot enablement
   - long-connection mode
   - required permissions/events
3. Add manual validation checklist.
4. Run unit tests.
5. If credentials are available, run a real Feishu chat smoke test.

Acceptance:

- README explains how to enable Feishu integration.
- Unit tests pass.
- Manual Feishu smoke test is recorded or explicitly skipped due to missing credentials.

## Test Strategy

- Unit tests for parser, renderers, settings, and service facade.
- Fake Feishu SDK tests for worker.
- Existing Hub/CLI/Web tests remain passing.
- Real Feishu test requires app credentials and should not be mandatory in CI.

## Risks

1. Feishu SDK/event payload changes.
2. Required bot permissions may differ by tenant configuration.
3. Long-connection worker inside Hub may need lifecycle hardening.
4. Permissive access policy is acceptable for MVP but should be revisited before broad rollout.
