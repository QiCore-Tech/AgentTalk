"""Tests for HubStore new tables: machines, workspaces, tasks, feishu_bots, notification_routes."""

import pytest
from pathlib import Path
from agenttalk.hub.store import HubStore


@pytest.fixture
def store(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return HubStore(db_path, heartbeat_ttl_seconds=30)


class TestMachineOperations:
    def test_create_and_get_machine(self, store):
        result = store.create_machine(
            user_id="user1",
            name="MacBook-Pro",
            host_name="macbook.local",
            relay_machine_id="env-wenda:coder",
            capabilities=["tmux", "codex"],
        )
        machine_id = result["id"]
        assert machine_id > 0

        machine = store.get_machine(machine_id)
        assert machine is not None
        assert machine["name"] == "MacBook-Pro"
        assert machine["host_name"] == "macbook.local"
        assert machine["relay_machine_id"] == "env-wenda:coder"
        assert machine["status"] in ("offline", "online")
        assert machine["user_id"] == "user1"

    def test_get_machine_by_relay(self, store):
        store.create_machine(
            user_id="user1",
            name="Test",
            host_name="test.local",
            relay_machine_id="relay-123",
        )
        machine = store.get_machine_by_relay("relay-123")
        assert machine is not None
        assert machine["name"] == "Test"

    def test_list_machines(self, store):
        store.create_machine(user_id="user1", name="M1", host_name="m1.local", relay_machine_id="relay-1")
        store.create_machine(user_id="user1", name="M2", host_name="m2.local", relay_machine_id="relay-2")
        store.create_machine(user_id="user2", name="M3", host_name="m3.local", relay_machine_id="relay-3")

        all_machines = store.list_machines()
        assert len(all_machines) == 3

        user1_machines = store.list_machines(user_id="user1")
        assert len(user1_machines) == 2

    def test_update_machine_status(self, store):
        result = store.create_machine(user_id="user1", name="M1", host_name="m1.local", relay_machine_id="relay-1")
        machine_id = result["id"]
        store.update_machine_status(machine_id, "online")
        machine = store.get_machine(machine_id)
        assert machine["status"] == "online"

    def test_delete_machine(self, store):
        result = store.create_machine(user_id="user1", name="M1", host_name="m1.local", relay_machine_id="relay-1")
        machine_id = result["id"]
        assert store.delete_machine(machine_id)
        assert store.get_machine(machine_id) is None


class TestWorkspaceOperations:
    def test_create_and_get_workspace(self, store):
        result = store.create_machine(user_id="user1", name="M1", host_name="m1.local", relay_machine_id="relay-1")
        machine_id = result["id"]
        result = store.create_workspace(
            name="rabbit",
            path="/workspace/rabbit",
            owner_id="user1",
            machine_id=machine_id,
            description="Rabbit project",
        )
        ws_id = result["id"]
        assert ws_id > 0

        ws = store.get_workspace(ws_id)
        assert ws["name"] == "rabbit"
        assert ws["path"] == "/workspace/rabbit"

    def test_list_workspaces(self, store):
        result = store.create_machine(user_id="user1", name="M1", host_name="m1.local", relay_machine_id="relay-1")
        machine_id = result["id"]
        store.create_workspace(name="ws1", path="/ws1", owner_id="user1", machine_id=machine_id)
        store.create_workspace(name="ws2", path="/ws2", owner_id="user1", machine_id=machine_id)
        store.create_workspace(name="ws3", path="/ws3", owner_id="user2", machine_id=machine_id)

        all_ws = store.list_workspaces()
        assert len(all_ws) == 3

        user1_ws = store.list_workspaces(user_id="user1")
        assert len(user1_ws) == 2

    def test_delete_workspace(self, store):
        result = store.create_machine(user_id="user1", name="M1", host_name="m1.local", relay_machine_id="relay-1")
        machine_id = result["id"]
        result = store.create_workspace(name="ws1", path="/ws1", owner_id="user1", machine_id=machine_id)
        ws_id = result["id"]
        assert store.delete_workspace(ws_id)
        assert store.get_workspace(ws_id) is None


class TestTaskOperations:
    def test_create_and_get_task(self, store):
        result = store.create_task(
            task_id="task-20260515-abc123",
            task_type="provision_agent",
            owner_id="user1",
            raw_request="Create a codex agent",
            parsed_steps='[{"step": 1, "action": "provision_agent"}]',
        )
        assert result is not None

        task = store.get_task("task-20260515-abc123")
        assert task is not None
        assert task["type"] == "provision_agent"
        assert task["status"] == "pending"
        assert task["owner_id"] == "user1"

    def test_update_task_status(self, store):
        store.create_task(
            task_id="task-test",
            task_type="test",
            owner_id="user1",
            raw_request="test",
            parsed_steps="[]",
        )
        store.update_task_status("task-test", "running", current_step=1)
        task = store.get_task("task-test")
        assert task["status"] == "running"
        assert task["current_step"] == 1

    def test_append_task_log(self, store):
        store.create_task(
            task_id="task-test",
            task_type="test",
            owner_id="user1",
            raw_request="test",
            parsed_steps="[]",
        )
        store.append_task_log("task-test", "Step 1 started")
        store.append_task_log("task-test", "Step 1 completed")
        task = store.get_task("task-test")
        assert "Step 1 started" in task["logs"]
        assert "Step 1 completed" in task["logs"]

    def test_list_tasks(self, store):
        store.create_task(task_id="task-1", task_type="test", owner_id="user1", raw_request="test1", parsed_steps="[]")
        store.create_task(task_id="task-2", task_type="test", owner_id="user1", raw_request="test2", parsed_steps="[]")
        store.create_task(task_id="task-3", task_type="test", owner_id="user2", raw_request="test3", parsed_steps="[]")

        all_tasks = store.list_tasks()
        assert len(all_tasks) == 3

        user1_tasks = store.list_tasks(user_id="user1")
        assert len(user1_tasks) == 2


class TestFeishuBotOperations:
    def test_create_and_get_bot(self, store):
        bot_id = store.create_feishu_bot(
            user_id="user1",
            name="Test Bot",
            app_id="cli_test",
            app_secret="secret123",
        )
        assert bot_id > 0

        bot = store.get_feishu_bot(bot_id)
        assert bot["name"] == "Test Bot"
        assert bot["app_id"] == "cli_test"
        assert bot["status"] == "active"

    def test_list_bots(self, store):
        store.create_feishu_bot("user1", "Bot1", "cli_1", "secret1")
        store.create_feishu_bot("user1", "Bot2", "cli_2", "secret2")
        store.create_feishu_bot("user2", "Bot3", "cli_3", "secret3")

        all_bots = store.list_feishu_bots()
        assert len(all_bots) == 3

        user1_bots = store.list_feishu_bots(user_id="user1")
        assert len(user1_bots) == 2

    def test_delete_bot(self, store):
        bot_id = store.create_feishu_bot("user1", "Bot1", "cli_1", "secret1")
        assert store.delete_feishu_bot(bot_id)
        assert store.get_feishu_bot(bot_id) is None


class TestNotificationRouteOperations:
    def test_create_and_get_route(self, store):
        bot_id = store.create_feishu_bot("user1", "Bot1", "cli_1", "secret1")
        route_id = store.create_notification_route(
            agent_short_id="codex-misc",
            user_id="user1",
            event_type="alert",
            destination_type="group",
            destination_id="oc_test",
            feishu_bot_id=bot_id,
        )
        assert route_id > 0

        route = store.get_notification_route(route_id)
        assert route["agent_short_id"] == "codex-misc"
        assert route["event_type"] == "alert"
        assert route["enabled"] is True

    def test_list_routes(self, store):
        bot_id = store.create_feishu_bot("user1", "Bot1", "cli_1", "secret1")
        store.create_notification_route("agent1", "user1", "alert", "group", "oc_1", bot_id)
        store.create_notification_route("agent1", "user1", "message", "private", "ou_1", bot_id)
        store.create_notification_route("agent2", "user1", "alert", "group", "oc_2", bot_id)

        all_routes = store.list_notification_routes()
        assert len(all_routes) == 3

        agent1_routes = store.list_notification_routes(agent_short_id="agent1")
        assert len(agent1_routes) == 2

    def test_update_route(self, store):
        bot_id = store.create_feishu_bot("user1", "Bot1", "cli_1", "secret1")
        route_id = store.create_notification_route("agent1", "user1", "alert", "group", "oc_1", bot_id)
        store.update_notification_route(route_id, enabled=False)
        route = store.get_notification_route(route_id)
        assert route["enabled"] is False

    def test_delete_route(self, store):
        bot_id = store.create_feishu_bot("user1", "Bot1", "cli_1", "secret1")
        route_id = store.create_notification_route("agent1", "user1", "alert", "group", "oc_1", bot_id)
        assert store.delete_notification_route(route_id)
        assert store.get_notification_route(route_id) is None


class TestFeishuBindingOperations:
    def test_bind_and_find_user(self, store):
        bot_id = store.create_feishu_bot("user1", "Bot1", "cli_1", "secret1")
        assert store.bind_user_feishu("user1", "ou_123", bot_id)

        user_id = store.find_user_by_open_id("ou_123", bot_id)
        assert user_id == "user1"

    def test_find_binding(self, store):
        bot_id = store.create_feishu_bot("user1", "Bot1", "cli_1", "secret1")
        store.bind_user_feishu("user1", "ou_123", bot_id)

        binding = store.find_binding_by_user("user1", bot_id)
        assert binding is not None
        assert binding["open_id"] == "ou_123"
        assert binding["bot_id"] == bot_id