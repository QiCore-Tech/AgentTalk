"""Tests for TaskOrchestrator."""

import pytest
import asyncio
from pathlib import Path
from agenttalk.hub.store import HubStore
from agenttalk.hub.orchestrator import TaskOrchestrator


@pytest.fixture
def store(tmp_path: Path):
    return HubStore(tmp_path / "test.db", heartbeat_ttl_seconds=30)


@pytest.fixture
def orchestrator(store):
    return TaskOrchestrator(store)


@pytest.mark.asyncio
class TestTaskOrchestrator:
    async def test_submit_task(self, orchestrator, store):
        task_id = await orchestrator.submit_task(
            user_id="user1",
            raw_request="Create a codex agent",
            target_machine_id=1,
        )
        assert task_id.startswith("task-")
        
        task = store.get_task(task_id)
        assert task is not None
        assert task["status"] == "pending"
        assert task["owner_id"] == "user1"
        assert task["raw_request"] == "Create a codex agent"

    async def test_execute_task_steps(self, orchestrator, store):
        parsed_steps = [
            {"step": 1, "action": "shell", "command": "echo hello"},
            {"step": 2, "action": "provision_agent", "kind": "codex", "short_id": "test-agent"},
        ]
        
        task_id = await orchestrator.submit_task(
            user_id="user1",
            raw_request="Test task",
            target_machine_id=1,
            parsed_steps=parsed_steps,
        )
        
        # Wait for execution
        await asyncio.sleep(0.5)
        
        task = store.get_task(task_id)
        assert task["status"] in ("completed", "running")
        assert "shell" in task["logs"] or "completed" in task["logs"]

    async def test_cancel_task(self, orchestrator, store):
        # Create a task with a long wait
        parsed_steps = [
            {"step": 1, "action": "wait_for_done_marker", "agent_id": "test", "timeout": 3600},
        ]
        
        task_id = await orchestrator.submit_task(
            user_id="user1",
            raw_request="Long task",
            target_machine_id=1,
            parsed_steps=parsed_steps,
        )
        
        # Give it a moment to start
        await asyncio.sleep(0.1)
        
        # Cancel it
        result = orchestrator.cancel_task(task_id)
        assert result is True
        
        task = store.get_task(task_id)
        assert task["status"] == "cancelled"

    def test_template_resolution(self, orchestrator):
        step = {
            "action": "send_message",
            "to": "{{step_1.short_id}}",
            "body": "Hello",
        }
        context = {
            "step_1": {"short_id": "agent-123"},
        }
        
        resolved = orchestrator._resolve_templates(step, context)
        assert resolved["to"] == "agent-123"

    async def test_task_with_workspace(self, orchestrator, store):
        task_id = await orchestrator.submit_task(
            user_id="user1",
            raw_request="Task with workspace",
            target_machine_id=1,
            target_workspace_id=2,
        )
        
        task = store.get_task(task_id)
        assert task["target_workspace_id"] == 2
        assert task["target_machine_id"] == 1