"""LLM-based task parser for Orchestrator."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

TASK_PARSE_PROMPT = """You are an AgentTalk task parser. Convert the user's natural language request into structured execution steps.

Available step types:
- ensure_workspace: Ensure workspace exists at path
- git_sync: Pull code from git
- provision_agent: Create and start an agent (codex/claude/etc)
- send_message: Send a task message to an agent
- wait_for_done_marker: Wait for agent completion
- shell: Execute a shell command

User request: {request}
Target workspace: {workspace}
Target machine: {machine}

Respond with JSON only:
{{
    "description": "Brief task description",
    "steps": [
        {{"step": 1, "action": "provision_agent", "kind": "codex", "short_id": "unique-id", "workspace": "/path"}},
        {{"step": 2, "action": "send_message", "to": "unique-id", "body": "task description"}},
        {{"step": 3, "action": "wait_for_done_marker", "agent_id": "unique-id", "timeout": 3600}}
    ],
    "estimated_duration": 300
}}

Rules:
- Use unique short_ids like "{{workspace}}-codex-{{random}}"
- Reference previous steps with template variables like {{step_1.short_id}}
- Include reasonable timeouts
- Keep steps minimal and focused
"""


class TaskParser:
    """Parse natural language tasks into structured steps using LLM."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini", base_url: str | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")

    async def parse(self, request: str, workspace: str | None = None, machine: str | None = None) -> dict[str, Any]:
        """Parse natural language request into structured task."""
        import openai

        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = openai.AsyncOpenAI(**client_kwargs)

        prompt = TASK_PARSE_PROMPT.format(
            request=request,
            workspace=workspace or "not specified",
            machine=machine or "not specified",
        )

        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a task parser. Respond with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.2,
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty LLM response")

        # Try to parse JSON
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                raise ValueError(f"Invalid JSON response: {content[:200]}")

        return result

    def _fallback_parse(self, request: str) -> dict[str, Any]:
        """Fallback parser when LLM is unavailable."""
        request_lower = request.lower()

        if "codex" in request_lower or "claude" in request_lower:
            kind = "codex" if "codex" in request_lower else "claude"
            return {
                "description": f"Provision {kind} agent",
                "steps": [
                    {"step": 1, "action": "provision_agent", "kind": kind, "short_id": f"auto-{kind}-1"},
                    {"step": 2, "action": "send_message", "to": f"auto-{kind}-1", "body": request},
                    {"step": 3, "action": "wait_for_done_marker", "agent_id": f"auto-{kind}-1"},
                ],
                "estimated_duration": 300,
            }

        return {
            "description": "Generic task",
            "steps": [
                {"step": 1, "action": "shell", "command": f"echo 'Executing: {request}'"},
            ],
            "estimated_duration": 60,
        }
