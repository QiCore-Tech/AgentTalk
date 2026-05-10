from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FeishuCommandKind(StrEnum):
    HELP = "help"
    AGENTS = "agents"
    AGENT = "agent"
    CONTEXT = "context"
    SEND = "send"
    STATUS = "status"
    RESPONSE = "response"
    TRACE = "trace"
    GUIDE = "guide"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FeishuCommand:
    kind: FeishuCommandKind
    args: tuple[str, ...] = ()
    raw: str = ""
    error: str = ""


def parse_command(text: str) -> FeishuCommand:
    raw = text.strip()
    if not raw:
        return FeishuCommand(FeishuCommandKind.HELP, raw=text)
    parts = raw.split(maxsplit=2)
    name = parts[0].lstrip("/").lower()
    rest = tuple(parts[1:])

    if name in {"help", "agenttalk"}:
        return FeishuCommand(FeishuCommandKind.HELP, rest, raw)
    if name == "agents":
        return FeishuCommand(FeishuCommandKind.AGENTS, rest, raw)
    if name == "agent":
        if not rest:
            return FeishuCommand(FeishuCommandKind.AGENT, rest, raw, "Usage: /agent <agent-id>")
        return FeishuCommand(FeishuCommandKind.AGENT, rest, raw)
    if name == "context":
        if not rest:
            return FeishuCommand(FeishuCommandKind.CONTEXT, rest, raw, "Usage: /context <agent-id>")
        return FeishuCommand(FeishuCommandKind.CONTEXT, rest, raw)
    if name == "send":
        if len(parts) < 3:
            return FeishuCommand(FeishuCommandKind.SEND, rest, raw, "Usage: /send <agent-id> <message>")
        return FeishuCommand(FeishuCommandKind.SEND, (parts[1], parts[2]), raw)
    if name == "status":
        if not rest:
            return FeishuCommand(FeishuCommandKind.STATUS, rest, raw, "Usage: /status <message-id>")
        return FeishuCommand(FeishuCommandKind.STATUS, rest, raw)
    if name == "response":
        if not rest:
            return FeishuCommand(FeishuCommandKind.RESPONSE, rest, raw, "Usage: /response <message-id>")
        return FeishuCommand(FeishuCommandKind.RESPONSE, rest, raw)
    if name == "trace":
        if not rest:
            return FeishuCommand(FeishuCommandKind.TRACE, rest, raw, "Usage: /trace <message-id>")
        return FeishuCommand(FeishuCommandKind.TRACE, rest, raw)
    if name == "guide":
        return FeishuCommand(FeishuCommandKind.GUIDE, rest, raw)
    return FeishuCommand(FeishuCommandKind.UNKNOWN, rest, raw, f"Unknown command: {parts[0]}")
