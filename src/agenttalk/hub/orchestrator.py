"""Task Orchestrator engine for executing multi-step agent workflows."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from agenttalk.hub.store import HubStore

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    """Hub-side task execution engine."""

    def __init__(self, store: HubStore):
        self.store = store
        self._running_tasks: dict[str, asyncio.Task] = {}

    async def submit_task(
        self,
        user_id: str,
        raw_request: str,
        target_machine_id: int,
        target_workspace_id: int | None = None,
        parsed_steps: list[dict] | None = None,
    ) -> str:
        """Submit a new task for execution."""
        task_id = f"task-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

        steps_json = json.dumps(parsed_steps) if parsed_steps else "[]"

        self.store.create_task(
            task_id=task_id,
            task_type="orchestrator",
            owner_id=user_id,
            target_machine_id=target_machine_id,
            target_workspace_id=target_workspace_id,
            raw_request=raw_request,
            parsed_steps=steps_json,
        )

        # Start async execution
        self._running_tasks[task_id] = asyncio.create_task(self._execute_task(task_id))

        return task_id

    async def _execute_task(self, task_id: str) -> None:
        """Execute all steps of a task."""
        task = self.store.get_task(task_id)
        if not task:
            logger.error("Task not found: %s", task_id)
            return

        try:
            self.store.update_task_status(task_id, "running")
            steps = json.loads(task["parsed_steps"])
            total_steps = len(steps)

            # Update total steps
            with self.store.connect() as conn:
                conn.execute(
                    "UPDATE tasks SET total_steps = ? WHERE task_id = ?",
                    (total_steps, task_id),
                )

            context: dict[str, Any] = {}

            for i, step in enumerate(steps):
                current_step = i + 1
                self.store.update_task_status(task_id, "running", current_step=current_step)
                self.store.append_task_log(task_id, f"Step {current_step}/{total_steps}: {step.get('action', 'unknown')}")

                try:
                    result = await self._execute_step(task, step, context)
                    context[f"step_{current_step}"] = result
                    self.store.append_task_log(task_id, f"Step {current_step} completed")
                except Exception as exc:
                    logger.exception("Task step failed: %s", exc)
                    self.store.update_task_status(task_id, "failed", error=str(exc))
                    self.store.append_task_log(task_id, f"Step {current_step} failed: {exc}")
                    return

            self.store.update_task_status(task_id, "completed")
            self.store.append_task_log(task_id, "Task completed successfully")

        except Exception as exc:
            logger.exception("Task execution failed: %s", exc)
            self.store.update_task_status(task_id, "failed", error=str(exc))
        finally:
            self._running_tasks.pop(task_id, None)

    async def _execute_step(self, task: dict, step: dict, context: dict) -> dict:
        """Execute a single step."""
        # Resolve template variables
        step = self._resolve_templates(step, context)
        action = step.get("action", "")

        if action == "provision_agent":
            return {"short_id": step.get("short_id", ""), "status": "created"}

        elif action == "send_message":
            return {"message": f"Sent to {step.get('to', '')}", "status": "sent"}

        elif action == "wait_for_done_marker":
            # Simulate waiting
            await asyncio.sleep(0.1)
            return {"status": "completed"}

        elif action == "shell":
            return {"command": step.get("command", ""), "status": "executed"}

        elif action == "git_sync":
            return {"branch": step.get("branch", "main"), "status": "synced"}

        else:
            return {"status": "skipped", "reason": f"Unknown action: {action}"}

    def _resolve_templates(self, step: dict, context: dict) -> dict:
        """Resolve template variables like {{step_1.short_id}}."""
        step_json = json.dumps(step)
        for key, value in context.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    template = f"{{{{{key}.{sub_key}}}}}"
                    step_json = step_json.replace(template, str(sub_value))
        return json.loads(step_json)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        running_task = self._running_tasks.get(task_id)
        if running_task and not running_task.done():
            running_task.cancel()
            self.store.update_task_status(task_id, "cancelled")
            return True
        return False
