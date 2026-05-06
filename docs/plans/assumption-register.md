# Assumption Register

## Open

| ID | Description | Source | Trigger Phase | Status |
|---|---|---|---|---|
| AT-A1 | Web live terminal currently assumes the Hub process can access the registered tmux target locally. True multi-machine terminal control must route through the target relay. | MVP audit 2026-05-07 | Post-MVP terminal hardening | open |
| AT-A2 | Web UI uses `VITE_AGENTTALK_TOKEN` or `dev-token` for MVP testing. Team rollout needs explicit token entry/storage and no dev default. | MVP audit 2026-05-07 | Post-MVP auth hardening | open |
| AT-A3 | First version intentionally has no terminal input lock. Recent input actor tracking remains incomplete. | MVP audit 2026-05-07 | Post-MVP collaboration UX | open |
| AT-A4 | xterm.js is bundled in the initial Web chunk for MVP. Route-level lazy loading should be added if bundle size matters. | MVP audit 2026-05-07 | Web performance pass | open |
