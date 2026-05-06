# Protected tmux Panes

Date: 2026-05-07

The user explicitly said existing tmux panes are doing important development and must not be affected.

Do not send input, attach, kill, resize, or otherwise control these panes:

| target | pane id | command | path | title |
|---|---|---|---|---|
| `0:0.0` | `%0` | `claude` | `/workspace/soha_pilot-v2` | `Fix RC QA unresolved issues with worktree` |
| `64:0.0` | `%71` | `node` | `/workspace/soha_pilot-v2` | `soha_pilot-v2` |
| `72:0.0` | `%86` | `node` | `/workspace/soha_agentTalk` | `soha_agentTalk` |
| `77:0.0` | `%84` | `claude` | `/workspace/soha_pilot-v2` | `Debug multi-turn agent issues and identify root causes` |
| `78:0.0` | `%85` | `claude` | `/workspace/soha_pilot-v2` | `Review Agent UX issues and identify additional risks` |
| `80:0.0` | `%87` | `node` | `/workspace/soha_pilot-v2` | `soha_pilot-v2` |

Real tmux tests may only create, use, and clean up dedicated sessions whose names start with:

```text
agenttalk-e2e-
```
